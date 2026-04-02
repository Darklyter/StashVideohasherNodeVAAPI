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
stash_scheme  = "http"           # Protocol: "http" or "https"
stash_host    = "192.168.1.71"  
stash_port    = 9999
stash_api_key = None             # Set your API key here (Stash → Settings → Security → API Key)

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
# Path Exclusions
# ─────────────────────────────────────────────
excluded_paths = [
    # "/mnt/archive/",   # Add Stash file paths to exclude from processing
]

# ─────────────────────────────────────────────
# Stash Tag IDs
# ─────────────────────────────────────────────
hashing_tag       = 15015  # Stash tag ID for "In Process"      — create these working tags and set numeric IDs here
hashing_error_tag = 15018  # Stash tag ID for "Hashing Error"   - for example the tag at: `http://stash.local:9999/tags/14800/scenes?sortby=date`
cover_error_tag   = 15019  # Stash tag ID for "Cover Error"     - the numeric ID would be 14800

# ─────────────────────────────────────────────
# Path Translations
# ─────────────────────────────────────────────
# 'orig' is the path as Stash sees it; 'local' is the path on this machine
translations = (
    [
        {'orig': '/data/',            'local': 'S:/'},  # If running on Windows
        {'orig': '/xerxes/',          'local': 'P:/'},  # If running on Windows
        {'orig': '/data_stranghouse/', 'local': 'R:/'}, # If running on Windows
        {'orig': '/mnt/gomorrah/',    'local': 'G:/'},  # If running on Windows
    ] if windows else [
        {'orig': '/data/',            'local': '/mnt/strangyr/'},       # If running on Linux
        {'orig': '/xerxes/',          'local': '/mnt/xerxes/'},         # If running on Linux
        {'orig': '/data_stranghouse/', 'local': '/mnt/stranghouse/'},   # If running on Linux
        {'orig': '/mnt/gomorrah/',    'local': '/mnt/gomorrah/'},       # If running on Linux
        {'orig': '/data_stranghouse/', 'local': '/mnt/Stranghouse/'},   # If running on Linux 
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
debug       = False  # --debug:        Enable debug output including step notifications and ffmpeg commands
filemask    = None   # --filemask:     Filter scenes by filename pattern (e.g. 'JoonMali*')

# ─────────────────────────────────────────────
# Hardware Acceleration
# ─────────────────────────────────────────────
vaapi       = True     # Enable VAAPI hardware acceleration if detected (Intel/AMD GPUs)
nvenc       = False      # Enable NVIDIA NVENC hardware encoder (NVIDIA GPUs)
hw_priority = "vaapi"   # Which encoder takes precedence when both are available: "vaapi" or "nvenc"

# ─────────────────────────────────────────────
# Sprite Generation
# ─────────────────────────────────────────────
generate_sprite = True  # --generate-sprite: Enable sprite image generation

# ─────────────────────────────────────────────
# Preview Video Generation
# ─────────────────────────────────────────────
generate_preview      = True   # --generate-preview: Enable preview video generation
preview_audio         = False  # Include audio track in preview video
preview_clips         = 15     # Number of clips to sample from the video
preview_clip_length   = 1      # Duration of each clip in seconds
preview_skip_seconds  = 15     # Skip this many seconds from the start before sampling

# ─────────────────────────────────────────────
# Marker Generation
# ─────────────────────────────────────────────
generate_markers      = True  # --generate-markers: Enable marker media generation
marker_batch_size     = 50     # Batch size for standalone marker mode

# Media type toggles (all enabled by default)
marker_preview_enabled    = True   # Generate MP4 previews
marker_thumbnail_enabled  = True   # Generate WebP thumbnails
marker_screenshot_enabled = True   # Generate JPG screenshots

# Media generation parameters
marker_preview_duration   = 20     # MP4 clip duration in seconds
marker_thumbnail_duration = 5      # WebP animation duration in seconds
marker_thumbnail_fps      = 12     # WebP animation frame rate
