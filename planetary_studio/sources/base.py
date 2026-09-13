"""Contract between image sources and the shared viewer/editor."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Protocol


class MetadataProvider(Protocol):
    def lookup(self, filename: str, collection_id: int) -> dict[str, Any]: ...


class ImageSource(ABC):
    id: str
    name: str
    collection_label = "Pasta"
    supports_downloads = False

    @abstractmethod
    def list_collections(self, root: Path) -> list[tuple[int, Path]]:
        """Return a collection identifier and folder for each sidebar entry."""

    @abstractmethod
    def create_metadata_client(self) -> MetadataProvider:
        """Return metadata access appropriate to this source."""

    def create_downloader(self, root: Path, **options):
        raise NotImplementedError("Esta fonte não oferece download automático.")
