"""HRV Human Classifier — independent Streamlit app.

Run from this folder (or repo root)::

    streamlit run HRVHumanClassifier/app.py

Uses only local modules and ``HRVHumanClassifier/data/`` (copied gap RR CSVs).
Does **not** import the parent analytics libraries.

Navigation is role-based via ``st.navigation``. Page scripts live under
``views/`` (not ``pages/``) so Streamlit cannot auto-discover Admin before
sign-in. Admin pages (all tasks, training, access codes, settings) are
registered only when the signed-in user is an admin.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

st.set_page_config(
    page_title="HRV Human Classifier",
    layout="wide",
    initial_sidebar_state="expanded",
)

from access_lib import is_admin, list_access_codes, log_activity, require_access  # noqa: E402
from hc_rr import list_participants  # noqa: E402
from hc_task import list_all_tasks  # noqa: E402
from hc_train import list_all_sessions  # noqa: E402

VIEWS = HERE / "views"


def _home_dashboard_counts() -> dict[str, int]:
    named_users = sum(
        1
        for row in list_access_codes()
        if str(row.get("name") or "").strip()
    )
    tasks_done = sum(
        1 for t in list_all_tasks() if str(t.get("status") or "") == "completed"
    )
    train_done = sum(
        1 for s in list_all_sessions() if str(s.get("status") or "") == "completed"
    )
    return {
        "participants": len(list_participants()),
        "users": named_users,
        "tasks_done": tasks_done,
        "training_done": train_done,
    }


def _render_home() -> None:
    user = require_access()
    if st.session_state.get("hc_logged_home") != user["access_code"]:
        log_activity("view_home", detail={"page": "home"})
        st.session_state["hc_logged_home"] = user["access_code"]

    st.markdown(
        """
        <style>
          :root {
            --hc-ink: #1a2332;
            --hc-muted: #5c6b7a;
            --hc-accent: #0d7a6f;
            --hc-accent-soft: #e6f3f1;
          }
          .stApp {
            background:
              radial-gradient(1200px 600px at 10% -10%, #dceeea 0%, transparent 55%),
              linear-gradient(180deg, #f7f4ef 0%, #eef2f4 100%);
          }
          .hc-hero {
            font-family: "Fraunces", "Palatino Linotype", Palatino, serif;
            font-size: clamp(2.2rem, 4vw, 3.2rem);
            font-weight: 600;
            color: var(--hc-ink);
            margin: 0.2rem 0 0.4rem 0;
            line-height: 1.1;
          }
          .hc-sub { color: var(--hc-muted); font-size: 1.05rem; max-width: 42rem; }
          .hc-dash {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.85rem;
            margin: 1.1rem 0 1.4rem 0;
          }
          @media (max-width: 900px) {
            .hc-dash { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          }
          .hc-dash-card {
            background: rgba(255, 255, 255, 0.72);
            border: 1px solid rgba(26, 35, 50, 0.08);
            border-radius: 12px;
            padding: 0.95rem 1rem 0.85rem 1rem;
          }
          .hc-dash-label {
            color: var(--hc-muted);
            font-size: 0.82rem;
            font-weight: 600;
            letter-spacing: 0.02em;
            text-transform: uppercase;
            margin: 0 0 0.35rem 0;
          }
          .hc-dash-value {
            font-family: "Fraunces", "Palatino Linotype", Palatino, serif;
            font-size: 2rem;
            font-weight: 600;
            color: var(--hc-ink);
            line-height: 1;
            margin: 0;
          }
          .hc-dash-hint {
            color: var(--hc-muted);
            font-size: 0.8rem;
            margin: 0.4rem 0 0 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="hc-hero">HRV Human Classifier</div>', unsafe_allow_html=True)
    st.markdown(
        '<p class="hc-sub">Standalone app for human gold-standard labeling of RR windows '
        "as <strong>paced</strong> vs <strong>not paced</strong>.</p>",
        unsafe_allow_html=True,
    )

    role_note = " (admin)" if is_admin() else ""
    st.success(f"Signed in as **{user['name']}**{role_note} · `{user['access_code']}`")

    counts = _home_dashboard_counts()
    st.markdown(
        f"""
        <div class="hc-dash">
          <div class="hc-dash-card">
            <p class="hc-dash-label">Participants</p>
            <p class="hc-dash-value">{counts["participants"]}</p>
            <p class="hc-dash-hint">Local cohort</p>
          </div>
          <div class="hc-dash-card">
            <p class="hc-dash-label">Users available</p>
            <p class="hc-dash-value">{counts["users"]}</p>
            <p class="hc-dash-hint">Access codes with names</p>
          </div>
          <div class="hc-dash-card">
            <p class="hc-dash-label">Tasks done</p>
            <p class="hc-dash-value">{counts["tasks_done"]}</p>
            <p class="hc-dash-hint">Completed labeling tasks</p>
          </div>
          <div class="hc-dash-card">
            <p class="hc-dash-label">Training done</p>
            <p class="hc-dash-value">{counts["training_done"]}</p>
            <p class="hc-dash-hint">Completed training sessions</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
### What you will do
1. Choose window length (10 / 20 / 30 s) and cohort settings.
2. Confirm total windows (and per-cohort counts if split).
3. For each RR plot, mark **Paced** or **Not paced**.
4. Use Previous / Next to review; each task is saved under your access code.
"""
    )

    if is_admin():
        st.markdown(
            """
### Admin
- **Gold-standard labeling** still shows only *your* (admin) tasks — use it to
  smoke-test with a limited participant count.
- **Admin · all tasks** — every user’s gold-standard scores (and delete tasks).
- **Admin · training** — every user’s training sessions and first-try error rate.
- **Admin · data transfer** — export / import access codes, tasks, and training.
"""
        )
        if st.button(
            "Open Admin · data transfer", type="primary", key="hc_goto_admin_data"
        ):
            st.switch_page("Admin · data transfer")
    else:
        st.caption("Your tasks are private to your access code.")


# Block until signed in (shows Access form and stops). No nav pages are
# registered before this returns, so Admin cannot appear pre-login.
# Sidebar/sign-out is rendered by the active page to avoid duplicate keys.
require_access(show_sidebar=False)

home_page = st.Page(_render_home, title="Home", default=True)
label_page = st.Page(str(VIEWS / "labeling.py"), title="Gold-standard labeling")
train_page = st.Page(str(VIEWS / "training.py"), title="Training")
nav_pages = [home_page, label_page, train_page]
if is_admin():
    nav_pages.extend(
        [
            st.Page(str(VIEWS / "admin_all_tasks.py"), title="Admin · all tasks"),
            st.Page(str(VIEWS / "admin_training.py"), title="Admin · training"),
            st.Page(
                str(VIEWS / "admin_access_codes.py"), title="Admin · access codes"
            ),
            st.Page(str(VIEWS / "admin_data.py"), title="Admin · data transfer"),
            st.Page(str(VIEWS / "admin_settings.py"), title="Admin · settings"),
        ]
    )

st.navigation(nav_pages).run()
