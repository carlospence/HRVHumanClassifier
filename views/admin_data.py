"""Admin export / import of access codes, tasks, and training sessions."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import is_admin, list_access_codes, log_activity, require_access  # noqa: E402
from hc_transfer import (  # noqa: E402
    build_export_zip,
    import_bundle,
    local_inventory,
    peek_bundle,
)

user = require_access()
if not is_admin():
    st.error("Admin access required.")
    st.stop()

if st.session_state.get("hc_logged_admin_data") != user["access_code"]:
    log_activity("view_page", detail={"page": "admin_data"})
    st.session_state["hc_logged_admin_data"] = user["access_code"]

st.title("Admin · data transfer")
st.caption(
    "Export a ZIP of access codes (users), gold-standard tasks, and training "
    "sessions from this deployment — then import that ZIP on another machine "
    "(e.g. pull online results into a local copy)."
)

inv = local_inventory()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Access codes", inv["access_codes"])
c2.metric("Named users", inv["named_users"])
c3.metric("Tasks", inv["tasks"])
c4.metric("Training sessions", inv["training"])

# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
st.markdown("### Export")
code_rows = list_access_codes()
code_labels = {
    f"{r['code']} · {r['name'] or '(unnamed)'} · {r['role']}": r["code"]
    for r in code_rows
}

ex1, ex2, ex3 = st.columns(3)
with ex1:
    include_codes = st.checkbox(
        "Access codes / users", value=True, key="hc_xfer_ex_codes"
    )
with ex2:
    include_tasks = st.checkbox("Labeling tasks", value=True, key="hc_xfer_ex_tasks")
with ex3:
    include_train = st.checkbox(
        "Training sessions", value=True, key="hc_xfer_ex_train"
    )

filter_mode = st.radio(
    "Scope",
    options=["All users", "Selected access codes"],
    horizontal=True,
    key="hc_xfer_scope",
)
selected_codes: list[str] | None = None
if filter_mode == "Selected access codes":
    picks = st.multiselect(
        "Access codes to include",
        options=list(code_labels.keys()),
        key="hc_xfer_code_picks",
    )
    selected_codes = [code_labels[p] for p in picks]
    if not selected_codes:
        st.warning("Select at least one access code, or switch scope to **All users**.")

can_export = (include_codes or include_tasks or include_train) and (
    filter_mode == "All users" or bool(selected_codes)
)

if st.button("Build export ZIP", type="primary", disabled=not can_export, key="hc_xfer_build"):
    try:
        blob, summary = build_export_zip(
            include_access_codes=include_codes,
            include_tasks=include_tasks,
            include_training=include_train,
            access_codes=selected_codes,
        )
    except Exception as exc:  # noqa: BLE001 — surface to admin UI
        st.error(f"Export failed: {exc}")
    else:
        stamp = str(summary.get("exported_at") or "export").replace(":", "").replace("+", "")
        fname = f"hrv_hc_transfer_{stamp}.zip"
        st.session_state["hc_xfer_blob"] = blob
        st.session_state["hc_xfer_fname"] = fname
        st.session_state["hc_xfer_summary"] = summary
        log_activity(
            "admin_export",
            detail={
                "access_codes": summary["access_codes"],
                "tasks": summary["tasks"],
                "training": summary["training"],
            },
        )
        st.success(
            f"Ready: **{summary['access_codes']}** codes · "
            f"**{summary['tasks']}** tasks · "
            f"**{summary['training']}** training sessions."
        )

if st.session_state.get("hc_xfer_blob"):
    st.download_button(
        "Download transfer ZIP",
        data=st.session_state["hc_xfer_blob"],
        file_name=st.session_state.get("hc_xfer_fname") or "hrv_hc_transfer.zip",
        mime="application/zip",
        key="hc_xfer_dl",
    )

# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------
st.markdown("### Import")
st.caption(
    "Upload a transfer ZIP from another deployment. By default existing task / "
    "session ids are **skipped** (safe merge). Enable overwrite to replace them. "
    "Access codes are merged; `HRVADMIN` always stays admin."
)

uploaded = st.file_uploader(
    "Transfer ZIP",
    type=["zip"],
    key="hc_xfer_upload",
)

if uploaded is not None:
    raw = uploaded.getvalue()
    try:
        peek = peek_bundle(raw)
    except ValueError as exc:
        st.error(str(exc))
        peek = None
    else:
        st.info(
            f"Bundle from **{peek.get('exported_at') or '—'}** · "
            f"**{peek['access_codes']}** codes · "
            f"**{peek['tasks']}** tasks · "
            f"**{peek['training']}** training"
            + (
                f" · filter `{', '.join(peek['access_code_filter'])}`"
                if peek.get("access_code_filter")
                else ""
            )
        )

    im1, im2, im3 = st.columns(3)
    with im1:
        do_codes = st.checkbox("Import access codes", value=True, key="hc_xfer_im_codes")
    with im2:
        do_tasks = st.checkbox("Import tasks", value=True, key="hc_xfer_im_tasks")
    with im3:
        do_train = st.checkbox("Import training", value=True, key="hc_xfer_im_train")

    ow1, ow2, ow3 = st.columns(3)
    with ow1:
        ow_codes = st.checkbox(
            "Overwrite existing codes",
            value=False,
            key="hc_xfer_ow_codes",
            help="Update name/role for codes that already exist.",
        )
    with ow2:
        ow_tasks = st.checkbox(
            "Overwrite existing tasks",
            value=False,
            key="hc_xfer_ow_tasks",
        )
    with ow3:
        ow_train = st.checkbox(
            "Overwrite existing training",
            value=False,
            key="hc_xfer_ow_train",
        )

    if st.button(
        "Import into this app",
        type="primary",
        disabled=peek is None or not (do_codes or do_tasks or do_train),
        key="hc_xfer_import",
    ):
        try:
            result = import_bundle(
                raw,
                import_access_codes=do_codes,
                import_tasks=do_tasks,
                import_training=do_train,
                overwrite_access_codes=ow_codes,
                overwrite_tasks=ow_tasks,
                overwrite_training=ow_train,
            )
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Import failed: {exc}")
        else:
            ac = result["access_codes"]
            tk = result["tasks"]
            tr = result["training"]
            st.success(
                f"Access codes — added **{ac.get('added', 0)}**, "
                f"updated **{ac.get('updated', 0)}**, "
                f"skipped **{ac.get('skipped', 0)}**.  \n"
                f"Tasks — written **{tk.get('written', 0)}**, "
                f"overwritten **{tk.get('overwritten', 0)}**, "
                f"skipped **{tk.get('skipped', 0)}**.  \n"
                f"Training — written **{tr.get('written', 0)}**, "
                f"overwritten **{tr.get('overwritten', 0)}**, "
                f"skipped **{tr.get('skipped', 0)}**."
            )
            errs = list(tk.get("errors") or []) + list(tr.get("errors") or [])
            if errs:
                st.warning("Some items failed:\n\n- " + "\n- ".join(errs[:20]))
            log_activity(
                "admin_import",
                detail={
                    "access_codes": ac,
                    "tasks": {
                        k: tk.get(k)
                        for k in ("written", "overwritten", "skipped")
                    },
                    "training": {
                        k: tr.get(k)
                        for k in ("written", "overwritten", "skipped")
                    },
                },
            )
            st.rerun()
