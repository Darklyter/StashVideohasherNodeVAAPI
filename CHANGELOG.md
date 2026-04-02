# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

- **v1.2.0** - NVENC support, hardware encoder priority, excluded paths, audio fix, health check encode tests
- **v1.1.0** - Marker generation, standalone modes, API key support, and performance fixes
- **v0.1.0** - Initial release with core functionality

---

For upgrade instructions and migration guides, see the [README.md](README.md).
