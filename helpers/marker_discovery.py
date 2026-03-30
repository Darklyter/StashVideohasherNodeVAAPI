# marker_discovery.py

import os
from helpers.stash_utils import stash
import config

def translate_path(docker_path):
    """Translate Stash/Docker paths to local paths using config.translations"""
    for t in config.translations:
        if docker_path.startswith(t['orig']):
            return docker_path.replace(t['orig'], t['local'], 1)
    return docker_path

def discover_missing_markers(limit=None):
    """
    Discover markers that need media generation.

    Args:
        limit: Maximum number of markers to return (None for no limit)

    Returns:
        list[dict]: List of marker dictionaries with keys:
            - marker_id: Stash marker ID
            - scene_id: Stash scene ID
            - seconds: Marker timestamp (float)
            - video_path: Translated local video path
            - oshash: Scene file hash
            - marker_title: Marker title for logging
    """
    from datetime import datetime

    # Query all markers with scene file information
    markers = stash.find_scene_markers(
        scene_marker_filter={},  # No filters - get all markers
        fragment="id title seconds scene { id files { path fingerprints { type value } } }"
    )

    missing = []

    for marker in markers:
        marker_id = marker['id']
        seconds = marker.get('seconds', 0)
        marker_title = marker.get('title', f"Marker at {seconds}s")
        scene = marker.get('scene', {})
        scene_id = scene.get('id')

        if not scene_id:
            continue  # Skip markers without a scene

        # Extract oshash and video path from scene files
        oshash = None
        video_path = None

        for file in scene.get('files', []):
            video_path = file.get('path')

            # Find oshash fingerprint
            for fp in file.get('fingerprints', []):
                if fp.get('type', '').lower() == 'oshash':
                    oshash = fp.get('value')
                    break

            if oshash:
                break  # Found file with oshash, use it

        if not oshash or not video_path:
            continue  # Skip markers without oshash or video path

        # Check which files are missing based on config
        marker_dir = os.path.join(config.marker_path, "markers", oshash)
        sec_int = int(seconds)  # Integer truncation for filename

        needs_generation = False

        # Check if enabled media types are missing
        if config.marker_preview_enabled:
            mp4_file = os.path.join(marker_dir, f"{sec_int}.mp4")
            if not os.path.exists(mp4_file):
                needs_generation = True

        if config.marker_thumbnail_enabled:
            webp_file = os.path.join(marker_dir, f"{sec_int}.webp")
            if not os.path.exists(webp_file):
                needs_generation = True

        if config.marker_screenshot_enabled:
            jpg_file = os.path.join(marker_dir, f"{sec_int}.jpg")
            if not os.path.exists(jpg_file):
                needs_generation = True

        if needs_generation:
            # Translate path and verify file exists
            translated_path = translate_path(video_path)

            if os.path.exists(translated_path):
                missing.append({
                    'marker_id': marker_id,
                    'scene_id': scene_id,
                    'seconds': seconds,
                    'video_path': translated_path,
                    'oshash': oshash,
                    'marker_title': marker_title
                })

                if limit and len(missing) >= limit:
                    break

    return missing
