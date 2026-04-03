#!/usr/bin/env python3
"""
Sprite Benchmark
Benchmarks sprite sheet generation using the same pipeline as VideoSpriteGenerator.
Supports VAAPI and software extraction. Mirrors the exact FFmpeg commands and
PIL resize logic used by the main script so results reflect real-world performance.

Usage:
    python benchmarking/sprite_benchmark.py --input video.mkv --output sprite.jpg [options]
    python benchmarking/sprite_benchmark.py --input video.mkv --output sprite.jpg --all
"""

import os
import sys
import time
import shutil
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from helpers.vaapi_utils import vaapi_available
from PIL import Image


def get_video_duration(input_file):
    result = subprocess.run([
        config.ffprobe, '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        input_file
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        stderr = result.stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(f"Could not determine duration for {input_file}: {stderr}")


def extract_frame(input_file, timestamp, output_file, use_vaapi, vaapi_device, max_width, max_height, verbose):
    """Extract a single frame — mirrors VideoSpriteGenerator.extract_and_resize()"""
    if use_vaapi:
        command = [
            config.ffmpeg, '-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi',
            '-vaapi_device', vaapi_device,
            '-v', 'error', '-y',
            '-ss', str(timestamp), '-i', input_file,
            '-frames:v', '1',
            '-vf', f'scale_vaapi={max_width}:-2,hwdownload,format=bgr0',
            '-c:v', 'png', output_file,
            '-loglevel', 'quiet'
        ]
    else:
        command = [
            config.ffmpeg,
            '-ss', str(timestamp),
            '-i', input_file,
            '-frames:v', '1',
            '-q:v', '2',
            output_file,
            '-loglevel', 'quiet'
        ]
    if verbose:
        print(f"  frame: {' '.join(command)}")
    subprocess.run(command, check=True)
    # Resize in PIL — matches VideoSpriteGenerator.extract_and_resize()
    with Image.open(output_file) as img:
        img = img.resize((max_width, max_height), Image.Resampling.LANCZOS)
        img.save(output_file)
    return output_file


def build_sprite(frame_files, output_file, columns, rows, max_width, max_height):
    """Assemble extracted frames into a sprite sheet — mirrors VideoSpriteGenerator.create_sprite()"""
    sprite = Image.new('RGB', (columns * max_width, rows * max_height))
    for idx, frame_file in enumerate(frame_files):
        with Image.open(frame_file) as img:
            x = (idx % columns) * max_width
            y = (idx // columns) * max_height
            sprite.paste(img, (x, y))
    sprite.save(output_file)


def run_benchmark(input_file, output_file, use_vaapi, vaapi_device,
                  total_shots, columns, rows, max_width, max_height, verbose):
    label = 'VAAPI' if use_vaapi else 'Software'
    print(f"\n[{label}] Starting sprite generation ({columns}×{rows} = {total_shots} frames)...")

    temp_dir = os.path.join(os.getcwd(), ".tmp", f"bench_sprite_{'vaapi' if use_vaapi else 'software'}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        duration = get_video_duration(input_file)
        interval = duration / total_shots
        timestamps = [i * interval for i in range(total_shots)]

        t_frames_start = time.time()

        def _extract(args):
            i, ts = args
            frame_file = os.path.join(temp_dir, f'frame_{i:03d}.jpg')
            return extract_frame(input_file, ts, frame_file, use_vaapi, vaapi_device,
                                 max_width, max_height, verbose)

        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
            frame_files = list(executor.map(_extract, enumerate(timestamps)))

        t_frames_elapsed = time.time() - t_frames_start
        print(f"  Frame extraction ({total_shots} frames): {t_frames_elapsed:.2f}s")

        t_sprite_start = time.time()
        build_sprite(frame_files, output_file, columns, rows, max_width, max_height)
        t_sprite_elapsed = time.time() - t_sprite_start
        print(f"  Sprite assembly: {t_sprite_elapsed:.2f}s")

        total = t_frames_elapsed + t_sprite_elapsed
        size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
        print(f"  Total: {total:.2f}s  |  Output: {size_mb:.1f} MB → {output_file}")
        return total

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description='Sprite generation benchmark — mirrors VideoSpriteGenerator pipeline'
    )
    parser.add_argument('--input',    required=True, help='Input video file')
    parser.add_argument('--output',   required=True, help='Output sprite file (or base name for --all)')
    parser.add_argument('--vaapi',    action='store_true', help='Force VAAPI on')
    parser.add_argument('--novaapi',  action='store_true', help='Force VAAPI off')
    parser.add_argument('--columns',  type=int, default=9,   help='Sprite grid columns (default: 9)')
    parser.add_argument('--rows',     type=int, default=9,   help='Sprite grid rows (default: 9)')
    parser.add_argument('--width',    type=int, default=160, help='Thumbnail width in pixels (default: 160)')
    parser.add_argument('--height',   type=int, default=90,  help='Thumbnail height in pixels (default: 90)')
    parser.add_argument('--all',      action='store_true',
                        help='Benchmark both VAAPI and software and compare')
    parser.add_argument('--verbose',  action='store_true', help='Show FFmpeg commands')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    os.makedirs(os.path.join(os.getcwd(), ".tmp"), exist_ok=True)

    total_shots = args.columns * args.rows
    vaapi_ok, vaapi_device = vaapi_available() if not config.windows else (False, None)

    print(f"\n{'='*60}")
    print(f"Sprite Benchmark  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Input:     {args.input}")
    print(f"Grid:      {args.columns}×{args.rows} = {total_shots} frames  ({args.width}×{args.height}px each)")
    print(f"VAAPI:     {'detected @ ' + vaapi_device if vaapi_ok else 'not available'}")
    print(f"{'='*60}")

    results = {}

    if args.all:
        base, ext = os.path.splitext(args.output)
        ext = ext or '.jpg'

        if vaapi_ok or args.vaapi:
            dev = vaapi_device or '/dev/dri/renderD128'
            out = f"{base}_vaapi{ext}"
            try:
                results['VAAPI'] = run_benchmark(args.input, out, True, dev,
                                                 total_shots, args.columns, args.rows,
                                                 args.width, args.height, args.verbose)
            except Exception as e:
                print(f"  VAAPI failed: {e}")

        out = f"{base}_software{ext}"
        try:
            results['Software'] = run_benchmark(args.input, out, False, None,
                                                total_shots, args.columns, args.rows,
                                                args.width, args.height, args.verbose)
        except Exception as e:
            print(f"  Software failed: {e}")

        if len(results) > 1:
            print(f"\n{'='*60}")
            print("Comparison:")
            fastest_name = min(results, key=results.get)
            for name, t in sorted(results.items(), key=lambda x: x[1]):
                speedup = f"  {results[max(results, key=results.get)] / t:.1f}× faster than slowest" if name == fastest_name else ""
                print(f"  {name:<12} {t:.2f}s{speedup}")
            print(f"{'='*60}")

    else:
        if args.novaapi:
            use_vaapi, device = False, None
        elif args.vaapi:
            use_vaapi, device = True, vaapi_device or '/dev/dri/renderD128'
        else:
            use_vaapi, device = vaapi_ok, vaapi_device

        label = 'VAAPI' if use_vaapi else 'Software'
        print(f"Encoder:   {label}" + (f" ({device})" if device else ""))

        try:
            run_benchmark(args.input, args.output, use_vaapi, device,
                          total_shots, args.columns, args.rows,
                          args.width, args.height, args.verbose)
        except Exception as e:
            print(f"Benchmark failed: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
