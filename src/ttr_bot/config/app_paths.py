"""Filesystem layout: development tree vs PyInstaller ``.app`` bundle.

Read-only assets (templates) live under the bundle when frozen. Logs, optional
``config.toml``, golf JSON, and debug frames go under the user writable
Application Support folder.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_APP_SUPPORT_REL = Path("Library") / "Application Support" / "TTR Bot"


def is_frozen_bundle() -> bool:
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def development_project_root() -> Path:
    """Repository root (parent of ``src/``) when running from source."""
    return Path(__file__).resolve().parents[3]


def bundled_resources_data_dir() -> Path:
    """Directory containing ``templates/``, ``golf_actions/``, etc.

    When frozen, this is inside the ``.app`` (read-only). When developing, it
    is ``<repo>/data``.
    """
    if is_frozen_bundle():
        return Path(sys._MEIPASS) / "data"
    return development_project_root() / "data"


def user_writable_root() -> Path:
    """Where logs, overrides, user golf JSON, and debug output are stored."""
    if is_frozen_bundle():
        d = Path.home() / _APP_SUPPORT_REL
        d.mkdir(parents=True, exist_ok=True)
        return d
    return development_project_root()


def logs_directory() -> Path:
    if is_frozen_bundle():
        d = user_writable_root() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = development_project_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_toml_path() -> Path:
    if is_frozen_bundle():
        return user_writable_root() / "config.toml"
    return bundled_resources_data_dir() / "config.toml"


def _seed_bundled_files(bundled_subdir: Path, dest_dir: Path) -> None:
    if not bundled_subdir.is_dir():
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in bundled_subdir.iterdir():
        if f.is_file() and not (dest_dir / f.name).exists():
            shutil.copy2(f, dest_dir / f.name)


def user_golf_actions_dir() -> Path:
    """Writable golf JSON directory; seeded from the bundle on first run."""
    bundled = bundled_resources_data_dir() / "golf_actions"
    if is_frozen_bundle():
        dest = user_writable_root() / "golf_actions"
        _seed_bundled_files(bundled, dest)
        dest.mkdir(parents=True, exist_ok=True)
        return dest
    bundled.mkdir(parents=True, exist_ok=True)
    return bundled


def user_sell_paths_dir() -> Path:
    bundled = bundled_resources_data_dir() / "sell_paths"
    if is_frozen_bundle():
        dest = user_writable_root() / "sell_paths"
        _seed_bundled_files(bundled, dest)
        dest.mkdir(parents=True, exist_ok=True)
        return dest
    bundled.mkdir(parents=True, exist_ok=True)
    return bundled


def debug_output_base_dir() -> Path:
    """Parent for ``_debug/sweep``, ``_debug/watcher``, etc."""
    if is_frozen_bundle():
        d = user_writable_root() / "_debug"
        d.mkdir(parents=True, exist_ok=True)
        return d
    d = bundled_resources_data_dir() / "_debug"
    d.mkdir(parents=True, exist_ok=True)
    return d
