# video_sprite_generator.py

import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PIL import Image
from tqdm import tqdm

import config
from helpers import ffmpeg_utils


class VideoSpriteGenerator:
    def __init__(self, video_path, sprite_path, vtt_path, filehash, ffmpeg='ffmpeg', ffprobe='ffprobe', total_shots=81, max_width=160, max_height=90, columns=9, rows=9, use_vaapi=None, vaapi_device=None):
        # max_height is accepted for backwards compatibility; tile height now follows
        # the video's aspect ratio (as Stash's own sprite generator does).
        self.video_path = os.path.abspath(video_path.strip('"').strip("'"))
        self.temp_dir = ffmpeg_utils.tmp_path(f"screenshots_{filehash}")
        self.sprite_path = os.path.abspath(sprite_path)
        self.vtt_path = os.path.abspath(vtt_path)
        self.total_shots = total_shots
        self.max_width = max_width
        self.columns = columns
        self.rows = rows
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.use_vaapi = bool(use_vaapi) and bool(vaapi_device)
        self.vaapi_device = vaapi_device

    def get_video_duration(self):
        return ffmpeg_utils.probe_duration(self.video_path)

    def _frame_command(self, timestamp, output_file, use_vaapi):
        if use_vaapi:
            return [
                self.ffmpeg, '-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi',
                '-vaapi_device', self.vaapi_device,
                '-v', 'error', '-y',
                '-ss', str(timestamp), '-i', self.video_path,
                '-frames:v', '1',
                '-vf', f'scale_vaapi={self.max_width}:-2,hwdownload,format=bgr0',
                '-c:v', 'png', output_file,
            ]
        return [
            self.ffmpeg, '-v', 'error', '-y',
            '-ss', str(timestamp), '-i', self.video_path,
            '-frames:v', '1',
            '-vf', f'scale={self.max_width}:-2',
            '-c:v', 'png', output_file,
        ]

    def extract_frame(self, i, interval):
        timestamp = i * interval
        output_file = os.path.join(self.temp_dir, f'frame_{i:03d}.png')
        if self.use_vaapi:
            try:
                ffmpeg_utils.run(self._frame_command(timestamp, output_file, True), timeout=120)
                return i, timestamp, output_file
            except Exception:
                # Hardware decode is not available for every codec/driver —
                # use software for this and all remaining frames of this video.
                self.use_vaapi = False
        try:
            ffmpeg_utils.run(self._frame_command(timestamp, output_file, False), timeout=120)
        except Exception as e:
            raise RuntimeError(f"ffmpeg failed extracting frame {i}: {ffmpeg_utils.error_detail(e)}")
        return i, timestamp, output_file

    def take_screenshots(self):
        """Extract all frames. Returns (interval, [(index, timestamp, file), ...]) in index order."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        duration = self.get_video_duration()
        if not duration or duration <= 0:
            raise RuntimeError(f"Invalid video duration ({duration}) for {self.video_path}")
        interval = duration / self.total_shots

        frames = []
        executor = ThreadPoolExecutor(max_workers=config.max_workers)
        try:
            futures = [executor.submit(self.extract_frame, i, interval) for i in range(self.total_shots)]
            iterator = tqdm(futures, desc="🖼️ Extracting Screenshots", unit="frame") if config.verbose else futures
            for future in iterator:
                frames.append(future.result())
        finally:
            # On the first failure (or shutdown) drop the frames not yet started
            executor.shutdown(wait=True, cancel_futures=True)
        return interval, frames

    def format_time(self, seconds):
        millisec = int((seconds % 1) * 1000)
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{millisec:03}"

    def create_sprite(self, interval, frames):
        if not frames:
            raise ValueError("Something went wrong, no images found to create sprite")

        with Image.open(frames[0][2]) as first:
            tile_w, tile_h = first.size

        sprite = Image.new('RGB', (tile_w * self.columns, tile_h * self.rows))
        vtt_lines = ["WEBVTT", ""]
        sprite_name = os.path.basename(self.sprite_path)

        iterator = tqdm(frames, desc="🧩 Assembling Sprite", unit="tile") if config.verbose else frames
        for i, timestamp, frame_file in iterator:
            x = (i % self.columns) * tile_w
            y = (i // self.columns) * tile_h
            with Image.open(frame_file) as img:
                if img.size != (tile_w, tile_h):
                    img = img.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
                sprite.paste(img.convert('RGB'), (x, y))
            vtt_lines.append(f"{self.format_time(timestamp)} --> {self.format_time(timestamp + interval)}")
            vtt_lines.append(f"{sprite_name}#xywh={x},{y},{tile_w},{tile_h}")
            vtt_lines.append("")

        # Sprite first, VTT last: both only appear once complete
        with ffmpeg_utils.atomic_output(self.sprite_path) as tmp_sprite:
            sprite.save(tmp_sprite, format='JPEG')
        with ffmpeg_utils.atomic_output(self.vtt_path) as tmp_vtt:
            with open(tmp_vtt, 'w') as vtt_file:
                vtt_file.write("\n".join(vtt_lines) + "\n")

    def clean_up(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def generate_sprite(self):
        """Generate the sprite sheet and VTT. Raises on any failure."""
        start = time.time()
        try:
            interval, frames = self.take_screenshots()
            self.create_sprite(interval, frames)
            elapsed = time.time() - start
            if config.verbose:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Sprite generation complete for {os.path.basename(self.video_path)} in {elapsed:.2f} seconds.")
        finally:
            self.clean_up()
