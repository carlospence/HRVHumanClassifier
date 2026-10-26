"""Admin settings: training limits and window sizes."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import is_admin, log_activity, require_access  # noqa: E402
from hc_settings import (  # noqa: E402
    SETTINGS_PATH,
    add_window_sec,
    get_max_training_sessions,
    get_window_secs,
    load_settings,
    remove_window_sec,
    save_settings,
    set_max_training_sessions,
)

user = require_access()
if not is_admin():
    st.error("Admin access required.")
    st.stop()

if st.session_state.get("hc_logged_settings") != user["access_code"]:
    log_activity("view_page", detail={"page": "admin_settings"})
    st.session_state["hc_logged_settings"] = user["access_code"]

st.title("Admin · settings")
st.caption(
    f"App-wide configuration stored in `{SETTINGS_PATH.name}`. "
    "Changes apply to new labeling tasks and training sessions."
)

settings = load_settings()

st.markdown("### Training sessions")
max_n = st.number_input(
    "Maximum training sessions per user",
    min_value=1,
    max_value=500,
    value=int(get_max_training_sessions()),
    step=1,
    key="hc_settings_max_train",
    help="Each access code can keep at most this many training sessions.",
)
c_thr, c_lo, c_hi = st.columns(3)
with c_thr:
    threshold = st.number_input(
        "Samples threshold (s)",
        min_value=1,
        max_value=600,
        value=int(settings.get("train_samples_threshold_sec") or 10),
        step=1,
        key="hc_settings_train_threshold",
        help="Windows at or below this length use the higher sample count.",
    )
with c_lo:
    samples_lo = st.number_input(
        "Samples/phase at or below threshold",
        min_value=1,
        max_value=100,
        value=int(settings.get("train_samples_per_phase_at_or_below_sec") or 10),
        step=1,
        key="hc_settings_train_lo",
    )
with c_hi:
    samples_hi = st.number_input(
        "Samples/phase above threshold",
        min_value=1,
        max_value=100,
        value=int(settings.get("train_samples_per_phase_above_sec") or 5),
        step=1,
        key="hc_settings_train_hi",
    )

if st.button("Save training settings", type="primary", key="hc_settings_save_train"):
    try:
        set_max_training_sessions(int(max_n))
        s = load_settings()
        s["train_samples_threshold_sec"] = int(threshold)
        s["train_samples_per_phase_at_or_below_sec"] = int(samples_lo)
        s["train_samples_per_phase_above_sec"] = int(samples_hi)
        save_settings(s)
    except ValueError as exc:
        st.error(str(exc))
    else:
        log_activity(
            "settings_updated",
            detail={
                "max_training_sessions": int(max_n),
                "train_samples_threshold_sec": int(threshold),
                "train_samples_per_phase_at_or_below_sec": int(samples_lo),
                "train_samples_per_phase_above_sec": int(samples_hi),
            },
        )
        st.success("Training settings saved.")
        st.rerun()

st.markdown("### Window sizes")
st.caption(
    "Allowed window lengths (seconds) for Gold-standard labeling and Training."
)
windows = list(get_window_secs())
st.write("**Current:** " + ", ".join(f"**{w}** s" for w in windows))

a1, a2 = st.columns([2, 1])
with a1:
    new_win = st.number_input(
        "Add window size (s)",
        min_value=1,
        max_value=600,
        value=15,
        step=1,
        key="hc_settings_add_win",
    )
with a2:
    st.markdown("<div style='height: 1.7rem'></div>", unsafe_allow_html=True)
    if st.button("Add", key="hc_settings_add_btn"):
        try:
            add_window_sec(int(new_win))
        except ValueError as exc:
            st.error(str(exc))
        else:
            log_activity("settings_window_added", detail={"window_sec": int(new_win)})
            st.success(f"Added **{int(new_win)}** s.")
            st.rerun()

if len(windows) <= 1:
    st.info("At least one window size must remain.")
else:
    rem = st.selectbox(
        "Remove window size",
        options=windows,
        key="hc_settings_rem_win",
    )
    if st.button("Remove selected", key="hc_settings_rem_btn"):
        try:
            remove_window_sec(int(rem))
        except ValueError as exc:
            st.error(str(exc))
        else:
            log_activity("settings_window_removed", detail={"window_sec": int(rem)})
            st.success(f"Removed **{int(rem)}** s.")
            st.rerun()

st.markdown("### Reset")
if st.button("Reset all settings to defaults", key="hc_settings_reset"):
    from hc_settings import default_settings

    save_settings(default_settings())
    log_activity("settings_reset", detail={})
    st.success("Settings reset to defaults.")
    st.rerun()
