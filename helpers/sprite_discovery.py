# sprite_discovery.py

import os
from helpers.stash_utils import stash
import config

def translate_path(docker_path):
    """Translate Stash/Docker paths to local paths using config.translations"""
    for t in config.translations:
        if docker_path.startswith(t['orig']):
            return docker_path.replace(t['orig'], t['local'], 1)
    return docker_path

def discover_missing_sprites(limit=None):
    """
    Discover scenes that are missing sprite sheets for standalone generation.

    Args:
        limit: Maximum number of scenes to return (None for no limit)

    Returns:
        list[dict]: List of scene dictionaries with keys:
            - scene_id: Stash scene ID
            - video_path: Translated local video path
            - oshash: Scene file hash
            - duration: Video duration in seconds
            - scene_title: Scene title for logging
    """
    from datetime import datetime

    # Query all scenes with file information
    # We need files with oshash fingerprints and video duration
    scenes = stash.find_scenes(
        f={},  # No filters - get all scenes
        filter={"per_page": -1},  # Get all at once
        fragment="id title files { id path fingerprints { type value } } files { duration }"
    )

    missing = []

    for scene in scenes:
        scene_id = scene['id']
        scene_title = scene.get('title', f"Scene {scene_id}")

        # Extract oshash and video path from scene files
        oshash = None
        video_path = None
        duration = 0

        for file in scene.get('files', []):
            video_path = file.get('path')
            duration = file.get('duration', 0)

            # Find oshash fingerprint
            for fp in file.get('fingerprints', []):
                if fp.get('type', '').lower() == 'oshash':
                    oshash = fp.get('value')
                    break

            if oshash:
                break  # Found file with oshash, use it

        if not oshash or not video_path:
            continue  # Skip scenes without oshash or video path

        # Check if sprite already exists
        sprite_file = os.path.join(config.sprite_path, f"{oshash}_sprite.jpg")
        vtt_file = os.path.join(config.sprite_path, f"{oshash}_thumbs.vtt")

        # Only add if either sprite or VTT is missing
        if not os.path.exists(sprite_file) or not os.path.exists(vtt_file):
            # Translate path and verify file exists
            translated_path = translate_path(video_path)

            if os.path.exists(translated_path):
                missing.append({
                    'scene_id': scene_id,
                    'video_path': translated_path,
                    'oshash': oshash,
                    'duration': duration,
                    'scene_title': scene_title
                })

                if limit and len(missing) >= limit:
                    break

    return missing
