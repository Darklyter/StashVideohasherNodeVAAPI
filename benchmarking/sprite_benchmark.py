#!/usr/bin/env python3
"""
Sprite Benchmark Script
Benchmarks VAAPI vs non-VAAPI sprite generation for a single video.
Uses config.py for sprite parameters. Output folder via CLI.
Generates a single sprite sheet (grid) of images from the video.
"""
import os
import sys
import time
import argparse
import subprocess
from config import ffmpeg, ffprobe, verbose
from helpers.vaapi_utils import vaapi_available
from PIL import Image

# Sprite grid parameters (customize as needed or add to config.py)
SPRITE_COLUMNS = 10  # Number of columns in the grid
SPRITE_ROWS = 5      # Number of rows in the grid
SPRITE_WIDTH = 160   # Width of each thumbnail
SPRITE_HEIGHT = 90   # Height of each thumbnail


def get_video_duration(filename):
    result = subprocess.run([
        ffprobe, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', filename
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return float(result.stdout)


def combine_frames_to_sprite(frame_files, output_file, columns, rows, thumb_width, thumb_height):
    sprite = Image.new('RGB', (columns * thumb_width, rows * thumb_height))
    for idx, frame_file in enumerate(frame_files):
        if idx >= columns * rows:
            break
        img = Image.open(frame_file).resize((thumb_width, thumb_height), Image.LANCZOS)
        x = (idx % columns) * thumb_width
        y = (idx // columns) * thumb_height
        sprite.paste(img, (x, y))
    sprite.save(output_file)


def run_ffmpeg_sprite(input_file, output_file, use_vaapi):
    total_thumbs = SPRITE_COLUMNS * SPRITE_ROWS
    duration = get_video_duration(input_file)
    interval = duration / (total_thumbs + 1)
    timestamps = [interval * (i + 1) for i in range(total_thumbs)]
    frame_files = []
    start = time.time()
    if use_vaapi:
        # Extract frames individually with VAAPI
        for idx, ts in enumerate(timestamps):
            frame_file = f"{output_file}_vaapi_{idx}.png"
            extract_frame_vaapi(input_file, ts, frame_file)
            frame_files.append(frame_file)
        # Combine frames into sprite sheet
        combine_frames_to_sprite(frame_files, output_file, SPRITE_COLUMNS, SPRITE_ROWS, SPRITE_WIDTH, SPRITE_HEIGHT)
        for f in frame_files:
            try:
                os.remove(f)
            except Exception:
                pass
        elapsed = time.time() - start
        return elapsed
    else:
        # Extract frames individually with software pipeline using same timestamps
        for idx, ts in enumerate(timestamps):
            frame_file = f"{output_file}_sw_{idx}.png"
            extract_frame_sw(input_file, ts, frame_file)
            frame_files.append(frame_file)
        # Combine frames into sprite sheet
        combine_frames_to_sprite(frame_files, output_file, SPRITE_COLUMNS, SPRITE_ROWS, SPRITE_WIDTH, SPRITE_HEIGHT)
        for f in frame_files:
            try:
                os.remove(f)
            except Exception:
                pass
        elapsed = time.time() - start
        return elapsed


def extract_frame_sw(input_file, timestamp, output_file):
    start = time.time()
    command = [
        ffmpeg, '-v', 'error', '-y',
        '-ss', str(timestamp), '-i', input_file,
        '-frames:v', '1',
        '-vf', f'scale={SPRITE_WIDTH}:-2',
        '-c:v', 'png', output_file
    ]
    if verbose:
        print('Software FFmpeg command:', ' '.join(command))
    subprocess.run(command, check=True)
    elapsed = time.time() - start
    return elapsed


def extract_frame_vaapi(input_file, timestamp, output_file):
    start = time.time()
    command = [
        ffmpeg, '-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi',
        '-vaapi_device', '/dev/dri/renderD128',
        '-v', 'error', '-y',
        '-ss', str(timestamp), '-i', input_file,
        '-frames:v', '1',
        '-vf', 'scale_vaapi=160:-2,hwdownload,format=nv12',
        '-c:v', 'png', output_file
    ]
    if verbose:
        print('VAAPI FFmpeg command:', ' '.join(command))
    subprocess.run(command, check=True)
    elapsed = time.time() - start
    return elapsed


def main():
    parser = argparse.ArgumentParser(description='Sprite Benchmark: VAAPI vs non-VAAPI')
    parser.add_argument('input', help='Input video file')
    parser.add_argument('output_dir', help='Output directory for sprite sheets')
    parser.add_argument('--vaapi', action='store_true', help='Force VAAPI')
    parser.add_argument('--novaapi', action='store_true', help='Force software (no VAAPI)')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')
    args = parser.parse_args()

    input_file = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    sprite_vaapi = os.path.join(output_dir, f'{base_name}_sprite_vaapi.png')
    sprite_sw = os.path.join(output_dir, f'{base_name}_sprite_sw.png')

    vaapi_ok, vaapi_device = vaapi_available()
    use_vaapi = args.vaapi or (vaapi_ok and not args.novaapi)
    if args.verbose:
        print(f"VAAPI available: {vaapi_ok}, device: {vaapi_device}")
        print(f"Using VAAPI: {use_vaapi}")

    # VAAPI benchmark
    if use_vaapi:
        print("\n[VAAPI] Generating sprite sheet...")
        try:
            t_vaapi = run_ffmpeg_sprite(input_file, sprite_vaapi, use_vaapi=True)
            print(f"VAAPI sprite generated in {t_vaapi:.2f} seconds: {sprite_vaapi}")
        except Exception as e:
            print(f"VAAPI sprite generation failed: {e}")
    else:
        print("\n[VAAPI] Skipped (not available or forced off)")

    # Software benchmark
    print("\n[Software] Generating sprite sheet...")
    try:
        t_sw = run_ffmpeg_sprite(input_file, sprite_sw, use_vaapi=False)
        print(f"Software sprite generated in {t_sw:.2f} seconds: {sprite_sw}")
    except Exception as e:
        print(f"Software sprite generation failed: {e}")

    # Example: Extract 3 frames at specific timestamps (10, 30, 60 seconds)
    timestamps = [10, 30, 60]
    for ts in timestamps:
        out_sw = os.path.join(output_dir, f'{base_name}_sw_{ts}.png')
        out_vaapi = os.path.join(output_dir, f'{base_name}_vaapi_{ts}.png')
        print(f'Extracting frame at {ts}s (software)...')
        try:
            t_sw = extract_frame_sw(input_file, ts, out_sw)
            print(f'Software frame saved: {out_sw} in {t_sw:.2f} seconds')
        except Exception as e:
            print(f'Software extraction failed at {ts}s: {e}')
        if use_vaapi:
            print(f'Extracting frame at {ts}s (VAAPI)...')
            try:
                t_vaapi = extract_frame_vaapi(input_file, ts, out_vaapi)
                print(f'VAAPI frame saved: {out_vaapi} in {t_vaapi:.2f} seconds')
            except Exception as e:
                print(f'VAAPI extraction failed at {ts}s: {e}')

if __name__ == '__main__':
    main()
