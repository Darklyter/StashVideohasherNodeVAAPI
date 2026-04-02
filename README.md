# 📼 StashVideohasherNode (VAAPI)

Got a big Stash library? This script takes the heavy lifting off your Stash server by spreading video processing across as many machines as you want. Each node grabs a batch of unprocessed scenes, does the work, and reports back — with full GPU acceleration to keep things fast.

## What it does

For each unprocessed scene it finds, the script can generate:

- **Perceptual hash (phash)** — visual fingerprint for your video, used for matching with Stashboxes and finding duplicate videos across your library
- **Cover image** — extracted from the video if you don't have one
- **Sprite sheet** — 9×9 thumbnail grid with WebVTT for timeline scrubbing
- **Preview video** — 15-second highlight reel (15 × 1s clips)
- **Marker media** — MP4 clips, WebP animations, and JPG screenshots for each scene marker

Everything runs in parallel, one scene won't block another, and a failed scene gets tagged for later review rather than crashing the batch.

> **Note:** This script uses **OSHASH** fingerprinting. If your Stash instance is set to MD5, make sure to switch it to OSHASH in Settings before running.

---

## Requirements

- Python 3.7+
- FFmpeg (with VAAPI support if you want GPU acceleration)

```bash
pip install stashapi Pillow tqdm
```

Phash generation uses the internal pure-Python implementation by default. If you prefer the original videohashes binary, see [PHash Backend](#phash-backend) below.

---

## Setup

### 1. Point it at your Stash server

Open `config.py` and fill in your connection details:

```python
stash_scheme  = "http"          # "http" or "https"
stash_host    = "127.0.0.1"    # Your Stash server IP or hostname
stash_port    = 9999            # Your Stash port
stash_api_key = None            # Paste your API key here if Stash requires auth
```

To get your API key: Stash → **Settings → Security** → copy or generate the key.

### 2. Set your output paths

Tell the script where your Stash-generated files live:

```python
sprite_path  = "/mnt/stash/generated/vtt"
preview_path = "/mnt/stash/generated/screenshots"
marker_path  = "/mnt/stash/generated"   # markers saved under markers/{oshash}/
```

### 3. Add your tag IDs

The script uses Stash tags to track which scenes are in-progress and which had errors. Create these tags in Stash and drop their IDs here:

```python
hashing_tag       = 15015   # "In Process" — claimed by a node, don't touch
hashing_error_tag = 15018   # "Phash Error" — hashing failed
cover_error_tag   = 15019   # "Cover Error" — cover extraction failed
```

### 4. Path translation (multi-machine setups)

If this node and your Stash server see the same files at different paths, add translations:

```python
translations = [
    {'orig': '/mnt/storage/', 'local': '/mnt/nas/'},
]
```

### 5. Run the health check

Before your first real run, make sure everything is wired up correctly:

```bash
python phash_videohasher_main.py --health-check
```

This validates your Stash connection, checks that the configured phash backend is ready, confirms output paths are writable, and does a real test encode on whichever GPU encoder you have configured. All green? You're ready to go.

---

## PHash Backend

Phash generation supports two backends, controlled by `phash_backend` in `config.py`:

### Internal (default)

```python
phash_backend = "internal"
```

Pure-Python implementation — no binary needed. Requires numpy and scipy:

```bash
pip install numpy scipy
```

Implements the same algorithm as goimagehash (the library Stash uses internally), validated against a library of stored hashes. VAAPI hardware decode is used for frame extraction when available.

### Videohashes binary

```python
phash_backend = "binary"
```

Uses [Peolic's videohashes binary](https://github.com/peolic/videohashes). Download the right executable for your OS into the `bin/` directory. No additional Python dependencies required.

---

## GPU Acceleration

The script auto-detects VAAPI at startup and picks the best encoder automatically. You can also override it from the CLI or lock it in via config.

### VAAPI (Intel / AMD)

```python
vaapi = True   # Use VAAPI if detected (default)
```

```bash
python phash_videohasher_main.py --vaapi    # force on
python phash_videohasher_main.py --novaapi  # force off
```

### NVENC (NVIDIA)

```python
nvenc = True   # Enable NVENC (default: False)
```

```bash
python phash_videohasher_main.py --nvenc
```

### When both are available

```python
hw_priority = "vaapi"   # "vaapi" (default) or "nvenc"
```

```bash
python phash_videohasher_main.py --hw-priority nvenc
```

Encoder resolution order: **VAAPI → NVENC → libx264**

### Performance comparison

When benchmarked on a batch of 25 comparable scenes VAAPI came out ~35% faster than NVENC. Results will vary depending on your GPU generation, driver version, and video characteristics — but GPU acceleration over software is always worth enabling if you have it.

---

## Usage

### The basics

**Phash is always generated** — it's the core job and runs unconditionally whenever a scene is processed. You don't need a flag for it.

Sprite and preview generation follow the `generate_sprite` and `generate_preview` settings in `config.py` (both default to `True`). Marker generation is off by default and must be enabled via config or `--generate-markers`. The CLI flags force these on regardless of config.

```bash
# Default run — phash + cover + whatever is enabled in config.py, loops until done
python phash_videohasher_main.py

# Force all generation on, regardless of config
python phash_videohasher_main.py --generate-sprite --generate-preview --generate-markers

# Run one batch and exit (good for cron)
python phash_videohasher_main.py --once --batch-size 25

# Test on a small sample first
python phash_videohasher_main.py --once --batch-size 5 --verbose

# Filter to specific files
python phash_videohasher_main.py --filemask "JoonMali*" --generate-sprite --generate-preview --once
```

### Generate missing media in bulk

The integrated flags (`--generate-sprite`, `--generate-preview`, `--generate-markers`) only run during scene processing — they won't touch scenes that already have a phash. If you want to backfill sprites, previews, or marker media for scenes that were already hashed, use the standalone modes instead. These search for scenes missing specific media regardless of phash status:

```bash
# Generate missing sprites (50 at a time)
python phash_videohasher_main.py --standalone-sprites --sprite-batch-size 50 --verbose

# Generate missing previews (25 at a time)
python phash_videohasher_main.py --standalone-previews --preview-batch-size 25 --verbose

# Generate missing marker media (100 at a time)
python phash_videohasher_main.py --standalone-markers --marker-batch-size 100 --verbose

# Run all three at once
python phash_videohasher_main.py --standalone-sprites --standalone-previews --standalone-markers
```

You can also generate only specific types of marker media:

```bash
python phash_videohasher_main.py --standalone-markers --marker-preview-only     # MP4 clips only
python phash_videohasher_main.py --standalone-markers --marker-thumbnail-only   # WebP animations only
python phash_videohasher_main.py --standalone-markers --marker-screenshot-only  # JPG screenshots only
```

### Error recovery

```bash
# Retry scenes that previously failed
python phash_videohasher_main.py --retry-errors

# Clear all error tags to start completely fresh
python phash_videohasher_main.py --clear-error-tags
```

### See what it would do

```bash
python phash_videohasher_main.py --dry-run --verbose --once
python phash_videohasher_main.py --standalone-markers --dry-run --verbose
```

---

## Marker Generation

Marker generation is off by default. Turn it on in `config.py` or with the `--generate-markers` flag:

```python
generate_markers = True

# What to generate (all on by default)
marker_preview_enabled    = True   # 20-second MP4 clips
marker_thumbnail_enabled  = True   # 5-second WebP animations
marker_screenshot_enabled = True   # Single JPG frames

# Timing and quality
marker_preview_duration   = 20     # MP4 clip length in seconds
marker_thumbnail_duration = 5      # WebP animation length in seconds
marker_thumbnail_fps      = 12     # WebP frame rate
marker_batch_size         = 50     # Batch size for standalone marker mode
```

Marker files are saved alongside your other generated media:

```
{marker_path}/markers/{oshash}/{seconds}.mp4
{marker_path}/markers/{oshash}/{seconds}.webp
{marker_path}/markers/{oshash}/{seconds}.jpg
```

---

## CLI Reference

```
Core options:
  --batch-size N        Scenes per batch (default: 25)
  --max-workers N       Parallel worker threads (default: 4)
  --once                Process one batch and exit
  --verbose             Progress bars and detailed output
  --debug               FFmpeg commands and timing breakdowns
  --dry-run             Simulate without making changes
  --filemask PATTERN    Filter scenes by filename (e.g. 'JoonMali*')
  --windows             Use Windows paths and binaries

Integrated scene processing (only runs on scenes missing a phash):
  --generate-sprite     Force sprite generation on during scene processing
  --generate-preview    Force preview generation on during scene processing
  --generate-markers    Force marker generation on during scene processing

Standalone modes (runs regardless of phash status — use to backfill existing scenes):
  --standalone-sprites          Generate missing sprites only
  --sprite-batch-size N         Batch size (default: 25)
  --standalone-previews         Generate missing previews only
  --preview-batch-size N        Batch size (default: 25)
  --standalone-markers          Generate missing marker media only
  --marker-batch-size N         Batch size (default: 50)
  --marker-preview-only         MP4 clips only
  --marker-thumbnail-only       WebP animations only
  --marker-screenshot-only      JPG screenshots only

Hardware acceleration:
  --vaapi                       Force VAAPI on
  --novaapi                     Force VAAPI off
  --nvenc                       Enable NVIDIA NVENC
  --hw-priority {vaapi,nvenc}   Which encoder wins when both are available

Utilities:
  --health-check        Validate config and exit
  --retry-errors        Process scenes with error tags
  --clear-error-tags    Remove all error tags and exit
```

---

## Running on multiple machines

This is where it really shines. Each node claims a batch of scenes via Stash tags, processes them, and releases the claims when done. Other nodes skip anything that's already claimed.

1. Node A claims scenes 1–25 (adds "In Process" tag)
2. Node B sees those as claimed, picks scenes 26–50
3. When Node A finishes a scene, it removes the tag
4. That scene is only eligible again if it still needs work

There's a small race window during random page selection, but the claiming system covers it almost entirely in practice.

---

## Error Handling

**One failure won't take down the batch.** Each scene processes independently. If something goes wrong:

- Phash failures get tagged with `hashing_error_tag`
- Cover failures get tagged with `cover_error_tag`
- The failure is logged to `error_log.txt` with a timestamp
- The scene is skipped in future runs until you explicitly retry it

Every scene also has a **10-minute timeout**. If a video is hanging for some reason, it gets tagged and the batch continues.

---

## Troubleshooting

**VAAPI not working** — Run `--health-check`. Make sure you have Intel/AMD GPU drivers installed, FFmpeg compiled with VAAPI support, and read/write access to `/dev/dri/renderD128` (or whichever device you have).

Setting up VAAPI on Ubuntu:

- **Intel (Broadwell and newer):** Install `intel-media-va-driver` (or `intel-media-va-driver-non-free` for additional codec support), then verify with `vainfo`. See the [intel/media-driver](https://github.com/intel/media-driver) repo for supported hardware.
  ```bash
  sudo apt install intel-media-va-driver vainfo
  ```
- **Intel (older / Haswell and below):** Use `i965-va-driver` instead.
  ```bash
  sudo apt install i965-va-driver vainfo
  ```
- **AMD:** VAAPI support is included in Mesa — install `mesa-va-drivers` and the AMDGPU firmware.
  ```bash
  sudo apt install mesa-va-drivers vainfo
  ```
- **FFmpeg VAAPI guide:** [trac.ffmpeg.org/wiki/Hardware/VAAPI](https://trac.ffmpeg.org/wiki/Hardware/VAAPI) — covers filter graphs, encode/decode support, and troubleshooting FFmpeg-specific issues.
- **Ubuntu community wiki:** [help.ubuntu.com/community/HardwareVideoAcceleration](https://help.ubuntu.com/community/HardwareVideoAcceleration) — broader overview of VA-API, VDPAU, and NVENC setup on Ubuntu.

**Leftover temp directories** — All temp files go in `.tmp/` and are cleaned automatically at the start and end of each run. If something was interrupted, just run the script again and it'll clean up.

**Error tags piling up** — Check `error_log.txt` to see what failed, fix any config issues, then:
```bash
python phash_videohasher_main.py --clear-error-tags
python phash_videohasher_main.py --retry-errors
```

**Process hangs** — The 10-minute timeout per scene should prevent this. If you're still seeing hangs, check `error_log.txt` for details on which scenes are timing out.

---

## License

MIT — see [LICENSE](LICENSE)

## Credits

- [Stash](https://github.com/stashapp/stash) — the media organizer this was built for
- [goimagehash](https://github.com/corona10/goimagehash) — the perceptual hash algorithm this implements
- [Peolic's videohashes](https://github.com/peolic/videohashes) — alternative binary backend
- Everyone who filed bugs and tested fixes

---

**Pro tip:** Run this on a few machines simultaneously, set `--batch-size 50`, schedule it with cron, and let it work through your backlog overnight.
