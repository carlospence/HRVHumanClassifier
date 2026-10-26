"""App settings persisted for admin configuration."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SETTINGS_PATH = HERE / "app_settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "max_training_sessions": 20,
    "window_secs": [10, 20, 30],
    "train_samples_per_phase_at_or_below_sec": 10,
    "train_samples_threshold_sec": 10,
    "train_samples_per_phase_above_sec": 5,
}


def default_settings() -> dict[str, Any]:
    return deepcopy(DEFAULT_SETTINGS)


def ensure_settings(path: Path | None = None) -> Path:
    path = Path(path or SETTINGS_PATH)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default_settings(), indent=2), encoding="utf-8")
    return path


def load_settings(path: Path | None = None) -> dict[str, Any]:
    path = ensure_settings(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid settings file: {path}")
    merged = default_settings()
    merged.update({k: v for k, v in data.items() if k in merged or k == "version"})
    # Normalize window list
    windows = merged.get("window_secs") or DEFAULT_SETTINGS["window_secs"]
    merged["window_secs"] = sorted({int(x) for x in windows if int(x) > 0})
    if not merged["window_secs"]:
        merged["window_secs"] = list(DEFAULT_SETTINGS["window_secs"])
    merged["max_training_sessions"] = max(1, int(merged.get("max_training_sessions") or 20))
    return merged


def save_settings(settings: dict[str, Any], path: Path | None = None) -> dict[str, Any]:
    path = Path(path or SETTINGS_PATH)
    cleaned = normalize_settings(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    tmp.replace(path)
    return cleaned


def normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    out = default_settings()
    out.update({k: v for k, v in (raw or {}).items() if k in out or k == "version"})
    windows = sorted({int(x) for x in (out.get("window_secs") or []) if int(x) > 0})
    if not windows:
        raise ValueError("At least one window size (seconds) is required.")
    out["window_secs"] = windows
    max_sessions = int(out.get("max_training_sessions") or 0)
    if max_sessions < 1:
        raise ValueError("max_training_sessions must be >= 1.")
    if max_sessions > 500:
        raise ValueError("max_training_sessions cannot exceed 500.")
    out["max_training_sessions"] = max_sessions
    out["train_samples_threshold_sec"] = max(
        1, int(out.get("train_samples_threshold_sec") or 10)
    )
    out["train_samples_per_phase_at_or_below_sec"] = max(
        1, int(out.get("train_samples_per_phase_at_or_below_sec") or 10)
    )
    out["train_samples_per_phase_above_sec"] = max(
        1, int(out.get("train_samples_per_phase_above_sec") or 5)
    )
    return out


def get_window_secs(path: Path | None = None) -> tuple[int, ...]:
    return tuple(load_settings(path)["window_secs"])


def get_max_training_sessions(path: Path | None = None) -> int:
    return int(load_settings(path)["max_training_sessions"])


def get_train_samples_per_phase(window_sec: int, path: Path | None = None) -> int:
    s = load_settings(path)
    if int(window_sec) <= int(s["train_samples_threshold_sec"]):
        return int(s["train_samples_per_phase_at_or_below_sec"])
    return int(s["train_samples_per_phase_above_sec"])


def set_max_training_sessions(n: int, path: Path | None = None) -> dict[str, Any]:
    s = load_settings(path)
    s["max_training_sessions"] = int(n)
    return save_settings(s, path)


def set_window_secs(window_secs: list[int] | tuple[int, ...], path: Path | None = None) -> dict[str, Any]:
    s = load_settings(path)
    s["window_secs"] = list(window_secs)
    return save_settings(s, path)


def add_window_sec(window_sec: int, path: Path | None = None) -> dict[str, Any]:
    sec = int(window_sec)
    if sec < 1 or sec > 600:
        raise ValueError("Window size must be between 1 and 600 seconds.")
    s = load_settings(path)
    windows = set(int(x) for x in s["window_secs"])
    windows.add(sec)
    s["window_secs"] = sorted(windows)
    return save_settings(s, path)


def remove_window_sec(window_sec: int, path: Path | None = None) -> dict[str, Any]:
    sec = int(window_sec)
    s = load_settings(path)
    windows = [int(x) for x in s["window_secs"] if int(x) != sec]
    if not windows:
        raise ValueError("Cannot remove the last window size.")
    s["window_secs"] = windows
    return save_settings(s, path)


__all__ = [
    "DEFAULT_SETTINGS",
    "SETTINGS_PATH",
    "add_window_sec",
    "default_settings",
    "ensure_settings",
    "get_max_training_sessions",
    "get_train_samples_per_phase",
    "get_window_secs",
    "load_settings",
    "normalize_settings",
    "remove_window_sec",
    "save_settings",
    "set_max_training_sessions",
    "set_window_secs",
]
