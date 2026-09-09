"""Local image discovery shared by every image source."""
import re
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

def natural_key(value: str) -> list[Any]:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", value)]


def list_images(folder: Path, cancel=None) -> list[Path]:
    try:
        files = []
        for p in folder.iterdir():
            if cancel is not None and cancel.is_set():
                return []
            if p.suffix.lower() in SUPPORTED_EXTENSIONS and p.is_file():
                files.append(p)
    except OSError:
        return []
    return sorted(files, key=lambda p: natural_key(p.name))


