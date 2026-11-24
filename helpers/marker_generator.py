# marker_generator.py

import os
import time

import config
from helpers import ffmpeg_utils


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
        self.vaapi_device = vaapi_device

    def _run_to(self, final_path, build_command, timeout, label):
        """
        Run an ffmpeg command that writes `final_path` (via a temp file).
        Returns None on success, or an error string.
        """
        try:
            with ffmpeg_utils.atomic_output(final_path) as tmp_output:
                ffmpeg_utils.run(build_command(tmp_output), timeout=timeout)
            return None
        except Exception as e:
            detail = ffmpeg_utils.error_detail(e)
            print(f"⚠️ Failed to generate {label}: {detail}")
            return f"{label} failed: {detail}"

    def generate_preview(self):
        """Generate MP4 preview (clip starting at marker timestamp). Returns error string or None."""
        use_vaapi = bool(self.use_vaapi) and bool(self.vaapi_device)
        input_opts, output_opts = ffmpeg_utils.h264_encode_args(use_vaapi, self.vaapi_device, width=640)

        def build(output):
            return ([self.ffmpeg, '-y'] + input_opts +
                    ['-ss', str(self.marker_seconds), '-t', str(self.preview_duration),
                     '-i', self.video_path] +
                    output_opts + ['-an', '-loglevel', 'error', output])

        return self._run_to(self.mp4_path, build, 300, "MP4 preview")

    def generate_thumbnail(self):
        """Generate WebP animated thumbnail. Returns error string or None."""
        def build(output):
            return [
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
                '-loglevel', 'error',
                output
            ]

        return self._run_to(self.webp_path, build, 180, "WebP thumbnail")

    def generate_screenshot(self):
        """Generate JPG screenshot (single frame at marker timestamp). Returns error string or None."""
        def build(output):
            return [
                self.ffmpeg, '-y',
                '-ss', str(self.marker_seconds),
                '-i', self.video_path,
                '-vframes', '1',
                '-q:v', '2',  # High quality
                '-loglevel', 'error',
                output
            ]

        return self._run_to(self.jpg_path, build, 60, "JPG screenshot")

    def generate_marker(self):
        """
        Generate every enabled media type (MP4, WebP, JPG) that does not exist yet.

        Returns:
            dict: Result dictionary with keys:
                - success: bool (True only if every enabled file now exists)
                - files: list of files generated by this call
                - elapsed_time: float (total generation time)
                - error: str (error messages if anything failed)
        """
        start_time = time.time()
        generated_files = []
        errors = []

        steps = [
            (self.preview_enabled, self.mp4_path, self.generate_preview),
            (self.thumbnail_enabled, self.webp_path, self.generate_thumbnail),
            (self.screenshot_enabled, self.jpg_path, self.generate_screenshot),
        ]

        try:
            os.makedirs(self.output_dir, exist_ok=True)
            for enabled, path, generate in steps:
                if not enabled or os.path.exists(path):
                    continue
                error = generate()
                if error:
                    errors.append(error)
                else:
                    generated_files.append(path)
        except Exception as e:
            errors.append(str(e))

        return {
            'success': not errors,
            'files': generated_files,
            'elapsed_time': time.time() - start_time,
            'error': '; '.join(errors) if errors else None,
        }
