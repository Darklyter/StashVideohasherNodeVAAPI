#!/usr/bin/env python3
"""
Preview Benchmark
Benchmarks preview video generation using the same pipeline as PreviewVideoGenerator.
Supports VAAPI, NVENC, and software encoding. Mirrors the encoder priority logic
used by the main script so results reflect real-world performance.

Usage:
    python benchmarking/preview_benchmark.py --input video.mkv --output preview.mp4 [options]
    python benchmarking/preview_benchmark.py --input video.mkv --output preview.mp4 --all
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


def get_start_times(duration, num_clips, clip_length, skip_seconds):
    usable = duration - skip_seconds - clip_length
    if usable <= 0:
        raise RuntimeError(
            f"Video too short ({duration:.1f}s) for skip_seconds={skip_seconds} + clip_length={clip_length}"
        )
    interval = usable / (num_clips + 1)
    return [skip_seconds + interval * i for i in range(1, num_clips + 1)]


def extract_clip(ffmpeg, input_file, clip_file, start_time, clip_length, encoder, vaapi_device, verbose):
    if encoder == 'vaapi':
        command = [
            ffmpeg,
            '-vaapi_device', vaapi_device,
            '-ss', str(start_time),
            '-i', input_file,
            '-t', str(clip_length),
            '-vf', 'format=nv12,hwupload,scale_vaapi=640:360',
            '-c:v', 'h264_vaapi',
            '-global_quality', '18',
            '-an', '-y', '-loglevel', 'quiet',
            clip_file
        ]
    elif encoder == 'nvenc':
        command = [
            ffmpeg,
            '-ss', str(start_time),
            '-i', input_file,
            '-t', str(clip_length),
            '-s', '640x360',
            '-c:v', 'h264_nvenc',
            '-cq:v', '18',
            '-preset', 'p4',
            '-an', '-y', '-loglevel', 'quiet',
            clip_file
        ]
    else:
        command = [
            ffmpeg,
            '-ss', str(start_time),
            '-i', input_file,
            '-t', str(clip_length),
            '-s', '640x360',
            '-c:v', 'libx264',
            '-crf', '18',
            '-preset', 'slow',
            '-an', '-y', '-loglevel', 'quiet',
            clip_file
        ]
    if verbose:
        print(f"  clip: {' '.join(command)}")
    subprocess.run(command, check=True)
    return clip_file


def concatenate_clips(ffmpeg, clip_files, concat_list, output_file, encoder, vaapi_device, verbose):
    with open(concat_list, 'w') as f:
        for clip in sorted(clip_files):
            safe_path = os.path.normpath(clip).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    command = [ffmpeg]
    if encoder == 'vaapi':
        command.extend([
            '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-vaapi_device', vaapi_device,
            '-vf', 'format=nv12,hwupload,scale_vaapi=640:360',
            '-c:v', 'h264_vaapi',
            '-global_quality', '18',
            '-an', '-y', '-loglevel', 'quiet',
            output_file
        ])
    elif encoder == 'nvenc':
        command.extend([
            '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-vf', 'scale=640:360',
            '-c:v', 'h264_nvenc',
            '-cq:v', '18',
            '-preset', 'p4',
            '-an', '-y', '-loglevel', 'quiet',
            output_file
        ])
    else:
        command.extend([
            '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-vf', 'scale=640:360',
            '-c:v', 'libx264',
            '-crf', '18',
            '-preset', 'slow',
            '-an', '-y', '-loglevel', 'quiet',
            output_file
        ])
    if verbose:
        print(f"  concat: {' '.join(command)}")
    subprocess.run(command, check=True)


def run_benchmark(input_file, output_file, encoder, vaapi_device, num_clips, clip_length, skip_seconds, verbose):
    label = {'vaapi': 'VAAPI', 'nvenc': 'NVENC', 'software': 'Software'}.get(encoder, encoder)
    print(f"\n[{label}] Starting preview generation...")

    temp_dir = os.path.join(os.getcwd(), ".tmp", f"bench_preview_{encoder}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        duration = get_video_duration(input_file)
        start_times = get_start_times(duration, num_clips, clip_length, skip_seconds)

        t_clips_start = time.time()
        clip_files = []

        def _extract(args):
            i, start = args
            clip_file = os.path.join(temp_dir, f"clip_{i:03d}.mp4")
            return extract_clip(config.ffmpeg, input_file, clip_file, start, clip_length,
                                encoder, vaapi_device, verbose)

        with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
            clip_files = list(executor.map(_extract, enumerate(start_times)))

        t_clips_elapsed = time.time() - t_clips_start
        print(f"  Clip extraction ({num_clips} clips): {t_clips_elapsed:.2f}s")

        concat_list = os.path.join(temp_dir, "clips.txt")
        t_concat_start = time.time()
        concatenate_clips(config.ffmpeg, clip_files, concat_list, output_file,
                          encoder, vaapi_device, verbose)
        t_concat_elapsed = time.time() - t_concat_start
        print(f"  Concatenation: {t_concat_elapsed:.2f}s")

        total = t_clips_elapsed + t_concat_elapsed
        size_mb = os.path.getsize(output_file) / (1024 * 1024) if os.path.exists(output_file) else 0
        print(f"  Total: {total:.2f}s  |  Output: {size_mb:.1f} MB → {output_file}")
        return total

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def resolve_encoder(vaapi_ok, vaapi_device, use_vaapi_flag, no_vaapi_flag, nvenc_flag, hw_priority):
    """Apply the same priority logic as the main script."""
    vaapi_supported = vaapi_ok

    # CLI overrides
    if use_vaapi_flag:
        vaapi_supported = True
        vaapi_device = vaapi_device or '/dev/dri/renderD128'
    elif no_vaapi_flag:
        vaapi_supported = False
        vaapi_device = None

    nvenc = nvenc_flag or config.nvenc

    # hw_priority tiebreak
    if vaapi_supported and nvenc and hw_priority == 'nvenc':
        vaapi_supported = False
        vaapi_device = None

    if vaapi_supported:
        return 'vaapi', vaapi_device
    elif nvenc:
        return 'nvenc', None
    else:
        return 'software', None


def main():
    parser = argparse.ArgumentParser(
        description='Preview generation benchmark — mirrors PreviewVideoGenerator pipeline'
    )
    parser.add_argument('--input',    required=True, help='Input video file')
    parser.add_argument('--output',   required=True, help='Output preview file (or base name for --all)')
    parser.add_argument('--vaapi',    action='store_true', help='Force VAAPI on')
    parser.add_argument('--novaapi',  action='store_true', help='Force VAAPI off')
    parser.add_argument('--nvenc',    action='store_true', help='Use NVIDIA NVENC encoder')
    parser.add_argument('--hw-priority', choices=['vaapi', 'nvenc'], default=None,
                        help='Encoder priority when both are available (default: vaapi)')
    parser.add_argument('--clips',    type=int,  default=config.preview_clips,
                        help=f'Number of clips to extract (default: {config.preview_clips})')
    parser.add_argument('--clip-length', type=float, default=config.preview_clip_length,
                        help=f'Duration of each clip in seconds (default: {config.preview_clip_length})')
    parser.add_argument('--skip',     type=float, default=config.preview_skip_seconds,
                        help=f'Seconds to skip from start (default: {config.preview_skip_seconds})')
    parser.add_argument('--all',      action='store_true',
                        help='Benchmark all available encoders and compare')
    parser.add_argument('--verbose',  action='store_true', help='Show FFmpeg commands')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}")
        sys.exit(1)

    os.makedirs(os.path.join(os.getcwd(), ".tmp"), exist_ok=True)

    vaapi_ok, vaapi_device = vaapi_available() if not config.windows else (False, None)
    hw_priority = args.hw_priority or config.hw_priority

    print(f"\n{'='*60}")
    print(f"Preview Benchmark  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Input:     {args.input}")
    print(f"Clips:     {args.clips} × {args.clip_length}s  (skip {args.skip}s)")
    print(f"VAAPI:     {'detected @ ' + vaapi_device if vaapi_ok else 'not available'}")
    print(f"NVENC:     {'enabled' if (args.nvenc or config.nvenc) else 'disabled'}")
    print(f"{'='*60}")

    results = {}

    if args.all:
        base, ext = os.path.splitext(args.output)
        ext = ext or '.mp4'

        if vaapi_ok or args.vaapi:
            dev = vaapi_device or '/dev/dri/renderD128'
            out = f"{base}_vaapi{ext}"
            try:
                results['VAAPI'] = run_benchmark(args.input, out, 'vaapi', dev,
                                                 args.clips, args.clip_length, args.skip, args.verbose)
            except Exception as e:
                print(f"  VAAPI failed: {e}")

        if args.nvenc or config.nvenc:
            out = f"{base}_nvenc{ext}"
            try:
                results['NVENC'] = run_benchmark(args.input, out, 'nvenc', None,
                                                 args.clips, args.clip_length, args.skip, args.verbose)
            except Exception as e:
                print(f"  NVENC failed: {e}")

        out = f"{base}_software{ext}"
        try:
            results['Software'] = run_benchmark(args.input, out, 'software', None,
                                                args.clips, args.clip_length, args.skip, args.verbose)
        except Exception as e:
            print(f"  Software failed: {e}")

        if len(results) > 1:
            print(f"\n{'='*60}")
            print("Comparison:")
            fastest_name = min(results, key=results.get)
            fastest_time = results[fastest_name]
            for name, t in sorted(results.items(), key=lambda x: x[1]):
                speedup = f"  {results[list(results.keys())[-1]] / t:.1f}× faster than slowest" if name == fastest_name else ""
                print(f"  {name:<12} {t:.2f}s{speedup}")
            print(f"{'='*60}")

    else:
        encoder, device = resolve_encoder(vaapi_ok, vaapi_device,
                                          args.vaapi, args.novaapi,
                                          args.nvenc, hw_priority)
        label = {'vaapi': 'VAAPI', 'nvenc': 'NVENC', 'software': 'Software'}[encoder]
        print(f"Encoder:   {label}" + (f" ({device})" if device else ""))

        try:
            run_benchmark(args.input, args.output, encoder, device,
                          args.clips, args.clip_length, args.skip, args.verbose)
        except Exception as e:
            print(f"Benchmark failed: {e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
