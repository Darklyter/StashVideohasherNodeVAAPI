# main.py

import argparse
import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures
from datetime import datetime
from itertools import islice

import config
from helpers import ffmpeg_utils
from helpers.ffmpeg_utils import shutdown_event, ShutdownRequested
from helpers.scene_discovery import discover_scenes
from helpers.scene_processor import process_scene
from helpers.stash_utils import (
    get_total_scene_count, get_error_scenes, clear_error_tags, get_hashing_scenes,
    clear_hashing_tags, reset_terminal, log_scene_failure, log_marker_failure, tag_scene_error
)
from helpers.health_check import run_health_check
from helpers.statistics import batch_stats

_signal_count = 0


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def apply_cli_args(args):
    """Apply CLI flags on top of config.py. A flag only overrides config when it was actually passed."""
    if args.windows:
        print("⚠️ --windows is deprecated and ignored: the platform is detected automatically.")
    if args.generate_sprite:
        config.generate_sprite = True
    if args.generate_preview:
        config.generate_preview = True
    for name in ("dry_run", "verbose", "once", "debug", "generate_markers"):
        value = getattr(args, name)
        if value is not None:
            setattr(config, name, value)
    for flag, value, target in (("--batch-size", args.batch_size, "per_page"),
                                ("--max-workers", args.max_workers, "max_workers"),
                                ("--marker-batch-size", args.marker_batch_size, "marker_batch_size")):
        if value is not None:
            if value < 1:
                print(f"❌ {flag} must be at least 1 (got {value})")
                sys.exit(1)
            setattr(config, target, value)
    if args.batch_sleep is not None:
        config.batch_sleep = max(0, args.batch_sleep)
    if args.filemask:
        config.filemask = args.filemask
    if args.nvenc:
        config.nvenc = True
    if args.hw_priority:
        config.hw_priority = args.hw_priority
    # VAAPI CLI overrides (take precedence over config.vaapi)
    if args.vaapi:
        config.vaapi_override = True
    elif args.novaapi:
        config.vaapi_override = False

    # Handle marker media type overrides
    if args.marker_preview_only:
        config.marker_preview_enabled = True
        config.marker_thumbnail_enabled = False
        config.marker_screenshot_enabled = False
    elif args.marker_thumbnail_only:
        config.marker_preview_enabled = False
        config.marker_thumbnail_enabled = True
        config.marker_screenshot_enabled = False
    elif args.marker_screenshot_only:
        config.marker_preview_enabled = False
        config.marker_thumbnail_enabled = False
        config.marker_screenshot_enabled = True


def signal_handler(signum, frame):
    """First signal: stop running jobs and exit cleanly. Second signal: force quit."""
    global _signal_count
    _signal_count += 1
    signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    if _signal_count == 1:
        print(f"\n🛑 Received {signal_name}. Stopping running jobs and exiting... (press Ctrl+C again to force quit)")
        ffmpeg_utils.request_shutdown()
    else:
        print("\n🛑 Forced exit. Scenes left tagged as in-process can be released with --clear-hashing-tags.")
        ffmpeg_utils.kill_all()
        reset_terminal()
        os._exit(130)


def process_sprite(scene_data, index, total, vaapi_supported, vaapi_device):
    """Process a single sprite for standalone mode."""
    import time
    from helpers.video_sprite_generator import VideoSpriteGenerator

    start_time = time.time()
    scene_id = scene_data['scene_id']
    oshash = scene_data['oshash']
    scene_title = scene_data['scene_title']

    print(f"[{_now()}] 🖼️ Sprite #{index} of {total}: Scene {scene_id} — {scene_title}")

    sprite_file = os.path.join(config.sprite_path, f"{oshash}_sprite.jpg")
    vtt_file = os.path.join(config.sprite_path, f"{oshash}_thumbs.vtt")

    if config.dry_run:
        print(f"[DRY RUN] Would generate sprite for scene {scene_id} → {sprite_file}")
        return {'success': True, 'elapsed_time': 0, 'scene_id': scene_id}

    try:
        VideoSpriteGenerator(
            scene_data['video_path'], sprite_file, vtt_file, oshash,
            config.ffmpeg, config.ffprobe,
            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
        ).generate_sprite()
        return {'success': True, 'elapsed_time': time.time() - start_time, 'scene_id': scene_id}

    except Exception as e:
        log_scene_failure(scene_id, scene_title, "sprite generation", e)
        tag_scene_error(scene_id, config.hashing_error_tag, f"sprite generation: {e}")
        return {'success': False, 'elapsed_time': time.time() - start_time, 'scene_id': scene_id}


def process_preview(scene_data, index, total, vaapi_supported, vaapi_device):
    """Process a single preview for standalone mode."""
    import time
    from helpers.preview_video_generator import PreviewVideoGenerator

    start_time = time.time()
    scene_id = scene_data['scene_id']
    oshash = scene_data['oshash']
    scene_title = scene_data['scene_title']

    print(f"[{_now()}] 🎞️ Preview #{index} of {total}: Scene {scene_id} — {scene_title}")

    preview_file = os.path.join(config.preview_path, f"{oshash}.mp4")

    if config.dry_run:
        print(f"[DRY RUN] Would generate preview for scene {scene_id} → {preview_file}")
        return {'success': True, 'elapsed_time': 0, 'scene_id': scene_id}

    try:
        PreviewVideoGenerator(
            scene_data['video_path'], preview_file, oshash,
            ffmpeg=config.ffmpeg, ffprobe=config.ffprobe,
            preview_clips=config.preview_clips,
            clip_length=config.preview_clip_length,
            skip_seconds=config.preview_skip_seconds,
            include_audio=config.preview_audio,
            scene_id=scene_id, scene_name=scene_title,
            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
        ).generate_preview()
        return {'success': True, 'elapsed_time': time.time() - start_time, 'scene_id': scene_id}

    except Exception as e:
        log_scene_failure(scene_id, scene_title, "preview generation", e)
        tag_scene_error(scene_id, config.hashing_error_tag, f"preview generation: {e}")
        return {'success': False, 'elapsed_time': time.time() - start_time, 'scene_id': scene_id}


def process_marker(marker_data, index, total, vaapi_supported, vaapi_device):
    """Process a single marker for standalone mode."""
    import time
    from helpers.marker_generator import MarkerGenerator

    start_time = time.time()
    marker_id = marker_data['marker_id']
    marker_title = marker_data['marker_title']
    scene_id = marker_data['scene_id']
    scene_title = marker_data.get('scene_title', f"Scene {scene_id}")

    print(f"[{_now()}] 🎯 Marker #{index} of {total}: ID {marker_id} — {marker_title or '(untitled)'} | Scene {scene_id} — {scene_title}")

    if config.dry_run:
        print(f"[DRY RUN] Would generate marker media for marker {marker_id}")
        return {'success': True, 'elapsed_time': 0, 'marker_id': marker_id}

    try:
        result = MarkerGenerator(
            marker_data['video_path'], marker_data['seconds'], marker_data['oshash'],
            config.marker_path,
            ffmpeg=config.ffmpeg, ffprobe=config.ffprobe,
            preview_enabled=config.marker_preview_enabled,
            thumbnail_enabled=config.marker_thumbnail_enabled,
            screenshot_enabled=config.marker_screenshot_enabled,
            preview_duration=config.marker_preview_duration,
            thumbnail_duration=config.marker_thumbnail_duration,
            thumbnail_fps=config.marker_thumbnail_fps,
            use_vaapi=vaapi_supported,
            vaapi_device=vaapi_device
        ).generate_marker()
        elapsed = time.time() - start_time

        if result['success']:
            if config.verbose:
                files_str = ', '.join(os.path.basename(f) for f in result['files'])
                print(f"[{_now()}] ✅ Generated {files_str} in {elapsed:.2f}s")
            return {'success': True, 'elapsed_time': elapsed, 'marker_id': marker_id}
        log_marker_failure(marker_id, marker_title, "generation", result.get('error') or 'Unknown')
        return {'success': False, 'elapsed_time': elapsed, 'marker_id': marker_id}

    except Exception as e:
        log_marker_failure(marker_id, marker_title, "generation", e)
        return {'success': False, 'elapsed_time': time.time() - start_time, 'marker_id': marker_id}


def run_batch(items, worker, desc, unit, timeout, vaapi_supported, vaapi_device):
    """
    Run `worker(item, index, total, vaapi_supported, vaapi_device)` for every item
    on the thread pool, record statistics and print the batch summary.
    Returns promptly once shutdown is requested.
    """
    batch_stats.start_batch(len(items))
    executor = ThreadPoolExecutor(max_workers=config.max_workers)
    try:
        futures = [executor.submit(worker, item, idx, len(items), vaapi_supported, vaapi_device)
                   for idx, item in enumerate(items, start=1)]

        if config.verbose:
            from tqdm import tqdm
            print()  # Blank line before progress bar
            iterator = tqdm(futures, desc=desc, unit=unit, total=len(futures),
                            leave=True, dynamic_ncols=True, position=0)
        else:
            iterator = futures

        for future in iterator:
            waited = 0.0
            while not future.done() and not shutdown_event.is_set() and waited < timeout:
                wait_futures([future], timeout=0.5)
                waited += 0.5
            if shutdown_event.is_set():
                break
            if not future.done():
                print(f"⚠️ {unit.capitalize()} processing timed out after {timeout // 60} minutes")
                batch_stats.record_failure()
                continue
            try:
                result = future.result()
            except ShutdownRequested:
                break
            except Exception as e:
                print(f"⚠️ Worker thread error: {e}")
                batch_stats.record_failure()
                continue
            if result and result.get('success'):
                batch_stats.record_success(result.get('elapsed_time'))
            elif result and (result.get('interrupted') or result.get('skipped')):
                pass  # neither a success nor a failure
            else:
                batch_stats.record_failure()

        if shutdown_event.is_set():
            print("🛑 Shutdown requested. Cancelling remaining work...")
        print(batch_stats.get_summary())
    finally:
        # In-flight workers stop within moments of shutdown (their child processes
        # are terminated); wait for them so claims are released and temp files removed.
        executor.shutdown(wait=True, cancel_futures=shutdown_event.is_set())


def sleep_between_batches():
    """Returns True when shutdown was requested during the wait."""
    if config.batch_sleep > 0:
        print(f"⏳ Waiting {config.batch_sleep}s before next batch... Press Ctrl+C to cancel.")
        return shutdown_event.wait(timeout=config.batch_sleep)
    return shutdown_event.is_set()


def run_standalone(args, vaapi_supported, vaapi_device):
    """
    Standalone generation modes. The library is scanned once per run; each batch
    takes the next items from that scan, so nothing is rediscovered (and a
    permanently failing item cannot loop forever).
    """
    sources = []

    if args.standalone_sprites:
        from helpers.sprite_discovery import iter_missing_sprites
        print("🖼️ Discovering scenes missing sprites...")
        sources.append(dict(items=iter_missing_sprites(), size=args.sprite_batch_size or 25,
                            worker=process_sprite, desc="🖼️ Generating Sprites", unit="sprite",
                            timeout=600, what="scenes needing sprites", done="✅ All scenes have sprites"))

    if args.standalone_previews:
        from helpers.preview_discovery import iter_missing_previews
        print("🎞️ Discovering scenes missing previews...")
        sources.append(dict(items=iter_missing_previews(), size=args.preview_batch_size or 25,
                            worker=process_preview, desc="🎞️ Generating Previews", unit="preview",
                            timeout=600, what="scenes needing previews", done="✅ All scenes have previews"))

    if args.standalone_markers:
        from helpers.marker_discovery import discover_missing_markers
        print("🎯 Discovering scenes with markers needing media generation...")
        by_scene = {}
        for marker in discover_missing_markers():
            by_scene.setdefault(marker['scene_id'], []).append(marker)
        # One item per scene, so every marker of a scene stays in the same batch
        sources.append(dict(items=iter(by_scene.values()), size=config.marker_batch_size, grouped=True,
                            worker=process_marker, desc="🎯 Processing Markers", unit="marker",
                            timeout=300, what="markers needing generation", done="✅ All markers have required media"))

    while not shutdown_event.is_set():
        ffmpeg_utils.clean_tmp()
        work_found = False

        for source in sources:
            if shutdown_event.is_set() or source.get('exhausted'):
                continue
            batch = list(islice(source['items'], source['size']))
            if source.get('grouped'):
                batch = [marker for group in batch for marker in group]
            if not batch:
                source['exhausted'] = True
                print(source['done'])
                continue
            work_found = True
            print(f"📦 Found {len(batch)} {source['what']}")
            run_batch(batch, source['worker'], source['desc'], source['unit'], source['timeout'],
                      vaapi_supported, vaapi_device)

        if shutdown_event.is_set():
            break
        if not work_found:
            print("✅ No remaining work found. Exiting.")
            break
        if config.once:
            print("✅ Finished single batch. Exiting due to --once flag.")
            break
        if sleep_between_batches():
            break


def run_scenes(args, vaapi_supported, vaapi_device):
    """Default mode: phash + cover (+ sprite / preview / markers) for scenes missing a phash."""
    retry_queue = None
    empty_pages = 0

    while not shutdown_event.is_set():
        ffmpeg_utils.clean_tmp()

        if args.retry_errors:
            # Take one snapshot of the error scenes and work through it; scenes that
            # fail again are re-tagged but not retried again in this run.
            if retry_queue is None:
                print("🔄 Fetching scenes with error tags for retry...")
                retry_queue = list(get_error_scenes() or [])
                if not retry_queue:
                    print("✅ No error scenes to retry. Exiting.")
                    break
            scenes = retry_queue[:config.per_page]
            del retry_queue[:config.per_page]
            if not scenes:
                print("✅ Finished retrying error scenes. Exiting.")
                break
            total_database = len(scenes) + len(retry_queue)
            # Clear error tags so they can be reprocessed
            clear_error_tags([s['id'] for s in scenes])
        else:
            total_database = get_total_scene_count()
            if total_database == 0:
                print("✅ No scenes to process. Exiting.")
                break
            scenes = discover_scenes(total_database)
            if not scenes:
                # Another node emptied the page between the count and the fetch
                empty_pages += 1
                if empty_pages >= 5:
                    print("✅ No scenes to process right now. Exiting.")
                    break
                if shutdown_event.wait(timeout=2):
                    break
                continue
            empty_pages = 0

        print(f"[{_now()}] 🎯 Selected page with {len(scenes)} scenes (out of {total_database} total)")
        run_batch(scenes, process_scene, "📦 Processing Batch", "scene", 600, vaapi_supported, vaapi_device)

        if shutdown_event.is_set():
            break
        if config.once:
            print("✅ Finished single batch. Exiting due to --once flag.")
            break
        if sleep_between_batches():
            break


def main():
    # Relative paths in config.py (binary, error log) are relative to the project,
    # not to wherever the script was started from (cron, systemd, ...)
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(
        description=(
            "VAAPI-accelerated Stash video processor.\n\n"
            "DEFAULT BEHAVIOR (no options): Discovers scenes missing a phash, then generates\n"
            "phash + cover image for each one. Sprite and preview generation also run if\n"
            "enabled in config.py (generate_sprite / generate_preview / generate_markers).\n"
            "Loops continuously until all scenes are processed. All generation types can\n"
            "be forced on via flags below regardless of config.\n\n"
            "Ctrl+C stops running jobs and exits cleanly; press it twice to force quit."
        ),
        epilog="""
Default run (loops until complete, runs whatever is enabled in config.py):
  python %(prog)s

One batch and exit — runs all generation types enabled in config.py (good for cron):
  python %(prog)s --once --verbose

Force all generation on regardless of config (one batch):
  python %(prog)s --generate-sprite --generate-preview --generate-markers --once --verbose

Standalone modes — generate missing media without reprocessing scenes:
  python %(prog)s --standalone-sprites --sprite-batch-size 50 --verbose
  python %(prog)s --standalone-previews --preview-batch-size 25 --verbose
  python %(prog)s --standalone-markers --marker-batch-size 100 --verbose
  python %(prog)s --standalone-sprites --standalone-previews --standalone-markers --verbose

Other useful options:
  python %(prog)s --filemask "JoonMali*" --once --verbose
  python %(prog)s --standalone-markers --dry-run --verbose
  python %(prog)s --vaapi --once --verbose
  python %(prog)s --novaapi --once --verbose
  python %(prog)s --health-check
  python %(prog)s --retry-errors --once --verbose
  python %(prog)s --clear-error-tags
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--version", action="version", version="%(prog)s 1.4.0")

    # Basic options
    basic = parser.add_argument_group('Basic Options')
    basic.add_argument("--windows", action="store_true", help=argparse.SUPPRESS)  # deprecated: platform is auto-detected
    basic.add_argument("--batch-size", type=int, help="Number of scenes to process per run (default: 25)")
    basic.add_argument("--max-workers", type=int, help="Number of threads for parallel processing (default: 4)")
    basic.add_argument("--batch-sleep", type=int, help="Seconds to wait between batches (default: 5, 0 = no delay)")
    basic.add_argument("--dry-run", action="store_true", default=None, help="Simulate processing without writing changes")
    basic.add_argument("--verbose", action="store_true", default=None, help="Enable detailed output and progress bars")
    basic.add_argument("--debug", action="store_true", default=None, help="Enable debug output including step notifications and ffmpeg commands")
    basic.add_argument("--once", action="store_true", default=None, help="Run a single batch and exit (don't loop)")
    basic.add_argument("--filemask", type=str, help="Filter scenes by filename pattern (e.g., 'JoonMali*' or '*.mp4')")

    # Integrated scene processing
    integrated = parser.add_argument_group('Integrated Scene Processing', 'Enable media generation during scene processing')
    integrated.add_argument("--generate-sprite", action="store_true", help="Generate sprite sheets during scene processing")
    integrated.add_argument("--generate-preview", action="store_true", help="Generate preview videos during scene processing")
    integrated.add_argument("--generate-markers", action="store_true", default=None, help="Generate marker media (MP4/WebP/JPG) during scene processing")

    # Standalone generation modes
    standalone = parser.add_argument_group('Standalone Generation Modes', 'Generate media without full scene processing')
    standalone.add_argument("--standalone-sprites", action="store_true", help="Generate sprites only (batch process missing sprites)")
    standalone.add_argument("--sprite-batch-size", type=int, help="Batch size for standalone sprite generation (default: 25)")
    standalone.add_argument("--standalone-previews", action="store_true", help="Generate previews only (batch process missing previews)")
    standalone.add_argument("--preview-batch-size", type=int, help="Batch size for standalone preview generation (default: 25)")
    standalone.add_argument("--standalone-markers", action="store_true", help="Generate markers only (batch process missing marker media)")
    standalone.add_argument("--marker-batch-size", type=int, help="Number of scenes to process per batch in standalone marker mode — all eligible markers for each scene are included (default: 50)")

    # Marker options
    markers = parser.add_argument_group('Marker Generation Options')
    markers.add_argument("--marker-preview-only", action="store_true", help="Generate only MP4 previews for markers (20s clips)")
    markers.add_argument("--marker-thumbnail-only", action="store_true", help="Generate only WebP thumbnails for markers (5s animations)")
    markers.add_argument("--marker-screenshot-only", action="store_true", help="Generate only JPG screenshots for markers (single frames)")

    # Hardware acceleration
    hardware = parser.add_argument_group('Hardware Acceleration')
    hardware.add_argument("--vaapi", action="store_true", help="Force VAAPI hardware acceleration on (overrides config.vaapi)")
    hardware.add_argument("--novaapi", action="store_true", help="Force VAAPI off (overrides config.vaapi)")
    hardware.add_argument("--nvenc", action="store_true", help="Enable NVIDIA NVENC hardware encoder (overrides config.nvenc)")
    hardware.add_argument("--hw-priority", choices=["vaapi", "nvenc"], help="Which encoder takes precedence when both are available (overrides config.hw_priority)")

    # Utilities
    utilities = parser.add_argument_group('Utilities')
    utilities.add_argument("--health-check", action="store_true", help="Run system health checks and exit")
    utilities.add_argument("--retry-errors", action="store_true", help="Process scenes with error tags (retry failed scenes)")
    utilities.add_argument("--clear-error-tags", action="store_true", help="Clear error tags from all scenes and exit")
    utilities.add_argument("--clear-hashing-tags", action="store_true", help="Clear stuck in-process tags (use after a crash) and exit")

    args = parser.parse_args()
    apply_cli_args(args)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        exit_code = _run(args)
    finally:
        ffmpeg_utils.clean_tmp(final=True)
        reset_terminal()
    if shutdown_event.is_set():
        print("🛑 Stopped.")
        exit_code = 130
    sys.exit(exit_code)


def _run(args):
    from helpers.vaapi_utils import vaapi_available

    # Hardware encoder resolution (evaluated once at startup)
    from helpers.vaapi_utils import vaapi_available

    # Step 1: Auto-detect VAAPI
    vaapi_supported, vaapi_device = vaapi_available() if not config.windows else (False, None)

    # Step 2: Apply CLI overrides — highest precedence
    vaapi_override = getattr(config, 'vaapi_override', None)
    if vaapi_override is True:
        vaapi_supported = True
        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI forced ON via --vaapi.")
    elif vaapi_override is False:
        vaapi_supported = False
        vaapi_device = None
        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI forced OFF via --novaapi.")
    elif not config.vaapi:
        # VAAPI disabled in config, no CLI override present
        vaapi_supported = False
        vaapi_device = None
        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI disabled in config.")
    elif config.verbose:
        if vaapi_supported:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI detected on {vaapi_device}.")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI not available.")

    # Default device path if VAAPI was forced on but detection returned no device
    if vaapi_supported and vaapi_device is None:
        vaapi_device = '/dev/dri/renderD128'

    # Step 3: Apply hw_priority when both VAAPI and NVENC are configured
    if vaapi_supported and config.nvenc and config.hw_priority == "nvenc":
        vaapi_supported = False
        vaapi_device = None
        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 NVENC takes priority over VAAPI (hw_priority=nvenc).")

    # Report final encoder selection
    if config.verbose:
        if vaapi_supported:
            encoder = f"VAAPI ({vaapi_device})"
        elif config.nvenc:
            encoder = "NVENC"
        else:
            encoder = "software (libx264)"
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🎬 Hardware encoder: {encoder}")

    # Handle special CLI commands
    if args.health_check:
        passed, results = run_health_check(vaapi_device if vaapi_supported else None)
        return 0 if passed else 1

    if args.clear_error_tags:
        print("🏷️  Fetching scenes with error tags...")
        error_scenes = get_error_scenes()
        if not error_scenes:
            print("✅ No scenes with error tags found.")
            return 0
        scene_ids = [s['id'] for s in error_scenes]
        print(f"🏷️  Clearing error tags from {len(scene_ids)} scenes...")
        clear_error_tags(scene_ids)
        print(f"✅ Cleared error tags from {len(scene_ids)} scenes.")
        return 0

    if args.clear_hashing_tags:
        print("🏷️  Fetching scenes with stuck in-process tags...")
        hashing_scenes = get_hashing_scenes()
        if not hashing_scenes:
            print("✅ No scenes with stuck hashing tags found.")
            return 0
        scene_ids = [s['id'] for s in hashing_scenes]
        print(f"🏷️  Clearing hashing tag from {len(scene_ids)} scenes...")
        clear_hashing_tags(scene_ids)
        print(f"✅ Cleared hashing tag from {len(scene_ids)} scenes.")
        return 0

    # Run health checks before processing (unless disabled)
    if not config.dry_run:
        passed, results = run_health_check(vaapi_device if vaapi_supported else None)
        if not passed:
            print("❌ Health checks failed. Aborting. Use --health-check to diagnose.")
            return 1

    if args.standalone_sprites or args.standalone_previews or args.standalone_markers:
        run_standalone(args, vaapi_supported, vaapi_device)
    else:
        run_scenes(args, vaapi_supported, vaapi_device)
    return 0


if __name__ == '__main__':
    main()
