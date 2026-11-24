# scene_processor.py

import os
import json
import base64
import shutil
import time
from datetime import datetime

import requests

import config
from helpers import ffmpeg_utils
from helpers.paths import translate_path
from helpers.video_sprite_generator import VideoSpriteGenerator
from helpers.preview_video_generator import PreviewVideoGenerator
from helpers.phash_generator import compute_phash
from helpers.stash_utils import (
    claim_scene, release_scene, tag_scene_error, is_scene_claimed,
    update_phash, update_cover, log_scene_failure
)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cover_is_placeholder(cover_url):
    """True when Stash is serving its default SVG placeholder instead of a real cover."""
    headers = {"ApiKey": config.stash_api_key} if config.stash_api_key else {}
    response = requests.get(cover_url, headers=headers, timeout=10)
    return "<svg" in response.content.decode('latin_1').lower()


def _generate_cover(scene_id, filename, filename_pretty, filehash, performed_options):
    temp_dir = ffmpeg_utils.tmp_path(f"cover_temp_{filehash}")
    os.makedirs(temp_dir, exist_ok=True)
    image_filename = os.path.join(temp_dir, f"{filehash}_cover.jpg")

    def command(seek):
        # -ss before -i: seek in the input instead of decoding everything up to that point
        return [
            config.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-ss', seek, '-i', filename, '-vframes', '1',
            image_filename
        ]

    if config.debug:
        print(f"🟡 [DEBUG] Starting cover image extraction for {filename_pretty}")
        print(f"🟡 [DEBUG] CLI: {' '.join(command('00:00:30'))}")
    cover_start = time.time()
    if config.dry_run:
        print(f"[DRY RUN] Would extract cover image using: {' '.join(command('00:00:30'))}")
        performed_options.append("cover (dry run)")
        return
    try:
        for seek in ('00:00:30', '00:00:05', '00:00:00'):
            ffmpeg_utils.run(command(seek), timeout=120, check=False)
            if os.path.exists(image_filename) and os.path.getsize(image_filename) > 0:
                break
        else:
            raise FileNotFoundError(f"Cover image not created: {image_filename}")
        with open(image_filename, "rb") as img:
            encoded = base64.b64encode(img.read()).decode()
        update_cover(scene_id, "data:image/jpeg;base64," + encoded)
        performed_options.append("cover")
        if config.debug:
            print(f"🟡 [DEBUG] Finished cover image extraction for {filename_pretty} in {time.time() - cover_start:.2f} seconds")
    except Exception as e:
        log_scene_failure(scene_id, filename_pretty, "cover image generation", ffmpeg_utils.error_detail(e))
        tag_scene_error(scene_id, config.cover_error_tag, str(e))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def process_scene(scene, index=None, total_batch=None, vaapi_supported=False, vaapi_device=None):
    start_time = time.time()
    scene_id = scene['id']

    def result(success, **extra):
        return {'success': success, 'elapsed_time': time.time() - start_time, 'scene_id': scene_id, **extra}

    if ffmpeg_utils.shutdown_event.is_set():
        return result(False, interrupted=True)
    if not scene.get('files'):
        return result(False)

    success = True
    file_id = scene['files'][0]['id']
    stash_path = scene['files'][0]['path']
    filename_pretty = os.path.basename(stash_path)

    if index and total_batch:
        print(f"[{_now()}] 📦 Scene #{index} of {total_batch}: ID {scene_id} — {filename_pretty}")
    else:
        print(f"[{_now()}] 📦 Processing scene: ID {scene_id} — {filename_pretty}")

    filehash = ""
    for fp in scene['files'][0].get('fingerprints', []):
        if fp['type'].lower() == "oshash":
            filehash = fp['value']

    if not filehash or ":" in filehash or "\\" in filehash or "/" in filehash:
        log_scene_failure(scene_id, filename_pretty, "oshash validation", f"Invalid or missing oshash: {filehash!r}")
        tag_scene_error(scene_id, config.hashing_error_tag, f"Invalid or missing oshash: {filehash!r}")
        return result(False)

    filename = os.path.normpath(translate_path(stash_path))

    if config.verbose:
        print(f"[{_now()}] 🔍 Translated path: {filename}")

    if not os.path.exists(filename):
        log_scene_failure(scene_id, filename_pretty, "file check", "File not found after translation")
        tag_scene_error(scene_id, config.hashing_error_tag, "File not found after translation")
        return result(False)

    # Another node may have picked the same random page — skip scenes it already claimed
    try:
        if is_scene_claimed(scene_id):
            print(f"[{_now()}] ⏭️ Scene {scene_id} is already being processed by another node. Skipping.")
            return result(False, skipped=True)
    except Exception:
        pass  # The check is an optimisation; carry on if it fails

    claim_scene(scene_id)

    try:
        performed_options = []

        # ── PHash ──────────────────────────────────────────
        binary_backend = config.phash_backend == "binary"
        if config.debug:
            print(f"🟡 [DEBUG] Starting phash generation for {filename_pretty}")
            if binary_backend:
                print(f"🟡 [DEBUG] CLI: {config.binary} -json '{filename}'")
        phash_start = time.time()
        if config.dry_run:
            print(f"[DRY RUN] Would compute phash for {filename}")
            performed_options.append("phash (dry run)")
        else:
            try:
                if binary_backend:
                    proc = ffmpeg_utils.run([config.binary, '-json', filename], timeout=300)
                    phash = json.loads(proc.stdout.decode("utf-8"))['phash']
                else:
                    phash = compute_phash(filename, vaapi_device=vaapi_device if vaapi_supported else None)['phash']
                update_phash(file_id, phash)
                performed_options.append("phash")
                if config.debug:
                    print(f"🟡 [DEBUG] Finished phash generation for {filename_pretty} in {time.time() - phash_start:.2f} seconds")
            except Exception as e:
                detail = ffmpeg_utils.error_detail(e)
                log_scene_failure(scene_id, filename_pretty, "hashing", detail)
                tag_scene_error(scene_id, config.hashing_error_tag, detail)
                success = False
                # Don't return early - release_scene in finally block

        # ── Cover ──────────────────────────────────────────
        try:
            cover_image = (scene.get('paths') or {}).get('screenshot')
            if cover_image and _cover_is_placeholder(cover_image):
                _generate_cover(scene_id, filename, filename_pretty, filehash, performed_options)
        except Exception as e:
            log_scene_failure(scene_id, filename_pretty, "cover image setup", e)
            tag_scene_error(scene_id, config.cover_error_tag, str(e))

        # ── Sprite ─────────────────────────────────────────
        if config.generate_sprite:
            sprite_file = os.path.join(config.sprite_path, f"{filehash}_sprite.jpg")
            vtt_file = os.path.join(config.sprite_path, f"{filehash}_thumbs.vtt")
            if not (os.path.exists(sprite_file) and os.path.exists(vtt_file)):
                if config.debug:
                    encoder_note = "VAAPI" if vaapi_supported else "software"
                    print(f"🟡 [DEBUG] Starting sprite generation for {filename_pretty}")
                    print(f"🟡 [DEBUG] VideoSpriteGenerator: 81 frames × {encoder_note} extraction → PIL assembly → {sprite_file}")
                if config.dry_run:
                    print(f"[DRY RUN] Would generate sprite for {filename_pretty} → {sprite_file}")
                    performed_options.append("sprite (dry run)")
                else:
                    try:
                        sprite_start = time.time()
                        VideoSpriteGenerator(
                            filename, sprite_file, vtt_file, filehash, config.ffmpeg, config.ffprobe,
                            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
                        ).generate_sprite()
                        performed_options.append("sprite")
                        if config.debug:
                            print(f"🟡 [DEBUG] Finished sprite generation for {filename_pretty} in {time.time() - sprite_start:.2f} seconds")
                    except Exception as e:
                        log_scene_failure(scene_id, filename_pretty, "sprite generation", e)
                        tag_scene_error(scene_id, config.hashing_error_tag, str(e))
                        success = False
                        # Don't return early - continue to release scene

        # ── Preview ────────────────────────────────────────
        if config.generate_preview:
            preview_file = os.path.join(config.preview_path, f"{filehash}.mp4")
            if not os.path.exists(preview_file):
                if config.debug:
                    print(f"🟡 [DEBUG] Starting preview generation for {filename_pretty}")
                if config.dry_run:
                    print(f"[DRY RUN] Would generate preview for {filename_pretty} → {preview_file}")
                    performed_options.append("preview (dry run)")
                else:
                    try:
                        preview_start = time.time()
                        PreviewVideoGenerator(
                            filename, preview_file, filehash,
                            ffmpeg=config.ffmpeg, ffprobe=config.ffprobe,
                            preview_clips=config.preview_clips, clip_length=config.preview_clip_length,
                            skip_seconds=config.preview_skip_seconds, include_audio=config.preview_audio,
                            scene_id=scene_id, scene_name=filename_pretty,
                            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
                        ).generate_preview()
                        performed_options.append("preview (vaapi)" if vaapi_supported else "preview")
                        if config.debug:
                            print(f"🟡 [DEBUG] Finished preview generation for {filename_pretty} in {time.time() - preview_start:.2f} seconds")
                    except Exception as e:
                        log_scene_failure(scene_id, filename_pretty, "preview generation", e)
                        tag_scene_error(scene_id, config.hashing_error_tag, str(e))
                        success = False
                        # Don't return early - continue to release scene

        # ── Markers (integrated mode) ──────────────────────
        if config.generate_markers and success:
            try:
                from helpers.marker_generator import MarkerGenerator
                from helpers.stash_utils import get_scene_markers_with_files, log_marker_failure

                markers = get_scene_markers_with_files(scene_id)

                if markers and config.verbose:
                    print(f"[{_now()}] 🎯 Found {len(markers)} markers for scene {scene_id}")

                for marker in markers or []:
                    marker_id = marker['id']
                    marker_seconds = marker['seconds']
                    marker_title = marker.get('title') or f"Marker at {marker_seconds}s"

                    if config.dry_run:
                        print(f"[DRY RUN] Would generate marker media for {marker_title}")
                        performed_options.append(f"marker {marker_id} (dry run)")
                        continue
                    try:
                        marker_result = MarkerGenerator(
                            filename, marker_seconds, filehash,
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

                        if marker_result['success']:
                            files_str = ', '.join(os.path.basename(f) for f in marker_result['files'])
                            performed_options.append(f"marker {marker_id}")
                            if config.verbose and files_str:
                                print(f"[{_now()}] ✅ Marker {marker_title} generated: {files_str}")
                        else:
                            log_marker_failure(marker_id, marker_title, "marker generation",
                                               marker_result.get('error') or 'Unknown error')
                    except Exception as e:
                        log_marker_failure(marker_id, marker_title, "marker generation", e)
                        # Don't fail scene processing for marker errors
            except Exception as e:
                log_scene_failure(scene_id, filename_pretty, "marker discovery", e)
                # Don't fail scene processing for marker discovery errors

        if config.verbose and success:
            options_str = ', '.join(performed_options) if performed_options else 'none'
            print(f"[{_now()}] ✅ Processed scene file '{filename_pretty}' in {time.time() - start_time:.2f} seconds. Options performed: {options_str}")

        return result(success)

    finally:
        release_scene(scene_id)
