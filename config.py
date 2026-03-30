# config.py

import platform
import os

# 🌐 Stash API connection
stash_host = "192.168.1.71"
stash_port = 9999
stash_api_key = None  # Set to your API key string if authentication is required (e.g., "your-api-key-here")

windows = platform.system() == "Windows"

# 📁 External tool paths
binary_windows = r".\bin\videohashes-windows.exe"
binary_linux = r"./bin/videohashes-linux"
binary = binary_windows if windows else binary_linux

ffmpeg = r"c:\mediatools\ffmpeg.exe" if windows else "/usr/bin/ffmpeg"
ffprobe = r"c:\mediatools\ffprobe.exe" if windows else "/usr/bin/ffprobe"

sprite_path = r"Y:/stash/generated/vtt" if windows else "/mnt/stash/stash/generated/vtt"
preview_path = r"Y:/stash/generated/screenshots" if windows else "/mnt/stash/stash/generated/screenshots"

# 🏷️ Stash tag IDs
hashing_tag = 15015
hashing_error_tag = 15018
cover_error_tag = 15019

# 🔢 Batch size for scene processing
per_page = 25  # --batch-size: Number of scenes to process per run (default: 25)

# ⚙️ Parallelism settings
max_workers = 4  # --max-workers: Number of threads for parallel processing

# 🖼️ Sprite generation settings
generate_sprite = True  # --generate-sprite: Enable sprite image generation

# 🎞️ Preview video settings
generate_preview = True  # --generate-preview: Enable preview video generation
preview_audio = False
preview_clips = 15
preview_clip_length = 1
preview_skip_seconds = 15

# 🧪 Dry run mode
dry_run = False  # --dry-run: Simulate processing without writing changes
once = False     # --once: Run one batch then exit
verbose = False  # --verbose: Display additional information including progress bars for generation tasks
filemask = None  # --filemask: Filter scenes by filename pattern (e.g., 'JoonMali*' or '*.mp4')

# 🔁 Path translations
translations = (
    [
        {'orig': '/data/', 'local': 'S:/'},
        {'orig': '/xerxes/', 'local': 'P:/'},
        {'orig': '/data_stranghouse/', 'local': 'R:/'},
        {'orig': '/mnt/gomorrah/', 'local': 'G:/'},
    ] if windows else [
        {'orig': '/data/', 'local': '/mnt/strangyr/'},
        {'orig': '/xerxes/', 'local': '/mnt/xerxes/'},
        {'orig': '/data_stranghouse/', 'local': '/mnt/Stranghouse/'},
    ]
)

# 🎯 Marker generation settings
generate_markers = False              # --generate-markers: Enable marker media generation
marker_path = r"Y:/stash/generated" if windows else "/mnt/stash/stash/generated"
marker_batch_size = 50                # Batch size for standalone marker mode

# Media type toggles (all enabled by default)
marker_preview_enabled = True         # Generate MP4 previews
marker_thumbnail_enabled = True       # Generate WebP thumbnails
marker_screenshot_enabled = True      # Generate JPG screenshots

# Media generation parameters
marker_preview_duration = 20          # MP4 clip duration in seconds
marker_thumbnail_duration = 5         # WebP animation duration in seconds
marker_thumbnail_fps = 12             # WebP animation frame rate
