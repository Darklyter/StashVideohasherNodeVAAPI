# main.py

import argparse
import re
import os
import shutil
import time
import subprocess
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import config
from helpers.scene_discovery import discover_scenes
from helpers.scene_processor import process_scene
from helpers.stash_utils import get_total_scene_count, get_error_scenes, clear_error_tags, reset_terminal
from helpers.health_check import run_health_check
from helpers.statistics import batch_stats

# Global shutdown flag for signal handling
shutdown_requested = False

def apply_cli_args(args):
    config.windows = args.windows
    if args.generate_sprite:
        config.generate_sprite = True
    if args.generate_preview:
        config.generate_preview = True
    config.dry_run = args.dry_run
    config.verbose = args.verbose
    config.once = args.once
    config.debug = args.debug
    if args.batch_size:
        config.per_page = args.batch_size
    if args.max_workers:
        config.max_workers = args.max_workers
    if args.filemask:
        config.filemask = args.filemask
    if hasattr(args, 'nvenc') and args.nvenc:
        config.nvenc = True
    if hasattr(args, 'hw_priority') and args.hw_priority:
        config.hw_priority = args.hw_priority
    # VAAPI CLI overrides (take precedence over config.vaapi)
    if hasattr(args, 'vaapi') and args.vaapi:
        config.vaapi_override = True
    elif hasattr(args, 'novaapi') and args.novaapi:
        config.vaapi_override = False

    # Marker generation settings (both --generate-markers and --standalone-markers)
    config.generate_markers = args.generate_markers or args.standalone_markers
    if args.marker_batch_size:
        config.marker_batch_size = args.marker_batch_size

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
    """Handle termination signals gracefully"""
    global shutdown_requested
    signal_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    print(f"\n🛑 Received {signal_name}. Shutting down gracefully...")
    shutdown_requested = True

def clean_temp_dirs(recreate=True):
    tmp_dir = os.path.join(os.getcwd(), ".tmp")

    # Remove entire .tmp directory if it exists
    if os.path.exists(tmp_dir):
        try:
            shutil.rmtree(tmp_dir)
            if config.verbose:
                print(f"🧹 Cleaned temporary directory: .tmp")
        except Exception as e:
            if config.verbose:
                print(f"⚠️ Failed to remove .tmp: {e}")

    # Create fresh .tmp directory (unless we're exiting)
    if recreate:
        try:
            os.makedirs(tmp_dir, exist_ok=True)
        except Exception as e:
            if config.verbose:
                print(f"⚠️ Failed to create .tmp: {e}")

def process_sprite(scene_data, index, total, vaapi_supported, vaapi_device):
    """Process a single sprite for standalone mode."""
    import time
    from datetime import datetime
    from helpers.video_sprite_generator import VideoSpriteGenerator
    from helpers.stash_utils import log_scene_failure

    start_time = time.time()
    scene_id = scene_data['scene_id']
    oshash = scene_data['oshash']
    scene_title = scene_data['scene_title']

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 🖼️ Sprite #{index} of {total}: Scene {scene_id} — {scene_title}")

    sprite_file = os.path.join(config.sprite_path, f"{oshash}_sprite.jpg")
    vtt_file = os.path.join(config.sprite_path, f"{oshash}_thumbs.vtt")

    try:
        generator = VideoSpriteGenerator(
            scene_data['video_path'], sprite_file, vtt_file, oshash,
            config.ffmpeg, config.ffprobe,
            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
        )
        generator.generate_sprite()
        elapsed = time.time() - start_time

        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Sprite generated in {elapsed:.2f}s")
        return {'success': True, 'elapsed_time': elapsed, 'scene_id': scene_id}

    except Exception as e:
        elapsed = time.time() - start_time
        log_scene_failure(scene_id, scene_title, "sprite generation", str(e))
        return {'success': False, 'elapsed_time': elapsed, 'scene_id': scene_id}

def process_preview(scene_data, index, total, vaapi_supported, vaapi_device):
    """Process a single preview for standalone mode."""
    import time
    from datetime import datetime
    from helpers.preview_video_generator import PreviewVideoGenerator
    from helpers.stash_utils import log_scene_failure

    start_time = time.time()
    scene_id = scene_data['scene_id']
    oshash = scene_data['oshash']
    scene_title = scene_data['scene_title']

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 🎞️ Preview #{index} of {total}: Scene {scene_id} — {scene_title}")

    preview_file = os.path.join(config.preview_path, f"{oshash}.mp4")

    try:
        generator = PreviewVideoGenerator(
            scene_data['video_path'], preview_file, oshash,
            ffmpeg=config.ffmpeg, ffprobe=config.ffprobe,
            preview_clips=config.preview_clips,
            clip_length=config.preview_clip_length,
            skip_seconds=config.preview_skip_seconds,
            include_audio=config.preview_audio,
            scene_id=scene_id, scene_name=scene_title,
            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
        )
        generator.generate_preview()
        elapsed = time.time() - start_time

        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Preview generated in {elapsed:.2f}s")
        return {'success': True, 'elapsed_time': elapsed, 'scene_id': scene_id}

    except Exception as e:
        elapsed = time.time() - start_time
        log_scene_failure(scene_id, scene_title, "preview generation", str(e))
        return {'success': False, 'elapsed_time': elapsed, 'scene_id': scene_id}

def process_marker(marker_data, index, total, vaapi_supported, vaapi_device):
    """Process a single marker for standalone mode."""
    import time
    from datetime import datetime
    from helpers.marker_generator import MarkerGenerator
    from helpers.stash_utils import log_marker_failure

    start_time = time.time()
    marker_id = marker_data['marker_id']
    marker_title = marker_data['marker_title']

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] 🎯 Marker #{index} of {total}: ID {marker_id} — {marker_title}")

    try:
        generator = MarkerGenerator(
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
        )

        result = generator.generate_marker()
        elapsed = time.time() - start_time

        if result['success']:
            files_str = ', '.join([os.path.basename(f) for f in result['files']])
            if config.verbose:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Generated {files_str} in {elapsed:.2f}s")
            return {'success': True, 'elapsed_time': elapsed, 'marker_id': marker_id}
        else:
            log_marker_failure(marker_id, marker_title, "generation", result.get('error', 'Unknown'))
            return {'success': False, 'elapsed_time': elapsed, 'marker_id': marker_id}

    except Exception as e:
        elapsed = time.time() - start_time
        log_marker_failure(marker_id, marker_title, "generation", str(e))
        return {'success': False, 'elapsed_time': elapsed, 'marker_id': marker_id}

def main():
    parser = argparse.ArgumentParser(
        description=(
            "VAAPI-accelerated Stash video processor.\n\n"
            "DEFAULT BEHAVIOR (no options): Discovers scenes missing a phash, then generates\n"
            "phash + cover image for each one. Sprite and preview generation also run if\n"
            "enabled in config.py (generate_sprite / generate_preview). Marker generation\n"
            "is off by default. Loops continuously until all scenes are processed.\n"
            "All generation types can be forced on via flags below regardless of config."
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

    # Basic options
    basic = parser.add_argument_group('Basic Options')
    basic.add_argument("--windows", action="store_true", help="Use Windows-style paths and binaries")
    basic.add_argument("--batch-size", type=int, help="Number of scenes to process per run (default: 25)")
    basic.add_argument("--max-workers", type=int, help="Number of threads for parallel processing (default: 4)")
    basic.add_argument("--dry-run", action="store_true", help="Simulate processing without writing changes")
    basic.add_argument("--verbose", action="store_true", help="Enable detailed output and progress bars")
    basic.add_argument("--debug", action="store_true", help="Enable debug output including step notifications and ffmpeg commands")
    basic.add_argument("--once", action="store_true", help="Run a single batch and exit (don't loop)")
    basic.add_argument("--filemask", type=str, help="Filter scenes by filename pattern (e.g., 'JoonMali*' or '*.mp4')")

    # Integrated scene processing
    integrated = parser.add_argument_group('Integrated Scene Processing', 'Enable media generation during scene processing')
    integrated.add_argument("--generate-sprite", action="store_true", help="Generate sprite sheets during scene processing")
    integrated.add_argument("--generate-preview", action="store_true", help="Generate preview videos during scene processing")
    integrated.add_argument("--generate-markers", action="store_true", help="Generate marker media (MP4/WebP/JPG) during scene processing")

    # Standalone generation modes
    standalone = parser.add_argument_group('Standalone Generation Modes', 'Generate media without full scene processing')
    standalone.add_argument("--standalone-sprites", action="store_true", help="Generate sprites only (batch process missing sprites)")
    standalone.add_argument("--sprite-batch-size", type=int, help="Batch size for standalone sprite generation (default: 25)")
    standalone.add_argument("--standalone-previews", action="store_true", help="Generate previews only (batch process missing previews)")
    standalone.add_argument("--preview-batch-size", type=int, help="Batch size for standalone preview generation (default: 25)")
    standalone.add_argument("--standalone-markers", action="store_true", help="Generate markers only (batch process missing marker media)")
    standalone.add_argument("--marker-batch-size", type=int, help="Batch size for standalone marker generation (default: 50)")

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

    args = parser.parse_args()
    apply_cli_args(args)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Hardware encoder resolution (evaluated once at startup)
    from datetime import datetime
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
        sys.exit(0 if passed else 1)

    if args.clear_error_tags:
        print("🏷️  Fetching scenes with error tags...")
        error_scenes = get_error_scenes()
        if not error_scenes:
            print("✅ No scenes with error tags found.")
            sys.exit(0)
        scene_ids = [s['id'] for s in error_scenes]
        print(f"🏷️  Clearing error tags from {len(scene_ids)} scenes...")
        clear_error_tags(scene_ids)
        print(f"✅ Cleared error tags from {len(scene_ids)} scenes.")
        sys.exit(0)

    # Run health checks before processing (unless disabled)
    if not config.dry_run:
        passed, results = run_health_check(vaapi_device if vaapi_supported else None)
        if not passed:
            print("❌ Health checks failed. Aborting. Use --health-check to diagnose.")
            sys.exit(1)

    # Standalone generation modes (process and exit, don't enter main loop)
    standalone_mode = args.standalone_sprites or args.standalone_previews or args.standalone_markers or args.generate_markers

    if standalone_mode:
        from tqdm import tqdm

        # Standalone sprite generation
        if args.standalone_sprites:
            from helpers.sprite_discovery import discover_missing_sprites

            print("🖼️ Discovering scenes missing sprites...")
            missing_sprites = discover_missing_sprites(limit=args.sprite_batch_size or 25)

            if missing_sprites:
                print(f"📦 Found {len(missing_sprites)} scenes needing sprites")
                batch_stats.start_batch(len(missing_sprites))

                executor = ThreadPoolExecutor(max_workers=config.max_workers)
                try:
                    futures = [executor.submit(process_sprite, scene_data, idx, len(missing_sprites),
                                              vaapi_supported, vaapi_device)
                              for idx, scene_data in enumerate(missing_sprites, 1)]

                    if config.verbose:
                        iterator = tqdm(futures, desc="🖼️ Generating Sprites", unit="sprite")
                    else:
                        iterator = futures

                    for future in iterator:
                        if shutdown_requested:
                            break
                        try:
                            result = future.result(timeout=600)
                            if result and result.get('success'):
                                batch_stats.record_success(result.get('elapsed_time'))
                            else:
                                batch_stats.record_failure()
                        except (TimeoutError, Exception) as e:
                            print(f"⚠️ Sprite generation error: {e}")
                            batch_stats.record_failure()

                    if config.verbose:
                        print(batch_stats.get_summary())
                finally:
                    executor.shutdown(wait=True)
            else:
                print("✅ All scenes have sprites")

        # Standalone preview generation
        if args.standalone_previews:
            from helpers.preview_discovery import discover_missing_previews

            print("🎞️ Discovering scenes missing previews...")
            missing_previews = discover_missing_previews(limit=args.preview_batch_size or 25)

            if missing_previews:
                print(f"📦 Found {len(missing_previews)} scenes needing previews")
                batch_stats.start_batch(len(missing_previews))

                executor = ThreadPoolExecutor(max_workers=config.max_workers)
                try:
                    futures = [executor.submit(process_preview, scene_data, idx, len(missing_previews),
                                              vaapi_supported, vaapi_device)
                              for idx, scene_data in enumerate(missing_previews, 1)]

                    if config.verbose:
                        iterator = tqdm(futures, desc="🎞️ Generating Previews", unit="preview")
                    else:
                        iterator = futures

                    for future in iterator:
                        if shutdown_requested:
                            break
                        try:
                            result = future.result(timeout=600)
                            if result and result.get('success'):
                                batch_stats.record_success(result.get('elapsed_time'))
                            else:
                                batch_stats.record_failure()
                        except (TimeoutError, Exception) as e:
                            print(f"⚠️ Preview generation error: {e}")
                            batch_stats.record_failure()

                    if config.verbose:
                        print(batch_stats.get_summary())
                finally:
                    executor.shutdown(wait=True)
            else:
                print("✅ All scenes have previews")

        # Standalone marker generation
        if args.standalone_markers or args.generate_markers:
            from helpers.marker_discovery import discover_missing_markers

            print("🎯 Discovering markers needing media generation...")
            missing_markers = discover_missing_markers(limit=config.marker_batch_size)

            if missing_markers:
                print(f"📦 Found {len(missing_markers)} markers needing media generation")
                batch_stats.start_batch(len(missing_markers))

                executor = None
                try:
                    executor = ThreadPoolExecutor(max_workers=config.max_workers)
                    futures = [executor.submit(process_marker, marker_data, idx, len(missing_markers),
                                              vaapi_supported, vaapi_device)
                              for idx, marker_data in enumerate(missing_markers, 1)]

                    if config.verbose:
                        print()
                        iterator = tqdm(futures, desc="🎯 Processing Markers", unit="marker")
                    else:
                        iterator = futures

                    for future in iterator:
                        if shutdown_requested:
                            print("\n🛑 Shutdown requested. Cancelling remaining markers...")
                            executor.shutdown(wait=False, cancel_futures=True)
                            break

                        try:
                            result = future.result(timeout=300)  # 5 minute timeout
                            if result and result.get('success'):
                                batch_stats.record_success(result.get('elapsed_time'))
                            else:
                                batch_stats.record_failure()
                        except TimeoutError:
                            print(f"⚠️ Marker processing timed out after 5 minutes")
                            batch_stats.record_failure()
                        except Exception as e:
                            print(f"⚠️ Worker thread error: {e}")
                            batch_stats.record_failure()

                    if config.verbose or config.debug:
                        print(batch_stats.get_summary())

                except KeyboardInterrupt:
                    print("\n🛑 Interrupted by user. Shutting down gracefully...")
                    if executor:
                        executor.shutdown(wait=False, cancel_futures=True)
                finally:
                    if executor:
                        executor.shutdown(wait=True)
            else:
                print("✅ All markers have required media")

        # Exit after standalone modes complete
        clean_temp_dirs(recreate=False)
        reset_terminal()
        sys.exit(0)

    while True:
        if shutdown_requested:
            print("🛑 Shutdown requested. Exiting...")
            clean_temp_dirs(recreate=False)
            reset_terminal()
            break

        clean_temp_dirs()

        # Get scenes to process (retry errors or normal discovery)
        if args.retry_errors:
            print("🔄 Fetching scenes with error tags for retry...")
            scenes = get_error_scenes()
            if not scenes:
                print("✅ No error scenes to retry. Exiting.")
                clean_temp_dirs(recreate=False)
                reset_terminal()
                break
            # Clear error tags so they can be reprocessed
            scene_ids = [s['id'] for s in scenes]
            clear_error_tags(scene_ids)
        else:
            scenes = discover_scenes()

        if not scenes:
            print("✅ No scenes to process. Exiting.")
            print("🧹 Cleaning up temporary directories...")
            clean_temp_dirs(recreate=False)
            reset_terminal()
            break

        total_batch = len(scenes)
        total_database = get_total_scene_count()
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🎯 Selected page with {total_batch} scenes (out of {total_database} total)")

        # Initialize statistics tracking
        batch_stats.start_batch(total_batch)

        executor = None
        try:
            executor = ThreadPoolExecutor(max_workers=config.max_workers)
            futures = []
            for index, scene in enumerate(scenes, start=1):
                futures.append(executor.submit(process_scene, scene, index, total_batch, vaapi_supported, vaapi_device))

            # Progress bar for batch completion
            if config.verbose:
                from tqdm import tqdm
                print()  # Blank line before progress bar
                iterator = tqdm(futures, desc="📦 Processing Batch", unit="scene", total=len(futures),
                               leave=True, dynamic_ncols=True, position=0)
            else:
                iterator = futures

            for future in iterator:
                if shutdown_requested:
                    print("\n🛑 Shutdown requested. Cancelling remaining scenes...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    result = future.result(timeout=600)  # 10 minute timeout per scene
                    if result and result.get('success'):
                        batch_stats.record_success(result.get('elapsed_time'))
                    else:
                        batch_stats.record_failure()
                except TimeoutError:
                    print(f"⚠️ Scene processing timed out after 10 minutes")
                    batch_stats.record_failure()
                except Exception as e:
                    print(f"⚠️ Worker thread error: {e}")
                    batch_stats.record_failure()

            # Print statistics summary
            if config.verbose or config.debug:
                print(batch_stats.get_summary())

        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user. Shutting down gracefully...")
            if executor:
                executor.shutdown(wait=False, cancel_futures=True)
            print("🧹 Cleaning up temporary directories...")
            clean_temp_dirs(recreate=False)
            reset_terminal()
            break
        finally:
            if executor:
                executor.shutdown(wait=True)

        if config.once:
            print("✅ Finished single batch. Exiting due to --once flag.")
            print("🧹 Cleaning up temporary directories...")
            clean_temp_dirs(recreate=False)
            reset_terminal()
            break

        print("⏳ Waiting 5 seconds before next batch... Press Ctrl+C to cancel.")
        time.sleep(5)

if __name__ == '__main__':
    main()
