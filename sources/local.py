"""Offline image collections for the Moon, planets or any other subject."""

import os
from pathlib import Path

from catalog import SUPPORTED_EXTENSIONS, natural_key
from .base import ImageSource


class LocalMetadata:
    def lookup(self, filename, collection_id):
        return {"filename": filename, "title": filename, "caption": "Coleção de imagens locais."}


class LocalImageSource(ImageSource):
    id = "local"
    name = "Imagens locais (Lua e outros)"

    def list_collections(self, root):
        folders = []
        for directory, children, filenames in os.walk(root, followlinks=False):
            children[:] = [name for name in children if not name.startswith(".")]
            if any(Path(name).suffix.lower() in SUPPORTED_EXTENSIONS for name in filenames):
                folders.append(Path(directory))
        folders.sort(key=lambda folder: natural_key(str(folder.relative_to(root))))
        return list(enumerate(folders))

    def create_metadata_client(self):
        return LocalMetadata()
