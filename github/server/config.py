from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "EcoInvoiceRecon"
APP_DISPLAY_NAME = "票核通"
APP_VERSION = "内测版demo_260630v0.2"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    path = runtime_dir() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def exports_dir() -> Path:
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def uploads_dir() -> Path:
    path = data_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def web_dist_dir() -> Path:
    return resource_dir() / "web" / "dist"


def local_tesseract_path() -> Path:
    return runtime_dir() / "tools" / "tesseract" / "tesseract.exe"


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
