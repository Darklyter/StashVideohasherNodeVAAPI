# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] - 2026-04-03

### Added
- **Pure-Python phash backend** - Eliminates the hard dependency on Peolic's `videohashes` binary
  - Implements the goimagehash `PerceptionHash` algorithm used by Stash in pure Python (numpy/scipy)
  - Selectable via `config.phash_backend`: `"internal"` or `"binary"` (default)
  - Accuracy: ~75% of hashes are bit-for-bit identical; remainder differ by Hamming distance 2–4, well within Stash's identical-match threshold. Use `"binary"` if exact hash reproduction is required
  - Benefits from VAAPI hardware decode during frame extraction when VAAPI is available
  - Health check updated: validates numpy/scipy for `"internal"` backend; validates binary path/executable bit for `"binary"` backend
  - `requirements.txt` updated with `numpy` and `scipy` dependencies
- **`batch_sleep` configuration** - Configurable inter-batch delay (default: 5 seconds)
  - `config.batch_sleep = 5` — set to 0 to disable delay entirely
  - `--batch-sleep N` CLI flag overrides config at runtime
- **`--version` flag** - Print version and exit (`python phash_videohasher_main.py --version`)
- **Paginated discovery** - Standalone discovery modules (`sprite_discovery`, `preview_discovery`, `marker_discovery`) now fetch scenes and markers in pages of 100 instead of loading the entire database into memory at once; early-exits as soon as the requested batch limit is reached
- **`--clear-hashing-tags` flag** - Recover from hard kills that leave scenes stuck with the in-process hashing tag; clears the tag from all affected scenes and exits
- **`excluded_paths` filtering in all discovery modules** - `sprite_discovery`, `preview_discovery`, and `marker_discovery` now respect `config.excluded_paths`; previously only `scene_discovery` filtered by path
- **Configurable error log path and rotation** - `config.error_log_path` and `config.error_log_max_mb` (default: `"error_log.txt"`, 10 MB); log is rotated to `.1` when size limit is reached
- **Test suite** - 53 tests across 4 test files covering the phash algorithm, preview generator, excluded-path filtering, oshash validation, and batch statistics

### Fixed
- **VAAPI device `None` crash** - All three generators now guard `use_vaapi` with `bool(self.use_vaapi) and bool(self.vaapi_device)`; VAAPI falls back to software if device is `None` rather than passing `None` as a literal string to ffmpeg
- **PIL file handle exhaustion in sprite assembly** - `create_sprite()` previously opened all 81 frame images simultaneously; images are now opened one at a time inside `with` blocks, preventing "Too many open files" errors
- **Silent ffmpeg failures** - All `subprocess.run(check=True)` calls in generators now capture `stderr`; the last line of ffmpeg output is included in error messages instead of being discarded
- **Bare `except:` in `VideoSpriteGenerator.get_video_duration()`** - Replaced with `except (ValueError, TypeError)` that raises a `RuntimeError` with the actual ffprobe error message; also fixed `stderr=subprocess.STDOUT` merging ffprobe errors into the duration output
- **Stash `update_scenes` ids not wrapped in lists** - All five `update_scenes` calls now pass `[scene_id]` instead of a bare string (`tag_scene_error`, `claim_scene`, `release_scene`, `clear_error_tags`)
- **`excluded_paths` substring matching** - Changed from `ep in path` to `path.startswith(ep)` in both `scene_discovery.py` and `stash_utils.py`; prevents partial-match false positives (e.g. `/mnt/archive/` no longer matches `/mnt/archive2/`)
- **Invalid oshash replaced with random string** - Instead of silently substituting a random 12-character hash, scenes with missing or malformed oshash are now tagged with an error and skipped
- **`filename_pretty` regex crash** - Replaced fragile `re.search(r'.*[/\\](.*?)$', ...).group(1)` with `os.path.basename()`
- **Requests call with no timeout** - Cover image screenshot check now uses `timeout=10`
- **Duplicate `sprite_start` timer reset** - The second `sprite_start = time.time()` (after generator creation) now only runs outside debug mode, preserving the debug timing set before generator setup
- **Hardcoded `/dev/dri/renderD128` fallback removed** from all three generator constructors
- **`ThreadPoolExecutor` max_workers hardcoded to 4** in sprite and preview generators; now uses `config.max_workers`
- **Case-sensitive `.jpg` extension check** in `VideoSpriteGenerator.create_sprite()` changed to `.lower().endswith('.jpg')`
- **Dead `preview_cmd` variable** removed from `scene_processor.py` — shell string was constructed but never executed; debug output it produced didn't match the actual ffmpeg command run by `PreviewVideoGenerator`
- **Dead `detect_vaapi()` function** removed from `phash_generator.py` along with its unused import
- **Dead `get_scenes_to_process()` function** removed from `stash_utils.py` — was replaced in an earlier refactor but never deleted
- **`--standalone-markers` incorrectly enabled integrated marker generation** - `apply_cli_args` was setting `config.generate_markers = args.generate_markers or args.standalone_markers`; standalone marker mode no longer enables the integrated marker step
- **`get_total_scene_count()` loaded full database** - When no `excluded_paths` are set, now uses a count-only query (`per_page=1, get_count=True`) instead of fetching all scene IDs; significantly faster on large databases
- **Benchmark scripts used hardcoded `max_workers=4`** - `preview_benchmark.py` and `sprite_benchmark.py` now use `config.max_workers`

### Changed
- Ctrl+C and SIGTERM during inter-batch sleep now exit immediately — replaced `time.sleep()` with `threading.Event.wait()` so the shutdown signal wakes the sleep instantly rather than waiting for the full delay to expire

## [1.2.0] - 2026-04-01

### Added
- **NVENC hardware encoder support** - NVIDIA GPU acceleration for preview and marker MP4 generation
  - `config.nvenc` toggle (default: False)
  - `--nvenc` CLI flag overrides config
  - Applies to preview clip extraction, concatenation, and marker MP4 previews
- **Hardware encoder priority** - Control which GPU encoder wins when both VAAPI and NVENC are configured
  - `config.hw_priority = "vaapi"` (default) or `"nvenc"`
  - `--hw-priority {vaapi,nvenc}` CLI flag overrides config
- **VAAPI enable/disable control** - Opt out of VAAPI without using the CLI
  - `config.vaapi = True/False` (default: True — use VAAPI if detected)
  - `--vaapi` / `--novaapi` CLI flags still override config at runtime
- **`excluded_paths` filtering** - Exclude scenes from processing by file path substring
  - `config.excluded_paths` list (default: empty)
  - Applied to both batch discovery and total scene count
- **`stash_scheme` configuration** - Choose `"http"` or `"https"` for the Stash API connection
- **Functional hardware encode tests in health check** - `--health-check` now performs a real encode using a synthetic video source
  - VAAPI encode test: verifies ffmpeg can use the GPU (not just that the device file exists)
  - NVENC encode test: verifies NVIDIA encoder is working
  - Health check only tests the encoder that will actually be used (respects `hw_priority`)

### Fixed
- **`include_audio` ignored in preview generator** — `config.preview_audio = True` had no effect; all codec branches (VAAPI, NVENC, libx264) now correctly include or exclude audio
- **Invalid VAAPI FFmpeg flags** — `h264_vaapi` does not support `-crf` or `-preset`; corrected to `-global_quality` in preview generator and marker generator
- **`get_total_scene_count()` ignored `excluded_paths`** — count shown to the user was inflated by excluded scenes; now filtered correctly
- **`debug` not declared in `config.py`** — dynamic attribute risked `AttributeError` if `process_scene` ran without CLI initialization; now declared with default `False`
- **UnicodeEncodeError crash in `log_scene_failure()`** — bare `print()` could crash on Windows with non-ASCII filenames; now has safe fallback
- **UnicodeEncodeError crash in `log_marker_failure()`** — same fix applied
- **Error log written without `encoding="utf-8"`** — could fail on Windows with non-ASCII characters in error messages; fixed in both `tag_scene_error()` and `log_marker_failure()`
- **Health check tested both encoders regardless of `hw_priority`** — when `hw_priority=vaapi`, NVENC was also tested even though it wouldn't be used; now mutually exclusive
- **Marker generator VAAPI command used `-crf` flag** — same invalid flag as preview generator; corrected to `-global_quality`

### Changed
- Hardware encoder resolution now follows a user defined priority chain.  For Example: VAAPI (if active) → NVENC (if configured) → libx264
- Encoder selection logged at startup with `--verbose`
- `--vaapi` / `--novaapi` / `--nvenc` help text updated to clarify they override config, not replace it
- **`benchmarking/preview_benchmark.py` rewritten** — now mirrors `PreviewVideoGenerator` pipeline exactly: VAAPI/NVENC/software encoder selection via `resolve_encoder()`, parallel clip extraction with `ThreadPoolExecutor`, correct VAAPI flags (`-global_quality`), `--all` flag for side-by-side encoder comparison
- **`benchmarking/sprite_benchmark.py` rewritten** — now mirrors `VideoSpriteGenerator` pipeline exactly: VAAPI device auto-detected and passed through (no hardcoded path), parallel frame extraction with `ThreadPoolExecutor`, correct software command (`-q:v 2`), PIL resize with `Image.Resampling.LANCZOS`, default grid updated to 9×9 (81 frames), `--all` flag for side-by-side comparison

## [1.1.0] - 2026-03-30

### Added
- Initial public release
- Comprehensive documentation (README.md, ARCHITECTURE.md, CONTRIBUTING.md)
- MIT License
- **Marker generation system** - Generate MP4 previews (20s), WebP thumbnails (5s animations), and JPG screenshots for scene markers
  - Integrated mode: Generate marker media during scene processing (--generate-markers)
  - Standalone mode: Batch process missing marker media (--standalone-markers)
  - Media type filters: --marker-preview-only, --marker-thumbnail-only, --marker-screenshot-only
  - VAAPI hardware acceleration support for MP4 preview generation
  - Configurable durations and quality settings
  - Error isolation: Marker failures don't affect scene processing
- **Standalone generation modes** - Generate sprites, previews, or markers without full scene processing
  - --standalone-sprites: Batch generate sprites only
  - --standalone-previews: Batch generate previews only
  - --standalone-markers: Batch generate marker media only
  - Configurable batch sizes for each mode
  - Combined mode support (run multiple standalone modes together)
- **Discovery modules** - New helper modules for finding missing media
  - sprite_discovery.py: Find scenes missing sprite sheets
  - preview_discovery.py: Find scenes missing preview videos
  - marker_discovery.py: Find markers missing media files
- **Enhanced CLI help** - Organized argument groups with comprehensive usage examples
- **Worker functions** - Dedicated functions for standalone sprite/preview/marker processing
- **Stash API key authentication** - Optional API key support for secured Stash instances
- **Health check system** - Validates configuration, paths, and dependencies before processing
- **Statistics tracking** - Shows success rate, average time, and total processing time after each batch
- **Signal handling** - Graceful shutdown on SIGTERM and SIGINT for systemd/cron compatibility
- **Thread-safe error logging** - Prevents race conditions when writing error_log.txt
- **Timeout protection** - 10-minute timeout per scene prevents hanging on problem videos
- **CLI error management** - New flags: --health-check, --retry-errors, --clear-error-tags
- **Filemask filtering** - Filter scenes by filename pattern for reproducible testing (--filemask)

### Fixed
- **Critical: Scene claim leak** - Scenes now always released via try/finally blocks
- **Critical: KeyboardInterrupt crash** - Executor reference moved outside context manager
- **Critical: Preview concatenation bug** - Now respects --novaapi flag instead of always using VAAPI
- **Performance: Per-frame VAAPI detection** - Moved out of 81× loop, saving 4-8 seconds per video
- **Bug: Unhandled worker exceptions** - Added exception handling around future.result()
- **Bug: Redundant scene claiming** - Removed duplicate claiming from batch loop
- **Bug: Ambiguous working directory** - clean_temp_dirs now uses explicit os.getcwd()
- **Bug: Hardcoded VAAPI device** - Now uses detected device path (renderD128, card0, card1, etc.)
- **Code quality: Duplicate imports** - Removed duplicate sys import in scene_processor.py
- **Code quality: Unused imports** - Removed unused claim_scene import from main

### Changed
- VAAPI detection now runs once at startup instead of hundreds of times per batch
- VAAPI device path now passed throughout pipeline instead of hardcoded
- Removed vaapi_available() calls from generator classes (now passed from parent)
- Scene processor now returns success/failure status for statistics tracking
- Error logging now includes timestamps for better debugging

### Performance
- Eliminated ~2,100 subprocess calls per batch (VAAPI detection optimization)
- Saved 4-8 seconds per video (per-frame VAAPI detection fix)
- Overall batch processing ~40-50% faster with VAAPI enabled

## [0.1.0] - 2026-02-05

### Added
- Core processing pipeline
  - Perceptual hash generation using videohashes binary
  - Cover image extraction from video frames
  - Sprite sheet generation (9×9 grid, 81 thumbnails)
  - Preview video generation (15 clips × 1 second)
- VAAPI hardware acceleration support
  - Automatic GPU detection
  - Fallback to software encoding
  - CLI override flags (--vaapi, --novaapi)
- Distributed processing support
  - Random batch selection for multi-system coordination
  - Scene claiming via Stash tags
  - Graceful error handling and recovery
- CLI interface
  - Configurable batch size and worker count
  - Dry-run mode for testing
  - Verbose and debug output modes
  - Single-batch mode (--once) for cron jobs
- Configuration system
  - Path translation for network storage
  - Customizable tag IDs
  - Preview and sprite settings
- Error handling
  - Per-scene error isolation
  - Comprehensive error logging (error_log.txt)
  - Specific error tags (phash errors vs. cover errors)
- Thread pool parallelism
  - Configurable worker count
  - Graceful shutdown on Ctrl+C
  - Exception handling for worker threads

### Documentation
- Inline code comments throughout
- Function docstrings for key methods
- Debug output for troubleshooting

---

## Version History

- **v1.3.0** - Pure-Python phash backend, paginated discovery, `--version`/`--clear-hashing-tags` flags, excluded_paths in all discovery modules, configurable error log, test suite (53 tests), bug fixes: VAAPI None crash, PIL file leak, silent ffmpeg errors, oshash validation, standalone-markers flag, count query optimization
- **v1.2.0** - NVENC support, hardware encoder priority, excluded paths, audio fix, health check encode tests
- **v1.1.0** - Marker generation, standalone modes, API key support, and performance fixes
- **v0.1.0** - Initial release with core functionality

---

For upgrade instructions and migration guides, see the [README.md](README.md).
