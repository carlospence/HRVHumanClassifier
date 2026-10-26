# HRV Human Classifier

**By Charles Ejedawe**

Standalone Streamlit app for human labeling of RR windows as **paced** vs **not paced**, plus practice training with immediate feedback.

## Run the app

From this folder (or the repo root):

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the URL Streamlit prints (usually `http://localhost:8501`).

You need a pre-issued **access code** from your administrator (for example `HRV001`).

---

## New user walkthrough

### 1. Register and sign in

1. On the **Access** screen, enter your access code and click **Continue**.
2. The first time that code is used, you see **Register**.
3. Enter your name (at least 2 characters) and click **Register and continue**.
4. Your name is permanently linked to that code. Later visits only need the access code.
5. You land on **Home**. Confirm you are signed in (name and code in the success banner / sidebar).

Use **Sign out** in the sidebar when you are done.

### 2. Do training sessions (practice)

Training shows the correct answer after each choice so you can learn the paced vs not-paced patterns. Use this before gold-standard labeling.

1. Open **Training** in the sidebar.
2. Choose a window length (**10 / 20 / 30 s**).
3. Click to start a new training session (you may keep a limited number of sessions per account).
4. For each RR plot, choose **Paced** or **Not paced**.
5. Read the immediate feedback (correct / incorrect and true phase), then continue.
6. Progress shows your **first-try error rate** (later retries after feedback do not change it).
7. When every window is answered, the session is marked complete. You can resume or start another session from the sidebar list.

Repeat a few sessions until you feel comfortable recognizing paced vs not paced.

### 3. Complete a gold-standard labeling task

Gold-standard labeling is **blind** (no feedback while you label). Each task is saved under your access code and does not overwrite earlier tasks.

1. Open **Gold-standard labeling** in the sidebar.
2. Choose settings for a **new task**:
   - Window length (**10 / 20 / 30 s**)
   - Whether to randomize across participants (recommended: on)
   - Cohort option (**1**, **2**, or **3**)
3. Review the pre-start summary (total windows, etc.) and start the task.
4. Optionally give the task a nickname so you can find it later.
5. For each RR plot, mark **Paced** or **Not paced**.
6. Use **Previous** / **Next** to review; you can change an answer before you finish.
7. Continue until all windows are labeled. The task status becomes **completed**.

You can start additional independent tasks anytime from the same page. Only your own tasks appear in your list.

---

## Tips

- Prefer finishing **training** before gold-standard tasks so practice feedback does not bias your scoring mindset.
- One access code = one registered name. Do not share your code.
- If login fails, ask an admin to confirm your code exists and is not already registered to someone else.
