"""Training sessions: randomized paced / not-paced practice (self-contained)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from hc_rr import DEFAULT_WINDOW_SECS, PHASES, sample_random_windows
from hc_settings import get_max_training_sessions, get_train_samples_per_phase, get_window_secs
from hc_task import normalize_nickname

HERE = Path(__file__).resolve().parent
TRAIN_DIR = HERE / "data" / "training"

# Fallback only if settings cannot be read; prefer get_max_training_sessions().
MAX_SESSIONS_PER_USER = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_train_dir() -> Path:
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)
    return TRAIN_DIR


def max_sessions_per_user() -> int:
    return int(get_max_training_sessions())


def samples_per_phase(window_sec: int) -> int:
    """Samples per phase from admin settings (threshold-based)."""
    return int(get_train_samples_per_phase(int(window_sec)))


def new_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]


def default_train_nickname(*, window_sec: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    n = samples_per_phase(window_sec)
    return f"Train {int(window_sec)}s · {n}/phase · {stamp}"


def session_path(session_id: str) -> Path:
    return ensure_train_dir() / f"{session_id}.json"


def responses_path(session_id: str) -> Path:
    return ensure_train_dir() / f"{session_id}_responses.jsonl"


def count_sessions_for_user(access_code: str) -> int:
    return len(list_sessions_for_user(access_code))


def build_training_plan(
    *,
    window_sec: int,
    seed: int | None = None,
) -> dict[str, Any]:
    allowed = tuple(get_window_secs()) or tuple(DEFAULT_WINDOW_SECS)
    if int(window_sec) not in allowed:
        raise ValueError(f"window_sec must be one of {allowed}")
    seed_i = int(seed if seed is not None else np.random.default_rng().integers(0, 2**31 - 1))
    rng = np.random.default_rng(seed_i)
    n_phase = samples_per_phase(int(window_sec))

    by_phase: dict[str, list[dict[str, Any]]] = {}
    for phase in PHASES:
        by_phase[phase] = sample_random_windows(
            window_sec=int(window_sec),
            phase=phase,
            n_samples=n_phase,
            rng=rng,
        )

    windows = by_phase["spreadsheet"] + by_phase["treatment"]
    order_idx = np.arange(len(windows))
    rng.shuffle(order_idx)
    presentation_order = [windows[i]["window_id"] for i in order_idx]

    return {
        "window_sec": int(window_sec),
        "seed": seed_i,
        "samples_per_phase": n_phase,
        "n_windows_total": len(windows),
        "n_spreadsheet": len(by_phase["spreadsheet"]),
        "n_treatment": len(by_phase["treatment"]),
        "presentation_order": presentation_order,
        "windows": windows,
    }


def create_training_session(
    *,
    access_code: str,
    name: str,
    window_sec: int,
    nickname: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Create a training session; enforces max sessions per user."""
    code = str(access_code).upper()
    existing = count_sessions_for_user(code)
    max_n = max_sessions_per_user()
    if existing >= max_n:
        raise ValueError(
            f"Maximum of {max_n} training sessions reached. "
            "Delete an old session to create another."
        )

    ensure_train_dir()
    session_id = new_session_id()
    plan = build_training_plan(window_sec=window_sec, seed=seed)
    nick = normalize_nickname(
        nickname,
        fallback=default_train_nickname(window_sec=int(window_sec)),
    )
    session = {
        "session_id": session_id,
        "nickname": nick,
        "access_code": code,
        "name": str(name),
        "created_at": _utc_now(),
        "status": "in_progress",
        "window_sec": plan["window_sec"],
        "seed": plan["seed"],
        "samples_per_phase": plan["samples_per_phase"],
        "n_windows_total": plan["n_windows_total"],
        "n_spreadsheet": plan["n_spreadsheet"],
        "n_treatment": plan["n_treatment"],
        "presentation_order": plan["presentation_order"],
        "current_index": 0,
        "windows": plan["windows"],
    }
    session_path(session_id).write_text(json.dumps(session, indent=2), encoding="utf-8")
    responses_path(session_id).write_text("", encoding="utf-8")
    return session


def load_session(session_id: str) -> dict[str, Any]:
    path = session_path(session_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def save_session(session: dict[str, Any]) -> None:
    sid = str(session["session_id"])
    session_path(sid).write_text(json.dumps(session, indent=2), encoding="utf-8")


def load_owned_session(session_id: str, access_code: str) -> dict[str, Any]:
    session = load_session(session_id)
    if str(session.get("access_code", "")).upper() != str(access_code).upper():
        raise PermissionError(
            f"Session {session_id} is not owned by {str(access_code).upper()}"
        )
    return session


def set_session_nickname(session_id: str, nickname: str) -> dict[str, Any]:
    session = load_session(session_id)
    nick = normalize_nickname(nickname)
    if not nick:
        raise ValueError("Nickname cannot be empty.")
    session["nickname"] = nick
    session["nickname_updated_at"] = _utc_now()
    save_session(session)
    return session


def delete_session(session_id: str, access_code: str | None = None) -> None:
    """Delete a training session and its responses.

    If ``access_code`` is given, ownership is required. Pass ``None`` for
    unrestricted admin delete.
    """
    if access_code is not None:
        session = load_owned_session(session_id, access_code)
    else:
        session = load_session(session_id)
    sid = str(session["session_id"])
    session_path(sid).unlink(missing_ok=True)
    responses_path(sid).unlink(missing_ok=True)


def _session_list_row(data: dict[str, Any], path: Path) -> dict[str, Any]:
    nick = normalize_nickname(
        data.get("nickname"),
        fallback=str(data.get("session_id") or path.stem),
    )
    return {
        "session_id": data.get("session_id"),
        "nickname": nick,
        "created_at": data.get("created_at"),
        "status": data.get("status"),
        "window_sec": data.get("window_sec"),
        "n_windows_total": data.get("n_windows_total"),
        "samples_per_phase": data.get("samples_per_phase"),
        "access_code": data.get("access_code"),
        "name": data.get("name"),
    }


def list_sessions_for_user(access_code: str) -> list[dict[str, Any]]:
    code = str(access_code).upper()
    rows = []
    for path in sorted(ensure_train_dir().glob("*.json")):
        if "_responses" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(data.get("access_code", "")).upper() != code:
            continue
        if not data.get("session_id"):
            continue
        rows.append(_session_list_row(data, path))
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def list_all_sessions() -> list[dict[str, Any]]:
    """All training sessions on disk (admin review)."""
    rows = []
    for path in sorted(ensure_train_dir().glob("*.json")):
        if "_responses" in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not data.get("session_id"):
            continue
        rows.append(_session_list_row(data, path))
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def load_responses(session_id: str) -> dict[str, dict[str, Any]]:
    """Latest response per window_id (may differ from first attempt after retries)."""
    path = responses_path(session_id)
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        wid = str(rec.get("window_id"))
        out[wid] = rec
    return out


def load_first_responses(session_id: str) -> dict[str, dict[str, Any]]:
    """First answer per window_id — used for training error rate."""
    path = responses_path(session_id)
    out: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        wid = str(rec.get("window_id"))
        if wid not in out:
            out[wid] = rec
    return out


def upsert_response(session_id: str, record: dict[str, Any]) -> None:
    path = responses_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def window_by_id(session: dict[str, Any], window_id: str) -> dict[str, Any] | None:
    for w in session.get("windows") or []:
        if w.get("window_id") == window_id:
            return w
    return None


def score_session(
    session: dict[str, Any],
    responses: dict[str, dict[str, Any]] | None = None,
    *,
    first_responses: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score a training session.

    Error rate / first-attempt accuracy use the **first** answer per window
    (before any corrected retry after feedback). ``n_answered`` / latest
    correct counts still reflect the latest answer when ``responses`` is the
    latest map.
    """
    sid = str(session["session_id"])
    if responses is None:
        responses = load_responses(sid)
    if first_responses is None:
        first_responses = load_first_responses(sid)

    n_total = int(session.get("n_windows_total") or len(session.get("windows") or []))
    n_answered = len(responses)
    n_correct_latest = sum(1 for r in responses.values() if r.get("correct") is True)
    n_wrong_latest = sum(1 for r in responses.values() if r.get("correct") is False)

    n_first = len(first_responses)
    n_first_correct = sum(
        1 for r in first_responses.values() if r.get("correct") is True
    )
    n_first_wrong = sum(
        1 for r in first_responses.values() if r.get("correct") is False
    )
    first_accuracy = (n_first_correct / n_first) if n_first else None
    error_rate = (n_first_wrong / n_first) if n_first else None

    return {
        "n_windows_total": n_total,
        "n_answered": n_answered,
        "n_correct": n_correct_latest,
        "n_wrong": n_wrong_latest,
        "accuracy": (n_correct_latest / n_answered) if n_answered else None,
        "n_first_answered": n_first,
        "n_first_correct": n_first_correct,
        "n_first_wrong": n_first_wrong,
        "first_accuracy": first_accuracy,
        "error_rate": error_rate,
    }


__all__ = [
    "MAX_SESSIONS_PER_USER",
    "TRAIN_DIR",
    "build_training_plan",
    "count_sessions_for_user",
    "create_training_session",
    "default_train_nickname",
    "delete_session",
    "list_all_sessions",
    "list_sessions_for_user",
    "load_first_responses",
    "load_owned_session",
    "load_responses",
    "load_session",
    "max_sessions_per_user",
    "samples_per_phase",
    "save_session",
    "score_session",
    "set_session_nickname",
    "upsert_response",
    "window_by_id",
]
