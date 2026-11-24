# helpers/paths.py
#
# Path helpers shared by scene processing and all discovery modules.

import os

import config


def translate_path(stash_path):
    """
    Translate a path as Stash sees it into a path on this machine using
    config.translations.

    Only prefixes are matched (a directory named like a mount point in the middle
    of a path is left alone). When several entries share the same 'orig' prefix,
    the first one whose translated file actually exists wins, so alternative
    local mount points can be listed one after another.
    """
    candidates = []
    for t in config.translations:
        if stash_path.startswith(t['orig']):
            candidates.append(t['local'] + stash_path[len(t['orig']):])
    if not candidates:
        return stash_path
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


def is_excluded(stash_path):
    """True when the (untranslated) Stash path falls under config.excluded_paths."""
    return any(stash_path.startswith(ep) for ep in (config.excluded_paths or []))
