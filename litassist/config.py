"""Where the app keeps its data, and the user's private settings.

Everything lives in one folder outside the code repository, so that keys and
research data are never committed. On Windows this is Documents\\LitAssist.
Set the LITASSIST_HOME environment variable to use a different folder.
"""

import json
import os
from pathlib import Path

SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "ncbi_email": "",
    "ncbi_api_key": "",
    "zotero_user_id": "",
    "zotero_api_key": "",
    "anthropic_api_key": "",
}


def data_dir() -> Path:
    override = os.environ.get("LITASSIST_HOME")
    if override:
        path = Path(override)
    else:
        path = Path.home() / "Documents" / "LitAssist"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "litassist.db"


def load_settings() -> dict:
    path = data_dir() / SETTINGS_FILE
    settings = dict(DEFAULT_SETTINGS)
    if path.exists():
        try:
            settings.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return settings


def save_settings(settings: dict) -> None:
    path = data_dir() / SETTINGS_FILE
    clean = {k: str(settings.get(k, "")).strip() for k in DEFAULT_SETTINGS}
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
