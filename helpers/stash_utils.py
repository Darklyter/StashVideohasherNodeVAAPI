# stash_utils.py

import fnmatch
import os
import re
import threading
from datetime import datetime

import config
from helpers.paths import is_excluded


class _LazyStash:
    """
    Connects to Stash on first use instead of at import time, so --help,
    --version and the health check work (and report cleanly) when Stash is down.
    """
    _instance = None
    _lock = threading.Lock()

    def _connect(self):
        with self._lock:
            if self._instance is None:
                from stashapi.stashapp import StashInterface
                stash_config = {
                    "scheme": config.stash_scheme,
                    "host": config.stash_host,
                    "port": config.stash_port,
                }
                if config.stash_api_key:
                    stash_config["apikey"] = config.stash_api_key
                type(self)._instance = StashInterface(stash_config)
            return self._instance

    def __getattr__(self, name):
        return getattr(self._connect(), name)


stash = _LazyStash()

# Thread-safe error logging
error_log_lock = threading.Lock()

def _rotate_log_if_needed():
    """Rotate error_log_path if it exceeds error_log_max_mb. Called inside error_log_lock."""
    if config.error_log_max_mb <= 0:
        return
    try:
        path = config.error_log_path
        if os.path.exists(path) and os.path.getsize(path) > config.error_log_max_mb * 1024 * 1024:
            rotated = path + ".1"
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(path, rotated)
    except Exception:
        pass  # Rotation failure is non-fatal

def _append_error_log(line):
    try:
        with error_log_lock:
            _rotate_log_if_needed()
            with open(config.error_log_path, "a", encoding="utf-8") as log:
                log.write(line + "\n")
    except Exception as log_err:
        print(f"⚠️ Failed to write {config.error_log_path}: {log_err}")

def _safe_print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('utf-8', errors='replace').decode('ascii', errors='replace'))

def log_scene_failure(scene_id, filename_pretty, step, error):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _safe_print(f"{timestamp} ❌ Scene {scene_id} — {filename_pretty} failed during {step}: {error}")

def reset_terminal():
    import platform
    import sys
    if platform.system() != "Windows" and sys.stdout.isatty():
        # Reset all terminal attributes
        print("\033[0m", end="")  # Reset colors/attributes
        print("\033[?25h", end="")  # Show cursor
        sys.stdout.flush()
        # Use stty to reset terminal state (handles echo, input modes, etc.)
        import subprocess
        try:
            subprocess.run(["stty", "sane"], check=False, timeout=5)
        except Exception:
            pass  # If stty fails, at least we reset colors/cursor


# ─────────────────────────────────────────────
# Scene filters
# ─────────────────────────────────────────────
def _glob_to_regex(mask):
    """Convert a filename glob (fnmatch style) to a regex Stash's path filter understands."""
    out = []
    for ch in mask:
        if ch == '*':
            out.append(r'[^/\\]*')
        elif ch == '?':
            out.append(r'[^/\\]')
        else:
            out.append(re.escape(ch))
    return r'(^|[/\\])' + ''.join(out) + '$'

def pending_scene_filter():
    """
    Stash scene filter for "still needs a phash": no phash, not claimed, not
    error-tagged — with excluded_paths and --filemask applied server-side so
    page counts and random page selection only ever see eligible scenes.
    """
    f = {
        "phash": {"value": "", "modifier": "IS_NULL"},
        "tags": {
            "value": [config.hashing_tag, config.hashing_error_tag, config.cover_error_tag],
            "modifier": "EXCLUDES",
        },
    }
    if config.excluded_paths:
        f["path"] = {
            "value": "^(" + "|".join(re.escape(ep) for ep in config.excluded_paths) + ")",
            "modifier": "NOT_MATCHES_REGEX",
        }
    if config.filemask:
        f["AND"] = {"path": {"value": _glob_to_regex(config.filemask), "modifier": "MATCHES_REGEX"}}
    return f

def scene_matches_local_filters(scene):
    """Client-side double check of excluded_paths / filemask for a fetched scene."""
    files = scene.get('files') or []
    if not files:
        return False
    if is_excluded(files[0].get('path', '')):
        return False
    if config.filemask:
        return any(fnmatch.fnmatch(os.path.basename(f.get('path', '')), config.filemask) for f in files)
    return True

def get_total_scene_count():
    count, _ = stash.find_scenes(
        f=pending_scene_filter(),
        filter={"per_page": 1},
        fragment="id",
        get_count=True
    )
    return count

def iter_scenes_with_files(page_size=100):
    """
    Walk every scene once (stable id order) and yield
    (scene, stash_path, oshash, duration) for scenes that have a file with an
    oshash, are not under excluded_paths and are not tagged as errors.
    Used by the standalone sprite/preview modes.
    """
    error_tags = {str(config.hashing_error_tag)}
    page = 1
    while True:
        scenes = stash.find_scenes(
            f={},
            filter={"per_page": page_size, "page": page, "sort": "id", "direction": "ASC"},
            fragment="id title tags { id } files { id path fingerprints { type value } duration }"
        )
        if not scenes:
            return
        for scene in scenes:
            if any(str(t.get('id')) in error_tags for t in scene.get('tags') or []):
                continue
            oshash = None
            video_path = None
            duration = 0
            for file in scene.get('files') or []:
                video_path = file.get('path')
                duration = file.get('duration', 0)
                for fp in file.get('fingerprints') or []:
                    if fp.get('type', '').lower() == 'oshash':
                        oshash = fp.get('value')
                        break
                if oshash:
                    break
            if not oshash or not video_path or is_excluded(video_path):
                continue
            yield scene, video_path, oshash, duration
        if len(scenes) < page_size:
            return
        page += 1


# ─────────────────────────────────────────────
# Tagging / updates
# ─────────────────────────────────────────────
def tag_scene_error(scene_id, error_tag, error_msg=None):
    if config.dry_run:
        print(f"[DRY RUN] Would tag scene {scene_id} with error tag {error_tag}")
        return
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": error_tag, "mode": "ADD"}})
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": config.hashing_tag, "mode": "REMOVE"}})
    if error_msg:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _append_error_log(f"[{timestamp}] Scene {scene_id}: {error_msg}")

def is_scene_claimed(scene_id):
    """True when another node has already tagged this scene as in-process."""
    scene = stash.find_scene(scene_id, fragment="id tags { id }")
    if not scene:
        return False
    return any(str(t.get('id')) == str(config.hashing_tag) for t in scene.get('tags') or [])

def claim_scene(scene_id):
    if config.dry_run:
        print(f"[DRY RUN] Would claim scene {scene_id}")
        return
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": config.hashing_tag, "mode": "ADD"}})

def release_scene(scene_id):
    if config.dry_run:
        print(f"[DRY RUN] Would release scene {scene_id}")
        return
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": config.hashing_tag, "mode": "REMOVE"}})

def update_phash(file_id, phash):
    if config.dry_run:
        print(f"[DRY RUN] Would update phash for file {file_id} to {phash}")
        return
    stash.file_set_fingerprints(file_id, [{"type": "phash", "value": phash}])

def update_cover(scene_id, cover_data):
    if config.dry_run:
        print(f"[DRY RUN] Would update cover image for scene {scene_id}")
        return True
    return stash.update_scene({"id": scene_id, "cover_image": cover_data})

def get_error_scenes():
    """Get scenes with error tags for retry"""
    return stash.find_scenes(
        f={"tags": {"value": [config.hashing_error_tag, config.cover_error_tag], "modifier": "INCLUDES"}},
        filter={"sort": "created_at", "direction": "DESC", "per_page": -1},
        fragment="id files{id path fingerprints{value type}} paths{screenshot}"
    )

def clear_error_tags(scene_ids):
    """Clear error tags from scenes"""
    if config.dry_run:
        print(f"[DRY RUN] Would clear error tags from {len(scene_ids)} scenes")
        return
    for scene_id in scene_ids:
        stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": config.hashing_error_tag, "mode": "REMOVE"}})
        stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": config.cover_error_tag, "mode": "REMOVE"}})

def get_hashing_scenes():
    """Get scenes currently tagged with the in-process hashing tag"""
    return stash.find_scenes(
        f={"tags": {"value": [config.hashing_tag], "modifier": "INCLUDES"}},
        filter={"per_page": -1},
        fragment="id"
    )

def clear_hashing_tags(scene_ids):
    """Clear the in-process hashing tag from scenes (recover from crashed runs)"""
    if config.dry_run:
        print(f"[DRY RUN] Would clear hashing tag from {len(scene_ids)} scenes")
        return
    for scene_id in scene_ids:
        stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": config.hashing_tag, "mode": "REMOVE"}})

def get_scene_markers_with_files(scene_id):
    """
    Get markers for a scene with file information.
    Used during integrated mode (scene processing).

    Args:
        scene_id: Stash scene ID

    Returns:
        list: Marker objects with scene file metadata
    """
    return stash.get_scene_markers(
        scene_id,
        fragment="id title seconds scene { id files { path fingerprints { type value } } }"
    )

def log_marker_failure(marker_id, marker_title, step, error):
    """
    Log marker generation failure.
    Similar to log_scene_failure but for markers.

    Args:
        marker_id: Stash marker ID
        marker_title: Marker title for display
        step: Processing step that failed
        error: Error message or exception
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _safe_print(f"{timestamp} ❌ Marker {marker_id} — {marker_title} failed during {step}: {error}")
    _append_error_log(f"[{timestamp}] Marker {marker_id} — {marker_title}: {step} failed: {error}")
