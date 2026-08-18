"""Shared Trulioo-inspired presentation layer for every Streamlit page.

Design language: Stripe-grade polish (Inter font, generous whitespace,
subtle shadows, refined borders) layered over Trulioo brand colours.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRAND_LOGO = PROJECT_ROOT / "assets" / "trulioo_wordmark_sidebar.png"


BRAND_CSS = """
<style>
/* ── Google Fonts ─────────────────────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ── Design tokens ────────────────────────────────────────────────────── */
:root {
    /* Brand */
    --t-ink:       #0A1F1E;
    --t-sidebar:   #0F2B28;
    --t-active:    #006B62;
    --t-active-hover: #00564F;
    --t-mint:      #A9DCB8;

    /* Surfaces */
    --t-canvas:    #F7F8FA;
    --t-surface:   #FFFFFF;
    --t-elevated:  #FFFFFF;

    /* Borders & lines */
    --t-border:    #E3E8EF;
    --t-border-subtle: #EEF1F6;
    --t-divider:   #F0F2F5;

    /* Text */
    --t-text:      #0A1F1E;
    --t-text-secondary: #5E6B74;
    --t-text-tertiary:  #8C959F;

    /* Semantic */
    --t-success:   #0D7C5F;
    --t-success-bg:#ECFDF5;
    --t-success-border:#D1FAE5;
    --t-info:      #1A6DD1;
    --t-info-bg:   #EFF6FF;
    --t-info-border:#DBEAFE;
    --t-warning:   #B45309;
    --t-warning-bg:#FFFBEB;
    --t-warning-border:#FEF3C7;
    --t-error:     #DC2626;
    --t-error-bg:  #FEF2F2;
    --t-error-border:#FEE2E2;

    /* Radii */
    --t-radius-sm: 6px;
    --t-radius:    8px;
    --t-radius-lg: 12px;

    /* Shadows */
    --t-shadow-xs:  0 1px 2px rgba(0,0,0,0.04);
    --t-shadow-sm:  0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --t-shadow-md:  0 4px 6px -1px rgba(0,0,0,0.06), 0 2px 4px -2px rgba(0,0,0,0.04);

    /* Transitions */
    --t-ease: cubic-bezier(0.4, 0, 0.2, 1);
}

/* ── Base typography ──────────────────────────────────────────────────── */
html, body, .stApp,
[data-testid="stAppViewContainer"],
p, li, label, span, div, input, textarea, button,
[data-baseweb="select"],
[data-baseweb="input"],
[data-baseweb="textarea"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased !important;
    -moz-osx-font-smoothing: grayscale !important;
}

/* Protect Material Symbols ligature font from the Inter override */
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

p, li, label, input, textarea, button, [data-baseweb="select"] {
    font-size: 0.875rem;
    line-height: 1.55;
    color: var(--t-text);
}

/* ── Headings ─────────────────────────────────────────────────────────── */
h1, h2, h3,
[data-testid="stHeading"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    color: var(--t-ink);
    letter-spacing: -0.025em;
    font-weight: 700;
}

h1 {
    font-size: 1.75rem !important;
    line-height: 1.2 !important;
    margin-bottom: 0.15rem !important;
}

h2 {
    font-size: 1.25rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.02em;
}

h3 {
    font-size: 1.05rem !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}

/* ── Page canvas ──────────────────────────────────────────────────────── */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background: var(--t-canvas);
    color: var(--t-text);
}

header[data-testid="stHeader"] {
    background: transparent;
    backdrop-filter: blur(8px);
}

[data-testid="stMainBlockContainer"],
.stMainBlockContainer,
.main .block-container {
    max-width: 1120px !important;
    margin: 0 auto !important;
    padding: 2rem 3rem 5rem !important;
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: var(--t-sidebar) !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
    min-width: 260px !important;
    width: 260px !important;
    max-width: 260px !important;
}

section[data-testid="stSidebar"] > div,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    background: var(--t-sidebar) !important;
    min-width: 260px !important;
    width: 260px !important;
}

section[data-testid="stSidebar"] [data-testid="stLogo"] {
    align-items: flex-start;
    height: 56px !important;
    margin: 0.75rem 0 0.75rem !important;
    overflow: hidden;
    padding-left: 0.5rem !important;
}

section[data-testid="stSidebar"] img[data-testid="stLogo"],
section[data-testid="stSidebar"] [data-testid="stLogo"] img {
    height: auto !important;
    width: 170px !important;
    max-height: none !important;
    max-width: 170px !important;
    object-fit: contain !important;
    object-position: left center !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
    padding-top: 0.5rem;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNav"] ul {
    gap: 2px;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {
    border-radius: var(--t-radius-sm);
    color: rgba(255,255,255,0.85) !important;
    margin: 0 0.5rem;
    min-height: 36px;
    padding: 0.4rem 0.65rem;
    transition: all 150ms var(--t-ease);
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {
    background: rgba(255, 255, 255, 0.08);
    color: #FFFFFF !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {
    background: var(--t-active) !important;
    box-shadow: none;
    color: #FFFFFF !important;
}

section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] p {
    color: inherit !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    font-size: 0.835rem !important;
    font-weight: 500 !important;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] button {
    color: #FFFFFF !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}

section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div {
    color: rgba(255,255,255,0.9);
}

section[data-testid="stSidebar"] hr {
    border-color: rgba(255, 255, 255, 0.1);
    margin: 0.75rem 0;
}

section[data-testid="stSidebarCollapsedControl"] button,
[data-testid="stSidebarCollapseButton"] button {
    background: var(--t-sidebar) !important;
    border: 1px solid rgba(255,255,255,0.12) !important;
    border-radius: var(--t-radius-sm) !important;
    color: #FFFFFF !important;
}

/* ── Cards & containers ───────────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--t-surface);
    border: 1px solid var(--t-border) !important;
    border-radius: var(--t-radius) !important;
    box-shadow: var(--t-shadow-xs);
    transition: box-shadow 150ms var(--t-ease);
}

[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: var(--t-shadow-sm);
}

/* ── Alerts ───────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {
    border-radius: var(--t-radius) !important;
    font-size: 0.855rem !important;
    line-height: 1.5 !important;
}

/* Success */
[data-testid="stAlert"][data-baseweb="notification"][kind="positive"],
div[data-testid="stAlert"]:has([data-testid="stNotificationContentSuccess"]) {
    background: var(--t-success-bg) !important;
    border: 1px solid var(--t-success-border) !important;
    border-left: 3px solid var(--t-success) !important;
    color: var(--t-text) !important;
}

/* Info */
[data-testid="stAlert"][data-baseweb="notification"][kind="info"],
div[data-testid="stAlert"]:has([data-testid="stNotificationContentInfo"]) {
    background: var(--t-info-bg) !important;
    border: 1px solid var(--t-info-border) !important;
    border-left: 3px solid var(--t-info) !important;
    color: var(--t-text) !important;
}

/* Warning */
[data-testid="stAlert"][data-baseweb="notification"][kind="warning"],
div[data-testid="stAlert"]:has([data-testid="stNotificationContentWarning"]) {
    background: var(--t-warning-bg) !important;
    border: 1px solid var(--t-warning-border) !important;
    border-left: 3px solid var(--t-warning) !important;
    color: var(--t-text) !important;
}

/* Error */
[data-testid="stAlert"][data-baseweb="notification"][kind="negative"],
div[data-testid="stAlert"]:has([data-testid="stNotificationContentError"]) {
    background: var(--t-error-bg) !important;
    border: 1px solid var(--t-error-border) !important;
    border-left: 3px solid var(--t-error) !important;
    color: var(--t-text) !important;
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button {
    border-radius: var(--t-radius-sm) !important;
    border: 1px solid var(--t-border) !important;
    font-weight: 500 !important;
    font-size: 0.855rem !important;
    min-height: 38px;
    padding: 0.45rem 1rem !important;
    transition: all 150ms var(--t-ease);
    box-shadow: var(--t-shadow-xs);
}

.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"],
[data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background: #0D9488 !important;
    border-color: #0D9488 !important;
    color: #FFFFFF !important;
    box-shadow: 0 1px 2px rgba(13, 148, 136, 0.2);
}

.stButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
    background: #0F766E !important;
    border-color: #0F766E !important;
    box-shadow: 0 1px 3px rgba(13, 148, 136, 0.3);
    transform: translateY(-0.5px);
}

.stButton > button:not([kind="primary"]):hover,
.stDownloadButton > button:not([kind="primary"]):hover {
    background: var(--t-canvas) !important;
    border-color: #CDD5DF !important;
    color: var(--t-text) !important;
    box-shadow: var(--t-shadow-sm);
}

/* ── Form inputs ──────────────────────────────────────────────────────── */
[data-baseweb="input"] > div,
[data-baseweb="select"] > div,
[data-baseweb="textarea"] > div {
    background: #FFFFFF !important;
    border: 1px solid var(--t-border) !important;
    border-radius: var(--t-radius-sm) !important;
    transition: border-color 150ms var(--t-ease), box-shadow 150ms var(--t-ease);
}

[data-baseweb="input"] > div:focus-within,
[data-baseweb="select"] > div:focus-within,
[data-baseweb="textarea"] > div:focus-within {
    border-color: var(--t-active) !important;
    box-shadow: 0 0 0 3px rgba(0, 107, 98, 0.12) !important;
}

[data-testid="stFileUploaderDropzone"] {
    background: #FFFFFF !important;
    border: 2px dashed var(--t-border) !important;
    border-radius: var(--t-radius) !important;
    transition: border-color 200ms var(--t-ease), background 200ms var(--t-ease);
    padding: 2rem !important;
}

[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--t-active) !important;
    background: rgba(0, 107, 98, 0.02) !important;
}

/* ── Tabs ─────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 0;
    border-bottom: 1px solid var(--t-border);
}

[data-testid="stTabs"] [data-baseweb="tab"] {
    color: var(--t-text-secondary);
    font-weight: 500;
    font-size: 0.855rem;
    padding: 0.6rem 1rem;
    border-bottom: 2px solid transparent;
    transition: all 150ms var(--t-ease);
}

[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: var(--t-text);
}

[data-testid="stTabs"] [aria-selected="true"] {
    color: var(--t-active) !important;
    border-bottom-color: var(--t-active) !important;
    font-weight: 600;
}

/* ── Metrics ──────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: var(--t-surface);
    border: 1px solid var(--t-border);
    border-radius: var(--t-radius);
    padding: 1rem 1.25rem;
    box-shadow: var(--t-shadow-xs);
}

[data-testid="stMetric"] [data-testid="stMetricLabel"] {
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    color: var(--t-text-secondary) !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: var(--t-ink) !important;
    letter-spacing: -0.02em;
}

/* ── Data tables ──────────────────────────────────────────────────────── */
[data-testid="stDataFrame"],
[data-testid="stTable"] {
    background: var(--t-surface);
    border: 1px solid var(--t-border);
    border-radius: var(--t-radius);
    overflow: hidden;
    box-shadow: var(--t-shadow-xs);
}

/* ── Expanders ────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: var(--t-surface);
    border: 1px solid var(--t-border) !important;
    border-radius: var(--t-radius) !important;
    box-shadow: var(--t-shadow-xs);
    transition: box-shadow 150ms var(--t-ease);
}

[data-testid="stExpander"]:hover {
    box-shadow: var(--t-shadow-sm);
}

[data-testid="stExpander"] summary {
    font-weight: 500;
    font-size: 0.875rem;
}

/* ── Captions & muted text ────────────────────────────────────────────── */
small, .stCaption, [data-testid="stCaptionContainer"] {
    color: var(--t-text-tertiary) !important;
    font-size: 0.8rem !important;
}

/* ── Dividers ─────────────────────────────────────────────────────────── */
hr, [data-testid="stMarkdownContainer"] hr {
    border-color: var(--t-divider) !important;
    opacity: 1;
}

/* ── Download button refinement ───────────────────────────────────────── */
.stDownloadButton > button {
    background: var(--t-surface) !important;
    color: var(--t-text) !important;
}

.stDownloadButton > button[kind="primary"] {
    background: var(--t-active) !important;
    color: #FFFFFF !important;
}

/* ── Checkbox ─────────────────────────────────────────────────────────── */
[data-testid="stCheckbox"] label {
    font-size: 0.855rem !important;
}

/* ── Progress bar ─────────────────────────────────────────────────────── */
[data-testid="stProgress"] > div > div {
    background-color: #34D399 !important;
    border-radius: 20px !important;
}

[data-testid="stProgress"] {
    background: transparent !important;
}

/* Progress text ("Done.", "Starting…", etc.) */
[data-testid="stProgress"] + div,
.stProgress + div {
    background: transparent !important;
}

/* ── Selectbox / multiselect tag pills ────────────────────────────────── */
[data-baseweb="tag"] {
    background: rgba(0, 107, 98, 0.08) !important;
    border: 1px solid rgba(0, 107, 98, 0.2) !important;
    border-radius: var(--t-radius-sm) !important;
    color: var(--t-active) !important;
    font-weight: 500;
}

/* ── Number input ─────────────────────────────────────────────────────── */
[data-testid="stNumberInput"] button {
    border-color: var(--t-border) !important;
}

/* ── Responsive ───────────────────────────────────────────────────────── */
@media (max-width: 900px) {
    [data-testid="stMainBlockContainer"],
    .stMainBlockContainer,
    .main .block-container {
        padding: 1.5rem 1rem 4rem !important;
        max-width: 100% !important;
    }
}

@media (min-width: 1400px) {
    [data-testid="stMainBlockContainer"],
    .stMainBlockContainer,
    .main .block-container {
        max-width: 1200px !important;
    }
}
</style>
"""


def apply_brand_theme() -> None:
    """Add the shared wordmark and application-wide visual styling."""
    if BRAND_LOGO.exists():
        st.logo(str(BRAND_LOGO), size="large")
    st.markdown(BRAND_CSS, unsafe_allow_html=True)
