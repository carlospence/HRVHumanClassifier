"""Export / import access codes, labeling tasks, and training sessions.

Bundle format (ZIP)::

    manifest.json
    access_codes.json          # optional
    tasks/<id>.json            # optional
    tasks/<id>_responses.jsonl
    training/<id>.json         # optional
    training/<id>_responses.jsonl

Designed so an online deployment can export user results and an admin can
import them into a local copy of the app.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from access_lib import (
    PROTECTED_ACCESS_CODE,
    VALID_ROLES,
    load_access_store,
    normalize_code,
    save_access_store,
)
from hc_task import (
    TASKS_DIR,
    ensure_tasks_dir,
    list_all_tasks,
    load_task,
    responses_path as task_responses_path,
    task_path,
)
from hc_train import (
    TRAIN_DIR,
    ensure_train_dir,
    list_all_sessions,
    load_session,
    responses_path as train_responses_path,
    session_path,
)

BUNDLE_KIND = "hrv_human_classifier_transfer"
BUNDLE_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_text_or_empty(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _norm_codes_filter(codes: list[str] | None) -> set[str] | None:
    if codes is None:
        return None
    out = {normalize_code(c) for c in codes if str(c or "").strip()}
    return out or None


def build_export_zip(
    *,
    include_access_codes: bool = True,
    include_tasks: bool = True,
    include_training: bool = True,
    access_codes: list[str] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Build a transfer ZIP. Returns ``(zip_bytes, summary)``."""
    code_filter = _norm_codes_filter(access_codes)
    buf = io.BytesIO()
    summary: dict[str, Any] = {
        "access_codes": 0,
        "tasks": 0,
        "training": 0,
        "exported_at": _utc_now(),
    }

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "kind": BUNDLE_KIND,
            "version": BUNDLE_VERSION,
            "exported_at": summary["exported_at"],
            "include_access_codes": bool(include_access_codes),
            "include_tasks": bool(include_tasks),
            "include_training": bool(include_training),
            "access_code_filter": sorted(code_filter) if code_filter else None,
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        if include_access_codes:
            store = load_access_store()
            codes = dict(store.get("codes") or {})
            if code_filter is not None:
                codes = {
                    k: v
                    for k, v in codes.items()
                    if normalize_code(k) in code_filter
                }
            payload = {"version": int(store.get("version") or 1), "codes": codes}
            zf.writestr("access_codes.json", json.dumps(payload, indent=2))
            summary["access_codes"] = len(codes)

        if include_tasks:
            ensure_tasks_dir()
            for meta in list_all_tasks():
                tid = str(meta.get("task_id") or "")
                if not tid:
                    continue
                if code_filter is not None:
                    if normalize_code(str(meta.get("access_code") or "")) not in code_filter:
                        continue
                tpath = task_path(tid)
                if not tpath.is_file():
                    continue
                zf.writestr(f"tasks/{tid}.json", tpath.read_text(encoding="utf-8"))
                zf.writestr(
                    f"tasks/{tid}_responses.jsonl",
                    _read_text_or_empty(task_responses_path(tid)),
                )
                summary["tasks"] += 1

        if include_training:
            ensure_train_dir()
            for meta in list_all_sessions():
                sid = str(meta.get("session_id") or "")
                if not sid:
                    continue
                if code_filter is not None:
                    if normalize_code(str(meta.get("access_code") or "")) not in code_filter:
                        continue
                spath = session_path(sid)
                if not spath.is_file():
                    continue
                zf.writestr(f"training/{sid}.json", spath.read_text(encoding="utf-8"))
                zf.writestr(
                    f"training/{sid}_responses.jsonl",
                    _read_text_or_empty(train_responses_path(sid)),
                )
                summary["training"] += 1

    return buf.getvalue(), summary


def _parse_bundle(data: bytes) -> tuple[dict[str, Any], zipfile.ZipFile]:
    buf = io.BytesIO(data)
    try:
        zf = zipfile.ZipFile(buf, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP transfer bundle.") from exc
    names = set(zf.namelist())
    if "manifest.json" not in names:
        zf.close()
        raise ValueError("Bundle missing manifest.json.")
    try:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        zf.close()
        raise ValueError("Invalid manifest.json in bundle.") from exc
    if str(manifest.get("kind") or "") != BUNDLE_KIND:
        zf.close()
        raise ValueError(
            f"Unrecognized bundle kind: {manifest.get('kind')!r} "
            f"(expected {BUNDLE_KIND!r})."
        )
    return manifest, zf


def _merge_access_codes(
    imported: dict[str, Any],
    *,
    overwrite_existing: bool,
) -> dict[str, int]:
    store = load_access_store()
    codes = store.setdefault("codes", {})
    added = updated = skipped = 0
    for raw_code, meta in (imported.get("codes") or {}).items():
        key = normalize_code(raw_code)
        if not key:
            continue
        incoming = dict(meta or {})
        role = str(incoming.get("role") or "user").strip().lower()
        if role not in VALID_ROLES:
            role = "user"
        if key == PROTECTED_ACCESS_CODE:
            role = "admin"
        incoming["role"] = role

        if key not in codes and normalize_code(key) not in {
            normalize_code(k) for k in codes
        }:
            codes[key] = {
                "name": incoming.get("name"),
                "role": role,
                "created_at": incoming.get("created_at") or _utc_now(),
                "registered_at": incoming.get("registered_at"),
            }
            added += 1
            continue

        # Resolve existing key with case-insensitive match
        stored_key = next(
            (k for k in codes if normalize_code(k) == key),
            key,
        )
        existing = codes[stored_key]
        if not overwrite_existing:
            # Fill empty name from import; never demote HRVADMIN
            changed = False
            if not (existing.get("name") or "").strip() and (
                incoming.get("name") or ""
            ).strip():
                existing["name"] = incoming.get("name")
                existing["registered_at"] = (
                    incoming.get("registered_at") or _utc_now()
                )
                changed = True
            if stored_key == PROTECTED_ACCESS_CODE:
                existing["role"] = "admin"
            if changed:
                updated += 1
            else:
                skipped += 1
            continue

        existing["name"] = incoming.get("name")
        existing["role"] = (
            "admin" if stored_key == PROTECTED_ACCESS_CODE else role
        )
        if incoming.get("created_at"):
            existing["created_at"] = incoming.get("created_at")
        existing["registered_at"] = incoming.get("registered_at")
        updated += 1

    save_access_store(store)
    return {"added": added, "updated": updated, "skipped": skipped}


def _write_entity(
    *,
    entity_json: dict[str, Any],
    responses_text: str,
    json_path: Path,
    responses_path: Path,
    overwrite: bool,
) -> str:
    """Return 'written' | 'overwritten' | 'skipped'."""
    exists = json_path.is_file()
    if exists and not overwrite:
        return "skipped"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(entity_json, indent=2), encoding="utf-8")
    responses_path.write_text(responses_text or "", encoding="utf-8")
    return "overwritten" if exists else "written"


def import_bundle(
    data: bytes,
    *,
    import_access_codes: bool = True,
    import_tasks: bool = True,
    import_training: bool = True,
    overwrite_access_codes: bool = False,
    overwrite_tasks: bool = False,
    overwrite_training: bool = False,
) -> dict[str, Any]:
    """Import a transfer ZIP into the local app store."""
    manifest, zf = _parse_bundle(data)
    result: dict[str, Any] = {
        "manifest": {
            "version": manifest.get("version"),
            "exported_at": manifest.get("exported_at"),
        },
        "access_codes": {"added": 0, "updated": 0, "skipped": 0},
        "tasks": {"written": 0, "overwritten": 0, "skipped": 0, "errors": []},
        "training": {"written": 0, "overwritten": 0, "skipped": 0, "errors": []},
    }
    try:
        names = zf.namelist()

        if import_access_codes and "access_codes.json" in names:
            try:
                payload = json.loads(zf.read("access_codes.json").decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError(f"Invalid access_codes.json: {exc}") from exc
            result["access_codes"] = _merge_access_codes(
                payload, overwrite_existing=overwrite_access_codes
            )

        if import_tasks:
            ensure_tasks_dir()
            task_files = [
                n
                for n in names
                if n.startswith("tasks/")
                and n.endswith(".json")
                and not n.endswith("_responses.json")
            ]
            for name in sorted(task_files):
                stem = Path(name).name
                if stem.endswith("_responses.json"):
                    continue
                tid = stem[: -len(".json")]
                try:
                    entity = json.loads(zf.read(name).decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    result["tasks"]["errors"].append(f"{tid}: {exc}")
                    continue
                if not entity.get("task_id"):
                    entity["task_id"] = tid
                resp_name = f"tasks/{tid}_responses.jsonl"
                resp_text = ""
                if resp_name in names:
                    resp_text = zf.read(resp_name).decode("utf-8")
                status = _write_entity(
                    entity_json=entity,
                    responses_text=resp_text,
                    json_path=task_path(tid),
                    responses_path=task_responses_path(tid),
                    overwrite=overwrite_tasks,
                )
                result["tasks"][status] = int(result["tasks"].get(status, 0)) + 1

        if import_training:
            ensure_train_dir()
            train_files = [
                n
                for n in names
                if n.startswith("training/")
                and n.endswith(".json")
                and "_responses" not in Path(n).name
            ]
            for name in sorted(train_files):
                sid = Path(name).stem
                try:
                    entity = json.loads(zf.read(name).decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    result["training"]["errors"].append(f"{sid}: {exc}")
                    continue
                if not entity.get("session_id"):
                    entity["session_id"] = sid
                resp_name = f"training/{sid}_responses.jsonl"
                resp_text = ""
                if resp_name in names:
                    resp_text = zf.read(resp_name).decode("utf-8")
                status = _write_entity(
                    entity_json=entity,
                    responses_text=resp_text,
                    json_path=session_path(sid),
                    responses_path=train_responses_path(sid),
                    overwrite=overwrite_training,
                )
                result["training"][status] = (
                    int(result["training"].get(status, 0)) + 1
                )
    finally:
        zf.close()

    return result


def peek_bundle(data: bytes) -> dict[str, Any]:
    """Lightweight summary of a transfer ZIP without writing anything."""
    manifest, zf = _parse_bundle(data)
    try:
        names = zf.namelist()
        n_codes = 0
        if "access_codes.json" in names:
            payload = json.loads(zf.read("access_codes.json").decode("utf-8"))
            n_codes = len(payload.get("codes") or {})
        n_tasks = sum(
            1
            for n in names
            if n.startswith("tasks/")
            and n.endswith(".json")
            and "_responses" not in Path(n).name
        )
        n_train = sum(
            1
            for n in names
            if n.startswith("training/")
            and n.endswith(".json")
            and "_responses" not in Path(n).name
        )
    finally:
        zf.close()
    return {
        "kind": manifest.get("kind"),
        "version": manifest.get("version"),
        "exported_at": manifest.get("exported_at"),
        "access_codes": n_codes,
        "tasks": n_tasks,
        "training": n_train,
        "access_code_filter": manifest.get("access_code_filter"),
    }


def local_inventory() -> dict[str, Any]:
    """Counts currently on disk (for the transfer UI)."""
    store = load_access_store()
    return {
        "access_codes": len(store.get("codes") or {}),
        "named_users": sum(
            1
            for m in (store.get("codes") or {}).values()
            if str((m or {}).get("name") or "").strip()
        ),
        "tasks": len(list_all_tasks()),
        "training": len(list_all_sessions()),
        "tasks_dir": str(TASKS_DIR),
        "training_dir": str(TRAIN_DIR),
    }


__all__ = [
    "BUNDLE_KIND",
    "BUNDLE_VERSION",
    "build_export_zip",
    "import_bundle",
    "local_inventory",
    "peek_bundle",
]
