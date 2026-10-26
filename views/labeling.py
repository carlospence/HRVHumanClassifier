"""Gold-standard RR window labeling (self-contained; no parent-repo imports)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import is_admin, log_activity, require_access  # noqa: E402
from hc_rr import TRUE_CLASS_LABELS, list_participants  # noqa: E402
from hc_settings import get_window_secs  # noqa: E402
from hc_task import (  # noqa: E402
    build_task_plan,
    create_task,
    default_nickname,
    indices_for_cohort,
    list_tasks_for_user,
    load_owned_task,
    load_responses,
    save_task,
    set_task_nickname,
    upsert_response,
    window_by_id,
)

user = require_access()
if st.session_state.get("hc_logged_label") != user["access_code"]:
    log_activity("view_page", detail={"page": "gold_standard_labeling"})
    st.session_state["hc_logged_label"] = user["access_code"]

st.title("Gold-standard labeling")
st.caption(
    "Classify each RR window as **Paced** (treatment) or **Not paced** (spreadsheet). "
    "You only see and edit **your own** tasks."
)

st.markdown(
    """
    <style>
      /* Taller only for the four labeling action keys */
      div[class*="st-key-hc_paced"] button,
      div[class*="st-key-hc_not"] button,
      div[class*="st-key-hc_prev"] button,
      div[class*="st-key-hc_next"] button {
        min-height: 3.5rem !important;
        font-size: 1.1rem !important;
        font-weight: 600 !important;
        padding-top: 0.65rem !important;
        padding-bottom: 0.65rem !important;
      }
      /* Paced only — widget key wrapper (st-key-hc_paced) */
      div[class*="st-key-hc_paced"] button,
      div[class*="st-key-hc_paced"] button[kind="primary"],
      div[class*="st-key-hc_paced"] [data-testid="stBaseButton-primary"] {
        background-color: #1b8f5a !important;
        background-image: none !important;
        border: 1px solid #167a4c !important;
        color: #ffffff !important;
      }
      div[class*="st-key-hc_paced"] button:hover,
      div[class*="st-key-hc_paced"] button:focus,
      div[class*="st-key-hc_paced"] button:active,
      div[class*="st-key-hc_paced"] button:focus-visible,
      div[class*="st-key-hc_paced"] [data-testid="stBaseButton-primary"]:hover {
        background-color: #147548 !important;
        background-image: none !important;
        border-color: #11663e !important;
        color: #ffffff !important;
      }
      div[class*="st-key-hc_paced"] button p,
      div[class*="st-key-hc_paced"] button span,
      div[class*="st-key-hc_paced"] [data-testid="stBaseButton-primary"] p {
        color: #ffffff !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def _active_task() -> dict | None:
    tid = st.session_state.get("hc_active_task_id")
    if not tid:
        return None
    try:
        return load_owned_task(str(tid), user["access_code"])
    except FileNotFoundError:
        st.session_state.pop("hc_active_task_id", None)
        return None
    except PermissionError:
        st.session_state.pop("hc_active_task_id", None)
        st.warning("That task belongs to another user and was closed.")
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


# ---------------------------------------------------------------------------
# Task picker / creator
# ---------------------------------------------------------------------------
task = _active_task()

with st.sidebar:
    st.subheader("Your tasks")
    st.caption(f"Only tasks for `{user['access_code']}`")
    existing = list_tasks_for_user(user["access_code"])
    if existing:
        id_by_label = {
            f"{e['nickname']} · {e['window_sec']}s · {e['status']} · n={e['n_windows_total']}": e[
                "task_id"
            ]
            for e in existing
        }
        labels = list(id_by_label.keys())
        pick = st.selectbox("Resume task", options=["(new task)"] + labels, key="hc_resume")
        if pick != "(new task)":
            tid = id_by_label[pick]
            if st.button("Open selected task", key="hc_open_task"):
                try:
                    load_owned_task(str(tid), user["access_code"])
                except (FileNotFoundError, PermissionError):
                    st.error("Cannot open that task.")
                else:
                    st.session_state["hc_active_task_id"] = tid
                    log_activity("task_resume", detail={"task_id": tid})
                    st.rerun()
    else:
        st.caption("No previous tasks yet.")

    if is_admin():
        st.markdown("---")
        st.caption("Admin: all users' tasks are on a separate page.")
        if st.button("Open Admin · all tasks", key="hc_goto_admin_from_label"):
            st.switch_page("Admin · all tasks")

if task is None:
    st.markdown("### Start a new task")
    _WINDOW_SECS = list(get_window_secs())
    if not _WINDOW_SECS:
        st.error("No window sizes configured. Ask an admin to set them in Admin · settings.")
        st.stop()
    _default_win = int(_WINDOW_SECS[0])
    nickname_in = st.text_input(
        "Task nickname",
        value=default_nickname(window_sec=_default_win, cohort_option=1),
        max_chars=80,
        key="hc_new_nickname",
        help="Friendly name so you can find this task later. You can rename it anytime.",
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        window_sec = st.selectbox(
            "Window length (s)",
            options=_WINDOW_SECS,
            index=0,
            key="hc_new_window",
        )
    with c2:
        cohort_option = st.selectbox(
            "Cohort option",
            options=[1, 2, 3],
            format_func=lambda n: (
                "1 — all participants together"
                if n == 1
                else f"{n} — split into {n} random cohorts"
            ),
            key="hc_new_cohort",
        )
    with c3:
        rand_part = st.checkbox(
            "Randomize across participants",
            value=True,
            key="hc_new_rand_part",
        )
    st.checkbox(
        "Randomize across treatment & spreadsheet",
        value=True,
        disabled=True,
        key="hc_new_rand_phase",
        help="Always on for now.",
    )

    max_participants: int | None = None
    if is_admin():
        n_avail = len(list_participants())
        st.markdown("#### Admin test options")
        use_subset = st.checkbox(
            "Limit participant count (for testing)",
            value=False,
            key="hc_admin_limit_pids",
            help="Randomly sample N participants so you can smoke-test without a full cohort.",
        )
        if use_subset:
            max_participants = int(
                st.number_input(
                    "Number of participants",
                    min_value=1,
                    max_value=max(1, n_avail),
                    value=min(3, n_avail),
                    step=1,
                    key="hc_admin_n_pids",
                )
            )
            st.caption(f"{n_avail} participants available in local data.")

    if st.button("Preview task size", key="hc_preview"):
        with st.spinner("Building window catalog…"):
            plan = build_task_plan(
                window_sec=int(window_sec),
                cohort_option=int(cohort_option),
                randomize_participants=bool(rand_part),
                randomize_phases=True,
                max_participants=max_participants,
            )
        st.session_state["hc_pending_plan"] = {
            "nickname": nickname_in,
            "window_sec": int(window_sec),
            "cohort_option": int(cohort_option),
            "randomize_participants": bool(rand_part),
            "max_participants": max_participants,
            "n_participants": plan["n_participants"],
            "participants": plan["participants"],
            "seed": plan["seed"],
            "n_windows_total": plan["n_windows_total"],
            "cohort_summary": plan["cohort_summary"],
        }

    pending = st.session_state.get("hc_pending_plan")
    if pending:
        st.markdown("### Task summary — confirm before labeling")
        nick_confirm = st.text_input(
            "Task nickname",
            value=str(pending.get("nickname") or ""),
            max_chars=80,
            key="hc_pending_nickname",
        )
        n_pids = pending.get("n_participants")
        pid_note = f"**{n_pids}**" if n_pids is not None else "all"
        if pending.get("max_participants") is not None:
            pid_note += f" (admin test limit {pending['max_participants']})"
        st.write(
            f"- **Window length:** {pending['window_sec']} s  \n"
            f"- **Participants:** {pid_note}  \n"
            f"- **Total windows:** **{pending['n_windows_total']}**  \n"
            f"- **Randomize phases:** yes (fixed on)  \n"
            f"- **Randomize participants:** "
            f"{'yes' if pending['randomize_participants'] else 'no'}  \n"
            f"- **Cohort option:** {pending['cohort_option']}"
        )
        if pending.get("max_participants") is not None and pending.get("participants"):
            st.caption("Selected: " + ", ".join(pending["participants"]))
        if int(pending["cohort_option"]) > 1:
            st.markdown("**Cohorts**")
            for row in pending.get("cohort_summary") or []:
                st.write(
                    f"- Cohort {int(row['cohort_index']) + 1}: "
                    f"**{row['n_participants']}** participants, "
                    f"**{row['n_windows']}** windows"
                )
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Create task and start", type="primary", key="hc_confirm_create"):
                with st.spinner("Saving task…"):
                    created = create_task(
                        access_code=user["access_code"],
                        name=user["name"],
                        window_sec=int(pending["window_sec"]),
                        cohort_option=int(pending["cohort_option"]),
                        randomize_participants=bool(pending["randomize_participants"]),
                        randomize_phases=True,
                        seed=int(pending["seed"]),
                        nickname=nick_confirm,
                        max_participants=pending.get("max_participants"),
                    )
                st.session_state["hc_active_task_id"] = created["task_id"]
                st.session_state[f"hc_begun_{created['task_id']}"] = True
                st.session_state.pop("hc_pending_plan", None)
                log_activity(
                    "task_created",
                    detail={
                        "task_id": created["task_id"],
                        "nickname": created.get("nickname"),
                        "window_sec": created["window_sec"],
                        "cohort_option": created["cohort_option"],
                        "n_windows": created["n_windows_total"],
                        "n_participants": created.get("n_participants"),
                        "max_participants": created.get("max_participants"),
                    },
                )
                st.rerun()
        with b2:
            if st.button("Cancel preview", key="hc_cancel_preview"):
                st.session_state.pop("hc_pending_plan", None)
                st.rerun()

    st.stop()

# ---------------------------------------------------------------------------
# Editable nickname (always available while a task is open)
# ---------------------------------------------------------------------------
nick_now = str(task.get("nickname") or task["task_id"])
st.markdown(f"### {nick_now}")
st.caption(f"Task id: `{task['task_id']}`")
with st.expander("Rename task", expanded=False):
    new_nick = st.text_input(
        "Nickname",
        value=nick_now,
        max_chars=80,
        key=f"hc_rename_{task['task_id']}",
    )
    if st.button("Save nickname", key=f"hc_save_nick_{task['task_id']}"):
        try:
            task = set_task_nickname(task["task_id"], new_nick)
        except ValueError as exc:
            st.error(str(exc))
        else:
            log_activity(
                "task_renamed",
                detail={"task_id": task["task_id"], "nickname": task.get("nickname")},
            )
            st.success(f"Renamed to **{task['nickname']}**")
            st.rerun()

# ---------------------------------------------------------------------------
# Pre-start summary if not yet begun labeling
# ---------------------------------------------------------------------------
responses = load_responses(task["task_id"])
begun = bool(responses) or bool(st.session_state.get(f"hc_begun_{task['task_id']}"))

if not begun:
    st.markdown("### Task summary — confirm before labeling")
    n_pids = task.get("n_participants") or len(task.get("participants") or [])
    st.write(
        f"- **Nickname:** **{task.get('nickname') or '—'}**  \n"
        f"- **Task id:** `{task['task_id']}`  \n"
        f"- **Window length:** {task['window_sec']} s  \n"
        f"- **Participants:** **{n_pids}**  \n"
        f"- **Total windows:** **{task['n_windows_total']}**  \n"
        f"- **Randomize phases:** yes (fixed on)  \n"
        f"- **Randomize participants:** {'yes' if task['randomize_participants'] else 'no'}  \n"
        f"- **Cohort option:** {task['cohort_option']}"
    )
    if int(task["cohort_option"]) > 1:
        st.markdown("**Cohorts**")
        for row in task.get("cohort_summary") or []:
            st.write(
                f"- Cohort {int(row['cohort_index']) + 1}: "
                f"**{row['n_participants']}** participants, "
                f"**{row['n_windows']}** windows"
            )
    b1, b2 = st.columns(2)
    with b1:
        if st.button("Start labeling", type="primary", key="hc_start"):
            st.session_state[f"hc_begun_{task['task_id']}"] = True
            task["status"] = "in_progress"
            save_task(task)
            log_activity("task_started", detail={"task_id": task["task_id"]})
            st.rerun()
    with b2:
        if st.button("Discard and create another", key="hc_discard"):
            st.session_state.pop("hc_active_task_id", None)
            st.session_state.pop("hc_preview_task", None)
            st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Labeling UI
# ---------------------------------------------------------------------------
order = list(task.get("presentation_order") or [])
cohort_opt = int(task.get("cohort_option") or 1)
cur_cohort = int(task.get("current_cohort_index") or 0)
cohort_idxs = indices_for_cohort(task, cur_cohort)
if not cohort_idxs:
    st.error("No windows in this cohort.")
    st.stop()

# Map local cohort position
local_pos = int(task.get("current_index") or 0)
# current_index is global into presentation_order; clamp to this cohort
if local_pos not in cohort_idxs:
    local_pos = cohort_idxs[0]
    task["current_index"] = local_pos
    save_task(task)

global_index = local_pos
window_id = order[global_index]
window = window_by_id(task, window_id)
if window is None:
    st.error(f"Missing window {window_id}")
    st.stop()

n_cohort = len(cohort_idxs)
pos_in_cohort = cohort_idxs.index(global_index) + 1
n_labeled_cohort = sum(1 for i in cohort_idxs if order[i] in responses)

n_total = int(task.get("n_windows_total") or len(order) or 1)
n_done = len(responses)
n_remaining = max(0, n_total - n_done)
pct_done = 100.0 * n_done / max(n_total, 1)
pct_remaining = 100.0 * n_remaining / max(n_total, 1)

st.markdown("#### Task tracking")
st.progress(min(1.0, n_done / max(n_total, 1)))
st.caption(
    f"**Overall:** {n_done}/{n_total} windows ({n_remaining} remaining) · "
    f"**{pct_done:.1f}%** completed · **{pct_remaining:.1f}%** remaining"
)
st.caption(
    f"Current: cohort {cur_cohort + 1}/{cohort_opt} · "
    f"window **{pos_in_cohort}/{n_cohort}** in this cohort "
    f"({n_labeled_cohort}/{n_cohort} labeled here)"
)

if cohort_opt > 1:
    cohort_lines = []
    for cidx in range(cohort_opt):
        idxs = indices_for_cohort(task, cidx)
        n_c = len(idxs)
        if n_c == 0:
            continue
        n_c_done = sum(1 for i in idxs if order[i] in responses)
        pct_c = 100.0 * n_c_done / n_c
        marker = " ← current" if cidx == cur_cohort else ""
        cohort_lines.append(
            f"- **Cohort {cidx + 1}:** {n_c_done}/{n_c} · **{pct_c:.1f}%** completed{marker}"
        )
    st.markdown("**By cohort**\n" + "\n".join(cohort_lines))

_CHART_WIDTH_FRACS = {
    "XS": 0.32,
    "Small": 0.48,
    "Medium": 0.72,
    "Full width": 1.0,
}
if "hc_chart_width" not in st.session_state:
    st.session_state["hc_chart_width"] = "Medium"
# Migrate older 3-level preference if needed
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
    st.plotly_chart(fig, use_container_width=True, key=f"hc_rr_{window_id}")
else:
    side = (1.0 - frac) / 2.0
    _left, mid, _right = st.columns([side, frac, side])
    with mid:
        st.plotly_chart(fig, use_container_width=True, key=f"hc_rr_{window_id}")

existing = responses.get(window_id)
if existing:
    st.info(
        f"Current answer: **{TRUE_CLASS_LABELS.get(existing.get('choice'), existing.get('choice'))}** "
        f"(you can change it)"
    )

def _save_choice(choice: str) -> None:
    true_class = str(window.get("true_class"))
    rec = {
        "response_id": f"{task['task_id']}_{window_id}_{len(responses)+1}",
        "task_id": task["task_id"],
        "access_code": user["access_code"],
        "name": user["name"],
        "window_id": window_id,
        "presentation_index": int(global_index),
        "choice": choice,
        "true_phase": window.get("phase"),
        "true_class": true_class,
        "correct": bool(choice == true_class),
        "participant": window.get("participant"),
        "start_millis": window.get("start_millis"),
        "end_millis": window.get("end_millis"),
        "responded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    upsert_response(task["task_id"], rec)
    log_activity(
        "response_saved",
        detail={
            "task_id": task["task_id"],
            "window_id": window_id,
            "choice": choice,
            "presentation_index": global_index,
        },
    )
    # advance within cohort
    pos = cohort_idxs.index(global_index)
    if pos + 1 < len(cohort_idxs):
        task["current_index"] = cohort_idxs[pos + 1]
        save_task(task)
    else:
        # end of cohort
        if cur_cohort + 1 < cohort_opt:
            task["current_cohort_index"] = cur_cohort + 1
            next_idxs = indices_for_cohort(task, cur_cohort + 1)
            task["current_index"] = next_idxs[0] if next_idxs else global_index
            save_task(task)
            st.session_state["hc_cohort_just_finished"] = cur_cohort
        else:
            task["status"] = "completed"
            save_task(task)
            st.session_state["hc_task_completed"] = task["task_id"]


try:
    _actions = st.container(key="hc_label_actions")
except TypeError:
    _actions = st.container()
with _actions:
    c_prev, c_paced, c_not, c_next = st.columns([1, 2, 2, 1])
    with c_paced:
        if st.button("Paced", type="primary", use_container_width=True, key="hc_paced"):
            _save_choice("paced")
            st.rerun()
    with c_not:
        if st.button("Not paced", type="primary", use_container_width=True, key="hc_not"):
            _save_choice("not_paced")
            st.rerun()
    with c_prev:
        if st.button("Previous", use_container_width=True, key="hc_prev"):
            pos = cohort_idxs.index(global_index)
            if pos > 0:
                task["current_index"] = cohort_idxs[pos - 1]
                save_task(task)
                st.rerun()
    with c_next:
        if st.button("Next", use_container_width=True, key="hc_next"):
            pos = cohort_idxs.index(global_index)
            if pos + 1 < len(cohort_idxs):
                task["current_index"] = cohort_idxs[pos + 1]
                save_task(task)
                st.rerun()

if st.session_state.pop("hc_cohort_just_finished", None) is not None:
    st.success("Cohort finished — continuing to the next cohort.")
if st.session_state.pop("hc_task_completed", None):
    st.success("Task completed. Thank you — you can start a new task from the sidebar.")
    if st.button("Start a new task", key="hc_new_after_done"):
        st.session_state.pop("hc_active_task_id", None)
        st.rerun()

if st.sidebar.button("Close task (keep progress)", key="hc_close_task"):
    st.session_state.pop("hc_active_task_id", None)
    st.rerun()
