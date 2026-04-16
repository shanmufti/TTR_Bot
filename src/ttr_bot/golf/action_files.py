"""Filesystem helpers for golf action JSON files."""

import os

from ttr_bot.config import settings


def list_action_stems() -> list[str]:
    """Basenames of *.json files in the golf actions directory."""
    d = settings.GOLF_ACTIONS_DIR
    if not d or not os.path.isdir(d):
        return []

    return [os.path.splitext(name)[0] for name in sorted(os.listdir(d)) if name.endswith(".json")]


def action_file_exists(stem: str) -> bool:
    """Return True if a JSON action file for *stem* exists on disk."""
    path = os.path.join(settings.GOLF_ACTIONS_DIR, f"{stem}.json")
    return os.path.isfile(path)


def path_for_stem(stem: str) -> str:
    """Return the full filesystem path for a golf action *stem*."""
    return os.path.join(settings.GOLF_ACTIONS_DIR, f"{stem}.json")
