"""Centralized path resolution for Kindle Brain.

All modules import paths from here instead of computing PROJECT_DIR locally.
Priority: KINDLE_BRAIN_DATA env var > config file > ~/.kindle-brain/
"""

import json
import os
from pathlib import Path

_data_dir: Path | None = None


def get_data_dir() -> Path:
    """Get the data directory, resolving from env/config/default."""
    global _data_dir
    if _data_dir is not None:
        return _data_dir

    # 1. Environment variable
    env_dir = os.environ.get("KINDLE_BRAIN_DATA")
    if env_dir:
        _data_dir = Path(env_dir)
        _data_dir.mkdir(parents=True, exist_ok=True)
        return _data_dir

    # 2. Config file
    config_file = Path.home() / ".kindle-brain" / "config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
            if "data_dir" in config:
                _data_dir = Path(config["data_dir"])
                _data_dir.mkdir(parents=True, exist_ok=True)
                return _data_dir
        except (json.JSONDecodeError, KeyError):
            pass

    # 3. Default
    _data_dir = Path.home() / ".kindle-brain"
    _data_dir.mkdir(parents=True, exist_ok=True)
    return _data_dir


def reset_data_dir():
    """Reset cached data dir (for testing)."""
    global _data_dir
    _data_dir = None


# Derived paths
def db_path() -> Path:
    return get_data_dir() / "kindle.db"

def memory_db_path() -> Path:
    return get_data_dir() / "memory.db"

def vectordb_dir() -> Path:
    return get_data_dir() / "vectordb"

def book_texts_dir() -> Path:
    return get_data_dir() / "book_texts"

def book_files_dir() -> Path:
    return get_data_dir() / "book_files"

def books_md_dir() -> Path:
    return get_data_dir() / "books_md"

def covers_dir() -> Path:
    return get_data_dir() / "covers"

def config_path() -> Path:
    return get_data_dir() / "config.json"


# Kindle mount detection
def find_kindle_mount() -> str | None:
    """Auto-detect Kindle mount point."""
    import platform
    system = platform.system()

    if system == "Darwin":
        # macOS: /Volumes/Kindle
        mount = "/Volumes/Kindle"
        if os.path.exists(mount):
            return mount
    elif system == "Linux":
        # Linux: /media/*/Kindle or /mnt/Kindle
        import glob
        for pattern in ["/media/*/Kindle", "/mnt/Kindle", "/run/media/*/Kindle"]:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]
    elif system == "Windows":
        # Windows: check drive letters
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\documents\\My Clippings.txt"
            if os.path.exists(path):
                return f"{letter}:\\"

    return None


def find_clippings_file(kindle_mount: str | None = None) -> str | None:
    """Find My Clippings.txt on a Kindle."""
    if kindle_mount is None:
        kindle_mount = find_kindle_mount()
    if kindle_mount is None:
        return None

    path = os.path.join(kindle_mount, "documents", "My Clippings.txt")
    if os.path.exists(path):
        return path
    return None


def find_calibre() -> str | None:
    """Find Calibre's ebook-convert binary."""
    import shutil
    import platform

    # 1. Check PATH
    which = shutil.which("ebook-convert")
    if which:
        return which

    # 2. Platform-specific defaults
    system = platform.system()
    if system == "Darwin":
        mac_path = "/Applications/calibre.app/Contents/MacOS/ebook-convert"
        if os.path.exists(mac_path):
            return mac_path
    elif system == "Linux":
        for path in ["/usr/bin/ebook-convert", "/usr/local/bin/ebook-convert"]:
            if os.path.exists(path):
                return path

    return None
