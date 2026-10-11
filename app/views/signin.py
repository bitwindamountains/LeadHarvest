"""Sign-in screen: brand panel beside a password card (the panel hides itself on phones)."""

from __future__ import annotations

import time

import streamlit as st

from leadharvest.config import Settings
from leadharvest.ui_support import password_ok

from views.common import ASSETS, MARK, eyebrow


def sign_in(settings: Settings) -> None:
    """Render the sign-in screen and stop the script until the password is right."""
    brand, form = st.columns([1.15, 1], gap="large", vertical_alignment="center")
    with brand:
        st.html((ASSETS / "brand_panel.html").read_text(encoding="utf-8"))
    with form:
        st.image(MARK, width=34)
        eyebrow("Private workspace")
        st.title("Sign in", anchor=False)
        if not settings.ui_password:
            st.error("Set LH_UI_PASSWORD in .env (or app secrets) so strangers can't run scrapes.")
            st.stop()
        st.caption("Enter the workspace password. It's set as LH_UI_PASSWORD in `.env`.")
        with st.form("sign_in"):
            attempt = st.text_input("Password", type="password", placeholder="Workspace password")
            if st.form_submit_button(
                "Sign in", type="primary", width="stretch", icon=":material/login:"
            ):
                if password_ok(settings, attempt):
                    st.session_state["authed"] = True
                    st.rerun()
                # Slows guessing; a new session per guess gets the same delay.
                time.sleep(1)
                st.error("Wrong password. Check LH_UI_PASSWORD in `.env`.")
    st.stop()
