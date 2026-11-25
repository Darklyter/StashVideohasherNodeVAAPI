# preview_video_generator.py

import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from tqdm import tqdm

import config
from helpers import ffmpeg_utils


class PreviewVideoGenerator:
    def __init__(self, filename, output_path, filehash, ffmpeg='ffmpeg', ffprobe='ffprobe',
                 preview_clips=15, clip_length=1, skip_seconds=0, include_audio=True,
                 scene_id=None, scene_name=None, use_vaapi=None, vaapi_device=None):
        self.filename = os.path.abspath(filename.strip('"').strip("'"))
        self.output_path = os.path.abspath(output_path)
        self.temp_dir = ffmpeg_utils.tmp_path(f"preview_temp_{filehash}")
        self.num_clips = preview_clips
        self.clip_length = clip_length
        self.skip_seconds = skip_seconds
        self.include_audio = include_audio
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.scene_id = scene_id
        self.scene_name = scene_name
        self.use_vaapi = use_vaapi
        self.vaapi_device = vaapi_device

    def get_video_duration(self):
        return ffmpeg_utils.probe_duration(self.filename)

    def clean_previous_clips(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def get_start_times(self, video_duration):
        usable = video_duration - self.skip_seconds - self.clip_length
        if usable <= 0:
            raise RuntimeError(
                f"Video too short ({video_duration:.1f}s) for skip_seconds={self.skip_seconds} + clip_length={self.clip_length}"
            )
        interval = usable / (self.num_clips + 1)
        return [self.skip_seconds + interval * i for i in range(1, self.num_clips + 1)]

    def plan_clips(self, video_duration):
        """
        Return [(start, length), ...]. Videos too short for the normal sampling
        get a single clip from the start instead of failing forever.
        """
        if not video_duration or video_duration <= 0:
            raise RuntimeError(f"Invalid video duration ({video_duration}) for {self.filename}")
        try:
            return [(start, self.clip_length) for start in self.get_start_times(video_duration)]
        except RuntimeError:
            return [(0, min(video_duration, self.num_clips * self.clip_length))]

    def _clip_command(self, start_time, length, clip_file):
        use_vaapi = bool(self.use_vaapi) and bool(self.vaapi_device)
        input_opts, output_opts = ffmpeg_utils.h264_encode_args(use_vaapi, self.vaapi_device, width=640)
        audio_args = ['-c:a', 'aac', '-b:a', '192k'] if self.include_audio else ['-an']
        # -t goes BEFORE -i so it limits the input: as an output option the decoder
        # keeps running past the clip, hwupload's surface pool overflows and
        # ffmpeg dies with ENOMEM (exit 244) on VAAPI.
        return ([self.ffmpeg] + input_opts +
                ['-ss', str(start_time), '-t', str(length), '-i', self.filename] +
                output_opts + audio_args +
                ['-y', '-loglevel', 'error', clip_file])

    def generate_clips(self):
        os.makedirs(self.temp_dir, exist_ok=True)
        plan = self.plan_clips(self.get_video_duration())
        errors = []

        def extract_clip(i, start_time, length):
            clip_file = os.path.join(self.temp_dir, f"clip_{i:03d}.mp4")
            try:
                ffmpeg_utils.run(self._clip_command(start_time, length, clip_file), timeout=300)
            except Exception as e:
                detail = ffmpeg_utils.error_detail(e)
                errors.append(detail)
                print(f"❌ Failed to generate clip {i} for scene {self.scene_id} — {self.scene_name}: {detail}")
                return None
            return clip_file if os.path.exists(clip_file) else None

        clips = []
        executor = ThreadPoolExecutor(max_workers=config.max_workers)
        try:
            futures = [executor.submit(extract_clip, i, start, length) for i, (start, length) in enumerate(plan)]
            iterator = tqdm(futures, desc="🎞️ Generating Preview Clips", unit="clip") if config.verbose else futures
            for future in iterator:
                clip = future.result()
                if clip:
                    clips.append(clip)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        if not clips:
            raise RuntimeError(f"No preview clips could be generated: {errors[0] if errors else 'unknown error'}")
        return clips

    def concatenate_clips(self, clips):
        missing = [clip for clip in clips if not os.path.exists(clip)]
        if missing:
            raise FileNotFoundError(f"Missing clips: {missing}")

        concat_file = os.path.join(self.temp_dir, "clips.txt")
        with open(concat_file, 'w') as f:
            for clip in sorted(clips):
                safe_path = os.path.normpath(clip).replace("\\", "/")
                f.write(f"file '{safe_path}'\n")

        # Clips were all encoded with identical settings, so they are joined with a
        # stream copy — no second encode, no extra quality loss.
        with ffmpeg_utils.atomic_output(self.output_path) as tmp_output:
            command = [
                self.ffmpeg, '-f', 'concat', '-safe', '0', '-i', concat_file,
                '-c', 'copy', '-y', '-loglevel', 'error', tmp_output,
            ]
            try:
                ffmpeg_utils.run(command, timeout=300)
            except Exception as e:
                raise RuntimeError(f"FFmpeg failed to concatenate clips: {ffmpeg_utils.error_detail(e)}")

    def generate_preview(self):
        """Generate the preview video. Raises on any failure."""
        self.clean_previous_clips()
        start = time.time()
        try:
            clips = self.generate_clips()
            self.concatenate_clips(clips)
            elapsed = time.time() - start
            if config.verbose:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Preview video created for ID {self.scene_id} — {self.scene_name} → {self.output_path} in {elapsed:.2f} seconds.")
        finally:
            self.clean_previous_clips()
