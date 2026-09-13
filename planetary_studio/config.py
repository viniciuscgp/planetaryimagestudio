"""Application identity and migration of existing user sessions."""

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "Planetary Image Studio"
APP_VERSION = "0.5.0"
APP_AUTHOR = "NaRede Labs"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "data"
STATE_FILENAME = "planetary_image_studio_state.json"


def _state_file_candidates():
    return [DATA_ROOT / STATE_FILENAME, Path.home() / ("." + STATE_FILENAME)]


def _legacy_state_candidates():
    return [PROJECT_ROOT / STATE_FILENAME, DATA_ROOT / "curiosity_viewer_state.json",
            PROJECT_ROOT / "curiosity_viewer_state.json", Path.home() / ".curiosity_sol_viewer_state.json"]


def load_app_state() -> dict[str, Any]:
    current = _state_file_candidates()
    # Prefer an existing project session over the home-directory fallback.
    for path in current[:1] + _legacy_state_candidates() + current[1:]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            data.setdefault("source", "curiosity")
            if path not in current:
                # Keep the legacy file as a backup; only write the new filename.
                save_app_state(data)
            return data
        except (OSError, ValueError):
            continue
    return {}


def save_app_state(state: dict[str, Any]) -> Path | None:
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    for path in _state_file_candidates():
        temporary = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
            return path
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return None
