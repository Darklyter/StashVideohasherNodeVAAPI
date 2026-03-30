# 📼 StashVideohasherNode (VAAPI) - VAAPI-Accelerated Stash Video Processor

A lightweight, distributed processing script that takes the heavy lifting off your Stash server. Instead of making your Stash instance do all the work, spread it across multiple nodes that can contribute back cover generation, sprite sheets, preview videos, and perceptual hashing. Now with GPU acceleration to make it even faster.

## ⚙️ Requirements

### The Essentials
- Python 3.7+ (you probably already have this)
- FFmpeg (with VAAPI support if you want GPU acceleration)
- [Peolic's videohashes binaries](https://github.com/peolic/videohashes) - grab the right one for your OS

### Python Packages
```bash
pip install stashapi Pillow tqdm
```

**Quick note:** This script uses **OSHASH** for file fingerprinting. If your Stash instance is currently set to MD5, these won't be compatible. Switch to OSHASH in your Stash settings.

## 🧠 How It Works

The script is designed to let multiple systems chip in on processing your Stash library:

- Processes scenes in configurable batches (default: 25 per node)
- Uses tag-based "claiming" to prevent multiple nodes from working on the same scenes
- Keeps going until all scenes are processed
- Targets scenes with **missing phash** (once a scene has a phash, it's done)
- If phash succeeds but something else fails (like cover extraction), the scene still gets skipped next time

### What Gets Generated

1. **Perceptual Hash (phash)** - For finding duplicate videos
2. **Cover Image** - Extracted from the video if you don't have one
3. **Sprite Sheet** - 9×9 grid of thumbnails with WebVTT metadata for scrubbing
4. **Preview Video** - 15-second compilation (15 clips × 1 second each)
5. **Marker Media** - MP4 previews (20s clips), WebP thumbnails (5s animations), and JPG screenshots for scene markers

## 🚀 Hardware Acceleration (VAAPI)

If you've got an Intel or AMD GPU, this script can use VAAPI to massively speed up preview and sprite generation. It auto-detects your GPU at startup, but you can override:

```bash
# Force VAAPI on
python phash_videohasher_main.py --vaapi

# Force VAAPI off (software encoding)
python phash_videohasher_main.py --novaapi
```

**Performance difference?** On a batch of 3 videos:
- WITH VAAPI: 1m30s (37% faster, 52% less CPU usage)
- WITHOUT VAAPI: 2m23s

Your mileage may vary, but GPU acceleration is a game-changer for large batches.

## 🛠️ Setup

### 1. Configure Your Stash Connection

Edit `config.py` and point it at your Stash server:

```python
stash_host = "127.0.0.1"       # Your Stash server IP
stash_port = 9999               # Your Stash port
stash_api_key = None            # Set to your API key if authentication is required
```

**API Key Authentication (Optional):**

If your Stash instance requires authentication, set the API key:
```python
stash_api_key = "your-api-key-here"
```

To get your Stash API key:
1. Open Stash web interface
2. Go to **Settings → Security**
3. Find or generate your API key
4. Copy the key and set it in `config.py`

### 2. Set Up Path Translations (if needed)

If you're running this on a different machine than your Stash server, you'll need to translate the file paths:

```python
translations = [
    {'orig': '/mnt/storage/', 'local': '/mnt/nas/'},
    # Add more as needed
]
```

### 3. Configure Tag IDs

The script uses Stash tags to track processing state. You'll need to create these tags in Stash and put their IDs in `config.py`:

```python
hashing_tag = 15015        # "In Process" tag
hashing_error_tag = 15018  # "Phash Error" tag
cover_error_tag = 15019    # "Cover Error" tag
```

### 4. Set Output Paths

Tell the script where to save sprites, previews, and markers:

```python
sprite_path = "/mnt/stash/stash/generated/vtt"
preview_path = "/mnt/stash/stash/generated/screenshots"
marker_path = "/mnt/stash/stash/generated"  # Markers go in markers/{oshash}/
```

### 5. Configure Marker Generation (Optional)

Marker generation is disabled by default. Configure in `config.py`:

```python
# Enable marker generation
generate_markers = True  # or use --generate-markers CLI flag

# Media type toggles (all enabled by default)
marker_preview_enabled = True         # Generate MP4 previews (20s clips)
marker_thumbnail_enabled = True       # Generate WebP thumbnails (5s animations)
marker_screenshot_enabled = True      # Generate JPG screenshots (single frames)

# Media generation parameters
marker_preview_duration = 20          # MP4 clip duration in seconds
marker_thumbnail_duration = 5         # WebP animation duration in seconds
marker_thumbnail_fps = 12             # WebP animation frame rate
marker_batch_size = 50                # Batch size for standalone marker mode
```

**Marker file structure:**
```
{marker_path}/markers/{oshash}/{seconds}.{mp4|webp|jpg}

Example:
/mnt/stash/stash/generated/markers/abc123def456/15.mp4
/mnt/stash/stash/generated/markers/abc123def456/15.webp
/mnt/stash/stash/generated/markers/abc123def456/15.jpg
```

### 6. Run Health Check

Make sure everything's configured correctly:

```bash
python phash_videohasher_main.py --health-check
```

If all checks pass ✅, you're ready to roll.

## 🎮 Usage

### Basic Usage

Process scenes with default settings (phash + cover only):
```bash
python phash_videohasher_main.py
```

### Integrated Scene Processing

Process scenes with all media generation during scene processing:
```bash
# Full processing (phash + cover + sprite + preview + markers)
python phash_videohasher_main.py --generate-sprite --generate-preview --generate-markers --once --verbose

# Single batch for testing
python phash_videohasher_main.py --once --verbose --batch-size 5

# Process specific videos (by filename pattern)
python phash_videohasher_main.py --filemask "JoonMali*" --generate-sprite --generate-preview --once
```

### Standalone Generation Modes

Generate media without full scene processing:

**Generate sprites only (50 scenes):**
```bash
python phash_videohasher_main.py --standalone-sprites --sprite-batch-size 50 --verbose
```

**Generate previews only (25 scenes):**
```bash
python phash_videohasher_main.py --standalone-previews --preview-batch-size 25 --verbose
```

**Generate marker media only (100 markers):**
```bash
python phash_videohasher_main.py --standalone-markers --marker-batch-size 100 --verbose
```

**Combined standalone generation:**
```bash
# Generate all three types at once
python phash_videohasher_main.py --standalone-sprites --standalone-previews --standalone-markers --verbose
```

**Marker media type filters:**
```bash
# Generate only MP4 previews (20-second clips)
python phash_videohasher_main.py --standalone-markers --marker-preview-only --verbose

# Generate only WebP thumbnails (5-second animations)
python phash_videohasher_main.py --standalone-markers --marker-thumbnail-only --verbose

# Generate only JPG screenshots (single frames)
python phash_videohasher_main.py --standalone-markers --marker-screenshot-only --verbose
```

### Common Patterns

**Retry scenes that had errors:**
```bash
python phash_videohasher_main.py --retry-errors
```

**Run as a cron job/service:**
```bash
python phash_videohasher_main.py --batch-size 50 --once
```

**See what it would do (dry run):**
```bash
python phash_videohasher_main.py --dry-run --verbose --once
python phash_videohasher_main.py --standalone-markers --dry-run --verbose
```

## 📋 CLI Options

Run `python phash_videohasher_main.py --help` for complete usage information.

### Basic Options
```
--batch-size BATCH_SIZE     Number of scenes per batch (default: 25)
--max-workers MAX_WORKERS   Parallel worker threads (default: 4)
--once                      Process one batch and exit (great for cron)
--verbose                   Show progress bars and detailed output
--debug                     Show FFmpeg commands and timing breakdowns
--dry-run                   Simulate processing without making changes
--filemask FILEMASK         Filter scenes by filename pattern (e.g., 'JoonMali*' or '*.mp4')
--windows                   Use Windows paths and binaries
```

### Integrated Scene Processing
Enable media generation during full scene processing:
```
--generate-sprite           Generate sprite sheets during scene processing
--generate-preview          Generate preview videos during scene processing
--generate-markers          Generate marker media during scene processing
```

### Standalone Generation Modes
Generate media without full scene processing:
```
--standalone-sprites        Batch generate sprites only
--sprite-batch-size SIZE    Batch size for standalone sprite generation (default: 25)

--standalone-previews       Batch generate previews only
--preview-batch-size SIZE   Batch size for standalone preview generation (default: 25)

--standalone-markers        Batch generate markers only
--marker-batch-size SIZE    Batch size for standalone marker generation (default: 50)
```

### Marker Generation Options
```
--marker-preview-only       Generate only MP4 previews (20s clips)
--marker-thumbnail-only     Generate only WebP thumbnails (5s animations)
--marker-screenshot-only    Generate only JPG screenshots (single frames)
```

### Hardware Acceleration
```
--vaapi                     Force VAAPI hardware acceleration ON
--novaapi                   Force VAAPI hardware acceleration OFF
```

### Utilities
```
--health-check              Validate configuration and exit
--retry-errors              Process scenes that previously failed
--clear-error-tags          Remove error tags from all scenes and exit
```

## 🏥 Health Checks

Before doing any real work, the script validates:
- ✅ Stash API is reachable
- ✅ videohashes binary exists and is executable
- ✅ FFmpeg and ffprobe are available
- ✅ Output directories are writable
- ✅ VAAPI device is accessible (if enabled)
- ✅ Temp directory can be created

Run standalone with:
```bash
python phash_videohasher_main.py --health-check
```

## 📊 Statistics & Monitoring

With `--verbose`, you get a summary after each batch:

```
📊 Batch Summary
============================================================
  ✅ Successful: 23/25 (92.0%)
  ❌ Failed: 2/25
  ⏱️  Average time per scene: 36.2s
  🎯 Total processing time: 15m 4s
============================================================
```

Failed scenes are tagged with error tags and logged to `error_log.txt` for later review.

## 🔧 Error Handling

### Automatic Isolation
Each scene processes independently - one failure won't crash the whole batch.

### Error Tags
- Scenes that fail hashing get the `hashing_error_tag`
- Scenes that fail cover extraction get the `cover_error_tag`
- Both are excluded from future processing until you explicitly retry

### Retry Failed Scenes
```bash
# Process only scenes with error tags
python phash_videohasher_main.py --retry-errors --batch-size 10 --once

# Clear all error tags to start fresh
python phash_videohasher_main.py --clear-error-tags
```

### Timeout Protection
Each scene has a 10-minute timeout to prevent hanging on problem videos. If a scene times out, it gets tagged with an error and the batch continues.

## 🌐 Distributed Processing

Run this script on multiple machines to process your library faster. The tag-based claiming system prevents overlap:

1. Node A claims scenes 1-25 (adds "In Process" tag)
2. Node B sees those are claimed, picks scenes 26-50
3. When Node A finishes a scene, it removes the tag
4. Scene becomes eligible for processing again only if it still needs work

**Note:** There's a small race condition window during random page selection, but scene claiming mitigates it almost entirely.

## 🐛 Troubleshooting

### Terminal text invisible after run
Fixed! The script now properly resets terminal state including colors, cursor, and echo mode.

### Leftover temp directories
All temp files go in `.tmp/` which is automatically cleaned at the start and end of each run.

### VAAPI not working
Run `--health-check` to verify your VAAPI device is accessible. Make sure you have:
- Intel/AMD GPU with VAAPI drivers installed
- FFmpeg compiled with VAAPI support
- Permissions to access `/dev/dri/renderD128` (or whichever device you have)

### Process hangs indefinitely
Each scene has a 10-minute timeout. If you're seeing hangs, check `error_log.txt` for details.

### Error tags piling up
Review errors in `error_log.txt`, fix any config issues, then:
```bash
python phash_videohasher_main.py --clear-error-tags
python phash_videohasher_main.py --retry-errors
```

## 💬 Support

The code is heavily commented. If you're stuck, you can probably figure it out from reading the source. For questions, you know where to find me on Discord (if you know this script exists, you probably know how to reach me there).

## 📜 License

MIT License - see [LICENSE](LICENSE) file for details.

## 🙏 Credits

- [Stash](https://github.com/stashapp/stash) - The adult media organizer this script was built for
- [Peolic's videohashes](https://github.com/peolic/videohashes) - The perceptual hashing engine
- Everyone who contributed bug reports and testing feedback

---

**Pro tip:** Run this on multiple systems, set `--batch-size 50`, schedule it with cron, and let it churn through your backlog overnight. Your Stash server will thank you. 🚀
