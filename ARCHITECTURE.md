# Architecture Documentation

This document provides detailed technical information about the phashvaapi system architecture, design decisions, and implementation details.

## Table of Contents
- [System Overview](#system-overview)
- [Core Components](#core-components)
- [Processing Pipeline](#processing-pipeline)
- [Standalone Generation Modes](#standalone-generation-modes)
- [Marker Generation System](#marker-generation-system)
- [Hardware Acceleration](#hardware-acceleration)
- [Distributed Processing](#distributed-processing)
- [Error Handling](#error-handling)
- [Performance Optimizations](#performance-optimizations)

## System Overview

phashvaapi is a multi-threaded video processing pipeline that integrates with Stash to automatically generate video metadata and derivatives. The system is designed for:

- **High throughput** - Process hundreds of videos per hour
- **Reliability** - Graceful error handling and recovery
- **Scalability** - Distributed processing across multiple systems
- **Efficiency** - Hardware acceleration and optimized workflows

### Design Principles

1. **Idempotency** - Operations can be safely retried without side effects
2. **Isolation** - Failures in one scene don't affect others
3. **Transparency** - Comprehensive logging and progress reporting
4. **Flexibility** - Configurable via CLI and config file

## Core Components

### 1. Main Orchestrator (`phash_videohasher_main.py`)

**Responsibilities:**
- CLI argument parsing and configuration
- VAAPI detection and device path resolution
- Batch processing loop coordination
- Thread pool management
- Graceful shutdown handling

**Key Functions:**
```python
def apply_cli_args(args)
    # Applies CLI arguments to config module

def clean_temp_dirs()
    # Removes leftover temporary directories from previous runs

def main()
    # Main processing loop
```

**Processing Loop:**
```
1. Clean temporary directories
2. Discover scenes (random batch selection)
3. Initialize thread pool
4. Submit scenes to workers
5. Wait for completion
6. Handle Ctrl+C gracefully
7. Repeat or exit based on --once flag
```

### 2. Scene Discovery (`helpers/scene_discovery.py`)

**Purpose:** Query Stash API to find unprocessed scenes and select a random batch to minimize overlap across distributed systems.

**Query Filter:**
- Scenes without a phash fingerprint
- Excludes scenes tagged with: `hashing_tag`, `hashing_error_tag`, `cover_error_tag`
- Sorted by creation date (newest first)

**Batch Selection Strategy:**
```python
# Step 1: Count total matching scenes
total_count = len(all_scenes)

# Step 2: Calculate total pages
total_pages = (total_count + per_page - 1) // per_page

# Step 3: Randomly select one page
selected_page = random.randint(1, total_pages)

# Step 4: Fetch that specific page
batch_scenes = stash.find_scenes(page=selected_page)
```

**Why Random Selection?**
- Multiple systems can run concurrently without coordination
- Reduces likelihood of processing the same scenes
- Combined with scene claiming for race condition mitigation

### 3. Scene Processor (`helpers/scene_processor.py`)

**Purpose:** Orchestrate all processing steps for a single scene.

**Function Signature:**
```python
def process_scene(scene, index=None, total_batch=None,
                  vaapi_supported=False, vaapi_device=None)
```

**Processing Steps:**
1. Path translation (network storage → local paths)
2. File existence verification
3. Scene claiming (add `hashing_tag`)
4. **Try block begins:**
   - Perceptual hash generation
   - Cover image extraction (if needed)
   - Sprite sheet generation (if enabled)
   - Preview video generation (if enabled)
5. **Finally block:**
   - Scene release (remove `hashing_tag`)

**Error Isolation:**
- Each step wrapped in try/except
- Early returns on critical failures
- Finally block ensures scene always released
- Errors logged and tagged appropriately

### 4. Stash API Wrapper (`helpers/stash_utils.py`)

**Purpose:** Abstraction layer over StashAPI with dry-run support.

**Key Functions:**
```python
claim_scene(scene_id)           # Add hashing_tag
release_scene(scene_id)         # Remove hashing_tag
tag_scene_error(scene_id, tag)  # Add error tag, remove hashing_tag
update_phash(file_id, phash)    # Set phash fingerprint
update_cover(scene_id, data)    # Upload cover image
log_scene_failure(...)          # Write to error_log.txt
```

**Dry-Run Mode:**
- All write operations check `config.dry_run`
- Print what would be done instead of making changes
- Allows safe testing without modifying Stash database

### 5. VAAPI Detection (`helpers/vaapi_utils.py`)

**Purpose:** Detect GPU video acceleration capability and device path.

**Detection Algorithm:**
```python
def vaapi_available():
    device_paths = [
        "/dev/dri/renderD128",  # Primary render node
        "/dev/dri/card0",       # Primary card
        "/dev/dri/card1"        # Secondary card
    ]
    for device in device_paths:
        try:
            result = subprocess.run([
                "vainfo", "--display", "drm", "--device", device
            ], timeout=5)
            if "VA-API version" in output and "Driver version" in output:
                return True, device  # Found working device
        except:
            continue
    return False, None  # No VAAPI support
```

**Detection Timing:**
- Called once at startup in main script
- Result passed to all workers and generators
- Eliminates hundreds of redundant subprocess calls

### 6. Sprite Generator (`helpers/video_sprite_generator.py`)

**Purpose:** Generate 9×9 thumbnail grids with WebVTT metadata for video scrubbing.

**Architecture:**
```python
class VideoSpriteGenerator:
    def __init__(self, ..., use_vaapi=None, vaapi_device=None)

    def generate_sprite(self)
        # Main entry point

    def take_screenshots(self)
        # Extract 81 frames in parallel
        # Detect VAAPI once, pass to all workers

    def extract_and_resize(self, i, interval, use_vaapi)
        # Worker function for single frame
        # Uses VAAPI or software based on passed flag

    def create_sprite(self)
        # Assemble frames into single image
```

**Optimization: Single VAAPI Detection**
```python
# BEFORE (inefficient):
def extract_and_resize(self, i, interval):
    vaapi_ok, _ = vaapi_available()  # Called 81 times! ❌

# AFTER (optimized):
def take_screenshots(self):
    use_vaapi = self.use_vaapi  # Passed from parent ✅
    futures = [executor.submit(self.extract_and_resize, i, interval, use_vaapi)]
```

**Performance Impact:**
- Each `vaapi_available()` call: ~50-100ms
- 81 calls per video: ~4-8 seconds overhead
- Optimization saves 4-8 seconds per video

### 7. Preview Generator (`helpers/preview_video_generator.py`)

**Purpose:** Create preview videos by extracting and concatenating clips.

**Architecture:**
```python
class PreviewVideoGenerator:
    def __init__(self, ..., use_vaapi=None, vaapi_device=None)

    def generate_preview(self)
        # Main entry point

    def generate_clips(self)
        # Extract 15 clips in parallel
        # Uses VAAPI device if enabled

    def concatenate_clips(self, clips)
        # Combine clips into single video
        # Respects VAAPI setting (critical fix!)
```

**Critical Fix: Concatenation VAAPI Respect**
```python
# BEFORE (bug):
def concatenate_clips(self, clips):
    command.extend([
        '-vaapi_device', '/dev/dri/renderD128',  # Always added! ❌
        '-c:v', 'h264_vaapi',
    ])

# AFTER (fixed):
def concatenate_clips(self, clips):
    use_vaapi = self.use_vaapi if self.use_vaapi is not None else False
    if use_vaapi:
        command.extend(['-vaapi_device', self.vaapi_device, ...])  ✅
    else:
        command.extend(['-c:v', 'libx264', ...])  ✅
```

### 8. Discovery Modules

**Purpose:** Find scenes/markers missing specific media types for standalone generation.

#### Sprite Discovery (`helpers/sprite_discovery.py`)
```python
def discover_missing_sprites(limit=None):
    """
    Query all scenes from Stash, check if sprite files exist.

    Returns: list[dict] with:
        - scene_id, video_path, oshash, duration, scene_title
    """
```

**Logic:**
1. Query all scenes via Stash API
2. Check if `{sprite_path}/{oshash}_sprite.jpg` exists
3. Translate Docker/Stash paths to local paths
4. Verify source video file exists
5. Apply limit if specified

#### Preview Discovery (`helpers/preview_discovery.py`)
```python
def discover_missing_previews(limit=None):
    """
    Query all scenes from Stash, check if preview files exist.

    Returns: list[dict] with:
        - scene_id, video_path, oshash, duration, scene_title
    """
```

**Logic:** Similar to sprite discovery, checks for `{preview_path}/{oshash}.mp4`

#### Marker Discovery (`helpers/marker_discovery.py`)
```python
def discover_missing_markers(limit=None):
    """
    Query all markers from Stash, check if marker media exists.

    Returns: list[dict] with:
        - marker_id, scene_id, seconds, video_path, oshash, marker_title
    """
```

**Logic:**
1. Query all markers via `stash.find_scene_markers()`
2. For each marker, check if output files exist:
   - `{marker_path}/markers/{oshash}/{int(seconds)}.mp4` (if enabled)
   - `{marker_path}/markers/{oshash}/{int(seconds)}.webp` (if enabled)
   - `{marker_path}/markers/{oshash}/{int(seconds)}.jpg` (if enabled)
3. Translate paths and verify source video exists
4. Apply limit if specified

### 9. Marker Generator (`helpers/marker_generator.py`)

**Purpose:** Generate media files (MP4/WebP/JPG) for scene markers (timestamps within videos).

**Architecture:**
```python
class MarkerGenerator:
    def __init__(self, video_path, marker_seconds, oshash, output_base_dir,
                 ffmpeg='ffmpeg', ffprobe='ffprobe',
                 preview_enabled=True, thumbnail_enabled=True, screenshot_enabled=True,
                 preview_duration=20, thumbnail_duration=5, thumbnail_fps=12,
                 use_vaapi=None, vaapi_device=None)

    def generate_preview(self)       # MP4 preview (20-second clip)
    def generate_thumbnail(self)     # WebP thumbnail (5-second animation)
    def generate_screenshot(self)    # JPG screenshot (single frame)
    def generate_marker(self)        # Main orchestrator with try/finally
    def clean_temp_dirs(self)        # Cleanup temporary directories
```

**File Structure:**
```
{marker_path}/markers/{oshash}/{int(seconds)}.{mp4|webp|jpg}

Example:
/mnt/stash/stash/generated/markers/abc123def456/15.mp4
/mnt/stash/stash/generated/markers/abc123def456/15.webp
/mnt/stash/stash/generated/markers/abc123def456/15.jpg
```

**Integer Truncation:**
- Marker at 15.2 seconds → filename `15.mp4`
- Marker at 15.9 seconds → filename `15.mp4` (overwrites previous)
- Design choice for collision handling

**Media Generation:**

1. **MP4 Preview (20-second clip):**
```bash
# VAAPI:
ffmpeg -vaapi_device {device} -ss {seconds} -t 20 -i {video} \
  -vf 'format=nv12,hwupload,scale_vaapi=640:-2' \
  -c:v h264_vaapi -global_quality 18 -an {output}

# NVENC:
ffmpeg -ss {seconds} -t 20 -i {video} \
  -vf 'scale=640:-2' -c:v h264_nvenc -cq:v 18 -preset p4 -an {output}

# Software fallback:
ffmpeg -ss {seconds} -t 20 -i {video} \
  -vf 'scale=640:-2' -c:v libx264 -crf 18 -preset slow -an {output}
```

2. **WebP Thumbnail (5-second animation):**
```bash
ffmpeg -ss {seconds} -t 5 -i {video} \
  -vf 'scale=640:-2,fps=12' \
  -c:v libwebp -lossless 1 -q:v 70 -compression_level 6 -loop 0 {output}
```

3. **JPG Screenshot (single frame):**
```bash
ffmpeg -ss {seconds} -i {video} \
  -vframes 1 -q:v 2 {output}
```

**Error Isolation:**
- Marker failures don't affect scene processing success
- Logged separately via `log_marker_failure()`
- Markers don't support Stash tags (no error tagging)
- Errors written to `error_log.txt`

## Standalone Generation Modes

Standalone modes allow generating sprites, previews, and markers without full scene processing.

### Architecture

**Worker Functions:**
```python
def process_sprite(scene_data, index, total, vaapi_supported, vaapi_device):
    """Generate sprite for a single scene (standalone mode)."""

def process_preview(scene_data, index, total, vaapi_supported, vaapi_device):
    """Generate preview for a single scene (standalone mode)."""

def process_marker(marker_data, index, total, vaapi_supported, vaapi_device):
    """Generate marker media for a single marker (standalone mode)."""
```

### Standalone Mode Detection

```python
standalone_mode = (
    args.standalone_sprites or
    args.standalone_previews or
    args.standalone_markers or
    args.generate_markers  # Alias for standalone_markers
)

if standalone_mode:
    # Execute standalone generation and exit
    # Don't enter main scene processing loop
```

### Usage Patterns

**Standalone sprite generation:**
```bash
python phash_videohasher_main.py --standalone-sprites --sprite-batch-size 50 --verbose
```

**Standalone preview generation:**
```bash
python phash_videohasher_main.py --standalone-previews --preview-batch-size 25 --verbose
```

**Standalone marker generation:**
```bash
python phash_videohasher_main.py --standalone-markers --marker-batch-size 100 --verbose
```

**Combined standalone generation:**
```bash
python phash_videohasher_main.py --standalone-sprites --standalone-previews --standalone-markers --verbose
```

### Benefits

1. **Flexibility** - Generate specific media types without full processing
2. **Performance** - Skip unnecessary work (phash, cover)
3. **Scheduling** - Run different generation types at different times
4. **Testing** - Test specific generators in isolation

## Processing Pipeline

### Mode Selection

```
┌─────────────────────────────────────────────────────────────┐
│                         Startup                              │
│  • Parse CLI arguments                                       │
│  • Detect VAAPI (once)                                       │
│  • Initialize configuration                                  │
│  • Run health checks                                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
           ┌─────────────┴─────────────┐
           │  Standalone Mode Active?  │
           └──────┬──────────────┬─────┘
                  │ YES          │ NO
                  ▼              ▼
      ┌───────────────┐   ┌──────────────────┐
      │  Standalone   │   │  Integrated      │
      │  Generation   │   │  Scene           │
      │  Mode         │   │  Processing      │
      └───────────────┘   └──────────────────┘
```

### High-Level Flow: Integrated Mode

```
┌─────────────────────────────────────────────────────────────┐
│                    Batch Processing Loop                     │
│  1. Clean temp directories                                   │
│  2. Discover scenes (random page selection)                  │
│  3. Create thread pool                                       │
│  4. Submit scenes to workers ──────────┐                     │
│  5. Collect results                    │                     │
│  6. Shutdown thread pool               │                     │
│  7. Repeat or exit                     │                     │
└────────────────────────────────────────┼────────────────────┘
                                         │
        ┌────────────────────────────────┘
        │ (parallel workers)
        ▼
┌─────────────────────────────────────────────────────────────┐
│                   Per-Scene Processing                       │
│  • Translate file paths                                      │
│  • Verify file exists                                        │
│  • Claim scene (add tag)                                     │
│  • TRY:                                                       │
│    ├─ Generate phash                                         │
│    ├─ Extract cover image                                    │
│    ├─ Generate sprite sheet (if --generate-sprite)           │
│    ├─ Generate preview video (if --generate-preview)         │
│    └─ Generate marker media (if --generate-markers)          │
│  • FINALLY:                                                  │
│    └─ Release scene (remove tag)                             │
└─────────────────────────────────────────────────────────────┘
```

### High-Level Flow: Standalone Mode

```
┌─────────────────────────────────────────────────────────────┐
│                   Standalone Generation                      │
│  1. Clean temp directories                                   │
│  2. Discover missing media (sprites/previews/markers)        │
│  3. Create thread pool                                       │
│  4. Submit items to workers ────────────┐                    │
│  5. Collect results                     │                    │
│  6. Shutdown thread pool                │                    │
│  7. Exit (no loop)                      │                    │
└─────────────────────────────────────────┼───────────────────┘
                                          │
         ┌────────────────────────────────┘
         │ (parallel workers)
         ▼
┌─────────────────────────────────────────────────────────────┐
│              Per-Item Processing (No Tags)                   │
│  • Translate file paths                                      │
│  • Verify file exists                                        │
│  • Generate media (sprite/preview/marker)                    │
│  • No scene claiming/releasing                               │
│  • Errors logged but don't affect other items                │
└─────────────────────────────────────────────────────────────┘
```

### Thread Pool Architecture

```python
# Main thread creates pool
executor = ThreadPoolExecutor(max_workers=config.max_workers)

# Submit scenes (non-blocking)
futures = []
for scene in scenes:
    future = executor.submit(process_scene, scene, ...)
    futures.append(future)

# Collect results (blocking)
for future in futures:
    try:
        future.result()  # Raises if worker failed
    except Exception as e:
        print(f"Worker error: {e}")

# Cleanup
executor.shutdown(wait=True)
```

**Worker Count Considerations:**
- Each worker processes one scene at a time
- Each scene spawns 4 sub-threads for clip/frame extraction
- Total threads: `max_workers * 5` (1 coordinator + 4 extractors)
- Recommended: `max_workers = CPU_cores / 2`

## Hardware Acceleration

The script supports three encoder paths, resolved once at startup and passed through the entire pipeline.

### Encoder Priority Chain

```
config.vaapi_override (--vaapi / --novaapi)
    │
    ├── Forced ON  → use VAAPI regardless of detection
    ├── Forced OFF → skip VAAPI
    └── Not set:
          config.vaapi == False → skip VAAPI
          config.vaapi == True  → use auto-detection result

          Then: if vaapi_supported AND config.nvenc AND config.hw_priority == "nvenc"
                    → disable VAAPI, use NVENC instead

Final order: VAAPI → NVENC → libx264 (software)
```

### Architecture Flow

```
Main Script                Scene Processor              Generators
────────────               ───────────────              ──────────
vaapi_available()  ────►   process_scene()  ────►      VideoSpriteGenerator
    │                          │                            │
    │ (once at startup)        │                            │    PreviewVideoGenerator
    ▼                          ▼                            ▼
(supported, device)    (pass both values)         (use device path)
                                                       MarkerGenerator
```

### Benefits of Centralized Detection

**Before (inefficient):**
- Main: 1 call
- Scene processor: 25 calls (per batch)
- Sprite generator: 25 × 81 = 2,025 calls (per batch)
- Preview generator: 25 × 2 = 50 calls (per batch)
- **Total: 2,101 subprocess calls per batch!**

**After (optimized):**
- Main: 1 call
- **Total: 1 subprocess call per batch!**
- **2,100 fewer calls = significant performance gain**

### FFmpeg Commands by Encoder

**Sprite Frame Extraction (VAAPI):**
```bash
ffmpeg -hwaccel vaapi -hwaccel_output_format vaapi \
  -vaapi_device /dev/dri/renderD128 \
  -i input.mp4 -frames:v 1 \
  -vf 'scale_vaapi=160:-2,hwdownload,format=nv12' \
  -c:v png frame.jpg
```

**Preview Clip Extraction (VAAPI):**
```bash
ffmpeg -vaapi_device /dev/dri/renderD128 \
  -ss 30 -i input.mp4 -t 1 \
  -vf 'format=nv12,hwupload,scale_vaapi=640:360' \
  -c:v h264_vaapi -global_quality 18 \
  -an clip.mp4
```

**Preview Clip Extraction (NVENC):**
```bash
ffmpeg -ss 30 -i input.mp4 -t 1 \
  -s 640x360 \
  -c:v h264_nvenc -cq:v 18 -preset p4 \
  -an clip.mp4
```

**Preview Clip Extraction (Software):**
```bash
ffmpeg -ss 30 -i input.mp4 -t 1 \
  -s 640x360 \
  -c:v libx264 -crf 18 -preset slow \
  -an clip.mp4
```

**Preview Concatenation (VAAPI):**
```bash
ffmpeg -f concat -i clips.txt \
  -vaapi_device /dev/dri/renderD128 \
  -vf 'format=nv12,hwupload,scale_vaapi=640:360' \
  -c:v h264_vaapi -global_quality 18 \
  -an preview.mp4
```

## Distributed Processing

### Coordination Strategy

Multiple systems can run simultaneously without explicit coordination:

1. **Random Batch Selection** - Each system selects a random page
   - Reduces probability of overlap
   - Not foolproof (race condition window exists)

2. **Scene Claiming** - Each scene tagged during processing
   - Discovery query excludes claimed scenes
   - Prevents duplicate work after claim
   - Critical: Always release in finally block

3. **Race Condition Window:**
```
Time    System A              System B
────────────────────────────────────────
T0      discover_scenes()
T1      [scenes 1-25]         discover_scenes()
T2      claim scene 1         [scenes 1-25]
T3      process scene 1       claim scene 1  ← Race!
T4      ...                   process scene 1 ← Duplicate work
```

**Mitigation:**
- Window is very small (milliseconds)
- Scene claiming happens before heavy work
- Most scenes will be claimed before System B processes
- Acceptable tradeoff for stateless coordination

### Failure Recovery

**Scene Stuck as "Processing":**
- Scene has `hashing_tag` but no worker processing it
- Caused by: Crash before finally block, power loss, kill -9
- **Solution:** Manually remove tag from scene in Stash

**Future Enhancement:**
- Add timestamp to claiming
- Automatically reclaim scenes claimed >1 hour ago

## Error Handling

### Error Classification

1. **Critical Errors** (abort scene processing)
   - File not found after translation
   - Phash generation failure
   - Sprite generation failure (if enabled)
   - Preview generation failure (if enabled)

2. **Non-Critical Errors** (log and continue)
   - Cover image extraction failure
   - Individual clip extraction failure (preview continues with fewer clips)

### Error Tagging Strategy

```python
# Processing tag (temporary)
hashing_tag = 15015          # "Currently processing"

# Error tags (permanent until fixed)
hashing_error_tag = 15018    # "Phash/sprite/preview failed"
cover_error_tag = 15019      # "Cover extraction failed"
```

**Error State Machine:**
```
Unprocessed Scene
    │
    ▼
[Claim] → hashing_tag added
    │
    ├─[Success]──► hashing_tag removed ──► Done
    │
    └─[Failure]──► hashing_tag removed
                   error_tag added ──► Requires manual review
```

### Error Logging

**error_log.txt Format:**
```
2026-02-05 14:32:15 ❌ Scene 12345 — video.mp4 failed during hashing: [Errno 2] No such file or directory
2026-02-05 14:33:42 ❌ Scene 67890 — movie.mkv failed during preview generation: FFmpeg failed to concatenate clips
```

**Logging Locations:**
- Console output (with timestamps and emojis)
- error_log.txt (persistent log file)
- Stash tags (searchable in UI)

## Performance Optimizations

### 1. VAAPI Detection Optimization
- **Before:** 2,100+ subprocess calls per batch
- **After:** 1 subprocess call per batch
- **Gain:** ~10-15 seconds per batch

### 2. Parallel Frame Extraction
```python
# Sprite: 81 frames extracted in parallel (4 workers)
# Preview: 15 clips extracted in parallel (4 workers)
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(extract, i) for i in range(count)]
```

### 3. Path Translation Caching
- Translations applied once per scene
- Result used for all operations
- Avoids repeated string operations

### 4. Temporary Directory Management
- Each operation uses unique temp dir (prevents conflicts)
- Cleaned up in finally blocks
- Startup cleanup removes leftover dirs

### 5. Progressive JPEG/PNG
- Thumbnails saved with minimal quality settings
- Reduces I/O overhead
- Final sprite assembled with LANCZOS resampling

### Benchmarking Results

**Single Scene (Intel i5-8400, VAAPI enabled):**
- Phash: ~3-5 seconds
- Cover: ~1 second
- Sprite (81 frames): ~8-12 seconds with VAAPI, ~15-20 without
- Preview (15 clips): ~10-15 seconds with VAAPI, ~20-30 without
- **Total: ~22-33 seconds with VAAPI, ~39-56 without**

**Batch of 25 Scenes (4 workers):**
- With VAAPI: ~3-5 minutes
- Without VAAPI: ~6-10 minutes
- **VAAPI provides ~40-50% improvement**

## Future Enhancements

### Planned Features
1. **Scene claim timeout** - Auto-reclaim stuck scenes after >1 hour
2. **Progress persistence** - Resume after crash
3. **Adaptive batch sizing** - Adjust based on error rate
4. **Health metrics** - Prometheus/Grafana integration

### Known Limitations
1. **Race condition** - Random page selection not perfect (mitigated by scene claiming)
2. **excluded_paths pagination** - Excluded scenes are counted in total/page calculation; a page may return fewer scenes than expected if many are excluded
3. **Windows VAAPI** - No VAAPI support on Windows; use NVENC instead

---

For more information, see [README.md](README.md) or open an issue on GitHub.
