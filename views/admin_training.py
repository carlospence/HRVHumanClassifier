"""Admin review: all users' training sessions and first-try error rates."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import is_admin, log_activity, require_access  # noqa: E402
from hc_rr import TRUE_CLASS_LABELS  # noqa: E402
from hc_train import (  # noqa: E402
    delete_session,
    list_all_sessions,
    load_first_responses,
    load_responses,
    load_session,
    score_session,
    window_by_id,
)


def _class_label(code: object) -> str:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return "—"
    return TRUE_CLASS_LABELS.get(str(code), str(code))


def _badge(text: str, *, color: str) -> str:
    """Inline colored badge HTML for dialog labels."""
    palette = {
        "blue": ("#1d4ed8", "#dbeafe"),
        "green": ("#15803d", "#dcfce7"),
        "red": ("#b91c1c", "#fee2e2"),
        "gray": ("#4b5563", "#f3f4f6"),
    }
    fg, bg = palette.get(color, palette["gray"])
    safe = (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return (
        f'<span style="display:inline-block;padding:0.2rem 0.65rem;'
        f"border-radius:999px;font-size:0.9rem;font-weight:600;"
        f'color:{fg};background:{bg};">{safe}</span>'
    )


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


def _choice_block(title: str, choice: object, correct: object, responded_at: object) -> None:
    st.markdown(f"**{title}**")
    if not choice:
        choice_badge = _badge("— (unanswered)", color="gray")
        verdict = "—"
    elif correct:
        choice_badge = _badge(_class_label(choice), color="green")
        verdict = "correct"
    else:
        choice_badge = _badge(_class_label(choice), color="red")
        verdict = "incorrect"
    st.markdown("Choice: " + choice_badge, unsafe_allow_html=True)
    st.write(f"Result: **{verdict}**  \nResponded: {responded_at or '—'}")


@st.dialog("Window detail", width="large")
def _show_window_dialog(session: dict, row: dict) -> None:
    """Popup with window metadata, true vs first/latest answers, and RR plot."""
    wid = str(row.get("window_id") or "")
    window = window_by_id(session, wid) or {}
    true_phase = row.get("true_phase") or window.get("phase")
    true_class = row.get("true_class") or window.get("true_class")

    st.markdown(f"### `{wid}`")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("**Window**")
        st.write(
            f"- Participant: `{window.get('participant') or row.get('participant') or '—'}`  \n"
            f"- Window length: {window.get('window_sec') or session.get('window_sec') or '—'} s  \n"
            f"- Beats: {window.get('n_beats') or '—'}  \n"
            f"- Presentation index: {row.get('presentation_index')}  \n"
            f"- Start ms: {row.get('start_millis') or window.get('start_millis')}  \n"
            f"- End ms: {row.get('end_millis') or window.get('end_millis')}"
        )
    with c2:
        st.markdown("**True phase (protocol)**")
        st.write(f"Phase: **{true_phase or '—'}**")
        st.markdown(
            "Class: " + _badge(_class_label(true_class), color="blue"),
            unsafe_allow_html=True,
        )
    with c3:
        _choice_block(
            "First answer (error rate)",
            row.get("first_choice"),
            row.get("first_correct"),
            row.get("first_responded_at"),
        )
    with c4:
        _choice_block(
            "Latest answer",
            row.get("latest_choice"),
            row.get("latest_correct"),
            row.get("latest_responded_at"),
        )

    if window.get("rr_ms") and window.get("t_rel_sec"):
        st.plotly_chart(
            _rr_figure(window),
            use_container_width=True,
            key=f"hc_admin_train_rr_{wid}",
        )
    else:
        st.warning("RR series not stored on this window; cannot plot.")

user = require_access()
if not is_admin():
    st.error("Admin access required.")
    st.stop()

if st.session_state.get("hc_logged_admin_train") != user["access_code"]:
    log_activity("view_page", detail={"page": "admin_training"})
    st.session_state["hc_logged_admin_train"] = user["access_code"]

st.title("Admin · training")
st.caption(
    "All training sessions across users. **Error rate** is based on each "
    "window’s **first** answer only (before any corrected retry after feedback)."
)

summaries = list_all_sessions()
if not summaries:
    st.info("No training sessions found yet.")
    st.stop()

overview_rows = []
for meta in summaries:
    sid = str(meta["session_id"])
    try:
        session = load_session(sid)
    except FileNotFoundError:
        continue
    score = score_session(
        session,
        load_responses(sid),
        first_responses=load_first_responses(sid),
    )
    err = score.get("error_rate")
    first_acc = score.get("first_accuracy")
    overview_rows.append(
        {
            "nickname": meta.get("nickname") or sid,
            "session_id": sid,
            "access_code": meta.get("access_code"),
            "name": meta.get("name"),
            "created_at": meta.get("created_at"),
            "status": meta.get("status"),
            "window_sec": meta.get("window_sec"),
            "n_windows": score["n_windows_total"],
            "first_answered": score["n_first_answered"],
            "first_wrong": score["n_first_wrong"],
            "first_correct": score["n_first_correct"],
            "error_rate_%": None if err is None else round(100.0 * err, 1),
            "first_accuracy_%": (
                None if first_acc is None else round(100.0 * first_acc, 1)
            ),
        }
    )

n_sessions = len(overview_rows)
n_completed = sum(
    1 for r in overview_rows if str(r.get("status") or "") == "completed"
)
n_raters = len({r.get("access_code") for r in overview_rows if r.get("access_code")})
sum_first = sum(int(r.get("first_answered") or 0) for r in overview_rows)
sum_wrong = sum(int(r.get("first_wrong") or 0) for r in overview_rows)
sum_correct = sum(int(r.get("first_correct") or 0) for r in overview_rows)
overall_err = (sum_wrong / sum_first) if sum_first else None
overall_first_acc = (sum_correct / sum_first) if sum_first else None

w1, w2, w3, w4, w5 = st.columns(5)
w1.metric("Sessions", n_sessions)
w2.metric("Completed", n_completed)
w3.metric("Raters", n_raters)
w4.metric("First answers", sum_first)
w5.metric(
    "Overall error rate",
    "—" if overall_err is None else f"{100.0 * overall_err:.1f}%",
    help=(
        f"{sum_wrong} first-try wrong · {sum_correct} first-try correct"
        + (
            f" · first accuracy {100.0 * overall_first_acc:.1f}%"
            if overall_first_acc is not None
            else ""
        )
    ),
)

user_keys = sorted(
    {
        f"{r.get('access_code') or '—'} · {r.get('name') or '—'}"
        for r in overview_rows
    }
)
st.markdown("### Sessions")
filter_choice = st.selectbox(
    "Filter by user",
    options=["All users"] + user_keys,
    key="hc_admin_train_user_filter",
)
if filter_choice == "All users":
    filtered = overview_rows
else:
    filtered = [
        r
        for r in overview_rows
        if f"{r.get('access_code') or '—'} · {r.get('name') or '—'}" == filter_choice
    ]

if not filtered:
    st.info("No training sessions for this filter.")
    st.stop()

st.caption(f"Showing **{len(filtered)}** of **{len(overview_rows)}** sessions.")
st.dataframe(
    pd.DataFrame(filtered),
    use_container_width=True,
    hide_index=True,
    column_config={
        "error_rate_%": st.column_config.NumberColumn("error rate %", format="%.1f"),
        "first_accuracy_%": st.column_config.NumberColumn(
            "first accuracy %", format="%.1f"
        ),
    },
)

# Per-user summary when filtered or always show aggregate by user
st.markdown("### Error rate by user")
by_user = (
    pd.DataFrame(filtered)
    .groupby(["access_code", "name"], dropna=False)
    .agg(
        sessions=("session_id", "count"),
        first_answered=("first_answered", "sum"),
        first_wrong=("first_wrong", "sum"),
        first_correct=("first_correct", "sum"),
    )
    .reset_index()
)
by_user["error_rate_%"] = by_user.apply(
    lambda r: (
        round(100.0 * r["first_wrong"] / r["first_answered"], 1)
        if r["first_answered"]
        else None
    ),
    axis=1,
)
st.dataframe(by_user, use_container_width=True, hide_index=True)

st.markdown("### Session detail")
label_by_id = {
    (
        f"{r['nickname']} · {r['access_code']} · {r['name']} · "
        f"err={r['error_rate_%'] if r['error_rate_%'] is not None else '—'}%"
    ): r["session_id"]
    for r in filtered
}
pick = st.selectbox("Select session", options=list(label_by_id.keys()), key="hc_admin_train_pick")
sid = label_by_id[pick]
session = load_session(sid)
first = load_first_responses(sid)
latest = load_responses(sid)
score = score_session(session, latest, first_responses=first)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Windows", score["n_windows_total"])
m2.metric("First answered", score["n_first_answered"])
m3.metric("First wrong", score["n_first_wrong"])
m4.metric(
    "Error rate",
    "—" if score["error_rate"] is None else f"{100.0 * score['error_rate']:.1f}%",
)

st.write(
    f"- **Nickname:** {session.get('nickname') or '—'}  \n"
    f"- **Session id:** `{sid}`  \n"
    f"- **Rater:** {session.get('name')} (`{session.get('access_code')}`)  \n"
    f"- **Window:** {session.get('window_sec')} s · "
    f"**Status:** {session.get('status')} · "
    f"**Seed:** `{session.get('seed')}`"
)

with st.expander("Delete this training session", expanded=False):
    st.warning(
        "Permanently deletes this training session and all of its responses. "
        "This cannot be undone."
    )
    confirm = st.text_input(
        "Type the session id to confirm delete",
        key=f"hc_admin_train_del_confirm_{sid}",
    )
    if st.button(
        "Delete session",
        type="primary",
        key=f"hc_admin_train_del_btn_{sid}",
        disabled=confirm.strip() != sid,
    ):
        try:
            delete_session(sid)
        except FileNotFoundError:
            st.error("Session not found (already deleted?).")
        else:
            log_activity(
                "admin_delete_training",
                detail={
                    "session_id": sid,
                    "access_code": session.get("access_code"),
                    "name": session.get("name"),
                },
            )
            st.success(f"Deleted session `{sid}`.")
            st.rerun()

detail_rows = []
for i, wid in enumerate(session.get("presentation_order") or []):
    w = window_by_id(session, wid) or {}
    fr = first.get(wid) or {}
    lr = latest.get(wid) or {}
    detail_rows.append(
        {
            "presentation_index": i,
            "window_id": wid,
            "participant": w.get("participant"),
            "true_phase": w.get("phase") or fr.get("true_phase"),
            "true_class": w.get("true_class") or fr.get("true_class"),
            "first_choice": fr.get("choice"),
            "first_correct": fr.get("correct"),
            "latest_choice": lr.get("choice"),
            "latest_correct": lr.get("correct"),
            "first_responded_at": fr.get("responded_at"),
            "latest_responded_at": lr.get("responded_at"),
            "start_millis": w.get("start_millis"),
            "end_millis": w.get("end_millis"),
        }
    )

if detail_rows:
    detail_df = pd.DataFrame(detail_rows)
    detail_df["true_class_label"] = detail_df["true_class"].map(
        lambda c: TRUE_CLASS_LABELS.get(str(c), c) if c is not None else None
    )
    detail_df["first_choice_label"] = detail_df["first_choice"].map(
        lambda c: TRUE_CLASS_LABELS.get(str(c), c) if c is not None else None
    )
    detail_df["latest_choice_label"] = detail_df["latest_choice"].map(
        lambda c: TRUE_CLASS_LABELS.get(str(c), c) if c is not None else None
    )
    show = detail_df[
        [
            "presentation_index",
            "window_id",
            "participant",
            "true_phase",
            "true_class_label",
            "first_choice_label",
            "first_correct",
            "latest_choice_label",
            "latest_correct",
            "first_responded_at",
        ]
    ].rename(
        columns={
            "true_class_label": "original (true)",
            "first_choice_label": "first choice",
            "latest_choice_label": "latest choice",
        }
    )
    st.caption(
        "Click a row to open the window detail (true phase, first/latest answers, RR plot)."
    )
    table_event = st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"hc_admin_train_windows_{sid}",
    )
    selected_rows = []
    if table_event and getattr(table_event, "selection", None) is not None:
        selected_rows = list(table_event.selection.rows or [])
    if selected_rows:
        sel_i = int(selected_rows[0])
        if 0 <= sel_i < len(detail_df):
            _show_window_dialog(session, detail_df.iloc[sel_i].to_dict())

    csv = detail_df[
        [
            "presentation_index",
            "window_id",
            "participant",
            "true_phase",
            "true_class",
            "first_choice",
            "first_correct",
            "latest_choice",
            "latest_correct",
            "first_responded_at",
            "latest_responded_at",
            "start_millis",
            "end_millis",
        ]
    ].to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download session CSV",
        data=csv,
        file_name=f"{sid}_training_first_answers.csv",
        mime="text/csv",
        key="hc_admin_train_dl",
    )
else:
    st.info("No windows in this session.")
