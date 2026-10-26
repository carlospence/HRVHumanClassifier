"""Admin review: all user tasks and responses vs protocol true labels."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import is_admin, log_activity, require_access  # noqa: E402
from hc_rr import PHASES, TRUE_CLASS_LABELS, load_phase_runs  # noqa: E402
from hc_task import (  # noqa: E402
    delete_task,
    list_all_tasks,
    load_responses,
    load_task,
    responses_vs_truth_rows,
    score_task,
    window_by_id,
)

_CLASS_ORDER = ["paced", "not_paced"]


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


@st.dialog("Window detail", width="large")
def _show_window_dialog(task: dict, row: dict) -> None:
    """Popup with window metadata, true vs human label, and RR plot."""
    wid = str(row.get("window_id") or "")
    window = window_by_id(task, wid) or {}
    true_phase = row.get("true_phase") or window.get("phase")
    true_class = row.get("true_class") or window.get("true_class")
    choice = row.get("choice")
    correct = row.get("correct")
    if correct is None and choice and true_class:
        correct = str(choice) == str(true_class)

    st.markdown(f"### `{wid}`")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Window**")
        st.write(
            f"- Participant: `{window.get('participant') or row.get('participant') or '—'}`  \n"
            f"- Window length: {window.get('window_sec') or task.get('window_sec') or '—'} s  \n"
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
        st.markdown("**Human choice**")
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
        st.write(
            f"Result: **{verdict}**  \n"
            f"Responded: {row.get('responded_at') or '—'}"
        )

    if window.get("rr_ms") and window.get("t_rel_sec"):
        st.plotly_chart(
            _rr_figure(window),
            use_container_width=True,
            key=f"hc_admin_rr_{wid}",
        )
    else:
        st.warning("RR series not stored on this window; cannot plot.")


def _task_participants(task: dict) -> list[str]:
    pids = list(task.get("participants") or [])
    if not pids:
        pids = sorted(
            {
                str(w.get("participant"))
                for w in task.get("windows") or []
                if w.get("participant")
            }
        )
    return sorted(pids)


def _windows_for_participant_phase(
    task: dict, participant: str, phase: str
) -> list[dict]:
    return [
        w
        for w in task.get("windows") or []
        if str(w.get("participant")) == str(participant)
        and str(w.get("phase")) == str(phase)
    ]


def _phase_label_metrics(
    windows: list[dict], responses: dict[str, dict]
) -> dict[str, float | int | None]:
    total = len(windows)
    n_correct = 0
    n_wrong = 0
    n_answered = 0
    for w in windows:
        rec = responses.get(str(w.get("window_id"))) or {}
        choice = rec.get("choice")
        if not choice:
            continue
        n_answered += 1
        true_class = rec.get("true_class") or w.get("true_class")
        ok = rec.get("correct")
        if ok is None and true_class is not None:
            ok = str(choice) == str(true_class)
        if ok:
            n_correct += 1
        else:
            n_wrong += 1
    accuracy = (n_correct / n_answered) if n_answered else None
    return {
        "total_windows": total,
        "answered": n_answered,
        "correct": n_correct,
        "wrong": n_wrong,
        "accuracy": accuracy,
    }


def _window_band_color(rec: dict | None, window: dict) -> str:
    """Shade by human choice: green = paced, red = not paced, gray = unanswered.

    Correctness is shown in the phase metrics (accuracy / correct / wrong).
    """
    del window  # reserved for future true-class overlays
    if not rec or not rec.get("choice"):
        return "rgba(156, 163, 175, 0.35)"
    choice = str(rec.get("choice"))
    if choice == "paced":
        return "rgba(34, 197, 94, 0.35)"
    if choice == "not_paced":
        return "rgba(239, 68, 68, 0.35)"
    return "rgba(156, 163, 175, 0.35)"


def _phase_timeline_figure(
    participant: str,
    phase: str,
    windows: list[dict],
    responses: dict[str, dict],
) -> go.Figure | None:
    runs = [r for r in load_phase_runs(participant) if r.phase == phase]
    if not runs:
        return None

    fig = go.Figure()
    t0 = float(min(float(r.millis_ms[0]) for r in runs if r.millis_ms.size))
    for run in runs:
        ms = run.millis_ms.astype(float)
        rr = run.rr_ms.astype(float)
        t_sec = (ms - t0) / 1000.0
        fig.add_trace(
            go.Scatter(
                x=t_sec,
                y=rr,
                mode="lines",
                line=dict(color="#1a2332", width=1.5, shape="spline"),
                name=f"run {run.phase_run_id}",
                hovertemplate="t=%{x:.2f}s<br>RR=%{y:.0f} ms<extra></extra>",
            )
        )

    for w in windows:
        start = w.get("start_millis")
        end = w.get("end_millis")
        if start is None or end is None:
            continue
        wid = str(w.get("window_id"))
        rec = responses.get(wid)
        color = _window_band_color(rec, w)
        choice = (rec or {}).get("choice")
        true_class = (rec or {}).get("true_class") or w.get("true_class")
        fig.add_vrect(
            x0=(float(start) - t0) / 1000.0,
            x1=(float(end) - t0) / 1000.0,
            fillcolor=color,
            opacity=1.0,
            line_width=0,
            annotation_text="",
            layer="below",
        )
        # Invisible marker at window mid for hover details
        mid = ((float(start) + float(end)) / 2.0 - t0) / 1000.0
        fig.add_trace(
            go.Scatter(
                x=[mid],
                y=[800],
                mode="markers",
                marker=dict(size=8, color="rgba(0,0,0,0)"),
                showlegend=False,
                hovertemplate=(
                    f"window={wid}<br>"
                    f"choice={_class_label(choice)}<br>"
                    f"true={_class_label(true_class)}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        height=360,
        margin=dict(t=40, b=40, l=50, r=20),
        xaxis_title="Time in phase (s)",
        yaxis_title="RR interval (ms)",
        yaxis=dict(range=[400, 1200]),
        title=f"{participant} · {phase}",
        showlegend=False,
    )
    return fig


@st.dialog("Participant phases", width="large")
def _show_participant_dialog(
    task: dict, responses: dict[str, dict], participant: str
) -> None:
    st.markdown(f"### Participant `{participant}`")
    st.caption(
        "Shaded bands are task windows — **green** = human chose paced, "
        "**red** = human chose not paced, **gray** = unanswered. "
        "**Spreadsheet**, protocol chose not paced and plot is expected to be all **red**."
        "**Treatment**, protocol chose paced and plot is expected to be all **green**."
        "**Metrics** below use protocol correctness."
    )
    for phase in PHASES:
        windows = _windows_for_participant_phase(task, participant, phase)
        metrics = _phase_label_metrics(windows, responses)
        st.markdown(f"#### {phase.capitalize()}")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total windows", metrics["total_windows"])
        m2.metric("Correct", metrics["correct"])
        m3.metric("Wrong", metrics["wrong"])
        acc = metrics["accuracy"]
        m4.metric(
            "Accuracy",
            "—" if acc is None else f"{100.0 * float(acc):.1f}%",
        )
        fig = _phase_timeline_figure(participant, phase, windows, responses)
        if fig is None:
            st.warning(f"No RR data for {participant} / {phase}.")
        else:
            st.plotly_chart(
                fig,
                use_container_width=True,
                key=f"hc_admin_phase_{task.get('task_id')}_{participant}_{phase}",
            )


def _confusion_matrix(answered: pd.DataFrame) -> pd.DataFrame:
    """Rows = original (true), columns = human choice; counts of answered windows."""
    labels = [_class_label(c) for c in _CLASS_ORDER]
    cm = pd.crosstab(
        answered["true_class"].map(_class_label),
        answered["choice"].map(_class_label),
    )
    cm = cm.reindex(index=labels, columns=labels, fill_value=0).astype(int)
    cm.index.name = "original (true)"
    cm.columns.name = "human choice"
    return cm


def _accuracy_by_class(answered: pd.DataFrame) -> pd.DataFrame:
    answered = answered.copy()
    answered["correct_num"] = (
        pd.to_numeric(answered["correct"], errors="coerce").fillna(0).astype(float)
    )
    by_true = (
        answered.groupby("true_class", dropna=False)["correct_num"]
        .agg(answered="count", correct="sum")
        .reset_index()
    )
    by_true["answered"] = by_true["answered"].astype(int)
    by_true["correct"] = by_true["correct"].astype(int)
    by_true["wrong"] = by_true["answered"] - by_true["correct"]
    by_true["accuracy_%"] = (
        (100.0 * by_true["correct"] / by_true["answered"]).astype(float).round(1)
    )
    by_true["original (true)"] = by_true["true_class"].map(_class_label)
    return by_true[
        ["original (true)", "answered", "correct", "wrong", "accuracy_%"]
    ]

user = require_access()

if not is_admin():
    st.error("Admin access required. Sign in with an admin code (e.g. `HRVADMIN`).")
    st.stop()

if st.session_state.get("hc_logged_admin") != user["access_code"]:
    log_activity("view_page", detail={"page": "admin_all_tasks"})
    st.session_state["hc_logged_admin"] = user["access_code"]

st.title("Admin · all tasks")
st.caption(
    "Cross-user view (admin only). Regular users only see their own tasks on "
    "**Gold-standard labeling**. Here every task is scored against the original "
    "protocol label (treatment → paced, spreadsheet → not paced)."
)

task_summaries = list_all_tasks()
if not task_summaries:
    st.info("No tasks found yet.")
    st.stop()

# Score every task for the overview table
overview_rows = []
for meta in task_summaries:
    tid = str(meta["task_id"])
    try:
        task = load_task(tid)
    except FileNotFoundError:
        continue
    responses = load_responses(tid)
    score = score_task(task, responses)
    acc = score["accuracy"]
    overview_rows.append(
        {
            "nickname": meta.get("nickname") or tid,
            "task_id": tid,
            "access_code": meta.get("access_code"),
            "name": meta.get("name"),
            "created_at": meta.get("created_at"),
            "status": meta.get("status"),
            "window_sec": meta.get("window_sec"),
            "n_participants": meta.get("n_participants"),
            "n_windows": score["n_windows_total"],
            "answered": score["n_answered"],
            "correct": score["n_correct"],
            "wrong": score["n_wrong"],
            "accuracy": None if acc is None else round(100.0 * acc, 1),
        }
    )

n_tasks = len(overview_rows)
n_completed = sum(1 for r in overview_rows if str(r.get("status") or "") == "completed")
n_raters = len({r.get("access_code") for r in overview_rows if r.get("access_code")})
sum_answered = sum(int(r.get("answered") or 0) for r in overview_rows)
sum_correct = sum(int(r.get("correct") or 0) for r in overview_rows)
sum_wrong = sum(int(r.get("wrong") or 0) for r in overview_rows)
overall_acc = (sum_correct / sum_answered) if sum_answered else None

w1, w2, w3, w4, w5 = st.columns(5)
w1.metric("Tasks", n_tasks)
w2.metric("Completed", n_completed)
w3.metric("Raters", n_raters)
w4.metric("Windows answered", sum_answered)
w5.metric(
    "Overall accuracy",
    "—" if overall_acc is None else f"{100.0 * overall_acc:.1f}%",
    help=f"{sum_correct} correct · {sum_wrong} wrong across all tasks",
)

# Filter by user (access code) or all
user_keys = sorted(
    {
        f"{r.get('access_code') or '—'} · {r.get('name') or '—'}"
        for r in overview_rows
    }
)
st.markdown("### Tasks")
filter_choice = st.selectbox(
    "Filter by user",
    options=["All users"] + user_keys,
    key="hc_admin_user_filter",
    help="Show every task, or only tasks for one access code / name.",
)
if filter_choice == "All users":
    filtered_rows = overview_rows
else:
    filtered_rows = [
        r
        for r in overview_rows
        if f"{r.get('access_code') or '—'} · {r.get('name') or '—'}" == filter_choice
    ]

if not filtered_rows:
    st.info("No tasks for this filter.")
    st.stop()

overview_df = pd.DataFrame(filtered_rows)
st.caption(f"Showing **{len(filtered_rows)}** of **{len(overview_rows)}** tasks.")
st.dataframe(
    overview_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "accuracy": st.column_config.NumberColumn("accuracy %", format="%.1f"),
        "created_at": st.column_config.TextColumn("created_at"),
    },
)

st.markdown("### Task detail — responses vs original result")
label_by_id = {
    (
        f"{r['nickname']} · {r['access_code']} · {r['name']} · "
        f"{r['answered']}/{r['n_windows']} · "
        f"{'—' if r['accuracy'] is None else f'{r['accuracy']}%'}"
    ): r["task_id"]
    for r in filtered_rows
}
pick = st.selectbox("Select task", options=list(label_by_id.keys()), key="hc_admin_pick")
tid = label_by_id[pick]
task = load_task(tid)
responses = load_responses(tid)
score = score_task(task, responses)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Windows", score["n_windows_total"])
m2.metric("Answered", score["n_answered"])
m3.metric("Correct", score["n_correct"])
m4.metric(
    "Accuracy",
    "—" if score["accuracy"] is None else f"{100.0 * score['accuracy']:.1f}%",
)

st.write(
    f"- **Nickname:** {task.get('nickname') or '—'}  \n"
    f"- **Task id:** `{tid}`  \n"
    f"- **Rater:** {task.get('name')} (`{task.get('access_code')}`)  \n"
    f"- **Window:** {task.get('window_sec')} s · "
    f"**Participants:** {task.get('n_participants') or len(task.get('participants') or [])} · "
    f"**Status:** {task.get('status')}"
)

with st.expander("Delete this task", expanded=False):
    st.warning(
        "Permanently deletes this labeling task and all of its responses. "
        "This cannot be undone."
    )
    confirm = st.text_input(
        "Type the task id to confirm delete",
        key=f"hc_admin_del_confirm_{tid}",
    )
    if st.button(
        "Delete task",
        type="primary",
        key=f"hc_admin_del_btn_{tid}",
        disabled=confirm.strip() != tid,
    ):
        try:
            delete_task(tid)
        except FileNotFoundError:
            st.error("Task not found (already deleted?).")
        else:
            log_activity(
                "admin_delete_task",
                detail={
                    "task_id": tid,
                    "access_code": task.get("access_code"),
                    "name": task.get("name"),
                },
            )
            st.success(f"Deleted task `{tid}`.")
            st.rerun()

st.markdown("#### Participants")
st.caption("Open a participant to see spreadsheet and treatment RR with labeled windows.")
pids = _task_participants(task)
if not pids:
    st.info("No participants on this task.")
else:
    n_cols = min(6, len(pids))
    for row_start in range(0, len(pids), n_cols):
        cols = st.columns(n_cols)
        for j, pid in enumerate(pids[row_start : row_start + n_cols]):
            with cols[j]:
                if st.button(pid, use_container_width=True, key=f"hc_admin_pid_{tid}_{pid}"):
                    _show_participant_dialog(task, responses, pid)

detail_rows = responses_vs_truth_rows(task, responses)
detail_df = pd.DataFrame(detail_rows)
if not detail_df.empty:
    detail_df["true_class_label"] = detail_df["true_class"].map(
        lambda c: TRUE_CLASS_LABELS.get(str(c), c) if c is not None else None
    )
    detail_df["choice_label"] = detail_df["choice"].map(
        lambda c: TRUE_CLASS_LABELS.get(str(c), c) if c is not None else None
    )
    show = detail_df[
        [
            "presentation_index",
            "window_id",
            "participant",
            "true_phase",
            "true_class_label",
            "choice_label",
            "correct",
            "responded_at",
            "start_millis",
            "end_millis",
        ]
    ].rename(
        columns={
            "true_class_label": "original (true)",
            "choice_label": "human choice",
        }
    )
    st.caption("Click a row to open the window detail (true phase, human choice, RR plot).")
    table_event = st.dataframe(
        show,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"hc_admin_windows_{tid}",
    )
    selected_rows = []
    if table_event and getattr(table_event, "selection", None) is not None:
        selected_rows = list(table_event.selection.rows or [])
    if selected_rows:
        sel_i = int(selected_rows[0])
        if 0 <= sel_i < len(detail_df):
            _show_window_dialog(task, detail_df.iloc[sel_i].to_dict())

    answered = detail_df[detail_df["choice"].notna()].copy()
    if not answered.empty:
        st.markdown("#### Scoring views")
        st.caption(
            "**answered** = number of labeled windows with that original class. "
            "Confusion matrix: rows = original protocol label, columns = human choice."
        )
        view_mode = st.radio(
            "Show as",
            options=["Table", "Chart"],
            horizontal=True,
            key="hc_admin_score_view",
        )
        by_true = _accuracy_by_class(answered)
        cm = _confusion_matrix(answered)

        c_acc, c_cm = st.columns(2)
        with c_acc:
            st.markdown("**Accuracy by original class**")
            if view_mode == "Table":
                st.dataframe(by_true, use_container_width=True, hide_index=True)
            else:
                fig_acc = px.bar(
                    by_true,
                    x="original (true)",
                    y="accuracy_%",
                    text="accuracy_%",
                    color="original (true)",
                    labels={"accuracy_%": "Accuracy (%)"},
                    range_y=[0, 100],
                )
                fig_acc.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig_acc.update_layout(
                    showlegend=False,
                    height=360,
                    margin=dict(t=40, b=40, l=40, r=20),
                    yaxis_title="Accuracy (%)",
                )
                st.plotly_chart(fig_acc, use_container_width=True)
                st.caption(
                    "Per class: "
                    + "; ".join(
                        f"{r['original (true)']}: {int(r['correct'])}/{int(r['answered'])}"
                        for _, r in by_true.iterrows()
                    )
                )

        with c_cm:
            st.markdown("**Confusion matrix**")
            if view_mode == "Table":
                st.dataframe(cm, use_container_width=True)
            else:
                fig_cm = go.Figure(
                    data=go.Heatmap(
                        z=cm.values,
                        x=list(cm.columns),
                        y=list(cm.index),
                        colorscale="Teal",
                        text=cm.values,
                        texttemplate="%{text}",
                        hovertemplate=(
                            "Original: %{y}<br>Human: %{x}<br>Count: %{z}<extra></extra>"
                        ),
                        colorbar=dict(title="count"),
                    )
                )
                fig_cm.update_layout(
                    height=360,
                    margin=dict(t=40, b=40, l=40, r=20),
                    xaxis_title="Human choice",
                    yaxis_title="Original (true)",
                    yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig_cm, use_container_width=True)

    csv = show.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download this task CSV",
        data=csv,
        file_name=f"{tid}_responses_vs_truth.csv",
        mime="text/csv",
        key="hc_admin_dl",
    )
else:
    st.info("No windows in this task.")
