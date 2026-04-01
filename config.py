# config.py

import platform
import os

# ─────────────────────────────────────────────
# Platform Detection
# ─────────────────────────────────────────────
windows = platform.system() == "Windows"

# ─────────────────────────────────────────────
# Stash API Connection
# ─────────────────────────────────────────────
stash_host = "192.168.1.71"
stash_port = 9999
stash_api_key = None  # Set to your API key string if authentication is required

# ─────────────────────────────────────────────
# External Tool Paths
# ─────────────────────────────────────────────
binary_windows = r".\bin\videohashes-windows.exe"
binary_linux   = r"./bin/videohashes-linux"
binary         = binary_windows if windows else binary_linux

ffmpeg  = r"c:\mediatools\ffmpeg.exe"  if windows else "/usr/bin/ffmpeg"
ffprobe = r"c:\mediatools\ffprobe.exe" if windows else "/usr/bin/ffprobe"

# ─────────────────────────────────────────────
# Output Paths
# ─────────────────────────────────────────────
sprite_path  = r"Y:/stash/generated/vtt"         if windows else "/mnt/stash/stash/generated/vtt"
preview_path = r"Y:/stash/generated/screenshots" if windows else "/mnt/stash/stash/generated/screenshots"
marker_path  = r"Y:/stash/generated"             if windows else "/mnt/stash/stash/generated"

# ─────────────────────────────────────────────
# Stash Tag IDs
# ─────────────────────────────────────────────
hashing_tag       = 15015
hashing_error_tag = 15018
cover_error_tag   = 15019

# ─────────────────────────────────────────────
# Path Translations
# ─────────────────────────────────────────────
translations = (
    [
        {'orig': '/data/',            'local': 'S:/'},
        {'orig': '/xerxes/',          'local': 'P:/'},
        {'orig': '/data_stranghouse/', 'local': 'R:/'},
        {'orig': '/mnt/gomorrah/',    'local': 'G:/'},
    ] if windows else [
        {'orig': '/data/',            'local': '/mnt/strangyr/'},
        {'orig': '/xerxes/',          'local': '/mnt/xerxes/'},
        {'orig': '/data_stranghouse/', 'local': '/mnt/Stranghouse/'},
    ]
)

# ─────────────────────────────────────────────
# Processing Settings
# ─────────────────────────────────────────────
per_page    = 25     # --batch-size:   Number of scenes to process per run
max_workers = 4      # --max-workers:  Number of threads for parallel processing
dry_run     = False  # --dry-run:      Simulate processing without writing changes
once        = False  # --once:         Run one batch then exit
verbose     = False  # --verbose:      Display additional info including progress bars
filemask    = None   # --filemask:     Filter scenes by filename pattern (e.g. 'JoonMali*')

# ─────────────────────────────────────────────
# Sprite Generation
# ─────────────────────────────────────────────
generate_sprite = True  # --generate-sprite: Enable sprite image generation

# ─────────────────────────────────────────────
# Preview Video Generation
# ─────────────────────────────────────────────
generate_preview      = True   # --generate-preview: Enable preview video generation
preview_audio         = False
preview_clips         = 15
preview_clip_length   = 1
preview_skip_seconds  = 15

# ─────────────────────────────────────────────
# Marker Generation
# ─────────────────────────────────────────────
generate_markers      = False  # --generate-markers: Enable marker media generation
marker_batch_size     = 50     # Batch size for standalone marker mode

# Media type toggles (all enabled by default)
marker_preview_enabled    = True   # Generate MP4 previews
marker_thumbnail_enabled  = True   # Generate WebP thumbnails
marker_screenshot_enabled = True   # Generate JPG screenshots

# Media generation parameters
marker_preview_duration   = 20     # MP4 clip duration in seconds
marker_thumbnail_duration = 5      # WebP animation duration in seconds
marker_thumbnail_fps      = 12     # WebP animation frame rate
