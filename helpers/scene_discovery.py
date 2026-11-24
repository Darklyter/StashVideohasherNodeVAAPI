# scene_discovery.py

import random

import config
from helpers.stash_utils import stash, pending_scene_filter, scene_matches_local_filters, get_total_scene_count

def discover_scenes(total_count=None):
    """
    Discovers a random batch of scenes to process.
    - Filters scenes that do not yet have a phash
    - Excludes scenes already tagged with hashing_tag, hashing_error_tag, or cover_error_tag
    - Applies excluded_paths and --filemask in the Stash query itself, so the
      page count only covers scenes that are actually eligible
    - Randomly selects one page of scenes to reduce overlap across multiple systems
    - Uses the current value of config.per_page, which may be overridden by CLI

    Args:
        total_count: number of eligible scenes if the caller already counted them
    """
    scene_filter = pending_scene_filter()

    # Step 1: Count matching scenes (count only — no scene data is transferred)
    if total_count is None:
        total_count = get_total_scene_count()
    if total_count == 0:
        print("🚫 No scenes found to process.")
        return []

    # Step 2: Calculate total number of pages based on configured batch size
    total_pages = max(1, (total_count + config.per_page - 1) // config.per_page)

    # Step 3: Randomly select one page to process
    # This helps distribute work across multiple systems
    selected_page = random.randint(1, total_pages)
    mask_note = f", filemask: {config.filemask}" if config.filemask else ""
    print(f"🎯 Selected page {selected_page} of {total_pages} (batch size: {config.per_page}, total: {total_count}{mask_note})")

    # Step 4: Fetch the selected page of scenes with full metadata
    batch_scenes = stash.find_scenes(
        f=scene_filter,
        filter={
            "sort": "created_at",           # Sort by creation date (newest first)
            "direction": "DESC",
            "per_page": config.per_page,    # Limit to configured batch size
            "page": selected_page           # Use randomly selected page
        },
        fragment="id files{id path fingerprints{value type}} paths{screenshot}"
    )

    # Step 5: Safety net — the query already applied these filters
    return [s for s in batch_scenes if scene_matches_local_filters(s)]
