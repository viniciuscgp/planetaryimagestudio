"""Persistent mission profiles and Planet / Mission collection paths."""

import copy
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from sources import get_source
from sources.base import ImageSource
from mission_catalog import MISSION_CATALOG

GROUPINGS = {"observation": "Observações", "sol": "SOLs", "date": "Datas", "orbit": "Órbitas", "folders": "Pastas do acervo"}


def folder_component(value):
    component = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    if not component or component in (".", ".."):
        raise ValueError("Informe um nome de planeta e de missão válido.")
    if component.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        component = "_" + component
    return component


class MissionSource(ImageSource):
    def __init__(self, profile):
        self.id = profile["id"]
        self.name = f"{profile['body']} — {profile['name']}"
        self.backend = get_source(profile["backend"])
        self.supports_downloads = self.backend.supports_downloads
        self.uses_sols = getattr(self.backend, "uses_sols", self.supports_downloads)
        self.download_description = getattr(self.backend, "download_description", "Download integrado de imagens por SOL.")
        self.collection_label = GROUPINGS[profile["grouping"]]

    def list_collections(self, root):
        return self.backend.list_collections(root)

    def create_metadata_client(self):
        return self.backend.create_metadata_client()

    def create_downloader(self, root, **options):
        return self.backend.create_downloader(root, **options)


class MissionRegistry:
    def __init__(self, state=None, current_root=None):
        state = state or {}
        settings = state.get("mission_config") or {}
        self.library_root = str(settings.get("library_root") or "")
        self.profiles = {}
        for entry in MISSION_CATALOG:
            profile = dict(entry)
            profile.update(enabled=True, folder_override="", auto_download=False, start_sol=0)
            self.profiles[profile["id"]] = profile
        for saved in settings.get("profiles", []):
            profile = dict(saved)
            if profile.get("id") in self.profiles:
                original = self.profiles[profile["id"]]
                original.update({key: value for key, value in profile.items() if key in ("enabled", "folder_override", "auto_download", "start_sol", "grouping")})
            elif profile.get("id") and profile.get("body") and profile.get("name"):
                profile["backend"] = "local"
                self.profiles[profile["id"]] = profile
        for profile in self.profiles.values():
            if profile["backend"] in ("hirise", "lroc", "esa_hrsc", "kaguya"):
                profile["grouping"] = "observation"
        if not settings:
            sessions = dict(state.get("source_sessions") or {})
            current_id = state.get("source", "curiosity")
            current = dict(state)
            if current_root is not None:
                current["root"] = str(current_root)
            sessions[current_id] = current
            for key, session in sessions.items():
                if key in self.profiles and session.get("root"):
                    self.profiles[key]["folder_override"] = str(session["root"])
                    self.profiles[key]["start_sol"] = int(session.get("download_start_sol", 0) or 0)
            # Preserve legacy Curiosity startup behavior only for the migrated profile.
            if current_id == "curiosity" and state.get("root"):
                self.profiles["curiosity"]["auto_download"] = True

    def serialize(self):
        return {"version": 1, "library_root": self.library_root, "profiles": copy.deepcopy(list(self.profiles.values()))}

    def folder_for(self, mission_id):
        profile = self.profiles[mission_id]
        if profile.get("folder_override"):
            return Path(profile["folder_override"]).expanduser()
        if not self.library_root:
            return None
        return Path(self.library_root).expanduser() / folder_component(profile["body"]).lower() / "missions" / folder_component(profile["name"]).lower()

    def source_for(self, mission_id):
        return MissionSource(self.profiles[mission_id])

    def add_custom(self, body, name):
        identifier = "custom_" + uuid.uuid4().hex[:12]
        self.profiles[identifier] = {
            "id": identifier, "body": body, "name": name, "backend": "local", "grouping": "folders",
            "archive_url": "", "enabled": True, "folder_override": "", "auto_download": False, "start_sol": 0,
        }
        return identifier

    def validate(self):
        if not any(profile.get("enabled", True) for profile in self.profiles.values()):
            raise ValueError("Mantenha pelo menos uma missão habilitada.")
        if self.library_root and not Path(self.library_root).expanduser().is_absolute():
            raise ValueError("A pasta-base precisa ser um caminho completo.")
        used = {}
        for profile in self.profiles.values():
            folder_component(profile["body"])
            folder_component(profile["name"])
            if profile["grouping"] not in GROUPINGS:
                raise ValueError("Organização de pastas inválida.")
            url = profile.get("archive_url", "")
            if url and (urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc):
                raise ValueError("O endereço do acervo precisa começar com https:// ou http://.")
            folder = self.folder_for(profile["id"])
            if folder is not None and not folder.is_absolute():
                raise ValueError(f"Informe um caminho completo para {profile['name']}.")
            if folder is not None and profile.get("enabled"):
                key = os.path.normcase(str(folder.resolve()))
                if key in used:
                    raise ValueError(f"{profile['name']} e {used[key]} não podem usar a mesma pasta.")
                used[key] = profile["name"]
            if profile.get("auto_download") and not self.source_for(profile["id"]).supports_downloads:
                raise ValueError(f"{profile['name']} ainda não tem download integrado.")
