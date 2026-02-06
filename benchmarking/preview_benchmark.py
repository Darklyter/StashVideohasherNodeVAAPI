import subprocess
import os
import time
import tempfile
import shutil
import config

def get_video_duration(input_file, ffprobe=None):
    ffprobe = ffprobe or config.ffprobe
    result = subprocess.run([
        ffprobe, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', input_file
    ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return float(result.stdout)

def run_ffmpeg_clip(input_file, output_file, start_time, clip_length, use_vaapi=False, ffmpeg=None):
    ffmpeg = ffmpeg or config.ffmpeg
    cmd = [ffmpeg]
    if use_vaapi:
        cmd += ['-vaapi_device', '/dev/dri/renderD128']
        vf_str = 'format=nv12,hwupload,scale_vaapi=640:360'
        codec = 'h264_vaapi'
        preset = 'fast'
    else:
        vf_str = 'scale=640:360'
        codec = 'libx264'
        preset = 'slow'
    cmd += [
        '-ss', str(start_time),
        '-i', input_file,
        '-t', str(clip_length),
        '-vf', vf_str,
        '-c:v', codec,
        '-crf', '18',
        '-preset', preset,
        '-an',  # Disable audio
        '-y', output_file
    ]
    # Mute ffmpeg output unless verbose
    import sys
    verbose = '--verbose' in sys.argv
    stdout_opt = None if verbose else subprocess.DEVNULL
    stderr_opt = None if verbose else subprocess.DEVNULL
    subprocess.run(cmd, check=True, stdout=stdout_opt, stderr=stderr_opt)
    return ' '.join(cmd)

def concatenate_clips(clips, output_file, ffmpeg=None, raw264=False):
    ffmpeg = ffmpeg or config.ffmpeg
    concat_file = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.txt')
    for clip in clips:
        concat_file.write(f"file '{os.path.abspath(clip)}'\n")
    concat_file.close()
    cmd = [
        ffmpeg,
        '-f', 'concat',
        '-safe', '0',
        '-i', concat_file.name,
        '-c:v', 'copy' if raw264 else 'libx264',
        '-an',  # Disable audio
        '-y', output_file
    ]
    if not raw264:
        cmd += ['-crf', '18', '-preset', 'fast']
    import sys
    verbose = '--verbose' in sys.argv
    stdout_opt = None if verbose else subprocess.DEVNULL
    stderr_opt = None if verbose else subprocess.DEVNULL
    subprocess.run(cmd, check=True, stdout=stdout_opt, stderr=stderr_opt)
    os.unlink(concat_file.name)
    return ' '.join(cmd)

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Multi-clip preview benchmark using config.py')
    parser.add_argument('--input', required=True, help='Input video file')
    parser.add_argument('--output', required=True, help='Output preview file')
    parser.add_argument('--vaapi', action='store_true', help='Use VAAPI hardware acceleration')
    parser.add_argument('--verbose', action='store_true', help='Show ffmpeg commands and timing')
    parser.add_argument('--raw264', action='store_true', help='Output raw H.264 (.264)')
    args = parser.parse_args()

    input_file = args.input
    output_file = args.output
    clips = config.preview_clips
    clip_length = config.preview_clip_length
    skip_seconds = config.preview_skip_seconds
    use_vaapi = args.vaapi
    verbose = args.verbose
    raw264 = args.raw264
    out_file = args.output
    if raw264:
        out_file = os.path.splitext(args.output)[0] + '.264'

    if not os.path.exists(input_file):
        print(f'Input file not found: {input_file}')
        return

    temp_dir = tempfile.mkdtemp(prefix='preview_benchmark_', dir=os.path.expanduser('~'))
    try:
        duration = get_video_duration(input_file)
        interval = (duration - skip_seconds - clip_length) / (clips + 1)
        start_times = [skip_seconds + interval * i for i in range(1, clips + 1)]
        print(f'\nTesting {"VAAPI" if use_vaapi else "Software"} preview generation...')
        clip_files = []
        t0 = time.time()
        for idx, start in enumerate(start_times):
            clip_file = os.path.join(temp_dir, f'clip_{idx:03d}.mp4')
            cmd_str = run_ffmpeg_clip(input_file, clip_file, start, clip_length, use_vaapi)
            if verbose:
                print(f'Clip {idx+1}: {cmd_str}')
            clip_files.append(clip_file)
        concat_cmd = concatenate_clips(clip_files, out_file, raw264=raw264)
        t1 = time.time()
        if verbose:
            print(f'Concat: {concat_cmd}')
        print(f'Preview generation took {t1-t0:.2f} seconds')
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

if __name__ == '__main__':
    main()
