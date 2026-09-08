"""Local image discovery shared by every image source."""
import re
from pathlib import Path
from typing import Any

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}

def natural_key(value: str) -> list[Any]:
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", value)]


def list_images(folder: Path) -> list[Path]:
    try:
        files = [
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
    except OSError:
        return []
    return sorted(files, key=lambda p: natural_key(p.name))


