# preview_discovery.py

import os
from itertools import islice

import config
from helpers.paths import translate_path
from helpers.stash_utils import iter_scenes_with_files


def iter_missing_previews():
    """
    Walk the library once and yield scenes that are missing a preview video.

    Yields dicts with keys: scene_id, video_path (translated), oshash, duration, scene_title
    """
    for scene, video_path, oshash, duration in iter_scenes_with_files():
        preview_file = os.path.join(config.preview_path, f"{oshash}.mp4")
        if os.path.exists(preview_file):
            continue
        translated_path = translate_path(video_path)
        if not os.path.exists(translated_path):
            continue
        yield {
            'scene_id': scene['id'],
            'video_path': translated_path,
            'oshash': oshash,
            'duration': duration,
            'scene_title': scene.get('title') or os.path.basename(video_path),
        }


def discover_missing_previews(limit=None):
    """Return up to `limit` scenes missing previews (None for all)."""
    return list(islice(iter_missing_previews(), limit))
