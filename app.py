"""Navigation entry point for the Standardization Tool."""

from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="Standardization Tool",
    page_icon="✓",
    layout="wide",
    initial_sidebar_state="expanded",
)

navigation = st.navigation([
    st.Page(
        "standardize_page.py",
        title="Standardize a File",
        icon=":material/upload_file:",
        default=True,
    ),
    st.Page(
        "pages/1_Help_and_Field_Guide.py",
        title="Help & Field Guide",
        icon=":material/menu_book:",
    ),
    st.Page(
        "pages/2_Review_Corrections.py",
        title="Review Corrections",
        icon=":material/rule:",
    ),
])
navigation.run()
