"""Task entities: create, randomize, persist responses (self-contained)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from hc_rr import (
    DEFAULT_WINDOW_SECS,
    build_window_catalog,
    list_participants,
)
from hc_settings import get_window_secs

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE / "data" / "tasks"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_tasks_dir() -> Path:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    return TASKS_DIR


def new_task_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]


def normalize_nickname(raw: str | None, *, fallback: str = "") -> str:
    """Trim and clamp a human-friendly task name."""
    text = " ".join(str(raw or "").split())
    if not text:
        text = str(fallback or "").strip()
    if len(text) > 80:
        text = text[:80].rstrip()
    return text


def default_nickname(*, window_sec: int, cohort_option: int) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    return f"{int(window_sec)}s · cohort {int(cohort_option)} · {stamp}"


def task_path(task_id: str) -> Path:
    return ensure_tasks_dir() / f"{task_id}.json"


def responses_path(task_id: str) -> Path:
    return ensure_tasks_dir() / f"{task_id}_responses.jsonl"


def partition_participants(
    participants: list[str],
    cohort_option: int,
    rng: np.random.Generator,
) -> dict[str, int]:
    """Map participant -> cohort_index in 0 .. cohort_option-1."""
    n = max(1, int(cohort_option))
    pids = list(participants)
    if n == 1:
        return {p: 0 for p in pids}
    order = pids[:]
    rng.shuffle(order)
    assign: dict[str, int] = {}
    for i, pid in enumerate(order):
        # Balanced round-robin after shuffle
        assign[pid] = int(i % n)
    return assign


def build_presentation_order(
    windows: list[dict[str, Any]],
    *,
    cohort_assignments: dict[str, int],
    randomize_participants: bool,
    rng: np.random.Generator,
) -> list[str]:
    """Phase mix always; optional participant mix. Cohort order: 0, then 1, then 2."""
    by_cohort: dict[int, list[dict[str, Any]]] = {}
    for w in windows:
        cidx = int(cohort_assignments.get(str(w["participant"]), 0))
        w = {**w, "cohort_index": cidx}
        by_cohort.setdefault(cidx, []).append(w)

    order: list[str] = []
    for cidx in sorted(by_cohort.keys()):
        pool = by_cohort[cidx]
        if randomize_participants:
            # Shuffle all windows in cohort (mixes phases and participants).
            idxs = np.arange(len(pool))
            rng.shuffle(idxs)
            order.extend(pool[i]["window_id"] for i in idxs)
        else:
            # Stable participant order; within each participant shuffle phases/windows.
            by_pid: dict[str, list[dict[str, Any]]] = {}
            for w in pool:
                by_pid.setdefault(str(w["participant"]), []).append(w)
            for pid in sorted(by_pid.keys()):
                chunk = by_pid[pid]
                idxs = np.arange(len(chunk))
                rng.shuffle(idxs)  # still mix treatment/spreadsheet within pid
                order.extend(chunk[i]["window_id"] for i in idxs)
    return order


def cohort_summary(
    windows: list[dict[str, Any]],
    cohort_assignments: dict[str, int],
    presentation_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    del presentation_order  # order does not affect cohort counts
    n_cohorts = max(cohort_assignments.values(), default=0) + 1
    rows = []
    for cidx in range(n_cohorts):
        pids = sorted(p for p, c in cohort_assignments.items() if c == cidx)
        n_win = sum(
            1
            for w in windows
            if int(cohort_assignments.get(str(w["participant"]), 0)) == cidx
        )
        rows.append(
            {
                "cohort_index": cidx,
                "n_participants": len(pids),
                "participants": pids,
                "n_windows": n_win,
            }
        )
    return rows


def select_participants(
    all_participants: list[str],
    *,
    max_participants: int | None,
    rng: np.random.Generator,
) -> list[str]:
    """Return all participants, or a seeded random subset of size ``max_participants``."""
    pids = list(all_participants)
    if max_participants is None:
        return pids
    n = int(max_participants)
    if n < 1:
        raise ValueError("max_participants must be >= 1")
    if n >= len(pids):
        return pids
    order = pids[:]
    rng.shuffle(order)
    return sorted(order[:n])


def build_task_plan(
    *,
    window_sec: int,
    cohort_option: int = 1,
    randomize_participants: bool = True,
    randomize_phases: bool = True,
    seed: int | None = None,
    max_participants: int | None = None,
) -> dict[str, Any]:
    """Build windows + order in memory (no disk write)."""
    allowed = tuple(get_window_secs()) or tuple(DEFAULT_WINDOW_SECS)
    if int(window_sec) not in allowed:
        raise ValueError(f"window_sec must be one of {allowed}")
    if int(cohort_option) not in (1, 2, 3):
        raise ValueError("cohort_option must be 1, 2, or 3")
    if not randomize_phases:
        raise ValueError("randomize_phases must remain True for now")

    seed_i = int(seed if seed is not None else np.random.default_rng().integers(0, 2**31 - 1))
    rng = np.random.default_rng(seed_i)

    all_participants = list_participants()
    if not all_participants:
        raise FileNotFoundError(f"No participant gap CSVs under {HERE / 'data'}")

    participants = select_participants(
        all_participants, max_participants=max_participants, rng=rng
    )
    if not participants:
        raise ValueError("No participants selected for this task.")

    windows = build_window_catalog(window_sec=int(window_sec), participants=participants)
    if not windows:
        raise ValueError("No windows produced for this window length.")

    cohort_assignments = partition_participants(participants, int(cohort_option), rng)
    for w in windows:
        w["cohort_index"] = int(cohort_assignments[str(w["participant"])])

    presentation_order = build_presentation_order(
        windows,
        cohort_assignments=cohort_assignments,
        randomize_participants=bool(randomize_participants),
        rng=rng,
    )
    summary = cohort_summary(windows, cohort_assignments, presentation_order)
    return {
        "window_sec": int(window_sec),
        "randomize_phases": True,
        "randomize_participants": bool(randomize_participants),
        "cohort_option": int(cohort_option),
        "max_participants": (
            int(max_participants) if max_participants is not None else None
        ),
        "n_participants": len(participants),
        "seed": seed_i,
        "participants": participants,
        "cohort_assignments": cohort_assignments,
        "cohort_summary": summary,
        "n_windows_total": len(windows),
        "presentation_order": presentation_order,
        "windows": windows,
    }


def create_task(
    *,
    access_code: str,
    name: str,
    window_sec: int,
    cohort_option: int = 1,
    randomize_participants: bool = True,
    randomize_phases: bool = True,
    seed: int | None = None,
    nickname: str | None = None,
    max_participants: int | None = None,
) -> dict[str, Any]:
    """Create an independent task entity on disk."""
    ensure_tasks_dir()
    task_id = new_task_id()
    plan = build_task_plan(
        window_sec=window_sec,
        cohort_option=cohort_option,
        randomize_participants=randomize_participants,
        randomize_phases=randomize_phases,
        seed=seed,
        max_participants=max_participants,
    )
    summary = plan["cohort_summary"]
    windows = plan["windows"]
    presentation_order = plan["presentation_order"]
    cohort_assignments = plan["cohort_assignments"]
    participants = plan["participants"]
    seed_i = plan["seed"]
    nick = normalize_nickname(
        nickname,
        fallback=default_nickname(
            window_sec=int(window_sec), cohort_option=int(cohort_option)
        ),
    )

    # Strip bulky arrays from sidecar index? Keep in task file for offline plots.
    task = {
        "task_id": task_id,
        "nickname": nick,
        "access_code": str(access_code).upper(),
        "name": str(name),
        "created_at": _utc_now(),
        "status": "in_progress",
        "window_sec": int(window_sec),
        "randomize_phases": True,
        "randomize_participants": bool(randomize_participants),
        "cohort_option": int(cohort_option),
        "max_participants": plan.get("max_participants"),
        "n_participants": plan.get("n_participants", len(participants)),
        "seed": seed_i,
        "participants": participants,
        "cohort_assignments": cohort_assignments,
        "cohort_summary": summary,
        "n_windows_total": len(windows),
        "presentation_order": presentation_order,
        "current_index": 0,
        "current_cohort_index": 0,
        "windows": windows,
    }
    task_path(task_id).write_text(json.dumps(task, indent=2), encoding="utf-8")
    responses_path(task_id).write_text("", encoding="utf-8")
    return task


def set_task_nickname(task_id: str, nickname: str) -> dict[str, Any]:
    """Update a task's friendly name and persist."""
    task = load_task(task_id)
    nick = normalize_nickname(nickname)
    if not nick:
        raise ValueError("Nickname cannot be empty.")
    task["nickname"] = nick
    task["nickname_updated_at"] = _utc_now()
    save_task(task)
    return task


def load_task(task_id: str) -> dict[str, Any]:
    path = task_path(task_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def task_owned_by(task: dict[str, Any], access_code: str) -> bool:
    return str(task.get("access_code", "")).upper() == str(access_code).upper()


def load_owned_task(task_id: str, access_code: str) -> dict[str, Any]:
    """Load a task only if it belongs to ``access_code``; else PermissionError."""
    task = load_task(task_id)
    if not task_owned_by(task, access_code):
        raise PermissionError(
            f"Task {task_id} is not owned by {str(access_code).upper()}"
        )
    return task


def save_task(task: dict[str, Any]) -> None:
    tid = str(task["task_id"])
    task_path(tid).write_text(json.dumps(task, indent=2), encoding="utf-8")


def delete_task(task_id: str, access_code: str | None = None) -> None:
    """Delete a task and its responses.

    If ``access_code`` is given, ownership is required. Pass ``None`` for
    unrestricted admin delete.
    """
    if access_code is not None:
        task = load_owned_task(task_id, access_code)
    else:
        task = load_task(task_id)
    tid = str(task["task_id"])
    task_path(tid).unlink(missing_ok=True)
    responses_path(tid).unlink(missing_ok=True)


def _task_list_row(data: dict[str, Any], path: Path) -> dict[str, Any]:
    nick = normalize_nickname(
        data.get("nickname"),
        fallback=str(data.get("task_id") or path.stem),
    )
    return {
        "task_id": data.get("task_id"),
        "nickname": nick,
        "created_at": data.get("created_at"),
        "status": data.get("status"),
        "window_sec": data.get("window_sec"),
        "cohort_option": data.get("cohort_option"),
        "n_windows_total": data.get("n_windows_total"),
        "n_participants": data.get("n_participants")
        or len(data.get("participants") or []),
        "max_participants": data.get("max_participants"),
        "access_code": data.get("access_code"),
        "name": data.get("name"),
    }


def list_tasks_for_user(access_code: str) -> list[dict[str, Any]]:
    code = str(access_code).upper()
    rows = []
    for path in sorted(ensure_tasks_dir().glob("*.json")):
        if path.name.endswith("_responses.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(data.get("access_code", "")).upper() != code:
            continue
        rows.append(_task_list_row(data, path))
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def list_all_tasks() -> list[dict[str, Any]]:
    """List every task on disk (admin review)."""
    rows = []
    for path in sorted(ensure_tasks_dir().glob("*.json")):
        if path.name.endswith("_responses.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not data.get("task_id"):
            continue
        rows.append(_task_list_row(data, path))
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows


def score_task(task: dict[str, Any], responses: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compare saved choices to protocol true_class for one task."""
    if responses is None:
        responses = load_responses(str(task["task_id"]))
    n_total = int(task.get("n_windows_total") or len(task.get("windows") or []))
    n_answered = len(responses)
    n_correct = sum(1 for r in responses.values() if r.get("correct") is True)
    n_wrong = sum(1 for r in responses.values() if r.get("correct") is False)
    accuracy = (n_correct / n_answered) if n_answered else None
    return {
        "task_id": task.get("task_id"),
        "n_windows_total": n_total,
        "n_answered": n_answered,
        "n_unanswered": max(0, n_total - n_answered),
        "n_correct": n_correct,
        "n_wrong": n_wrong,
        "accuracy": accuracy,
    }


def responses_vs_truth_rows(
    task: dict[str, Any],
    responses: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """One row per window: human choice vs original protocol label."""
    if responses is None:
        responses = load_responses(str(task["task_id"]))
    order = list(task.get("presentation_order") or [])
    id_to_w = {w["window_id"]: w for w in task.get("windows") or []}
    rows: list[dict[str, Any]] = []
    for i, wid in enumerate(order):
        w = id_to_w.get(wid) or {}
        rec = responses.get(wid) or {}
        true_class = rec.get("true_class") or w.get("true_class")
        true_phase = rec.get("true_phase") or w.get("phase")
        choice = rec.get("choice")
        correct = rec.get("correct")
        if correct is None and choice and true_class:
            correct = str(choice) == str(true_class)
        rows.append(
            {
                "presentation_index": i,
                "window_id": wid,
                "participant": w.get("participant") or rec.get("participant"),
                "true_phase": true_phase,
                "true_class": true_class,
                "choice": choice,
                "correct": correct,
                "start_millis": w.get("start_millis") or rec.get("start_millis"),
                "end_millis": w.get("end_millis") or rec.get("end_millis"),
                "responded_at": rec.get("responded_at"),
            }
        )
    return rows


def load_responses(task_id: str) -> dict[str, dict[str, Any]]:
    path = responses_path(task_id)
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


def upsert_response(task_id: str, record: dict[str, Any]) -> None:
    """Append response; latest line for a window_id wins when reloading."""
    path = responses_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def window_by_id(task: dict[str, Any], window_id: str) -> dict[str, Any] | None:
    for w in task.get("windows") or []:
        if w.get("window_id") == window_id:
            return w
    return None


def indices_for_cohort(task: dict[str, Any], cohort_index: int) -> list[int]:
    order = list(task.get("presentation_order") or [])
    assign = task.get("cohort_assignments") or {}
    id_to_w = {w["window_id"]: w for w in task.get("windows") or []}
    idxs = []
    for i, wid in enumerate(order):
        w = id_to_w.get(wid)
        if w is None:
            continue
        cidx = int(w.get("cohort_index", assign.get(str(w.get("participant")), 0)))
        if cidx == int(cohort_index):
            idxs.append(i)
    return idxs


__all__ = [
    "TASKS_DIR",
    "DEFAULT_WINDOW_SECS",
    "build_presentation_order",
    "build_task_plan",
    "cohort_summary",
    "create_task",
    "default_nickname",
    "delete_task",
    "indices_for_cohort",
    "list_all_tasks",
    "list_tasks_for_user",
    "load_owned_task",
    "load_responses",
    "load_task",
    "normalize_nickname",
    "partition_participants",
    "responses_vs_truth_rows",
    "save_task",
    "score_task",
    "select_participants",
    "set_task_nickname",
    "task_owned_by",
    "upsert_response",
    "window_by_id",
]
