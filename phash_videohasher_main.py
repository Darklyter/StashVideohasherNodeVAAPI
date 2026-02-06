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
    config.generate_sprite = args.generate_sprite
    config.generate_preview = args.generate_preview
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
    # VAAPI override logic
    if hasattr(args, 'vaapi') and args.vaapi:
        config.vaapi_override = True
    elif hasattr(args, 'novaapi') and args.novaapi:
        config.vaapi_override = False

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

def main():
    parser = argparse.ArgumentParser(description="Stash Scene Processor CLI")
    parser.add_argument("--windows", action="store_true", help="Use Windows-style paths and binaries")
    parser.add_argument("--generate-sprite", action="store_true", help="Enable sprite image generation")
    parser.add_argument("--generate-preview", action="store_true", help="Enable preview video generation")
    parser.add_argument("--batch-size", type=int, help="Number of scenes to process per run (default: 25)")
    parser.add_argument("--max-workers", type=int, help="Number of threads for parallel processing (default: 4)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate processing without writing changes")
    parser.add_argument("--verbose", action="store_true", help="Enable detailed output and progress bars")
    parser.add_argument("--once", action="store_true", help="Run a single batch and exit")
    parser.add_argument("--vaapi", action="store_true", help="Force VAAPI hardware acceleration for preview generation")
    parser.add_argument("--novaapi", action="store_true", help="Disable VAAPI hardware acceleration for preview generation")
    parser.add_argument("--debug", action="store_true", help="Enable debug output including step notifications and ffmpeg commands")
    parser.add_argument("--filemask", type=str, help="Filter scenes by filename pattern (e.g., 'JoonMali*' or '*.mp4')")
    parser.add_argument("--health-check", action="store_true", help="Run health checks and exit")
    parser.add_argument("--retry-errors", action="store_true", help="Process scenes with error tags")
    parser.add_argument("--clear-error-tags", action="store_true", help="Clear error tags from all scenes and exit")

    args = parser.parse_args()
    apply_cli_args(args)

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # VAAPI notification (only once at start)
    from datetime import datetime
    from helpers.vaapi_utils import vaapi_available
    vaapi_supported, vaapi_device = vaapi_available() if not config.windows else (False, None)
    vaapi_override = getattr(config, 'vaapi_override', None)
    if vaapi_override is True:
        vaapi_supported = True
        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI forced ON via CLI. VAAPI will be used for preview and sprite generation.")
    elif vaapi_override is False:
        vaapi_supported = False
        vaapi_device = None
        if config.verbose:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI forced OFF via CLI. Software will be used for preview and sprite generation.")
    elif config.verbose:
        if vaapi_supported:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI detected on {vaapi_device} and will be used for preview and sprite generation.")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 VAAPI not available. Software will be used for preview and sprite generation.")

    # Default to renderD128 if VAAPI forced but device not detected
    if vaapi_supported and vaapi_device is None:
        vaapi_device = '/dev/dri/renderD128'

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
