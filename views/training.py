"""Practice training sessions with randomized RR windows and immediate feedback."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import log_activity, require_access  # noqa: E402
from hc_rr import TRUE_CLASS_LABELS  # noqa: E402
from hc_settings import get_window_secs  # noqa: E402
from hc_train import (  # noqa: E402
    count_sessions_for_user,
    create_training_session,
    default_train_nickname,
    delete_session,
    list_sessions_for_user,
    load_first_responses,
    load_owned_session,
    load_responses,
    max_sessions_per_user,
    samples_per_phase,
    save_session,
    score_session,
    set_session_nickname,
    upsert_response,
    window_by_id,
)

user = require_access()
if st.session_state.get("hc_logged_train") != user["access_code"]:
    log_activity("view_page", detail={"page": "training"})
    st.session_state["hc_logged_train"] = user["access_code"]

_MAX_SESSIONS = max_sessions_per_user()
_WINDOW_SECS = list(get_window_secs())

st.title("Training")
st.caption(
    "Practice paced vs not-paced on highly randomized RR windows. "
    f"You may keep up to **{_MAX_SESSIONS}** training sessions."
)

st.markdown(
    """
    <style>
      div[class*="st-key-hc_train_actions"] div.stButton > button {
        min-height: 3.5rem !important;
        font-size: 1.1rem !important;
        font-weight: 600 !important;
      }
      /* Paced only — widget key wrapper */
      div[class*="st-key-hc_train_paced"] button,
      div[class*="st-key-hc_train_paced"] button[kind="primary"],
      div[class*="st-key-hc_train_paced"] [data-testid="stBaseButton-primary"] {
        background-color: #1b8f5a !important;
        background-image: none !important;
        border: 1px solid #167a4c !important;
        color: #ffffff !important;
      }
      div[class*="st-key-hc_train_paced"] button:hover,
      div[class*="st-key-hc_train_paced"] button:focus,
      div[class*="st-key-hc_train_paced"] button:active,
      div[class*="st-key-hc_train_paced"] [data-testid="stBaseButton-primary"]:hover {
        background-color: #147548 !important;
        background-image: none !important;
        border-color: #11663e !important;
        color: #ffffff !important;
      }
      div[class*="st-key-hc_train_paced"] button p,
      div[class*="st-key-hc_train_paced"] button span {
        color: #ffffff !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def _active_session() -> dict | None:
    sid = st.session_state.get("hc_active_train_id")
    if not sid:
        return None
    try:
        return load_owned_session(str(sid), user["access_code"])
    except FileNotFoundError:
        st.session_state.pop("hc_active_train_id", None)
        return None
    except PermissionError:
        st.session_state.pop("hc_active_train_id", None)
        st.warning("That training session belongs to another user and was closed.")
        return None


def _rr_figure(window: dict) -> go.Figure:
    t = window.get("t_rel_sec") or []
    rr = window.get("rr_ms") or []
    fig = go.Figure(
        data=[
            go.Scatter(
                x=t,
                y=rr,
                mode="lines+markers",
                line=dict(color="#0d7a6f", width=2, shape="spline"),
                marker=dict(size=7, color="#1a2332"),
                name="RR",
            )
        ]
    )
    fig.update_layout(
        height=420,
        margin=dict(t=30, b=40, l=50, r=20),
        xaxis_title="Time in window (s)",
        yaxis_title="RR interval (ms)",
        yaxis=dict(range=[400, 1200]),
        title=f"{int(window.get('window_sec', 0))} s window · {int(window.get('n_beats', 0))} beats",
    )
    return fig


session = _active_session()
n_existing = count_sessions_for_user(user["access_code"])

with st.sidebar:
    st.subheader("Your training sessions")
    st.caption(f"{n_existing}/{_MAX_SESSIONS} used · `{user['access_code']}`")
    existing = list_sessions_for_user(user["access_code"])
    if existing:
        id_by_label = {}
        for e in existing:
            sid_e = str(e["session_id"])
            err = score_session(
                {"session_id": sid_e, "n_windows_total": e.get("n_windows_total")},
                first_responses=load_first_responses(sid_e),
            ).get("error_rate")
            err_txt = "—" if err is None else f"{100.0 * err:.0f}% err"
            label = (
                f"{e['nickname']} · {e['window_sec']}s · {e['status']} · "
                f"n={e['n_windows_total']} · {err_txt}"
            )
            id_by_label[label] = sid_e
        labels = list(id_by_label.keys())
        pick = st.selectbox(
            "Resume session", options=["(new session)"] + labels, key="hc_train_resume"
        )
        if pick != "(new session)":
            sid = id_by_label[pick]
            if st.button("Open selected session", key="hc_train_open"):
                try:
                    load_owned_session(str(sid), user["access_code"])
                except (FileNotFoundError, PermissionError):
                    st.error("Cannot open that session.")
                else:
                    st.session_state["hc_active_train_id"] = sid
                    st.session_state.pop("hc_train_feedback", None)
                    log_activity("train_resume", detail={"session_id": sid})
                    st.rerun()
            if st.button("Delete selected session", key="hc_train_delete"):
                try:
                    delete_session(str(sid), user["access_code"])
                except (FileNotFoundError, PermissionError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    if st.session_state.get("hc_active_train_id") == sid:
                        st.session_state.pop("hc_active_train_id", None)
                    log_activity("train_deleted", detail={"session_id": sid})
                    st.success("Session deleted.")
                    st.rerun()
    else:
        st.caption("No training sessions yet.")

# ---------------------------------------------------------------------------
# Create new session
# ---------------------------------------------------------------------------
if session is None:
    st.markdown("### Start a training session")
    if n_existing >= _MAX_SESSIONS:
        st.warning(
            f"You already have {_MAX_SESSIONS} sessions. "
            "Delete one from the sidebar to create another."
        )
        st.stop()

    if not _WINDOW_SECS:
        st.error("No window sizes configured. Ask an admin to set them in Admin · settings.")
        st.stop()

    window_sec = st.selectbox(
        "Window length (s)",
        options=_WINDOW_SECS,
        index=0,
        key="hc_train_new_window",
        help="Sample counts per phase follow admin settings (threshold-based).",
    )
    win_i = int(window_sec)
    # Keep default nickname in sync with the selected window length.
    suggested_nick = default_train_nickname(window_sec=win_i)
    if st.session_state.get("hc_train_nick_for_window") != win_i:
        st.session_state["hc_train_new_nickname"] = suggested_nick
        st.session_state["hc_train_nick_for_window"] = win_i
    nickname_in = st.text_input(
        "Session nickname",
        max_chars=80,
        key="hc_train_new_nickname",
    )
    n_phase = samples_per_phase(win_i)
    st.info(
        f"This session will draw **{n_phase}** random windows from **spreadsheet** and "
        f"**{n_phase}** from **treatment** (total **{2 * n_phase}**), "
        "from random participants and random positions within each phase, then shuffle them."
    )

    if st.button("Create training session", type="primary", key="hc_train_create"):
        with st.spinner("Sampling randomized windows…"):
            try:
                created = create_training_session(
                    access_code=user["access_code"],
                    name=user["name"],
                    window_sec=win_i,
                    nickname=nickname_in,
                )
            except ValueError as exc:
                st.error(str(exc))
                st.stop()
        st.session_state["hc_active_train_id"] = created["session_id"]
        st.session_state.pop("hc_train_feedback", None)
        log_activity(
            "train_created",
            detail={
                "session_id": created["session_id"],
                "window_sec": created["window_sec"],
                "n_windows": created["n_windows_total"],
                "samples_per_phase": created["samples_per_phase"],
            },
        )
        st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Active session
# ---------------------------------------------------------------------------
nick_now = str(session.get("nickname") or session["session_id"])
st.markdown(f"### {nick_now}")
st.caption(
    f"Session id: `{session['session_id']}` · "
    f"{session['window_sec']} s · "
    f"{session.get('samples_per_phase')} per phase · "
    f"seed `{session.get('seed')}`"
)
with st.expander("Rename session", expanded=False):
    new_nick = st.text_input(
        "Nickname",
        value=nick_now,
        max_chars=80,
        key=f"hc_train_rename_{session['session_id']}",
    )
    if st.button("Save nickname", key=f"hc_train_save_nick_{session['session_id']}"):
        try:
            session = set_session_nickname(session["session_id"], new_nick)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success(f"Renamed to **{session['nickname']}**")
            st.rerun()

responses = load_responses(session["session_id"])
first_responses = load_first_responses(session["session_id"])
score = score_session(session, responses, first_responses=first_responses)
order = list(session.get("presentation_order") or [])
n_total = int(session.get("n_windows_total") or len(order) or 1)
idx = int(session.get("current_index") or 0)
if idx < 0:
    idx = 0
if idx >= len(order) and order:
    idx = len(order) - 1
    session["current_index"] = idx
    save_session(session)

n_done = score["n_answered"]
n_remaining = max(0, n_total - n_done)
pct_done = 100.0 * n_done / max(n_total, 1)
err = score.get("error_rate")

st.markdown("#### Progress")
st.progress(min(1.0, n_done / max(n_total, 1)))
st.caption(
    f"**{n_done}/{n_total}** answered ({n_remaining} remaining) · "
    f"**{pct_done:.1f}%** · "
    f"First-try wrong: **{score['n_first_wrong']}** / **{score['n_first_answered']}**"
    + (
        f" · **Error rate: {100.0 * err:.1f}%**"
        if err is not None
        else ""
    )
    + (
        f" · First-try accuracy: **{100.0 * score['first_accuracy']:.1f}%**"
        if score.get("first_accuracy") is not None
        else ""
    )
)
st.caption(
    "Error rate uses only the **first** answer on each window "
    "(retries after feedback do not change it)."
)

if not order:
    st.error("This session has no windows.")
    st.stop()

# Session complete
if n_done >= n_total and session.get("status") != "completed":
    session["status"] = "completed"
    save_session(session)

if session.get("status") == "completed" and n_done >= n_total:
    st.success(
        f"Training complete — first-try error rate "
        f"**{100.0 * (score.get('error_rate') or 0):.1f}%** "
        f"({score['n_first_wrong']}/{score['n_first_answered']} wrong on first answer) · "
        f"first-try accuracy **{100.0 * (score.get('first_accuracy') or 0):.1f}%**."
    )
    if st.button("Close session", key="hc_train_close_done"):
        st.session_state.pop("hc_active_train_id", None)
        st.session_state.pop("hc_train_feedback", None)
        st.rerun()
    # Still allow review of last window below

window_id = order[idx]
window = window_by_id(session, window_id)
if window is None:
    st.error(f"Missing window {window_id}")
    st.stop()

st.caption(f"Window **{idx + 1} / {n_total}**")

_CHART_WIDTH_FRACS = {
    "XS": 0.32,
    "Small": 0.48,
    "Medium": 0.72,
    "Full width": 1.0,
}
if "hc_chart_width" not in st.session_state:
    st.session_state["hc_chart_width"] = "Medium"
elif st.session_state["hc_chart_width"] not in _CHART_WIDTH_FRACS:
    st.session_state["hc_chart_width"] = "Medium"
chart_width = st.select_slider(
    "Chart width",
    options=list(_CHART_WIDTH_FRACS.keys()),
    key="hc_chart_width",
    help="Desktop layout: narrow the chart and keep it centered (4 sizes).",
)
frac = float(_CHART_WIDTH_FRACS[chart_width])
fig = _rr_figure(window)
if frac >= 0.999:
    st.plotly_chart(
        fig, use_container_width=True, key=f"hc_train_rr_{window_id}"
    )
else:
    side = (1.0 - frac) / 2.0
    _left, mid, _right = st.columns([side, frac, side])
    with mid:
        st.plotly_chart(
            fig, use_container_width=True, key=f"hc_train_rr_{window_id}"
        )

feedback = st.session_state.get("hc_train_feedback")
if feedback and feedback.get("window_id") == window_id:
    if feedback.get("correct"):
        st.success(
            f"Correct — true class was **{TRUE_CLASS_LABELS.get(feedback.get('true_class'), feedback.get('true_class'))}** "
            f"(phase: `{feedback.get('true_phase')}`)."
        )
    else:
        st.error(
            f"Incorrect — you chose **{TRUE_CLASS_LABELS.get(feedback.get('choice'), feedback.get('choice'))}**; "
            f"true class was **{TRUE_CLASS_LABELS.get(feedback.get('true_class'), feedback.get('true_class'))}** "
            f"(phase: `{feedback.get('true_phase')}`)."
        )

existing = responses.get(window_id)
if existing and not (feedback and feedback.get("window_id") == window_id):
    st.info(
        f"Saved answer: **{TRUE_CLASS_LABELS.get(existing.get('choice'), existing.get('choice'))}** "
        f"({'correct' if existing.get('correct') else 'incorrect'})"
    )


def _save_choice(choice: str) -> None:
    true_class = str(window.get("true_class"))
    correct = bool(choice == true_class)
    rec = {
        "response_id": f"{session['session_id']}_{window_id}_{len(responses)+1}",
        "session_id": session["session_id"],
        "access_code": user["access_code"],
        "name": user["name"],
        "window_id": window_id,
        "presentation_index": int(idx),
        "choice": choice,
        "true_phase": window.get("phase"),
        "true_class": true_class,
        "correct": correct,
        "participant": window.get("participant"),
        "start_millis": window.get("start_millis"),
        "end_millis": window.get("end_millis"),
        "responded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    upsert_response(session["session_id"], rec)
    log_activity(
        "train_response_saved",
        detail={
            "session_id": session["session_id"],
            "window_id": window_id,
            "choice": choice,
            "correct": correct,
        },
    )
    st.session_state["hc_train_feedback"] = {
        "window_id": window_id,
        "choice": choice,
        "true_class": true_class,
        "true_phase": window.get("phase"),
        "correct": correct,
    }
    # Stay on this window so feedback is visible; user advances with Next.
    if len(responses) + (0 if window_id in responses else 1) >= n_total:
        session["status"] = "completed"
        save_session(session)


try:
    _train_actions = st.container(key="hc_train_actions")
except TypeError:
    _train_actions = st.container()
with _train_actions:
    c_prev, c_paced, c_not, c_next = st.columns([1, 2, 2, 1])
    with c_prev:
        if st.button("Previous", use_container_width=True, key="hc_train_prev"):
            if idx > 0:
                session["current_index"] = idx - 1
                save_session(session)
                st.session_state.pop("hc_train_feedback", None)
                st.rerun()
    with c_paced:
        if st.button(
            "Paced", type="primary", use_container_width=True, key="hc_train_paced"
        ):
            _save_choice("paced")
            st.rerun()
    with c_not:
        if st.button(
            "Not paced", type="primary", use_container_width=True, key="hc_train_not"
        ):
            _save_choice("not_paced")
            st.rerun()
    with c_next:
        if st.button("Next", use_container_width=True, key="hc_train_next"):
            if idx + 1 < len(order):
                session["current_index"] = idx + 1
                save_session(session)
                st.session_state.pop("hc_train_feedback", None)
                st.rerun()

if st.sidebar.button("Close session (keep progress)", key="hc_train_close"):
    st.session_state.pop("hc_active_train_id", None)
    st.session_state.pop("hc_train_feedback", None)
    st.rerun()
