# HRV Human Classifier — Gold-standard labeling plan

## Deployment independence

This app is **self-contained** under `HRVHumanClassifier/`:

- Local RR data: `data/pXX/pXX-hrv-generated-gap.csv` (copied cohort; 26 participants)
- Local libs only: `hc_rr.py`, `hc_task.py`, `access_lib.py` — **no imports** from the
  parent analytics repo (`frp_glcm`, `hrv_settling_lib`, etc.)
- Tasks/responses: `data/tasks/`
- Access codes: `access_codes.json`

Deploy by shipping this folder + `pip install -r requirements.txt`, then
`streamlit run app.py`.

## Purpose

Humans create a **gold-standard** classification by viewing RR plots cut into
fixed windows (e.g. 10 / 20 / 30 s) from **treatment** (paced) and
**spreadsheet** (not paced) phases. Labels are stored per access code and
compared later to protocol labels and model predictions.

---

## Independent user tasks

- A signed-in user may run this **many times** by starting a **new task**.
- Each task is an **independent trackable entity** with its own:
  - task id
  - settings (window size, randomization, cohort option)
  - randomized trial order / cohort partition (seed stored)
  - progress (which trials done)
  - labels submitted
  - timestamps / access code / registered name
- Starting a new task does **not** overwrite a previous task’s labels.
- Activity log and task store both key by `access_code` + `task_id`.

---

## Task settings (before start)

| Setting | Values | Notes |
|--------|--------|--------|
| Window length | Pre-selected set (e.g. 10, 20, 30 s) | Splits both treatment and spreadsheet RR into windows of this size |
| Randomize across treatment & spreadsheet | **Always on** | Shown in UI but **not changeable for now** (Option 1) |
| Randomize across participants | true / false (**default true**) | Option 2 |
| Cohort option | **1**, **2**, or **3** | How participants are grouped for the session |
| Max participants (admin only) | 1 … full cohort | Optional random subset for smoke-testing |

### Randomization levels

1. **Option 1 — Phase mix (fixed on)**  
   Trials mix **paced (treatment)** and **not paced (spreadsheet)** windows so
   the rater cannot infer label from block order.

2. **Option 2 — Across participants (default on)**  
   When true, participant order (and thus which person’s windows appear when)
   is randomized for this task. When false, a stable participant order is used
   (still phase-mixed by Option 1).

Each task stores its own RNG seed so the exact schedule is reproducible and
auditable.

### Cohort option

- **1 — Single cohort**  
  All eligible participants are in one pool. The user does the full set of
  windows in one run (subject to the randomization settings).

- **2 or 3 — Split cohorts**  
  Eligible participants are **randomly partitioned into 2 or 3 cohorts** for
  **this task only** (different users / new tasks get different partitions).
  The user completes **cohort 1, then cohort 2, (then cohort 3)** — not all
  participants interleaved across cohort boundaries.

Within each cohort, Option 1 (and Option 2 if enabled) still apply to trial order.

---

## Pre-start summary (required UI)

Before the task starts, show at least:

- **Total windows** to classify in this task  
- If cohort option is 2 or 3:
  - **Participants per cohort** (counts; optionally list ids after start or in admin)
  - **Windows per cohort**

User confirms → task entity is created → first cohort (or full set) begins.

---

## Trial flow (unchanged core)

1. Build windows of selected length from full treatment + spreadsheet RR.
2. Build trial list for the active cohort (or all participants if cohort = 1).
3. Apply randomization (phase mix always; participant mix if Option 2).
4. Show one RR plot at a time; rater chooses **Paced** or **Not paced**.
5. Save label with `task_id`, window identity, true phase (hidden), rater code.
6. When a cohort finishes, offer next cohort until all cohorts done → task complete.

---

## Presenting RR levels and next / previous navigation

### What the rater sees (one window at a time)

For `presentation_order[i]` → load that `window_id`’s RR slice and show:

1. **Main plot — RR level vs time (within the window)**  
   - X: time relative to window start (0 … `window_sec`), from `millis_ms - start_millis`  
   - Y: RR interval in ms (`rr_ms`)  
   - Style: markers + line (beat-to-beat “RR level” trace), fixed Y-axis range optional
     (e.g. 400–1200 ms) so windows are visually comparable  
   - **No phase name, no participant id, no “paced/not paced” hint** on the plot

2. **Minimal chrome**  
   - Progress: `Window i + 1 / N` (within current cohort, and overall if useful)  
   - Window length reminder: e.g. “30 s window”  
   - Optional: beat count only (not diagnostic of class)

3. **Response controls** (primary)  
   - **Paced** / **Not paced** (two clear buttons)  
   - Selecting one **saves** the response for this `window_id` and, by default,
     **advances to the next unanswered** window in `presentation_order`

### Navigation model

Session holds:

- `task_id`
- `current_index` — index into `presentation_order` (0-based)
- `responses` map: `window_id → choice` (loaded from disk + live updates)

**Next**

- Button **Next** (and auto-advance after labeling):  
  `current_index = min(current_index + 1, len(presentation_order) - 1)`  
- If the new window already has a saved response, show that choice as selected
  (editable until cohort/task locked — default: allow change).

**Previous**

- Button **Previous**:  
  `current_index = max(current_index - 0, 0)` → `max(current_index - 1, 0)`  
- Reload plot for `presentation_order[current_index]`  
- Prefill buttons from any existing response for that `window_id`

**Jump / safety**

- Do **not** skip by participant or phase (that would leak structure).  
- Optional later: jump to first unlabeled only via “Resume”.  
- At end of cohort: **Next** becomes **Finish cohort** / **Start next cohort**.

### What is stored on each move

| Action | Persist |
|--------|---------|
| Choose Paced / Not paced | Upsert `responses` for `window_id` + `presentation_index` + `responded_at` |
| Previous / Next without changing choice | Only update `current_index` in task progress (no new label) |
| Change an earlier answer | Overwrite response for that `window_id`; keep history optional in activity log |

### Plot data source

- Prefer arrays already attached to `windows[]` at task creation, **or**  
- Reload from participant RR using `start_millis` / `end_millis` so JSON stays light.  
- Cleaning: same RR clean rules as the FRP pipeline (min/max ms) so plots match analysis.

### Explicitly hidden from the rater

- `phase`, `true_class`, participant id, cohort mate list, correctness feedback
  (feedback can be admin-only or post-task summary later)

---

## Data to persist (per task)

Suggested fields:

- `task_id`, `access_code`, `name`, `created_at`, `status`
- `window_sec`, `randomize_phases=true`, `randomize_participants`, `cohort_option`
- `seed`, `cohort_assignments` (participant → cohort index)
- `windows[]` — **canonical window catalog** (identity + timeline; not shuffled)
- `presentation_order[]` — list of `window_id` in the order shown to the user
- `responses[]` — one row per answer, keyed by `window_id` (and optional `presentation_index`)

---

## Records, randomization tracking, and timeline remapping

### Design principle

**Separate “what the window is” from “when we showed it.”**

- Randomization only changes **presentation order**.
- Each window keeps a **stable identity** and **absolute timestamps** from the
  original RR recording so answers can always be put back on the timeline.

### 1. Canonical window catalog (`windows[]`)

Built once when the task is created (before any labeling). One row per cut
window, for example:

| Field | Meaning |
|-------|---------|
| `window_id` | Stable id, e.g. `p07_treatment_r1_w003` |
| `participant` | e.g. `p07` |
| `phase` | `treatment` or `spreadsheet` (true protocol label; hidden in UI) |
| `phase_run_id` | Which contiguous run of that phase |
| `window_index` | 0-based index along that phase run |
| `window_sec` | Task window length |
| `start_millis` / `end_millis` | Absolute times on the recording clock |
| `start_sec_in_phase` / `end_sec_in_phase` | Offset within that phase run |
| `n_beats` | Beats in the slice |
| `cohort_index` | 0 .. cohort_option-1 for this task |
| `rr_ms` / `millis_ms` | (optional) store arrays, or reload from RR store by ids |

These rows are **never reordered**. They are the ground-truth map back to time.

### 2. Randomized presentation (`presentation_order[]`)

After applying Option 1 (phase mix, always) and Option 2 (participant mix,
default on), and respecting cohort boundaries:

```text
presentation_order = [
  "p03_spreadsheet_r0_w011",
  "p18_treatment_r1_w002",
  ...
]
```

Also store:

- `rng_seed` — reproduces the same order later
- `presentation_index` — 0, 1, 2, … position in the UI queue

The UI shows `windows[presentation_order[i]]` but only the plot, not `phase`.

### 3. User responses (`responses[]`)

Each click appends (or upserts) a record:

| Field | Meaning |
|-------|---------|
| `response_id` | Unique id |
| `task_id` | Parent task |
| `access_code` / `name` | Who answered |
| `window_id` | **Link back to catalog** (not “trial 17” alone) |
| `presentation_index` | Where it appeared in the shuffled queue |
| `choice` | `paced` or `not_paced` |
| `choice_label` | optional display string |
| `responded_at` | UTC timestamp of the click |
| `true_phase` | Copied from window at save time (for easy scoring; still hidden in UI) |
| `correct` | `choice` vs protocol (`treatment`↔paced, `spreadsheet`↔not_paced) |

Because every response carries `window_id`, shuffling never loses the link.

### 4. Putting answers back on the timeline

To rebuild a timeline view (per participant / phase):

1. Join `responses` → `windows` on `window_id`.
2. Sort by `participant`, `phase`, `phase_run_id`, `start_millis`
   (ignore `presentation_index` for physiology time).
3. Plot or export:
   - x = `start_millis` … `end_millis` (or phase-relative seconds)
   - color / marker = human `choice` vs `true_phase`

Example export columns:

`access_code, task_id, participant, phase, phase_run_id, window_index,
 start_millis, end_millis, start_sec_in_phase, window_sec, choice, true_phase,
 correct, presentation_index, responded_at`

That file is in **recording time order**, even though the user saw windows in
random order.

### 5. Where files live (intended)

Under `HRVHumanClassifier/data/tasks/`:

- `tasks/{task_id}.json` — settings, seed, cohort_assignments, presentation_order, windows metadata
- `tasks/{task_id}_responses.jsonl` — append-only responses (safe if app restarts)
- Optional: omit bulky RR arrays from JSON and reload from `data/` / RR store using
  `participant` + `phase` + `start_millis`/`end_millis` when plotting

Activity log (`activity_log.jsonl`) still records high-level events
(`task_created`, `cohort_started`, `response_saved`, `task_completed`) keyed by
`access_code` + `task_id`.

### 6. Why this works

| Concern | Approach |
|---------|----------|
| Track randomized window | `presentation_order` + `presentation_index` |
| Keep user response | `responses[]` keyed by `window_id` |
| Remap to timeline | `windows[].start_millis` / `end_millis` (+ phase offsets) |
| Reproducibility | stored `rng_seed` |
| Multi-task users | each `task_id` is a separate folder/file set |

---

## Task visibility

- **Users** see only tasks whose `access_code` matches their session
  (`list_tasks_for_user` / `load_owned_task`). Opening another user’s task id
  is rejected.
- Logout / login clears workspace session keys so an open task cannot leak
  across accounts in the same browser.

## Admin features

Signed in as admin (`HRVADMIN`):

1. **Test tasks with fewer participants**  
   On Gold-standard labeling, enable **Limit participant count** and choose N.
   The task RNG samples N participants from the local cohort; settings, seed,
   and selected ids are stored on the task. Labeling still lists only the
   admin’s own tasks.

2. **Admin · all tasks** (`views/admin_all_tasks.py`)  
   Shown in the sidebar **only after admin sign-in**. Page scripts live under
   `views/` (not `pages/`) so Streamlit cannot auto-discover Admin before
   login; `st.navigation` registers Admin only when `is_admin()`. Separate
   cross-user view: every task with answered / correct / accuracy, confusion
   matrix, participant phase plots, CSV export, and **admin delete task**.

3. **Admin · training** (`views/admin_training.py`)  
   All users’ training sessions with first-try **error rate**, per-user
   aggregate, per-window first vs latest answer detail + CSV export, and
   admin delete session.

4. **Admin · access codes** (`views/admin_access_codes.py`)  
   Create / edit / delete access codes and assign roles (`user` / `admin`).
   `HRVADMIN` cannot be deleted and must remain role `admin`.

5. **Admin · data transfer** (`views/admin_data.py`, `hc_transfer.py`)  
   Export / import a ZIP of access codes (users), labeling tasks (+ responses),
   and training sessions (+ responses). Safe merge by default; optional
   overwrite. Intended for pulling online deployment results into a local app.

6. **Admin · settings** (`views/admin_settings.py`, `hc_settings.py` →
   `app_settings.json`)  
   Configure max training sessions per user, training sample counts by window
   threshold, and the allowed window sizes used by labeling and training.

---

## Training sessions

Page: **Training** (`views/training.py`, library `hc_train.py`).

- Each user may keep up to **20** training sessions (`data/training/`).
- Choose window length **10 / 20 / 30 s**.
- Sampler draws random windows from random participants at **random positions**
  inside spreadsheet and treatment phase runs (`hc_rr.sample_random_windows`).
- Sample size: **10 per phase** when window is 10 s; **5 per phase** when
  window is 20 or 30 s; then phases are shuffled together for presentation.
- After each answer, show immediate correct/incorrect feedback (true phase
  revealed). Gold-standard labeling remains blind.
- **Error rate** uses only the **first** answer per window; later retries after
  feedback do not change it. Admins review sessions on **Admin · training**.

---

## Out of scope for this plan slice

- Changing Option 1 off
- Overlapping windows / expanding-prefix protocol (unless added later)
