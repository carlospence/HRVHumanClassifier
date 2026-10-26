"""Access-code gate and activity logging for HRV Human Classifier.

Pre-generated codes live in ``access_codes.json``. A code may be unnamed
until the user registers; all subsequent activity is logged under that code.

Login survives browser refresh via an Http cookie (and a query-param fallback).
Streamlit ``session_state`` alone is wiped on refresh.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import streamlit as st
import streamlit.components.v1 as components

HERE = Path(__file__).resolve().parent
ACCESS_CODES_PATH = HERE / "access_codes.json"
ACTIVITY_LOG_PATH = HERE / "activity_log.jsonl"

SESSION_CODE = "hc_access_code"
SESSION_NAME = "hc_user_name"
SESSION_AUTH = "hc_authenticated"
SESSION_ROLE = "hc_user_role"

# Browser persistence (survives refresh; cleared on Sign out)
COOKIE_NAME = "hc_access_code"
AUTH_QUERY_PARAM = "hc_auth"
COOKIE_MAX_AGE_SEC = 60 * 60 * 24 * 30  # 30 days

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{3,63}$")

PROTECTED_ACCESS_CODE = "HRVADMIN"
VALID_ROLES = ("user", "admin")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def default_access_store() -> dict[str, Any]:
    """Seed store: HRV001–HRV010 (users) + HRVADMIN."""
    now = _utc_now()
    codes: dict[str, Any] = {
        f"HRV{i:03d}": {
            "name": None,
            "role": "user",
            "created_at": now,
            "registered_at": None,
        }
        for i in range(1, 11)
    }
    codes["HRVADMIN"] = {
        "name": "Administrator",
        "role": "admin",
        "created_at": now,
        "registered_at": now,
    }
    return {"version": 1, "codes": codes}


def ensure_access_store(path: Path | None = None) -> Path:
    path = Path(path or ACCESS_CODES_PATH)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(default_access_store(), indent=2),
            encoding="utf-8",
        )
    return path


def load_access_store(path: Path | None = None) -> dict[str, Any]:
    path = ensure_access_store(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if "codes" not in data or not isinstance(data["codes"], dict):
        raise ValueError(f"Invalid access store (missing codes): {path}")
    return data


def save_access_store(store: dict[str, Any], path: Path | None = None) -> None:
    path = Path(path or ACCESS_CODES_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    tmp.replace(path)


def normalize_code(raw: str) -> str:
    return str(raw or "").strip().upper()


def lookup_code(code: str, store: dict[str, Any] | None = None) -> dict[str, Any] | None:
    store = store or load_access_store()
    key = normalize_code(code)
    # Allow case-insensitive match against stored keys.
    for stored, meta in store.get("codes", {}).items():
        if normalize_code(stored) == key:
            return {"code": stored, **dict(meta)}
    return None


def register_name(code: str, name: str, path: Path | None = None) -> dict[str, Any]:
    """Attach a display name to an unnamed access code."""
    clean_name = " ".join(str(name or "").split())
    if len(clean_name) < 2:
        raise ValueError("Please enter a name with at least 2 characters.")
    store = load_access_store(path)
    entry = lookup_code(code, store)
    if entry is None:
        raise ValueError("Unknown access code.")
    stored_key = entry["code"]
    existing = store["codes"][stored_key].get("name")
    if existing and str(existing).strip():
        raise ValueError("This access code is already registered to a name.")
    now = _utc_now()
    store["codes"][stored_key]["name"] = clean_name
    store["codes"][stored_key]["registered_at"] = now
    save_access_store(store, path)
    return {"code": stored_key, "name": clean_name, "registered_at": now}


def list_access_codes(path: Path | None = None) -> list[dict[str, Any]]:
    """All access codes as rows for admin management."""
    store = load_access_store(path)
    rows: list[dict[str, Any]] = []
    for code, meta in store.get("codes", {}).items():
        rows.append(
            {
                "code": code,
                "name": meta.get("name"),
                "role": str(meta.get("role") or "user"),
                "created_at": meta.get("created_at"),
                "registered_at": meta.get("registered_at"),
                "protected": normalize_code(code) == PROTECTED_ACCESS_CODE,
            }
        )
    rows.sort(key=lambda r: str(r["code"]))
    return rows


def create_access_code(
    code: str,
    *,
    role: str = "user",
    name: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Create a new access code (admin)."""
    key = normalize_code(code)
    if not _CODE_RE.match(key):
        raise ValueError(
            "Invalid access code format (4–64 chars: letters, digits, _ or -)."
        )
    role_n = str(role or "user").strip().lower()
    if role_n not in VALID_ROLES:
        raise ValueError(f"Role must be one of: {', '.join(VALID_ROLES)}")
    clean_name = " ".join(str(name or "").split()) or None
    if clean_name is not None and len(clean_name) < 2:
        raise ValueError("Name must be empty or at least 2 characters.")

    store = load_access_store(path)
    if lookup_code(key, store) is not None:
        raise ValueError(f"Access code `{key}` already exists.")
    now = _utc_now()
    store["codes"][key] = {
        "name": clean_name,
        "role": role_n,
        "created_at": now,
        "registered_at": now if clean_name else None,
    }
    save_access_store(store, path)
    return {"code": key, **store["codes"][key]}


def update_access_code(
    code: str,
    *,
    role: str | None = None,
    name: str | None = None,
    clear_name: bool = False,
    path: Path | None = None,
) -> dict[str, Any]:
    """Update role and/or display name for an access code (admin)."""
    store = load_access_store(path)
    entry = lookup_code(code, store)
    if entry is None:
        raise ValueError("Unknown access code.")
    stored_key = entry["code"]
    meta = store["codes"][stored_key]

    if role is not None:
        role_n = str(role).strip().lower()
        if role_n not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(VALID_ROLES)}")
        if (
            normalize_code(stored_key) == PROTECTED_ACCESS_CODE
            and role_n != "admin"
        ):
            raise ValueError(
                f"`{PROTECTED_ACCESS_CODE}` must keep the admin role."
            )
        meta["role"] = role_n

    if clear_name:
        if normalize_code(stored_key) == PROTECTED_ACCESS_CODE:
            raise ValueError(
                f"Cannot clear the name on `{PROTECTED_ACCESS_CODE}`."
            )
        meta["name"] = None
        meta["registered_at"] = None
    elif name is not None:
        clean_name = " ".join(str(name).split())
        if len(clean_name) < 2:
            raise ValueError("Name must be at least 2 characters.")
        meta["name"] = clean_name
        if not meta.get("registered_at"):
            meta["registered_at"] = _utc_now()

    save_access_store(store, path)
    return {"code": stored_key, **meta}


def delete_access_code(code: str, path: Path | None = None) -> str:
    """Delete an access code (admin). ``HRVADMIN`` cannot be deleted."""
    key = normalize_code(code)
    if key == PROTECTED_ACCESS_CODE:
        raise ValueError(f"`{PROTECTED_ACCESS_CODE}` cannot be deleted.")
    store = load_access_store(path)
    entry = lookup_code(key, store)
    if entry is None:
        raise ValueError("Unknown access code.")
    stored_key = entry["code"]
    del store["codes"][stored_key]
    save_access_store(store, path)
    return stored_key


def log_activity(
    action: str,
    *,
    detail: dict[str, Any] | None = None,
    access_code: str | None = None,
    name: str | None = None,
    path: Path | None = None,
) -> None:
    """Append one JSON line to the activity log."""
    code = access_code or st.session_state.get(SESSION_CODE)
    uname = name if name is not None else st.session_state.get(SESSION_NAME)
    if not code:
        return
    record = {
        "ts": _utc_now(),
        "access_code": normalize_code(str(code)),
        "name": uname,
        "action": str(action),
        "detail": detail or {},
    }
    out = Path(path or ACTIVITY_LOG_PATH)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def is_authenticated() -> bool:
    return bool(st.session_state.get(SESSION_AUTH)) and bool(
        st.session_state.get(SESSION_CODE)
    )


def current_user() -> dict[str, str] | None:
    if not is_authenticated():
        return None
    return {
        "access_code": str(st.session_state.get(SESSION_CODE)),
        "name": str(st.session_state.get(SESSION_NAME) or ""),
        "role": str(st.session_state.get(SESSION_ROLE) or "user"),
    }


def is_admin() -> bool:
    user = current_user()
    return bool(user and user.get("role") == "admin")


def clear_workspace_session() -> None:
    """Drop task/UI session keys so one user cannot keep another's open task."""
    keep = {
        SESSION_AUTH,
        SESSION_CODE,
        SESSION_NAME,
        SESSION_ROLE,
        "hc_pending_code",
    }
    for key in list(st.session_state.keys()):
        if str(key).startswith("hc_") and key not in keep:
            st.session_state.pop(key, None)


def _read_persisted_code() -> str | None:
    """Read access code from cookie or URL query param."""
    try:
        cookies = getattr(st.context, "cookies", None)
        if cookies is not None:
            raw = cookies.get(COOKIE_NAME)
            if raw:
                code = normalize_code(str(raw))
                if _CODE_RE.match(code):
                    return code
    except Exception:
        pass
    try:
        raw = st.query_params.get(AUTH_QUERY_PARAM)
        if raw:
            code = normalize_code(str(raw))
            if _CODE_RE.match(code):
                return code
    except Exception:
        pass
    return None


def _persist_login(code: str) -> None:
    """Keep login across refresh (cookie + query param)."""
    code = normalize_code(code)
    if not _CODE_RE.match(code):
        return
    try:
        st.query_params[AUTH_QUERY_PARAM] = code
    except Exception:
        pass
    # components.html runs in an iframe — set cookie on the parent document.
    components.html(
        f"""<script>
        try {{
          parent.document.cookie = "{COOKIE_NAME}={code}; path=/; max-age={COOKIE_MAX_AGE_SEC}; SameSite=Lax";
        }} catch (e) {{}}
        </script>""",
        height=0,
    )


def _clear_persisted_login() -> None:
    try:
        if AUTH_QUERY_PARAM in st.query_params:
            del st.query_params[AUTH_QUERY_PARAM]
    except Exception:
        pass
    components.html(
        f"""<script>
        try {{
          parent.document.cookie = "{COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
        }} catch (e) {{}}
        </script>""",
        height=0,
    )


def try_restore_session() -> bool:
    """Rebuild session_state from cookie/query after a refresh. Returns True if signed in."""
    if is_authenticated():
        return True
    code = _read_persisted_code()
    if not code:
        return False
    entry = lookup_code(code)
    if entry is None:
        _clear_persisted_login()
        return False
    name = entry.get("name")
    if not name or not str(name).strip():
        st.session_state["hc_pending_code"] = entry["code"]
        return False
    st.session_state[SESSION_AUTH] = True
    st.session_state[SESSION_CODE] = entry["code"]
    st.session_state[SESSION_NAME] = str(name).strip()
    st.session_state[SESSION_ROLE] = str(entry.get("role") or "user")
    st.session_state.pop("hc_pending_code", None)
    return True


def logout() -> None:
    code = st.session_state.get(SESSION_CODE)
    name = st.session_state.get(SESSION_NAME)
    if code:
        log_activity("logout", access_code=str(code), name=name)
    clear_workspace_session()
    for key in (
        SESSION_AUTH,
        SESSION_CODE,
        SESSION_NAME,
        SESSION_ROLE,
        "hc_pending_code",
    ):
        st.session_state.pop(key, None)
    _clear_persisted_login()


def _set_session(code: str, name: str, role: str = "user") -> None:
    clear_workspace_session()
    st.session_state[SESSION_AUTH] = True
    st.session_state[SESSION_CODE] = normalize_code(code)
    st.session_state[SESSION_NAME] = name
    st.session_state[SESSION_ROLE] = str(role or "user")
    st.session_state.pop("hc_pending_code", None)
    _persist_login(code)


def render_auth_sidebar() -> None:
    """Show signed-in identity + logout when authenticated."""
    user = current_user()
    if user is None:
        return
    st.sidebar.markdown("---")
    label = user["name"]
    if user.get("role") == "admin":
        label = f"{label} (admin)"
    st.sidebar.markdown(f"**{label}**")
    st.sidebar.caption(f"Access code: `{user['access_code']}`")
    if st.sidebar.button("Sign out", key="hc_logout"):
        logout()
        st.rerun()


def _access_gate_styles() -> None:
    """Login-page chrome: hide sidebar, soft background, card polish."""
    st.markdown(
        """
        <style>
          [data-testid="stSidebar"],
          [data-testid="stSidebarCollapsedControl"],
          [data-testid="stSidebarCollapseButton"] {
            display: none !important;
          }
          [data-testid="stAppViewContainer"] {
            background:
              radial-gradient(900px 480px at 50% 0%, #dceeea 0%, transparent 55%),
              linear-gradient(180deg, #f7f4ef 0%, #eef2f4 100%);
          }
          [data-testid="stHeader"] { background: transparent; }
          div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #ffffff;
            border: 1px solid rgba(26, 35, 50, 0.08) !important;
            border-radius: 16px !important;
            box-shadow: 0 12px 40px rgba(26, 35, 50, 0.08);
            padding: 0.35rem 0.5rem 0.75rem 0.5rem;
          }
          div.hc-access-brand {
            font-family: "Fraunces", "Palatino Linotype", Palatino, serif;
            font-size: 1.75rem;
            font-weight: 600;
            color: #1a2332;
            text-align: center;
            margin: 0.4rem 0 0.25rem 0;
            line-height: 1.15;
          }
          div.hc-access-sub {
            color: #5c6b7a;
            text-align: center;
            font-size: 0.95rem;
            margin: 0 0 0.85rem 0;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def _access_card(*, title: str, subtitle: str) -> Iterator[None]:
    """Vertically padded, horizontally centered bordered sign-in card."""
    _access_gate_styles()
    st.markdown("<div style='height: 8vh'></div>", unsafe_allow_html=True)
    _left, mid, _right = st.columns([1, 1.2, 1])
    with mid:
        with st.container(border=True):
            st.markdown(
                '<div class="hc-access-brand">HRV Human Classifier</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="hc-access-sub">{subtitle}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"### {title}")
            yield


def require_access(*, show_sidebar: bool = True) -> dict[str, str]:
    """Block the page until a valid access code (and name) are in session.

    ``show_sidebar=False`` is used by the app entry gate so the active page can
    render the sign-out control once (avoids duplicate ``hc_logout`` keys).
    """
    ensure_access_store()
    if not is_authenticated():
        try_restore_session()

    if is_authenticated():
        # Refresh name from store in case it was edited externally.
        entry = lookup_code(str(st.session_state[SESSION_CODE]))
        if entry is None:
            logout()
            st.rerun()
        name = entry.get("name")
        if name and str(name).strip():
            st.session_state[SESSION_NAME] = str(name).strip()
        st.session_state[SESSION_ROLE] = str(entry.get("role") or "user")
        if show_sidebar:
            render_auth_sidebar()
        return current_user()  # type: ignore[return-value]

    pending = st.session_state.get("hc_pending_code")
    if pending:
        entry = lookup_code(str(pending))
        if entry is None:
            st.session_state.pop("hc_pending_code", None)
            with _access_card(
                title="Access",
                subtitle="Enter your pre-issued access code to continue.",
            ):
                st.error("Access code is no longer valid.")
            st.stop()
        with _access_card(
            title="Register",
            subtitle="First-time use — attach your name to this access code.",
        ):
            st.info(f"Access code `{entry['code']}` needs a name before first use.")
            with st.form("hc_register_form"):
                name = st.text_input("Your name", max_chars=80)
                submitted = st.form_submit_button(
                    "Register and continue",
                    type="primary",
                    use_container_width=True,
                )
            if submitted:
                try:
                    reg = register_name(entry["code"], name)
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                role = str(entry.get("role") or "user")
                _set_session(reg["code"], reg["name"], role=role)
                log_activity(
                    "register",
                    detail={"registered_at": reg["registered_at"]},
                    access_code=reg["code"],
                    name=reg["name"],
                )
                log_activity(
                    "login",
                    detail={"via": "register", "role": role},
                    access_code=reg["code"],
                    name=reg["name"],
                )
                st.rerun()
        st.stop()

    with _access_card(
        title="Sign in",
        subtitle="Enter your pre-issued access code to continue.",
    ):
        with st.form("hc_login_form"):
            code_in = st.text_input(
                "Access code", max_chars=64, placeholder="e.g. HRV001"
            )
            submitted = st.form_submit_button(
                "Continue", type="primary", use_container_width=True
            )
        if not submitted:
            st.stop()

        code = normalize_code(code_in)
        if not code:
            st.error("Please enter an access code.")
            st.stop()
        if not _CODE_RE.match(code):
            st.error("Invalid access code format.")
            st.stop()

        entry = lookup_code(code)
        if entry is None:
            st.error("Unknown access code.")
            log_activity(
                "login_failed",
                detail={"reason": "unknown_code", "attempt": code},
                access_code=code,
                name=None,
            )
            st.stop()

        name = entry.get("name")
        if not name or not str(name).strip():
            st.session_state["hc_pending_code"] = entry["code"]
            st.rerun()

        role = str(entry.get("role") or "user")
        _set_session(entry["code"], str(name).strip(), role=role)
        log_activity("login", detail={"via": "existing_name", "role": role})
        st.rerun()

    st.stop()


__all__ = [
    "ACCESS_CODES_PATH",
    "ACTIVITY_LOG_PATH",
    "PROTECTED_ACCESS_CODE",
    "VALID_ROLES",
    "clear_workspace_session",
    "create_access_code",
    "current_user",
    "delete_access_code",
    "ensure_access_store",
    "is_admin",
    "is_authenticated",
    "list_access_codes",
    "load_access_store",
    "log_activity",
    "logout",
    "lookup_code",
    "normalize_code",
    "register_name",
    "require_access",
    "save_access_store",
    "try_restore_session",
    "update_access_code",
]
