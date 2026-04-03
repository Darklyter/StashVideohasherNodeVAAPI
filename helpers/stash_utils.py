# stash_utils.py

from stashapi.stashapp import StashInterface
from config import hashing_tag, hashing_error_tag, cover_error_tag, dry_run, stash_scheme, stash_host, stash_port, stash_api_key, excluded_paths, error_log_path, error_log_max_mb
from datetime import datetime
import os
import threading

# Initialize Stash connection with optional API key
stash_config = {
    "scheme": stash_scheme,
    "host": stash_host,
    "port": stash_port
}

# Add API key to config if it's set
if stash_api_key:
    stash_config["apikey"] = stash_api_key

stash = StashInterface(stash_config)

# Thread-safe error logging
error_log_lock = threading.Lock()

def _rotate_log_if_needed():
    """Rotate error_log_path if it exceeds error_log_max_mb. Called inside error_log_lock."""
    if error_log_max_mb <= 0:
        return
    try:
        if os.path.exists(error_log_path) and os.path.getsize(error_log_path) > error_log_max_mb * 1024 * 1024:
            rotated = error_log_path + ".1"
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(error_log_path, rotated)
    except Exception:
        pass  # Rotation failure is non-fatal

def log_scene_failure(scene_id, filename_pretty, step, error):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"{timestamp} ❌ Scene {scene_id} — {filename_pretty} failed during {step}: {error}"
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('utf-8', errors='replace').decode('ascii', errors='replace'))

def reset_terminal():
    import platform
    import sys
    if platform.system() != "Windows":
        # Reset all terminal attributes
        print("\033[0m", end="")  # Reset colors/attributes
        print("\033[?25h", end="")  # Show cursor
        sys.stdout.flush()
        # Use stty to reset terminal state (handles echo, input modes, etc.)
        import subprocess
        try:
            subprocess.run(["stty", "sane"], check=False)
        except:
            pass  # If stty fails, at least we reset colors/cursor

def get_total_scene_count():
    if excluded_paths:
        # Need paths to filter — fetch all IDs+paths but only one field each
        scenes = stash.find_scenes(
            f={
                "phash": {"value": "", "modifier": "IS_NULL"},
                "tags": {"value": [hashing_tag, hashing_error_tag, cover_error_tag], "modifier": "EXCLUDES"}
            },
            filter={"per_page": -1},
            fragment="id files{path}"
        )
        return sum(
            1 for s in scenes
            if s.get('files') and not any(s['files'][0]['path'].startswith(ep) for ep in excluded_paths)
        )
    else:
        count, _ = stash.find_scenes(
            f={
                "phash": {"value": "", "modifier": "IS_NULL"},
                "tags": {"value": [hashing_tag, hashing_error_tag, cover_error_tag], "modifier": "EXCLUDES"}
            },
            filter={"per_page": 1},
            fragment="id",
            get_count=True
        )
        return count

def tag_scene_error(scene_id, error_tag, error_msg=None):
    if dry_run:
        print(f"[DRY RUN] Would tag scene {scene_id} with error tag {error_tag}")
        return
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": error_tag, "mode": "ADD"}})
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": hashing_tag, "mode": "REMOVE"}})
    if error_msg:
        # Thread-safe error logging
        try:
            with error_log_lock:
                _rotate_log_if_needed()
                with open(error_log_path, "a", encoding="utf-8") as log:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log.write(f"[{timestamp}] Scene {scene_id}: {error_msg}\n")
        except Exception as log_err:
            print(f"⚠️ Failed to write {error_log_path}: {log_err}")

def claim_scene(scene_id):
    if dry_run:
        print(f"[DRY RUN] Would claim scene {scene_id}")
        return
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": hashing_tag, "mode": "ADD"}})

def release_scene(scene_id):
    if dry_run:
        print(f"[DRY RUN] Would release scene {scene_id}")
        return
    stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": hashing_tag, "mode": "REMOVE"}})

def update_phash(file_id, phash):
    if dry_run:
        print(f"[DRY RUN] Would update phash for file {file_id} to {phash}")
        return
    stash.file_set_fingerprints(file_id, [{"type": "phash", "value": phash}])

def update_cover(scene_id, cover_data):
    if dry_run:
        print(f"[DRY RUN] Would update cover image for scene {scene_id}")
        return True
    return stash.update_scene({"id": scene_id, "cover_image": cover_data})

def get_error_scenes():
    """Get scenes with error tags for retry"""
    return stash.find_scenes(
        f={"tags": {"value": [hashing_error_tag, cover_error_tag], "modifier": "INCLUDES"}},
        filter={"sort": "created_at", "direction": "DESC", "per_page": -1},
        fragment="id files{id path fingerprints{value type}} paths{screenshot}"
    )

def clear_error_tags(scene_ids):
    """Clear error tags from scenes"""
    if dry_run:
        print(f"[DRY RUN] Would clear error tags from {len(scene_ids)} scenes")
        return
    for scene_id in scene_ids:
        stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": hashing_error_tag, "mode": "REMOVE"}})
        stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": cover_error_tag, "mode": "REMOVE"}})

def get_hashing_scenes():
    """Get scenes currently tagged with the in-process hashing tag"""
    return stash.find_scenes(
        f={"tags": {"value": [hashing_tag], "modifier": "INCLUDES"}},
        filter={"per_page": -1},
        fragment="id"
    )

def clear_hashing_tags(scene_ids):
    """Clear the in-process hashing tag from scenes (recover from crashed runs)"""
    if dry_run:
        print(f"[DRY RUN] Would clear hashing tag from {len(scene_ids)} scenes")
        return
    for scene_id in scene_ids:
        stash.update_scenes({"ids": [scene_id], "tag_ids": {"ids": hashing_tag, "mode": "REMOVE"}})

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
    msg = f"{timestamp} ❌ Marker {marker_id} — {marker_title} failed during {step}: {error}"
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('utf-8', errors='replace').decode('ascii', errors='replace'))

    # Thread-safe error logging
    try:
        with error_log_lock:
            _rotate_log_if_needed()
            with open(error_log_path, "a", encoding="utf-8") as log:
                log.write(f"[{timestamp}] Marker {marker_id} — {marker_title}: {step} failed: {error}\n")
    except Exception as log_err:
        print(f"⚠️ Failed to write {error_log_path}: {log_err}")

