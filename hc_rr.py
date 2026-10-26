"""Self-contained RR loading and window cutting for HRV Human Classifier.

No imports from the parent analytics repo. Reads local ``data/pXX/*-hrv-generated-gap.csv``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"

GAP_FILE_SUFFIX = "-hrv-generated-gap.csv"
EXCLUDED_PARTICIPANTS = ("p16", "p19", "p23", "p28")
PHASES = ("spreadsheet", "treatment")
SEGMENT_BREAK_SEC = 15.0
RR_MIN_MS = 333.0
RR_MAX_MS = 2000.0
DEFAULT_WINDOW_SECS = (10, 20, 30)
MIN_BEATS_PER_WINDOW = 8

PHASE_TO_TRUE_CLASS = {
    "treatment": "paced",
    "spreadsheet": "not_paced",
}
TRUE_CLASS_LABELS = {
    "paced": "Paced (treatment)",
    "not_paced": "Not paced (spreadsheet)",
}


def normalize_participant_id(participant: str) -> str:
    pid = str(participant).strip()
    if pid.startswith("p") and pid[1:].isdigit():
        return f"p{int(pid[1:]):02d}"
    if pid.isdigit():
        return f"p{int(pid):02d}"
    return pid


def gap_path(participant: str, data_dir: Path | None = None) -> Path:
    root = Path(data_dir or DATA_DIR)
    pid = normalize_participant_id(participant)
    return root / pid / f"{pid}{GAP_FILE_SUFFIX}"


def list_participants(data_dir: Path | None = None) -> list[str]:
    root = Path(data_dir or DATA_DIR)
    excluded = set(EXCLUDED_PARTICIPANTS)
    pids = sorted(
        {
            p.parent.name
            for p in root.glob(f"p*/p*{GAP_FILE_SUFFIX}")
            if p.parent.name not in excluded
        }
    )
    return pids


def clean_rr_series(
    rr_ms: np.ndarray,
    millis_ms: np.ndarray | None = None,
    *,
    rr_min_ms: float = RR_MIN_MS,
    rr_max_ms: float = RR_MAX_MS,
) -> tuple[np.ndarray, np.ndarray | None]:
    rr = np.asarray(rr_ms, dtype=float).ravel()
    mask = np.isfinite(rr) & (rr >= float(rr_min_ms)) & (rr <= float(rr_max_ms))
    rr_c = rr[mask]
    if millis_ms is None:
        return rr_c, None
    ms = np.asarray(millis_ms, dtype=float).ravel()
    if ms.size != rr.size:
        raise ValueError("rr_ms and millis_ms length mismatch.")
    return rr_c, ms[mask]


@dataclass(frozen=True)
class PhaseRun:
    participant: str
    phase: str
    phase_run_id: int
    rr_ms: np.ndarray
    millis_ms: np.ndarray

    @property
    def duration_sec(self) -> float:
        if self.millis_ms.size < 2:
            return 0.0
        return float((self.millis_ms[-1] - self.millis_ms[0]) / 1000.0)


def iter_phase_runs(
    beat_df: pd.DataFrame,
    *,
    participant: str,
    phases: Iterable[str] = PHASES,
    segment_break_sec: float = SEGMENT_BREAK_SEC,
) -> list[dict[str, Any]]:
    """Split beat table into contiguous phase runs (gap or phase change)."""
    required = {"millis", "rr", "phase"}
    missing = required.difference(beat_df.columns)
    if missing:
        raise ValueError(f"Beat data missing columns: {sorted(missing)}")

    ordered = beat_df.sort_values("millis").reset_index(drop=True).copy()
    if ordered.empty:
        return []
    ordered["phase"] = ordered["phase"].astype(str)
    phase_set = {str(p) for p in phases}
    millis = pd.to_numeric(ordered["millis"], errors="coerce")
    gap_break = millis.diff().div(1000.0).gt(float(segment_break_sec))
    phase_break = ordered["phase"].ne(ordered["phase"].shift())
    ordered["_run"] = (gap_break | phase_break).cumsum().astype(int)

    runs: list[dict[str, Any]] = []
    phase_run_id = 0
    for _, group in ordered.groupby("_run", sort=False):
        phase = str(group["phase"].iloc[0])
        if phase not in phase_set:
            continue
        rr = pd.to_numeric(group["rr"], errors="coerce").to_numpy(dtype=float)
        ms = pd.to_numeric(group["millis"], errors="coerce").to_numpy(dtype=float)
        rr_c, ms_c = clean_rr_series(rr, ms)
        if ms_c is None or rr_c.size < 2:
            phase_run_id += 1
            continue
        runs.append(
            {
                "participant": normalize_participant_id(participant),
                "phase": phase,
                "phase_run_id": int(phase_run_id),
                "rr_ms": rr_c,
                "millis_ms": ms_c,
            }
        )
        phase_run_id += 1
    return runs


def load_phase_runs(
    participant: str,
    *,
    data_dir: Path | None = None,
    phases: Iterable[str] = PHASES,
) -> list[PhaseRun]:
    path = gap_path(participant, data_dir)
    if not path.is_file():
        return []
    beats = pd.read_csv(path)
    out: list[PhaseRun] = []
    for run in iter_phase_runs(beats, participant=participant, phases=phases):
        out.append(
            PhaseRun(
                participant=run["participant"],
                phase=run["phase"],
                phase_run_id=run["phase_run_id"],
                rr_ms=np.asarray(run["rr_ms"], dtype=float),
                millis_ms=np.asarray(run["millis_ms"], dtype=float),
            )
        )
    return out


def cut_nonoverlapping_windows(
    rr_ms: np.ndarray,
    millis_ms: np.ndarray,
    window_sec: float,
    *,
    min_beats: int = MIN_BEATS_PER_WINDOW,
) -> list[dict[str, Any]]:
    """Cut contiguous non-overlapping windows of ``window_sec`` from a phase run."""
    rr = np.asarray(rr_ms, dtype=float).ravel()
    ms = np.asarray(millis_ms, dtype=float).ravel()
    if rr.size < int(min_beats) or ms.size != rr.size:
        return []
    w_ms = float(window_sec) * 1000.0
    t0 = float(ms[0])
    t_last = float(ms[-1])
    if t_last - t0 + 1e-9 < w_ms:
        return []

    windows: list[dict[str, Any]] = []
    start = t0
    index = 0
    while start + w_ms <= t_last + 1e-6:
        end = start + w_ms
        mask = (ms >= start - 1e-9) & (ms <= end + 1e-9)
        rr_w = rr[mask]
        ms_w = ms[mask]
        if rr_w.size >= int(min_beats):
            windows.append(
                {
                    "window_index": int(index),
                    "start_millis": float(ms_w[0]),
                    "end_millis": float(ms_w[-1]),
                    "start_sec_in_phase": float((ms_w[0] - t0) / 1000.0),
                    "end_sec_in_phase": float((ms_w[-1] - t0) / 1000.0),
                    "n_beats": int(rr_w.size),
                    "rr_ms": rr_w.astype(float).tolist(),
                    "millis_ms": ms_w.astype(float).tolist(),
                    "t_rel_sec": ((ms_w - ms_w[0]) / 1000.0).astype(float).tolist(),
                }
            )
        start = end
        index += 1
    return windows


def build_window_catalog(
    *,
    window_sec: int,
    participants: Iterable[str] | None = None,
    data_dir: Path | None = None,
    min_beats: int = MIN_BEATS_PER_WINDOW,
) -> list[dict[str, Any]]:
    """Build canonical window list for all (or selected) participants."""
    pids = list(participants) if participants is not None else list_participants(data_dir)
    catalog: list[dict[str, Any]] = []
    for pid in pids:
        for run in load_phase_runs(pid, data_dir=data_dir):
            cuts = cut_nonoverlapping_windows(
                run.rr_ms,
                run.millis_ms,
                float(window_sec),
                min_beats=min_beats,
            )
            for cut in cuts:
                window_id = (
                    f"{run.participant}_{run.phase}_r{run.phase_run_id}"
                    f"_w{cut['window_index']:03d}"
                )
                catalog.append(
                    {
                        "window_id": window_id,
                        "participant": run.participant,
                        "phase": run.phase,
                        "true_class": PHASE_TO_TRUE_CLASS[run.phase],
                        "phase_run_id": int(run.phase_run_id),
                        "window_index": int(cut["window_index"]),
                        "window_sec": int(window_sec),
                        "start_millis": float(cut["start_millis"]),
                        "end_millis": float(cut["end_millis"]),
                        "start_sec_in_phase": float(cut["start_sec_in_phase"]),
                        "end_sec_in_phase": float(cut["end_sec_in_phase"]),
                        "n_beats": int(cut["n_beats"]),
                        "rr_ms": cut["rr_ms"],
                        "t_rel_sec": cut["t_rel_sec"],
                    }
                )
    return catalog


def extract_window_at(
    rr_ms: np.ndarray,
    millis_ms: np.ndarray,
    *,
    start_millis: float,
    window_sec: float,
    min_beats: int = MIN_BEATS_PER_WINDOW,
) -> dict[str, Any] | None:
    """Extract one window starting near ``start_millis`` (length ``window_sec``)."""
    rr = np.asarray(rr_ms, dtype=float).ravel()
    ms = np.asarray(millis_ms, dtype=float).ravel()
    if rr.size < int(min_beats) or ms.size != rr.size:
        return None
    w_ms = float(window_sec) * 1000.0
    t0 = float(ms[0])
    end = float(start_millis) + w_ms
    mask = (ms >= float(start_millis) - 1e-9) & (ms <= end + 1e-9)
    rr_w = rr[mask]
    ms_w = ms[mask]
    if rr_w.size < int(min_beats):
        return None
    return {
        "start_millis": float(ms_w[0]),
        "end_millis": float(ms_w[-1]),
        "start_sec_in_phase": float((ms_w[0] - t0) / 1000.0),
        "end_sec_in_phase": float((ms_w[-1] - t0) / 1000.0),
        "n_beats": int(rr_w.size),
        "rr_ms": rr_w.astype(float).tolist(),
        "t_rel_sec": ((ms_w - ms_w[0]) / 1000.0).astype(float).tolist(),
    }


def sample_random_windows(
    *,
    window_sec: int,
    phase: str,
    n_samples: int,
    rng: np.random.Generator,
    participants: Iterable[str] | None = None,
    data_dir: Path | None = None,
    min_beats: int = MIN_BEATS_PER_WINDOW,
    max_attempts: int = 5000,
) -> list[dict[str, Any]]:
    """Draw ``n_samples`` random windows from ``phase`` across participants.

    Each draw picks a random participant phase-run (weighted by duration) and a
    random start time within that run so the slice can be anywhere in the phase.
    """
    if phase not in PHASES:
        raise ValueError(f"phase must be one of {PHASES}")
    pids = list(participants) if participants is not None else list_participants(data_dir)
    runs: list[PhaseRun] = []
    for pid in pids:
        for run in load_phase_runs(pid, data_dir=data_dir, phases=(phase,)):
            if run.phase != phase:
                continue
            if run.duration_sec + 1e-9 < float(window_sec):
                continue
            if run.rr_ms.size < int(min_beats):
                continue
            runs.append(run)
    if not runs:
        raise ValueError(f"No usable {phase} phase runs for {window_sec}s windows.")

    durations = np.array([max(r.duration_sec, 1e-3) for r in runs], dtype=float)
    weights = durations / durations.sum()
    w_ms = float(window_sec) * 1000.0
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()  # participant, phase_run_id, start_ms_rounded

    attempts = 0
    while len(out) < int(n_samples) and attempts < int(max_attempts):
        attempts += 1
        run = runs[int(rng.choice(len(runs), p=weights))]
        ms = run.millis_ms.astype(float)
        t0 = float(ms[0])
        t_last = float(ms[-1])
        latest_start = t_last - w_ms
        if latest_start <= t0:
            continue
        start = float(rng.uniform(t0, latest_start))
        cut = extract_window_at(
            run.rr_ms,
            run.millis_ms,
            start_millis=start,
            window_sec=float(window_sec),
            min_beats=min_beats,
        )
        if cut is None:
            continue
        start_key = int(round(cut["start_millis"]))
        sig = (run.participant, int(run.phase_run_id), start_key)
        if sig in seen:
            continue
        seen.add(sig)
        window_id = (
            f"{run.participant}_{run.phase}_r{run.phase_run_id}"
            f"_t{start_key}_train{len(out):03d}"
        )
        out.append(
            {
                "window_id": window_id,
                "participant": run.participant,
                "phase": run.phase,
                "true_class": PHASE_TO_TRUE_CLASS[run.phase],
                "phase_run_id": int(run.phase_run_id),
                "window_sec": int(window_sec),
                "start_millis": float(cut["start_millis"]),
                "end_millis": float(cut["end_millis"]),
                "start_sec_in_phase": float(cut["start_sec_in_phase"]),
                "end_sec_in_phase": float(cut["end_sec_in_phase"]),
                "n_beats": int(cut["n_beats"]),
                "rr_ms": cut["rr_ms"],
                "t_rel_sec": cut["t_rel_sec"],
            }
        )

    if len(out) < int(n_samples):
        raise ValueError(
            f"Could only sample {len(out)}/{n_samples} random {phase} "
            f"windows of {window_sec}s (try again or use a shorter window)."
        )
    return out


__all__ = [
    "DATA_DIR",
    "DEFAULT_WINDOW_SECS",
    "EXCLUDED_PARTICIPANTS",
    "MIN_BEATS_PER_WINDOW",
    "PHASES",
    "PHASE_TO_TRUE_CLASS",
    "TRUE_CLASS_LABELS",
    "PhaseRun",
    "build_window_catalog",
    "clean_rr_series",
    "cut_nonoverlapping_windows",
    "extract_window_at",
    "gap_path",
    "list_participants",
    "load_phase_runs",
    "normalize_participant_id",
    "sample_random_windows",
]
