# 📼 phashvaapi - VAAPI-Accelerated Stash Video Processor

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
stash_host = "192.168.1.71"  # Your Stash server IP
stash_port = 9999            # Your Stash port
```

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

Tell the script where to save sprites and previews:

```python
sprite_path = "/mnt/stash/stash/generated/vtt"
preview_path = "/mnt/stash/stash/generated/screenshots"
```

### 5. Run Health Check

Make sure everything's configured correctly:

```bash
python phash_videohasher_main.py --health-check
```

If all checks pass ✅, you're ready to roll.

## 🎮 Usage

### Basic Usage

Process scenes with default settings:
```bash
python phash_videohasher_main.py
```

### Common Patterns

**Single batch for testing:**
```bash
python phash_videohasher_main.py --once --verbose --batch-size 5
```

**Process specific videos (by filename pattern):**
```bash
python phash_videohasher_main.py --filemask "JoonMali*" --once
```

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
```

## 📋 CLI Options

```
usage: phash_videohasher_main.py [-h] [--windows] [--generate-sprite] [--generate-preview]
                                 [--batch-size BATCH_SIZE] [--max-workers MAX_WORKERS]
                                 [--dry-run] [--verbose] [--once] [--vaapi] [--novaapi]
                                 [--debug] [--filemask FILEMASK] [--health-check]
                                 [--retry-errors] [--clear-error-tags]

Processing Options:
  --batch-size BATCH_SIZE     Number of scenes per batch (default: 25)
  --max-workers MAX_WORKERS   Parallel worker threads (default: 4)
  --once                      Process one batch and exit (great for cron)
  --generate-sprite           Enable sprite sheet generation
  --generate-preview          Enable preview video generation

VAAPI / Hardware Acceleration:
  --vaapi                     Force VAAPI hardware acceleration ON
  --novaapi                   Force VAAPI hardware acceleration OFF

Filtering:
  --filemask FILEMASK         Filter scenes by filename pattern (e.g., 'JoonMali*' or '*.mp4')

Error Management:
  --retry-errors              Process scenes that previously failed
  --clear-error-tags          Remove error tags from all scenes and exit
  --health-check              Validate configuration and exit

Output Control:
  --verbose                   Show progress bars and detailed output
  --debug                     Show FFmpeg commands and timing breakdowns
  --dry-run                   Simulate processing without making changes

Platform:
  --windows                   Use Windows paths and binaries
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
