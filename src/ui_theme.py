"""Shared Trulioo-inspired presentation layer for every Streamlit page."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRAND_LOGO = PROJECT_ROOT / "assets" / "trulioo_wordmark_sidebar.png"


BRAND_CSS = """
<style>
:root {
    --trulioo-ink: #102F2D;
    --trulioo-sidebar: #123330;
    --trulioo-active: #006B62;
    --trulioo-mint: #A9DCB8;
    --trulioo-canvas: #F8F8FE;
    --trulioo-surface: #FFFFFF;
    --trulioo-border: #DDE5E3;
    --trulioo-muted: #647774;
}

html, body {
    font-family: Arial, Helvetica, sans-serif;
}

/* Streamlit renders navigation, expander, and collapse icons as Material
   Symbols ligatures. Never allow the application font to replace this font or
   internal names such as "upload_file" become visible text. */
[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] span,
.material-symbols-rounded,
[class*="material-symbols"] {
    direction: ltr !important;
    display: inline-block !important;
    font-family: "Material Symbols Rounded" !important;
    font-feature-settings: "liga" !important;
    font-style: normal !important;
    font-weight: normal !important;
    letter-spacing: normal !important;
    line-height: 1 !important;
    text-transform: none !important;
    white-space: nowrap !important;
    word-wrap: normal !important;
    -webkit-font-feature-settings: "liga" !important;
    -webkit-font-smoothing: antialiased !important;
}

.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: var(--trulioo-canvas);
    color: var(--trulioo-ink);
}

header[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stMainBlockContainer"],
.stMainBlockContainer,
.main .block-container {
    max-width: none !important;
    width: 100% !important;
    padding: 1.25rem 2.6rem 4rem !important;
}

h1, h2, h3,
[data-testid="stHeading"] {
    color: #0C2524;
    font-family: Georgia, "Times New Roman", serif;
    letter-spacing: -0.015em;
}

h1 {
    font-size: 2rem !important;
    line-height: 1.18 !important;
    margin-bottom: 0.25rem !important;
}

h2 { font-size: 1.5rem !important; }
h3 { font-size: 1.12rem !important; }

p, li, label, input, textarea, button, [data-baseweb="select"] {
    font-size: 0.94rem;
}

section[data-testid="stSidebar"] {
    background: var(--trulioo-sidebar) !important;
    border-right: 0 !important;
    min-width: 270px !important;
    width: 270px !important;
    max-width: 270px !important;
}

section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    background: var(--trulioo-sidebar) !important;
    min-width: 270px !important;
    width: 270px !important;
}

section[data-testid="stSidebar"] [data-testid="stLogo"] {
    align-items: flex-start;
    height: 64px !important;
    margin: 0.55rem 0 0.6rem !important;
    overflow: hidden;
    padding-left: 0.45rem !important;
}

section[data-testid="stSidebar"] img[data-testid="stLogo"],
section[data-testid="stSidebar"] [data-testid="stLogo"] img {
    height: auto !important;
    width: 190px !important;
    max-height: none !important;
    max-width: 190px !important;
    object-fit: contain !important;
    object-position: left center !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
    padding-top: 0.25rem;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
    gap: 0.24rem;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
    border-radius: 7px;
    color: #FFFFFF !important;
    margin: 0 0.45rem;
    min-height: 38px;
    padding: 0.45rem 0.7rem;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {
    background: rgba(255, 255, 255, 0.08);
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {
    background: var(--trulioo-active) !important;
    box-shadow: none;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] p {
    color: #FFFFFF !important;
    font-family: Arial, Helvetica, sans-serif !important;
    font-size: 0.88rem !important;
    font-weight: 600 !important;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] button {
    color: #FFFFFF !important;
    font-family: Arial, Helvetica, sans-serif !important;
}

section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {
    color: #FFFFFF;
}

section[data-testid="stSidebar"] hr {
    border-color: rgba(255, 255, 255, 0.16);
}

section[data-testid="stSidebarCollapsedControl"] button,
[data-testid="stSidebarCollapseButton"] button {
    background: var(--trulioo-sidebar) !important;
    border: 1px solid rgba(255,255,255,0.16) !important;
    color: #FFFFFF !important;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--trulioo-surface);
    border-color: var(--trulioo-border) !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 2px rgba(16, 47, 45, 0.04);
}

[data-testid="stAlert"] {
    background: #E8F2EA !important;
    border: 1px solid #D0E4D5 !important;
    border-left: 4px solid var(--trulioo-active) !important;
    border-radius: 7px !important;
    color: var(--trulioo-ink) !important;
}

.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button {
    border-radius: 7px !important;
    border-color: var(--trulioo-active) !important;
    font-weight: 600 !important;
    min-height: 40px;
}

.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"],
[data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background: var(--trulioo-active) !important;
    color: #FFFFFF !important;
}

.stButton > button:hover,
.stDownloadButton > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {
    border-color: #00564F !important;
    color: #00564F !important;
}

[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-baseweb="textarea"] > div,
[data-testid="stFileUploaderDropzone"] {
    background: #FFFFFF !important;
    border-color: #CAD7D4 !important;
    border-radius: 7px !important;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0.4rem;
    border-bottom: 1px solid var(--trulioo-border);
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    color: var(--trulioo-muted);
    font-weight: 600;
    padding-left: 0.9rem;
    padding-right: 0.9rem;
}

[data-testid="stTabs"] [aria-selected="true"] {
    color: var(--trulioo-active) !important;
}

[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid var(--trulioo-border);
    border-radius: 8px;
    padding: 0.8rem 1rem;
}

[data-testid="stDataFrame"],
[data-testid="stTable"] {
    background: #FFFFFF;
    border-radius: 8px;
    overflow: hidden;
}

[data-testid="stExpander"] {
    background: #FFFFFF;
    border-color: var(--trulioo-border) !important;
    border-radius: 8px !important;
}

small, .stCaption, [data-testid="stCaptionContainer"] {
    color: var(--trulioo-muted) !important;
}

@media (max-width: 900px) {
    [data-testid="stMainBlockContainer"],
    .stMainBlockContainer,
    .main .block-container {
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
}
</style>
"""


def apply_brand_theme() -> None:
    """Add the shared wordmark and application-wide visual styling."""
    if BRAND_LOGO.exists():
        st.logo(str(BRAND_LOGO), size="large")
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
