# video_sprite_generator.py

import subprocess
from PIL import Image
import os
import shutil
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from config import verbose, max_workers
import time
from datetime import datetime

class VideoSpriteGenerator:
    def __init__(self, video_path, sprite_path, vtt_path, filehash, ffmpeg='ffmpeg', ffprobe='ffprobe', total_shots=81, max_width=160, max_height=90, columns=9, rows=9, use_vaapi=None, vaapi_device=None):
        self.video_path = os.path.abspath(video_path.strip('"').strip("'"))
        self.temp_dir = os.path.abspath(os.path.join(".tmp", f"screenshots_{filehash}"))
        self.sprite_path = os.path.abspath(sprite_path)
        self.vtt_path = os.path.abspath(vtt_path)
        self.total_shots = total_shots
        self.max_width = max_width
        self.max_height = max_height
        self.columns = columns
        self.rows = rows
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.use_vaapi = use_vaapi
        self.vaapi_device = vaapi_device

    def get_video_duration(self):
        result = subprocess.run(
            [self.ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', self.video_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        try:
            return float(result.stdout.strip())
        except (ValueError, TypeError):
            stderr = result.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(f"Could not determine duration for {self.video_path}: {stderr}")

    def clean_previous_files(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        if os.path.exists(self.vtt_path):
            os.remove(self.vtt_path)

    def extract_and_resize(self, i, interval, use_vaapi):
        time = i * interval
        output_file = os.path.join(self.temp_dir, f'frame_{i:03d}.jpg')
        if use_vaapi:
            command = [
                self.ffmpeg, '-hwaccel', 'vaapi', '-hwaccel_output_format', 'vaapi',
                '-vaapi_device', self.vaapi_device,
                '-v', 'error', '-y',
                '-ss', str(time), '-i', self.video_path,
                '-frames:v', '1',
                '-vf', f'scale_vaapi={self.max_width}:-2,hwdownload,format=bgr0',
                '-c:v', 'png', output_file,
                '-loglevel', 'quiet'
            ]
        else:
            command = [
                self.ffmpeg,
                '-ss', str(time),
                '-i', self.video_path,
                '-frames:v', '1',
                '-q:v', '2',
                output_file,
                '-loglevel', 'quiet'
            ]
        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode('utf-8', errors='replace').strip().splitlines()
            detail = stderr[-1] if stderr else str(e)
            raise RuntimeError(f"ffmpeg failed extracting frame {i}: {detail}")
        with Image.open(output_file) as img:
            img = img.resize((self.max_width, self.max_height), Image.Resampling.LANCZOS)
            img.save(output_file)
        return (i, time)

    def take_screenshots(self):
        self.clean_previous_files()
        os.makedirs(self.temp_dir, exist_ok=True)
        duration = self.get_video_duration()
        if not duration or duration <= 0:
            return False
        interval = duration / self.total_shots

        use_vaapi = bool(self.use_vaapi) and bool(self.vaapi_device)

        with open(self.vtt_path, 'w') as vtt_file:
            vtt_file.write("WEBVTT\n\n")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(self.extract_and_resize, i, interval, use_vaapi) for i in range(self.total_shots)]
                iterator = tqdm(futures, desc="🖼️ Extracting Screenshots", unit="frame") if verbose else futures
                for future in iterator:
                    i, time = future.result()
                    end_time = time + interval
                    start_time_str = self.format_time(time)
                    end_time_str = self.format_time(end_time)
                    x = (i % self.columns) * self.max_width
                    y = (i // self.columns) * self.max_height
                    vtt_file.write(f"{start_time_str} --> {end_time_str}\n")
                    vtt_file.write(f"{os.path.basename(self.sprite_path)}#xywh={x},{y},{self.max_width},{self.max_height}\n\n")
        return True

    def format_time(self, seconds):
        millisec = int((seconds % 1) * 1000)
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02}.{millisec:03}"

    def create_sprite(self):
        image_files = sorted(
            f for f in os.listdir(self.temp_dir) if f.lower().endswith('.jpg')
        )
        if not image_files:
            raise ValueError("Something went wrong, no images found to create sprite")

        sprite_width = self.max_width * self.columns
        sprite_height = self.max_height * self.rows
        sprite = Image.new('RGB', (sprite_width, sprite_height))

        iterator = tqdm(enumerate(image_files), desc="🧩 Assembling Sprite", unit="tile", total=len(image_files)) if verbose else enumerate(image_files)
        for idx, fname in iterator:
            x = (idx % self.columns) * self.max_width
            y = (idx // self.columns) * self.max_height
            with Image.open(os.path.join(self.temp_dir, fname)) as img:
                sprite.paste(img, (x, y))

        sprite.save(self.sprite_path)

    def clean_up(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def generate_sprite(self):
        start = time.time()
        try:
            result = self.take_screenshots()
            if result:
                self.create_sprite()
            elapsed = time.time() - start
            if verbose:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Sprite generation complete for {os.path.basename(self.video_path)} in {elapsed:.2f} seconds.")
        finally:
            self.clean_up()
