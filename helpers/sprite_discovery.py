# sprite_discovery.py

import os
from itertools import islice

import config
from helpers.paths import translate_path
from helpers.stash_utils import iter_scenes_with_files


def iter_missing_sprites():
    """
    Walk the library once and yield scenes that are missing a sprite sheet or VTT.

    Yields dicts with keys: scene_id, video_path (translated), oshash, duration, scene_title
    """
    for scene, video_path, oshash, duration in iter_scenes_with_files():
        sprite_file = os.path.join(config.sprite_path, f"{oshash}_sprite.jpg")
        vtt_file = os.path.join(config.sprite_path, f"{oshash}_thumbs.vtt")
        if os.path.exists(sprite_file) and os.path.exists(vtt_file):
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


def discover_missing_sprites(limit=None):
    """Return up to `limit` scenes missing sprites (None for all)."""
    return list(islice(iter_missing_sprites(), limit))
