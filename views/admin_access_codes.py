"""Admin: manage access codes and roles."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from access_lib import (  # noqa: E402
    PROTECTED_ACCESS_CODE,
    VALID_ROLES,
    create_access_code,
    current_user,
    delete_access_code,
    is_admin,
    list_access_codes,
    log_activity,
    normalize_code,
    require_access,
    update_access_code,
)

user = require_access()
if not is_admin():
    st.error("Admin access required.")
    st.stop()

if st.session_state.get("hc_logged_access_admin") != user["access_code"]:
    log_activity("view_page", detail={"page": "admin_access_codes"})
    st.session_state["hc_logged_access_admin"] = user["access_code"]

st.title("Admin · access codes")
st.caption(
    "Create and manage access codes and roles. "
    f"`{PROTECTED_ACCESS_CODE}` cannot be deleted."
)

rows = list_access_codes()
table = pd.DataFrame(
    [
        {
            "code": r["code"],
            "name": r["name"] or "—",
            "role": r["role"],
            "created_at": r.get("created_at") or "—",
            "registered_at": r.get("registered_at") or "—",
            "protected": "yes" if r["protected"] else "",
        }
        for r in rows
    ]
)
st.markdown("### Current codes")
st.dataframe(table, use_container_width=True, hide_index=True)

st.markdown("### Add access code")
with st.form("hc_admin_create_code"):
    c1, c2 = st.columns(2)
    with c1:
        new_code = st.text_input("Access code", max_chars=64, placeholder="e.g. HRV011")
    with c2:
        new_role = st.selectbox("Role", options=list(VALID_ROLES), index=0)
    new_name = st.text_input(
        "Display name (optional)",
        max_chars=80,
        help="Leave blank so the user registers their own name on first login.",
    )
    create_ok = st.form_submit_button("Create code", type="primary")
if create_ok:
    try:
        created = create_access_code(
            new_code,
            role=str(new_role),
            name=new_name or None,
        )
    except ValueError as exc:
        st.error(str(exc))
    else:
        log_activity(
            "access_code_created",
            detail={
                "code": created["code"],
                "role": created.get("role"),
                "name": created.get("name"),
            },
        )
        st.success(f"Created `{created['code']}` ({created['role']}).")
        st.rerun()

st.markdown("### Edit access code")
edit_codes = [r["code"] for r in rows]
edit_pick = st.selectbox("Select code", options=edit_codes, key="hc_admin_edit_pick")
edit_meta = next(r for r in rows if r["code"] == edit_pick)
is_protected = bool(edit_meta["protected"])

# Keys include the selected code so Streamlit resets widgets when the pick changes
# (a fixed key keeps the previous code's empty/stale name in session_state).
_name_key = f"hc_admin_edit_name_{edit_pick}"
_clear_key = f"hc_admin_clear_name_{edit_pick}"
_role_key = f"hc_admin_edit_role_{edit_pick}"
if _name_key not in st.session_state:
    st.session_state[_name_key] = str(edit_meta["name"] or "")

with st.form("hc_admin_edit_code"):
    role_opts = list(VALID_ROLES)
    role_index = role_opts.index(edit_meta["role"]) if edit_meta["role"] in role_opts else 0
    edit_role = st.selectbox(
        "Role",
        options=role_opts,
        index=role_index,
        disabled=is_protected,
        key=_role_key,
        help=(
            f"`{PROTECTED_ACCESS_CODE}` must remain admin."
            if is_protected
            else "user or admin"
        ),
    )
    edit_name = st.text_input(
        "Display name",
        max_chars=80,
        key=_name_key,
    )
    clear_name = st.checkbox(
        "Clear name (require re-registration)",
        value=False,
        disabled=is_protected,
        key=_clear_key,
    )
    save_ok = st.form_submit_button("Save changes", type="primary")
if save_ok:
    try:
        updated = update_access_code(
            edit_pick,
            role=None if is_protected else str(edit_role),
            name=None if clear_name else (edit_name or None),
            clear_name=bool(clear_name) and not is_protected,
        )
    except ValueError as exc:
        st.error(str(exc))
    else:
        log_activity(
            "access_code_updated",
            detail={
                "code": updated["code"],
                "role": updated.get("role"),
                "name": updated.get("name"),
            },
        )
        st.success(f"Updated `{updated['code']}`.")
        st.rerun()

st.markdown("### Delete access code")
deletable = [r["code"] for r in rows if not r["protected"]]
if not deletable:
    st.info(f"No deletable codes (only `{PROTECTED_ACCESS_CODE}` remains).")
else:
    del_pick = st.selectbox("Code to delete", options=deletable, key="hc_admin_del_pick")
    me = current_user() or {}
    if normalize_code(del_pick) == normalize_code(str(me.get("access_code") or "")):
        st.warning("You are about to delete your own signed-in access code.")
    confirm = st.text_input(
        f"Type `{del_pick}` to confirm deletion",
        key="hc_admin_del_confirm",
    )
    if st.button("Delete code", type="primary", key="hc_admin_del_btn"):
        if confirm.strip().upper() != del_pick.upper():
            st.error("Confirmation text does not match.")
        else:
            try:
                deleted = delete_access_code(del_pick)
            except ValueError as exc:
                st.error(str(exc))
            else:
                log_activity("access_code_deleted", detail={"code": deleted})
                st.success(f"Deleted `{deleted}`.")
                st.rerun()
