# Architecture Documentation

This document provides detailed technical information about the phashvaapi system architecture, design decisions, and implementation details.

## Table of Contents
- [System Overview](#system-overview)
- [Core Components](#core-components)
- [Processing Pipeline](#processing-pipeline)
- [VAAPI Integration](#vaapi-integration)
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

## Processing Pipeline

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────┐
│                         Startup                              │
│  • Parse CLI arguments                                       │
│  • Detect VAAPI (once)                                       │
│  • Initialize configuration                                  │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
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
│    ├─ Generate sprite sheet (if enabled)                     │
│    └─ Generate preview video (if enabled)                    │
│  • FINALLY:                                                  │
│    └─ Release scene (remove tag)                             │
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

## VAAPI Integration

### Architecture Flow

```
Main Script                Scene Processor              Generators
────────────               ───────────────              ──────────
vaapi_available()  ────►   process_scene()  ────►      VideoSpriteGenerator
    │                          │                            │
    │ (once at startup)        │                            │
    ▼                          ▼                            ▼
(supported, device)    (pass both values)         (use device path)
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

### VAAPI FFmpeg Commands

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
  -c:v h264_vaapi -crf 18 -preset fast \
  -an clip.mp4
```

**Preview Concatenation (VAAPI):**
```bash
ffmpeg -f concat -i clips.txt \
  -vaapi_device /dev/dri/renderD128 \
  -vf 'format=nv12,hwupload,scale_vaapi=640:360' \
  -c:v h264_vaapi -crf 18 -preset fast \
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
1. **Scene claim timeout** - Auto-reclaim stuck scenes
2. **Progress persistence** - Resume after crash
3. **Adaptive batch sizing** - Adjust based on error rate
4. **Health metrics** - Prometheus/Grafana integration
5. **NVIDIA NVENC support** - Alternative to VAAPI

### Known Limitations
1. **Race condition** - Random page selection not perfect
2. **No retries** - Failed scenes require manual intervention
3. **No progress bar** - For overall batch completion
4. **Windows VAAPI** - Limited/no support on Windows

---

For more information, see [README.md](README.md) or open an issue on GitHub.
