# preview_discovery.py

import os
from helpers.stash_utils import stash
import config

_PAGE_SIZE = 100

def translate_path(docker_path):
    """Translate Stash/Docker paths to local paths using config.translations"""
    for t in config.translations:
        if docker_path.startswith(t['orig']):
            return docker_path.replace(t['orig'], t['local'], 1)
    return docker_path

def discover_missing_previews(limit=None):
    """
    Discover scenes that are missing preview videos for standalone generation.

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
    missing = []
    page = 1

    while True:
        scenes = stash.find_scenes(
            f={},
            filter={"per_page": _PAGE_SIZE, "page": page},
            fragment="id title files { id path fingerprints { type value } duration }"
        )

        if not scenes:
            break

        for scene in scenes:
            scene_id = scene['id']
            scene_title = scene.get('title', f"Scene {scene_id}")

            oshash = None
            video_path = None
            duration = 0

            for file in scene.get('files', []):
                video_path = file.get('path')
                duration = file.get('duration', 0)

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

            preview_file = os.path.join(config.preview_path, f"{oshash}.mp4")

            if not os.path.exists(preview_file):
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
                        return missing

        if len(scenes) < _PAGE_SIZE:
            break

        page += 1

    return missing
