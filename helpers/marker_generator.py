# marker_generator.py

import subprocess
import os
import shutil
import time
from datetime import datetime
from config import verbose

class MarkerGenerator:
    def __init__(self, video_path, marker_seconds, oshash, output_base_dir,
                 ffmpeg='ffmpeg', ffprobe='ffprobe',
                 preview_enabled=True, thumbnail_enabled=True, screenshot_enabled=True,
                 preview_duration=20, thumbnail_duration=5, thumbnail_fps=12,
                 use_vaapi=None, vaapi_device=None):
        """
        Initialize marker generator for creating marker media files.

        Args:
            video_path: Path to source video file
            marker_seconds: Marker timestamp in seconds (float)
            oshash: Scene file hash for organizing output
            output_base_dir: Base output directory (markers will be in markers/{oshash}/)
            ffmpeg: Path to ffmpeg binary
            ffprobe: Path to ffprobe binary
            preview_enabled: Generate MP4 preview
            thumbnail_enabled: Generate WebP thumbnail
            screenshot_enabled: Generate JPG screenshot
            preview_duration: MP4 clip duration in seconds
            thumbnail_duration: WebP animation duration in seconds
            thumbnail_fps: WebP animation frame rate
            use_vaapi: Enable VAAPI hardware acceleration
            vaapi_device: VAAPI device path
        """
        self.video_path = os.path.abspath(video_path.strip('"').strip("'"))
        self.marker_seconds = marker_seconds
        self.marker_int = int(marker_seconds)  # Integer truncation for filenames
        self.oshash = oshash

        # Output directory structure: {base}/markers/{oshash}/
        self.output_dir = os.path.abspath(os.path.join(output_base_dir, "markers", oshash))

        # Output files
        self.mp4_path = os.path.join(self.output_dir, f"{self.marker_int}.mp4")
        self.webp_path = os.path.join(self.output_dir, f"{self.marker_int}.webp")
        self.jpg_path = os.path.join(self.output_dir, f"{self.marker_int}.jpg")

        # Settings
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.preview_enabled = preview_enabled
        self.thumbnail_enabled = thumbnail_enabled
        self.screenshot_enabled = screenshot_enabled
        self.preview_duration = preview_duration
        self.thumbnail_duration = thumbnail_duration
        self.thumbnail_fps = thumbnail_fps
        self.use_vaapi = use_vaapi
        self.vaapi_device = vaapi_device if vaapi_device else '/dev/dri/renderD128'

        # Temp directory
        self.temp_dir = os.path.abspath(os.path.join(".tmp", f"marker_{oshash}_{self.marker_int}"))

    def generate_preview(self):
        """
        Generate MP4 preview (20-second clip starting at marker timestamp).

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.preview_enabled:
            return False

        os.makedirs(os.path.dirname(self.mp4_path), exist_ok=True)

        use_vaapi = self.use_vaapi if self.use_vaapi is not None else False

        if use_vaapi:
            # VAAPI hardware-accelerated encoding
            command = [
                self.ffmpeg, '-y',
                '-vaapi_device', self.vaapi_device,
                '-ss', str(self.marker_seconds),
                '-t', str(self.preview_duration),
                '-i', self.video_path,
                '-vf', 'format=nv12,hwupload,scale_vaapi=640:-2',
                '-c:v', 'h264_vaapi',
                '-crf', '18',
                '-an',  # No audio
                '-loglevel', 'quiet',
                self.mp4_path
            ]
        else:
            # Software encoding fallback
            command = [
                self.ffmpeg, '-y',
                '-ss', str(self.marker_seconds),
                '-t', str(self.preview_duration),
                '-i', self.video_path,
                '-vf', 'scale=640:-2',
                '-c:v', 'libx264',
                '-crf', '18',
                '-preset', 'slow',
                '-an',  # No audio
                '-loglevel', 'quiet',
                self.mp4_path
            ]

        try:
            subprocess.run(command, check=True)
            return os.path.exists(self.mp4_path)
        except subprocess.CalledProcessError as e:
            if verbose:
                print(f"⚠️ Failed to generate MP4 preview: {e}")
            return False

    def generate_thumbnail(self):
        """
        Generate WebP animated thumbnail (5-second animation at 12fps).

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.thumbnail_enabled:
            return False

        os.makedirs(os.path.dirname(self.webp_path), exist_ok=True)

        command = [
            self.ffmpeg, '-y',
            '-ss', str(self.marker_seconds),
            '-t', str(self.thumbnail_duration),
            '-i', self.video_path,
            '-vf', f'scale=640:-2,fps={self.thumbnail_fps}',
            '-c:v', 'libwebp',
            '-lossless', '1',
            '-q:v', '70',
            '-compression_level', '6',
            '-preset', 'default',
            '-loop', '0',  # Infinite loop
            '-loglevel', 'quiet',
            self.webp_path
        ]

        try:
            subprocess.run(command, check=True)
            return os.path.exists(self.webp_path)
        except subprocess.CalledProcessError as e:
            if verbose:
                print(f"⚠️ Failed to generate WebP thumbnail: {e}")
            return False

    def generate_screenshot(self):
        """
        Generate JPG screenshot (single frame at marker timestamp).

        Returns:
            bool: True if successful, False otherwise
        """
        if not self.screenshot_enabled:
            return False

        os.makedirs(os.path.dirname(self.jpg_path), exist_ok=True)

        command = [
            self.ffmpeg, '-y',
            '-ss', str(self.marker_seconds),
            '-i', self.video_path,
            '-vframes', '1',
            '-q:v', '2',  # High quality
            '-loglevel', 'quiet',
            self.jpg_path
        ]

        try:
            subprocess.run(command, check=True)
            return os.path.exists(self.jpg_path)
        except subprocess.CalledProcessError as e:
            if verbose:
                print(f"⚠️ Failed to generate JPG screenshot: {e}")
            return False

    def clean_temp_dirs(self):
        """Clean up temporary directories."""
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                if verbose:
                    print(f"⚠️ Failed to remove temp directory: {e}")

    def generate_marker(self):
        """
        Main orchestrator for marker generation.
        Generates all enabled media types (MP4, WebP, JPG).

        Returns:
            dict: Result dictionary with keys:
                - success: bool (True if at least one file generated)
                - files: list of successfully generated file paths
                - elapsed_time: float (total generation time)
                - error: str (error message if failed)
        """
        start_time = time.time()
        generated_files = []
        errors = []

        try:
            # Create output directory
            os.makedirs(self.output_dir, exist_ok=True)

            # Generate MP4 preview
            if self.preview_enabled:
                if self.generate_preview():
                    generated_files.append(self.mp4_path)
                else:
                    errors.append("MP4 preview generation failed")

            # Generate WebP thumbnail
            if self.thumbnail_enabled:
                if self.generate_thumbnail():
                    generated_files.append(self.webp_path)
                else:
                    errors.append("WebP thumbnail generation failed")

            # Generate JPG screenshot
            if self.screenshot_enabled:
                if self.generate_screenshot():
                    generated_files.append(self.jpg_path)
                else:
                    errors.append("JPG screenshot generation failed")

            elapsed_time = time.time() - start_time

            if generated_files:
                return {
                    'success': True,
                    'files': generated_files,
                    'elapsed_time': elapsed_time,
                    'error': None
                }
            else:
                error_msg = '; '.join(errors) if errors else "No files generated"
                return {
                    'success': False,
                    'files': [],
                    'elapsed_time': elapsed_time,
                    'error': error_msg
                }

        except Exception as e:
            elapsed_time = time.time() - start_time
            return {
                'success': False,
                'files': generated_files,
                'elapsed_time': elapsed_time,
                'error': str(e)
            }

        finally:
            # Always clean up temp directories
            self.clean_temp_dirs()
