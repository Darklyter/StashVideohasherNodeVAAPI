# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial public release
- Comprehensive documentation (README.md, ARCHITECTURE.md, CONTRIBUTING.md)
- MIT License
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

- **v0.1.0** - Initial release with core functionality
- **Unreleased** - Bug fixes and performance optimizations

---

For upgrade instructions and migration guides, see the [README.md](README.md).
