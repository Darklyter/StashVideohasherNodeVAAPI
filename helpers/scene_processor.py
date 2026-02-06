# scene_processor.py

import os
import re
import subprocess
import json
import string
import base64
import random
import requests
import shutil
from json.decoder import JSONDecodeError
from datetime import datetime

from helpers.video_sprite_generator import VideoSpriteGenerator
from helpers.preview_video_generator import PreviewVideoGenerator

from config import (
    windows, binary, ffmpeg, ffprobe,
    generate_sprite, generate_preview, sprite_path, preview_path,
    preview_audio, preview_clips, preview_clip_length, preview_skip_seconds,
    translations, dry_run, verbose,
    hashing_tag, hashing_error_tag, cover_error_tag
)

from helpers.stash_utils import (
    claim_scene, release_scene, tag_scene_error,
    update_phash, update_cover, log_scene_failure
)

def process_scene(scene, index=None, total_batch=None, vaapi_supported=False, vaapi_device=None):
    import time
    import config
    start_time = time.time()
    vaapi_used = False
    success = True
    scene_id = scene['id']
    file_id = scene['files'][0]['id']
    filename = scene['files'][0]['path']
    filename_pretty = re.search(r'.*[/\\](.*?)$', filename).group(1)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if index and total_batch:
        print(f"[{timestamp}] 📦 Scene #{index} of {total_batch}: ID {scene_id} — {filename_pretty}")
    else:
        print(f"[{timestamp}] 📦 Processing scene: ID {scene_id} — {filename_pretty}")

    for t in translations:
        filename = filename.replace(t['orig'], t['local'], 1)

    filehash = ""
    for fp in scene['files'][0].get('fingerprints', []):
        if fp['type'].lower() == "oshash":
            filehash = fp['value']

    if not filehash or ":" in filehash or "\\" in filehash or "/" in filehash:
        filehash = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))

    filename = os.path.normpath(filename)
    file_exists = os.path.exists(filename)

    if config.verbose:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🔍 Translated path: {filename}")

    if not file_exists:
        log_scene_failure(scene_id, filename_pretty, "file check", "File not found after translation")
        tag_scene_error(scene_id, hashing_error_tag, "File not found after translation")
        elapsed = time.time() - start_time
        return {'success': False, 'elapsed_time': elapsed, 'scene_id': scene_id}

    claim_scene(scene_id)

    try:
        performed_options = []

        if config.debug:
            print(f"🟡 [DEBUG] Starting phash generation for {filename_pretty}")
            print(f"🟡 [DEBUG] CLI: {binary} -json '{filename}'")
            phash_start = time.time()
        if dry_run:
            print(f"[DRY RUN] Would run videohash on {filename}")
            performed_options.append("phash (dry run)")
            if config.debug:
                phash_elapsed = time.time() - phash_start
                print(f"🟡 [DEBUG] Finished phash generation for {filename_pretty} in {phash_elapsed:.2f} seconds")
        else:
            try:
                result = subprocess.run([binary, '-json', filename], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
                results = json.loads(result.stdout.decode("utf-8"))
                update_phash(file_id, results['phash'])
                performed_options.append("phash")
                if config.debug:
                    phash_elapsed = time.time() - phash_start
                    print(f"🟡 [DEBUG] Finished phash generation for {filename_pretty} in {phash_elapsed:.2f} seconds")
            except Exception as e:
                log_scene_failure(scene_id, filename_pretty, "hashing", e)
                tag_scene_error(scene_id, hashing_error_tag, str(e))
                success = False
                # Don't return early - release_scene in finally block

        try:
            cover_image = scene['paths'].get('screenshot')
            if cover_image and "<svg" in requests.get(cover_image).content.decode('latin_1').lower():
                temp_dir = os.path.abspath(os.path.join(".tmp", f"cover_temp_{filehash}"))
                os.makedirs(temp_dir, exist_ok=True)
                image_filename = os.path.join(temp_dir, f"{filehash}_cover.jpg")
                ffmpegcmd = [
                    ffmpeg, '-hide_banner', '-loglevel', 'error',
                    '-i', filename, '-ss', '00:00:30', '-vframes', '1',
                    image_filename, '-nostdin'
                ]
                if config.debug:
                    print(f"🟡 [DEBUG] Starting cover image extraction for {filename_pretty}")
                    print(f"🟡 [DEBUG] CLI: {' '.join(ffmpegcmd)}")
                    cover_start = time.time()
                if dry_run:
                    print(f"[DRY RUN] Would extract cover image using: {' '.join(ffmpegcmd)}")
                    performed_options.append("cover (dry run)")
                    if config.debug:
                        cover_elapsed = time.time() - cover_start
                        print(f"🟡 [DEBUG] Finished cover image extraction for {filename_pretty} in {cover_elapsed:.2f} seconds")
                else:
                    try:
                        subprocess.run(ffmpegcmd, check=True)
                        if not os.path.exists(image_filename):
                            ffmpegcmd[ffmpegcmd.index('-ss') + 1] = '00:00:05'
                            subprocess.run(ffmpegcmd, check=True)
                        if not os.path.exists(image_filename):
                            raise FileNotFoundError(f"Cover image not created: {image_filename}")
                        with open(image_filename, "rb") as img:
                            encoded = base64.b64encode(img.read()).decode()
                        update_cover(scene_id, "data:image/jpg;base64," + encoded)
                        performed_options.append("cover")
                        if config.debug:
                            cover_elapsed = time.time() - cover_start
                            print(f"🟡 [DEBUG] Finished cover image extraction for {filename_pretty} in {cover_elapsed:.2f} seconds")
                    except Exception as e:
                        log_scene_failure(scene_id, filename_pretty, "cover image generation", e)
                        tag_scene_error(scene_id, cover_error_tag, str(e))
                    finally:
                        shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            log_scene_failure(scene_id, filename_pretty, "cover image setup", e)
            tag_scene_error(scene_id, cover_error_tag, str(e))

        if generate_sprite:
            sprite_file = os.path.join(sprite_path, f"{filehash}_sprite.jpg")
            vtt_file = os.path.join(sprite_path, f"{filehash}_thumbs.vtt")
        # VAAPI notification handled by main script
            sprite_cmd = f"{ffmpeg} -i '{filename}' -vf 'scale=320:240,tile=5x5' -frames:v 1 '{sprite_file}'"
            if not os.path.exists(sprite_file):
                if config.debug:
                    print(f"🟡 [DEBUG] Starting sprite generation for {filename_pretty}")
                    print(f"🟡 [DEBUG] CLI: {sprite_cmd}")
                    sprite_start = time.time()
                if dry_run:
                    print(f"[DRY RUN] Would generate sprite for {filename_pretty} → {sprite_file}")
                    performed_options.append("sprite (dry run)")
                    if config.debug:
                        sprite_elapsed = time.time() - sprite_start
                        print(f"🟡 [DEBUG] Finished sprite generation for {filename_pretty} in {sprite_elapsed:.2f} seconds")
                else:
                    try:
                        generator = VideoSpriteGenerator(
                            filename, sprite_file, vtt_file, filehash, ffmpeg, ffprobe,
                            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
                        )
                        sprite_start = time.time()
                        generator.generate_sprite()
                        sprite_elapsed = time.time() - sprite_start
                        performed_options.append("sprite")
                        if config.verbose:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Sprite generation complete for {filename_pretty} in {sprite_elapsed:.2f} seconds.")
                    except Exception as e:
                        log_scene_failure(scene_id, filename_pretty, "sprite generation", e)
                        tag_scene_error(scene_id, hashing_error_tag, str(e))
                        success = False
                        # Don't return early - continue to release scene

        if generate_preview:
            preview_file = os.path.join(preview_path, f"{filehash}.mp4")
        # VAAPI notification handled by main script
            if vaapi_supported and vaapi_device:
                preview_cmd = f"{ffmpeg} -vaapi_device {vaapi_device} -ss 0 -i '{filename}' -vf 'format=nv12,hwupload,scale_vaapi=640:360' -c:v h264_vaapi -crf 18 -preset fast -an -y '{preview_file}'"
            else:
                preview_cmd = f"{ffmpeg} -i '{filename}' -vf 'scale=640:360' -c:v libx264 -crf 18 -preset slow -an -y '{preview_file}'"
            if not os.path.exists(preview_file):
                if config.debug:
                    print(f"🟡 [DEBUG] Starting preview generation for {filename_pretty}")
                    print(f"🟡 [DEBUG] CLI: {preview_cmd}")
                    preview_start = time.time()
                if dry_run:
                    print(f"[DRY RUN] Would generate preview for {filename_pretty} → {preview_file}")
                    performed_options.append("preview (dry run)")
                    if config.debug:
                        preview_elapsed = time.time() - preview_start
                        print(f"🟡 [DEBUG] Finished preview generation for {filename_pretty} in {preview_elapsed:.2f} seconds")
                else:
                    try:
                        if vaapi_supported:
                            vaapi_used = True
                            performed_options.append("preview (vaapi)")
                        preview_start = time.time()
                        generator = PreviewVideoGenerator(
                            filename, preview_file, filehash,
                            ffmpeg=ffmpeg, ffprobe=ffprobe,
                            preview_clips=preview_clips, clip_length=preview_clip_length,
                            skip_seconds=preview_skip_seconds, include_audio=preview_audio,
                            scene_id=scene_id, scene_name=filename_pretty,
                            use_vaapi=vaapi_supported, vaapi_device=vaapi_device
                        )
                        generator.generate_preview()
                        preview_elapsed = time.time() - preview_start
                        if not vaapi_used:
                            performed_options.append("preview")
                        if config.verbose:
                            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Preview generation complete for {filename_pretty} in {preview_elapsed:.2f} seconds.")
                    except Exception as e:
                        log_scene_failure(scene_id, filename_pretty, "preview generation", e)
                        tag_scene_error(scene_id, hashing_error_tag, str(e))
                        success = False
                        # Don't return early - continue to release scene

        end_time = time.time()
        elapsed = end_time - start_time
        options_str = ', '.join(performed_options) if performed_options else 'none'
        vaapi_note = " (VAAPI used)" if vaapi_used else ""
        if config.verbose and success:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Processed scene file '{filename_pretty}' in {elapsed:.2f} seconds. Options performed: {options_str}{vaapi_note}")

        return {'success': success, 'elapsed_time': elapsed, 'scene_id': scene_id}

    finally:
        release_scene(scene_id)
