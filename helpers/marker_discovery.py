# marker_discovery.py

import os
from helpers.stash_utils import stash
import config

_PAGE_SIZE = 100

_MARKER_QUERY = """
query findSceneMarkers($scene_marker_filter: SceneMarkerFilterType, $filter: FindFilterType) {
    findSceneMarkers(scene_marker_filter: $scene_marker_filter, filter: $filter) {
        scene_markers {
            id title seconds
            scene { id title files { path fingerprints { type value } } }
        }
    }
}
"""

def translate_path(docker_path):
    """Translate Stash/Docker paths to local paths using config.translations"""
    for t in config.translations:
        if docker_path.startswith(t['orig']):
            return docker_path.replace(t['orig'], t['local'], 1)
    return docker_path

def discover_missing_markers(limit=None):
    """
    Discover markers that need media generation, grouped by scene.

    Args:
        limit: Maximum number of SCENES to process (all eligible markers per
               scene are always included). None means no limit.

    Returns:
        list[dict]: Marker dictionaries, all markers for each scene together.
            Keys: marker_id, scene_id, seconds, video_path, oshash,
                  marker_title, scene_title
    """
    # scenes_markers preserves insertion order (Python 3.7+).
    # scene_id -> list of marker dicts.
    scenes_markers = {}
    page = 1

    while True:
        result = stash.call_GQL(_MARKER_QUERY, {
            "scene_marker_filter": {},
            "filter": {"per_page": _PAGE_SIZE, "page": page}
        })
        markers = result.get("findSceneMarkers", {}).get("scene_markers", [])

        if not markers:
            break

        for marker in markers:
            marker_id = marker['id']
            seconds = marker.get('seconds', 0)
            marker_title = marker.get('title', '') or f"Marker at {seconds}s"
            scene = marker.get('scene', {})
            scene_id = scene.get('id')

            if not scene_id:
                continue

            oshash = None
            video_path = None

            for file in scene.get('files', []):
                video_path = file.get('path')
                for fp in file.get('fingerprints', []):
                    if fp.get('type', '').lower() == 'oshash':
                        oshash = fp.get('value')
                        break
                if oshash:
                    break

            if not oshash or not video_path:
                continue

            if config.excluded_paths and any(video_path.startswith(ep) for ep in config.excluded_paths):
                continue

            marker_dir = os.path.join(config.marker_path, "markers", oshash)
            sec_int = int(seconds)

            needs_generation = False
            if config.marker_preview_enabled:
                if not os.path.exists(os.path.join(marker_dir, f"{sec_int}.mp4")):
                    needs_generation = True
            if config.marker_thumbnail_enabled:
                if not os.path.exists(os.path.join(marker_dir, f"{sec_int}.webp")):
                    needs_generation = True
            if config.marker_screenshot_enabled:
                if not os.path.exists(os.path.join(marker_dir, f"{sec_int}.jpg")):
                    needs_generation = True

            if not needs_generation:
                continue

            translated_path = translate_path(video_path)
            if not os.path.exists(translated_path):
                continue

            # If this is a new scene, check whether we've hit the scene limit.
            # Always accept markers for scenes already in our working set so
            # every marker for a given scene is processed together.
            if scene_id not in scenes_markers:
                if limit and len(scenes_markers) >= limit:
                    continue
                scenes_markers[scene_id] = []

            scene_title = scene.get('title') or os.path.basename(video_path)

            scenes_markers[scene_id].append({
                'marker_id': marker_id,
                'scene_id': scene_id,
                'seconds': seconds,
                'video_path': translated_path,
                'oshash': oshash,
                'marker_title': marker_title,
                'scene_title': scene_title,
            })

        if len(markers) < _PAGE_SIZE:
            break

        page += 1

    # Flatten: all markers for scene 1, then all for scene 2, etc.
    return [m for ms in scenes_markers.values() for m in ms]
