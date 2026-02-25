"""Veranda — NYC Luxury Service Lead Command Center.

A Streamlit command center with a master-detail layout for identifying
and engaging high-net-worth leads through public wealth signals.

Layout:
  Left Sidebar  — Business profile input + collapsible NYC filters
  Center Gallery — Selectable lead table (Bloomberg-style)
  Right Drawer   — Detail panel that slides in on row click
"""

import os
import sys
import logging
import math
from datetime import datetime
from urllib.parse import quote_plus

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from src.engines.real_estate import fetch_properties, NEIGHBORHOOD_ZIP_CODES
from src.engines.outreach_generator import (
    generate_outreach_for_lead,
    parse_lead_criteria,
    _get_llm_key,
)
from src.engines.professional_mapping import generate_search_links
from src.engines.sec_edgar import fetch_insider_sales, configure_edgar
from src.engines.fec import fetch_fec_donors
from src.utils.pdf_extractor import extract_text_from_pdf
from src.models.lead import Lead, LeadSource
from src.db import (
    get_connection,
    init_db,
    save_leads,
    query_leads,
    get_lead_count,
    get_last_sync,
    update_outreach,
    _make_name_key,
)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

LEADS_PER_PAGE = 100

# ── Reverse-map ZIP → Neighborhood ───────────────────────────────────────────
ZIP_TO_NEIGHBORHOOD: dict[str, str] = {}
for _nbhd, _zips in NEIGHBORHOOD_ZIP_CODES.items():
    for _z in _zips:
        ZIP_TO_NEIGHBORHOOD[_z] = _nbhd

# ─── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Veranda",
    page_icon="🏡",
    layout="wide",
)

# ─── LUXURY THEME ─────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&family=Inter:wght@300;400;500;600&display=swap');

/* ── Palette ─────────────────────────────────────────────────────────────── */
:root {
  --bg:           #0C0C0F;
  --bg-sidebar:   #0F0F14;
  --bg-card:      #16161C;
  --bg-hover:     #1D1D26;
  --gold:         #C8A96E;
  --gold-dim:     #7A6535;
  --gold-faint:   rgba(200,169,110,0.10);
  --text:         #EDE8E0;
  --text-dim:     #7A7570;
  --border:       #252530;
  --border-gold:  rgba(200,169,110,0.28);
  --serif:        'Cormorant Garamond', Georgia, serif;
  --sans:         'Inter', system-ui, sans-serif;
}

/* ── Base ─────────────────────────────────────────────────────────────────── */
.stApp, body, html {
  background-color: var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--sans) !important;
}
header[data-testid="stHeader"] { display: none !important; }
.block-container {
  padding-top: 1.5rem !important;
  padding-bottom: 4rem !important;
  max-width: 100% !important;
  padding-left: 2rem !important;
  padding-right: 2rem !important;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background-color: var(--bg-sidebar) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] > div {
  background-color: var(--bg-sidebar) !important;
}

/* ── Typography ──────────────────────────────────────────────────────────── */
h1, h2, h3 {
  font-family: var(--serif) !important;
  font-weight: 400 !important;
  color: var(--text) !important;
  letter-spacing: 0.02em !important;
}
p, li { font-family: var(--sans) !important; font-size: 13px !important; }
label {
  font-family: var(--sans) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  color: var(--text-dim) !important;
}

/* ── Inputs ──────────────────────────────────────────────────────────────── */
.stTextInput input,
.stTextArea textarea {
  background-color: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 3px !important;
  color: var(--text) !important;
  font-family: var(--sans) !important;
  font-size: 13px !important;
}
.stTextInput input:focus,
.stTextArea textarea:focus {
  border-color: var(--gold-dim) !important;
  box-shadow: 0 0 0 1px var(--gold-dim) !important;
}
input::placeholder, textarea::placeholder { color: var(--text-dim) !important; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton button {
  font-family: var(--sans) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  letter-spacing: 0.12em !important;
  text-transform: uppercase !important;
  border-radius: 3px !important;
  transition: all 0.15s ease !important;
}
.stButton button[kind="primary"] {
  background-color: var(--gold) !important;
  color: #0C0C0F !important;
  border: none !important;
}
.stButton button[kind="primary"]:hover { background-color: #D4B878 !important; }
.stButton button[kind="secondary"] {
  background-color: transparent !important;
  border: 1px solid var(--border) !important;
  color: var(--text-dim) !important;
}
.stButton button[kind="secondary"]:hover {
  border-color: var(--gold-dim) !important;
  color: var(--text) !important;
}

/* ── Metrics ─────────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
  background-color: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  padding: 1rem 1.25rem !important;
}
[data-testid="stMetricValue"] {
  font-family: var(--serif) !important;
  font-size: 1.8rem !important;
  color: var(--gold) !important;
}
[data-testid="stMetricLabel"] {
  font-size: 10px !important;
  letter-spacing: 0.1em !important;
  text-transform: uppercase !important;
  color: var(--text-dim) !important;
}

/* ── Expanders ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
  background-color: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  margin-bottom: 0.4rem !important;
}
[data-testid="stExpander"] summary {
  font-size: 10px !important;
  font-weight: 600 !important;
  letter-spacing: 0.14em !important;
  text-transform: uppercase !important;
  color: var(--text-dim) !important;
}

/* ── Checkboxes / Sliders ────────────────────────────────────────────────── */
.stCheckbox label span,
.stCheckbox label p,
.stRadio label span,
.stRadio label p,
[data-testid="stCheckbox"] label p,
[data-testid="stCheckbox"] label span {
  font-family: var(--sans) !important;
  font-size: 12px !important;
  color: #EDE8E0 !important;
  text-transform: none !important;
  letter-spacing: normal !important;
  font-weight: 400 !important;
}

/* ── Dividers ────────────────────────────────────────────────────────────── */
hr { border-color: var(--border) !important; margin: 1.25rem 0 !important; }

/* ── Info / Warning / Error ──────────────────────────────────────────────── */
[data-testid="stAlert"] {
  background-color: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 4px !important;
  color: var(--text) !important;
}

/* ── Caption / small text ────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"] {
  color: var(--text-dim) !important;
  font-size: 11px !important;
}

/* ── File uploader — hidden, triggered by JS link ────────────────────────── */
[data-testid="stFileUploader"] {
  position: fixed !important;
  left: -9999px !important;
  top: -9999px !important;
}

/* ── Scrollbar ───────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

/* ── Detail panel prose ──────────────────────────────────────────────────── */
.detail-name {
  font-family: var(--serif);
  font-size: 1.75rem;
  font-weight: 400;
  color: var(--text);
  line-height: 1.15;
  margin-bottom: 0.2rem;
}
.detail-trigger {
  font-size: 10px;
  color: var(--gold);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 1.25rem;
}
.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 0.45rem 0;
  border-bottom: 1px solid var(--border);
}
.detail-label {
  font-size: 10px;
  color: var(--text-dim);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  white-space: nowrap;
  margin-right: 1rem;
  flex-shrink: 0;
}
.detail-value {
  font-size: 13px;
  color: var(--text);
  font-family: var(--sans);
  text-align: right;
}
.source-badge {
  display: inline-block;
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 2px 8px;
  border-radius: 2px;
  background: var(--gold-faint);
  color: var(--gold);
  border: 1px solid var(--border-gold);
}
.section-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--gold-dim);
  margin-bottom: 0.75rem;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--border);
}

/* ── Welcome hero ────────────────────────────────────────────────────────── */
.welcome-hero { text-align: center; padding: 5rem 2rem; }
.welcome-title {
  font-family: var(--serif);
  font-size: 4rem;
  font-weight: 300;
  color: var(--text);
  letter-spacing: 0.06em;
}
.welcome-rule {
  width: 40px;
  height: 1px;
  background: var(--gold);
  margin: 1.75rem auto;
}
.welcome-sub {
  font-size: 11px;
  color: var(--text-dim);
  letter-spacing: 0.2em;
  text-transform: uppercase;
}
.welcome-body {
  font-size: 13px;
  color: var(--text-dim);
  max-width: 480px;
  margin: 2rem auto 0;
  line-height: 1.9;
}
</style>
""",
    unsafe_allow_html=True,
)

# ─── DATABASE ─────────────────────────────────────────────────────────────────
@st.cache_resource
def _get_db():
    conn = get_connection()
    init_db(conn)
    return conn


_db = _get_db()


# ─── UTILITIES ────────────────────────────────────────────────────────────────
def _deduplicate_leads(leads: list[Lead]) -> list[Lead]:
    """Keep highest-value entry per unique person."""
    seen: dict[str, Lead] = {}
    for lead in leads:
        key = f"{lead.first_name}_{lead.last_name}".lower().strip("_")
        if key not in seen or (lead.estimated_wealth or 0) > (seen[key].estimated_wealth or 0):
            seen[key] = lead
    return list(seen.values())


def _get_neighborhood(lead: Lead) -> str:
    return ZIP_TO_NEIGHBORHOOD.get(lead.zip_code or "", "Other")


def _fmt_value(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def _source_label(source: LeadSource) -> str:
    return {
        LeadSource.TAX_ASSESSOR: "Property",
        LeadSource.SEC_EDGAR: "Insider Sale",
        LeadSource.FEC_CAMPAIGN_FINANCE: "Donor",
        LeadSource.PROFESSIONAL_MAPPING: "Professional",
        LeadSource.MANUAL: "Manual",
    }.get(source, source.value)


# ─── BROWSE-ALL SHORTCUT ──────────────────────────────────────────────────────
if st.query_params.get("browse_all") == "1":
    with st.spinner("Loading leads from database..."):
        leads_all = query_leads(_db, max_value=35_000_000, limit=10_000)
    st.session_state["leads"] = leads_all
    st.session_state["search_done"] = True
    st.session_state["current_page"] = 0
    st.session_state.pop("selected_lead_idx", None)
    del st.query_params["browse_all"]
    st.rerun()


# ─── SIDEBAR ──────────────────────────────────────────────────────────────────
with st.sidebar:
    # ── Brand mark ──
    st.markdown(
        """
        <div style="padding: 1rem 0 1.5rem;">
          <div style="font-family:'Cormorant Garamond',serif; font-size:1.55rem;
                      font-weight:400; letter-spacing:0.1em; color:#EDE8E0;">
            VERANDA
          </div>
          <div style="font-size:9px; letter-spacing:0.2em; text-transform:uppercase;
                      color:#7A7570; margin-top:3px;">
            NYC Intelligence Platform
          </div>
          <div style="height:1px; background:#252530; margin-top:1rem;"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Status line ──
    _last_sync = get_last_sync(_db)
    _db_count = get_lead_count(_db)
    if _last_sync:
        try:
            _sync_dt = datetime.fromisoformat(_last_sync).strftime("%b %d, %Y")
        except ValueError:
            _sync_dt = _last_sync
        st.markdown(
            f"<p style='font-size:11px; color:#7A7570; margin-bottom:1.25rem;'>"
            f"{_db_count:,} leads · synced {_sync_dt}</p>",
            unsafe_allow_html=True,
        )

    # ── Business profile ──
    st.markdown('<div class="section-label">Your Business</div>', unsafe_allow_html=True)

    components.html(
        """
        <style>
          * { box-sizing:border-box; margin:0; padding:0; }
          body {
            font-family: 'Inter', sans-serif; font-size: 12px;
            color: #7A7570; line-height: 1.55;
          }
          a { color: #C8A96E; text-decoration: none; }
          a:hover { text-decoration: underline; }
        </style>
        <p>Describe your service, or
          <a href="#" id="upload-link">upload a PDF</a>.
        </p>
        <script>
          document.getElementById('upload-link').addEventListener('click', function(e) {
            e.preventDefault();
            var inp = window.parent.document.querySelector(
              '[data-testid="stFileUploaderDropzone"] input[type="file"]'
            );
            if (inp) inp.click();
          });
        </script>
        """,
        height=22,
        scrolling=False,
    )

    uploaded_pdf = st.file_uploader(
        "upload",
        type=["pdf"],
        key="pdf_upload",
        label_visibility="collapsed",
    )

    service_description = st.text_area(
        "Business description",
        height=120,
        placeholder=(
            "e.g. Boutique interior design firm specializing in pre-war "
            "brownstone renovations. Ideal clients own $3M+ homes in the "
            "West Village, Tribeca, or Park Slope."
        ),
        key="service_desc",
        label_visibility="collapsed",
    )

    if uploaded_pdf is not None:
        extracted = extract_text_from_pdf(uploaded_pdf)
        if extracted:
            service_description = extracted
            st.caption(f"Using PDF · {len(extracted):,} characters")
        else:
            st.warning("Could not extract text from this PDF.")

    if not _get_llm_key():
        st.caption("Add GROQ_API_KEY for AI neighborhood selection")

    generate_btn = st.button(
        "Generate Leads",
        type="primary",
        use_container_width=True,
        key="generate_btn",
    )

    # ── Neighborhood filter (always visible, all neighborhoods) ───────────────
    st.markdown("<div style='height:1.25rem;'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-label">Refine Results</div>', unsafe_allow_html=True)

    _all_nbhds = sorted(NEIGHBORHOOD_ZIP_CODES.keys())
    with st.expander("Neighborhood", expanded=False):
        _sel_nbhds = [
            n for n in _all_nbhds
            if st.checkbox(n, value=False, key=f"nbhd_{n}")
        ]
    st.session_state["_f_nbhds"] = _sel_nbhds


# ─── GENERATE LEADS ───────────────────────────────────────────────────────────
if generate_btn:
    if not service_description.strip():
        st.warning("Please describe your business first.")
    else:
        try:
            with st.spinner("Analyzing your business profile..."):
                criteria = parse_lead_criteria(service_description.strip())

            selected_neighborhoods = criteria["neighborhoods"]
            min_market_value = criteria["min_value"]
            residential_only = criteria["residential_only"]
            individuals_only = criteria["individuals_only"]
            include_condos = criteria["include_condos"]

            st.info(
                f"Targeting **{len(selected_neighborhoods)} neighborhoods** "
                f"({', '.join(selected_neighborhoods)}), "
                f"properties over **${min_market_value:,.0f}**"
            )

            zip_codes: list[str] = []
            for name in selected_neighborhoods:
                zip_codes.extend(NEIGHBORHOOD_ZIP_CODES.get(name, []))

            db_count = get_lead_count(_db)

            if db_count > 0:
                leads = query_leads(
                    _db,
                    zip_codes=zip_codes if zip_codes else None,
                    min_value=min_market_value,
                    max_value=35_000_000,
                    residential_only=residential_only,
                    individuals_only=individuals_only,
                )
            else:
                with st.spinner("Searching NYC properties and SEC insider sales..."):
                    progress_cb = None
                    if include_condos:
                        acris_status = st.empty()
                        acris_bar = st.progress(0, text="Preparing condo search...")

                        def progress_cb(completed: int, total: int) -> None:
                            pct = completed / total if total > 0 else 0
                            acris_bar.progress(
                                pct,
                                text=f"Scanning condo deed records… ({completed}/{total})",
                            )

                    leads = fetch_properties(
                        zip_codes=zip_codes,
                        min_market_value=min_market_value,
                        limit=50_000,
                        residential_only=residential_only,
                        individuals_only=individuals_only,
                        include_condos=include_condos,
                        app_token=os.getenv("SOCRATA_APP_TOKEN"),
                        progress_callback=progress_cb,
                    )

                if include_condos:
                    acris_bar.empty()
                    acris_status.empty()

                try:
                    configure_edgar()
                    sec_leads = fetch_insider_sales(lookback_days=30, max_filings=1_000)
                    leads = leads + sec_leads
                except Exception as sec_exc:
                    logger.warning("SEC EDGAR fetch failed: %s", sec_exc)

                try:
                    fec_leads = fetch_fec_donors(
                        min_donation=2_500.0, lookback_days=180, max_results=0
                    )
                    leads = leads + fec_leads
                except Exception as fec_exc:
                    logger.warning("FEC fetch failed: %s", fec_exc)

                leads = _deduplicate_leads(leads)

                try:
                    save_leads(_db, leads)
                except Exception as db_exc:
                    logger.warning("Failed to save leads to DB: %s", db_exc)

            st.session_state["leads"] = leads
            st.session_state["service_description"] = service_description.strip()
            st.session_state["search_done"] = True
            st.session_state["current_page"] = 0
            st.session_state.pop("selected_lead_idx", None)

        except Exception as exc:
            st.error(f"Error: {exc}")
            st.session_state["search_done"] = False


# ─── MAIN CONTENT ─────────────────────────────────────────────────────────────
if not st.session_state.get("search_done"):
    # ── Welcome / hero screen ──────────────────────────────────────────────────
    st.markdown(
        """
        <div class="welcome-hero">
          <div class="welcome-title">Veranda</div>
          <div class="welcome-rule"></div>
          <div class="welcome-sub">NYC Luxury Lead Intelligence</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

else:
    # ── Retrieve + sort leads ──────────────────────────────────────────────────
    all_leads: list[Lead] = st.session_state.get("leads", [])
    sorted_leads = sorted(all_leads, key=lambda l: l.estimated_wealth or 0, reverse=True)

    # ── Apply sidebar filters ──────────────────────────────────────────────────
    def _apply_filters(leads: list[Lead]) -> list[Lead]:
        f_nbhds: list[str] = st.session_state.get("_f_nbhds", [])
        result = []
        for lead in leads:
            nbhd = _get_neighborhood(lead)
            if f_nbhds and nbhd != "Other" and nbhd not in f_nbhds:
                continue
            result.append(lead)
        return result

    filtered_leads = _apply_filters(sorted_leads)

    if not filtered_leads:
        st.warning("No leads match the current filters. Adjust the sidebar to broaden results.")
        st.stop()

    # ── Metrics row ───────────────────────────────────────────────────────────
    st.metric("Total Leads", f"{len(filtered_leads):,}")

    st.markdown("<div style='height:1rem;'></div>", unsafe_allow_html=True)

    # ── Search bar ────────────────────────────────────────────────────────────
    search_query = st.text_input(
        "Search",
        placeholder="Search by name, address, neighborhood, or company…",
        key="lead_search",
        label_visibility="collapsed",
    )
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_leads = [
            l
            for l in filtered_leads
            if q
            in " ".join(
                filter(
                    None,
                    [
                        l.full_name,
                        l.address,
                        l.company,
                        l.building_type,
                        l.professional_title,
                        _get_neighborhood(l),
                    ],
                )
            ).lower()
        ]
        st.caption(
            f"{len(filtered_leads)} result{'s' if len(filtered_leads) != 1 else ''} "
            f"for \"{search_query.strip()}\""
        )

    # ── Pagination state ──────────────────────────────────────────────────────
    total_leads = len(filtered_leads)
    total_pages = max(1, math.ceil(total_leads / LEADS_PER_PAGE))
    current_page = min(
        st.session_state.get("current_page", 0), total_pages - 1
    )
    start_idx = current_page * LEADS_PER_PAGE
    end_idx = min(start_idx + LEADS_PER_PAGE, total_leads)
    page_leads = filtered_leads[start_idx:end_idx]

    # ── Determine layout: split if a lead is selected ─────────────────────────
    selected_idx = st.session_state.get("selected_lead_idx")
    has_selection = selected_idx is not None and selected_idx < len(filtered_leads)

    if has_selection:
        gallery_col, detail_col = st.columns([5, 4], gap="large")
    else:
        gallery_col = st.container()
        detail_col = None

    # ── Gallery ───────────────────────────────────────────────────────────────
    with gallery_col:
        rows = []
        for i, lead in enumerate(page_leads):
            is_llc = lead.company is not None and lead.first_name == ""
            owner = lead.company if is_llc else lead.full_name
            nbhd = _get_neighborhood(lead)

            info_parts: list[str] = []
            if lead.source == LeadSource.SEC_EDGAR:
                if lead.professional_title:
                    info_parts.append(lead.professional_title)
                if lead.company:
                    info_parts.append(lead.company)
            elif lead.source == LeadSource.FEC_CAMPAIGN_FINANCE:
                if lead.company:
                    info_parts.append(lead.company)
                if lead.city:
                    info_parts.append(lead.city)
            else:
                if lead.address:
                    addr = lead.address
                    if lead.unit_number:
                        addr += f", Unit {lead.unit_number}"
                    info_parts.append(addr)
                if lead.building_type:
                    info_parts.append(lead.building_type)
                if nbhd != "Other":
                    info_parts.append(nbhd)

            rows.append(
                {
                    "Name": owner,
                    "Details": " · ".join(info_parts) if info_parts else "—",
                }
            )

        df = pd.DataFrame(rows)

        table_event = st.dataframe(
            df,
            column_config={
                "Name": st.column_config.TextColumn(width="medium"),
                "Details": st.column_config.TextColumn(width="large"),
            },
            hide_index=True,
            use_container_width=True,
            selection_mode="single-row",
            on_select="rerun",
            key="lead_table",
            height=min(620, max(200, 38 + len(df) * 35)),
        )

        # Handle row selection from the dataframe
        _sel_rows = (
            table_event.selection.rows
            if hasattr(table_event, "selection") and table_event.selection
            else []
        )
        if _sel_rows:
            _new_idx = start_idx + _sel_rows[0]
            if _new_idx != st.session_state.get("selected_lead_idx"):
                st.session_state["selected_lead_idx"] = _new_idx
                st.rerun()

        # Pagination controls
        if total_pages > 1:
            st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
            pg_caption, prev_btn, pg_info, next_btn = st.columns([3, 1, 1, 1])
            pg_caption.caption(f"Showing {start_idx + 1}–{end_idx} of {total_leads} leads")

            with prev_btn:
                if st.button(
                    "← Prev",
                    disabled=(current_page == 0),
                    use_container_width=True,
                    key="prev_page",
                ):
                    st.session_state["current_page"] = current_page - 1
                    st.session_state.pop("selected_lead_idx", None)
                    st.rerun()

            pg_info.markdown(
                f"<div style='text-align:center; padding:6px 0; font-size:11px; "
                f"color:#7A7570;'>{current_page + 1} / {total_pages}</div>",
                unsafe_allow_html=True,
            )

            with next_btn:
                if st.button(
                    "Next →",
                    disabled=(current_page >= total_pages - 1),
                    use_container_width=True,
                    key="next_page",
                ):
                    st.session_state["current_page"] = current_page + 1
                    st.session_state.pop("selected_lead_idx", None)
                    st.rerun()

    # ── Detail Drawer ─────────────────────────────────────────────────────────
    if has_selection and detail_col is not None:
        lead = filtered_leads[selected_idx]
        is_llc = lead.company is not None and lead.first_name == ""
        display_name = lead.company if is_llc else lead.full_name
        has_llm = _get_llm_key() is not None
        nbhd = _get_neighborhood(lead)

        with detail_col:
            # Close button
            _close_col, _ = st.columns([2, 5])
            with _close_col:
                if st.button("✕  Close", key="close_detail"):
                    st.session_state.pop("selected_lead_idx", None)
                    st.session_state.pop("lead_table", None)
                    st.rerun()

            st.markdown("<div style='height:0.25rem;'></div>", unsafe_allow_html=True)

            # Name + trigger headline
            st.markdown(
                f'<div class="detail-name">{display_name}</div>'
                f'<div class="detail-trigger">{lead.discovery_trigger}</div>',
                unsafe_allow_html=True,
            )

            # Source badge + value
            _badge_col, _val_col = st.columns([3, 2])
            with _badge_col:
                st.markdown(
                    f'<span class="source-badge">{_source_label(lead.source)}</span>',
                    unsafe_allow_html=True,
                )
            with _val_col:
                st.markdown(
                    f"<div style='text-align:right; font-family:\"Cormorant Garamond\",serif;"
                    f" font-size:1.4rem; color:#C8A96E;'>"
                    f"{_fmt_value(lead.estimated_wealth)}</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<hr>", unsafe_allow_html=True)

            # Property / profile data rows
            def _row(label: str, value: str) -> None:
                st.markdown(
                    f'<div class="detail-row">'
                    f'<span class="detail-label">{label}</span>'
                    f'<span class="detail-value">{value}</span>'
                    f"</div>",
                    unsafe_allow_html=True,
                )

            if lead.source == LeadSource.SEC_EDGAR:
                if lead.professional_title:
                    _row("Title", lead.professional_title)
                if lead.company:
                    _row("Company", lead.company)
                if lead.estimated_wealth:
                    _row("Insider Sale", f"${lead.estimated_wealth:,.0f}")

            elif lead.source == LeadSource.FEC_CAMPAIGN_FINANCE:
                if lead.professional_title:
                    _row("Occupation", lead.professional_title)
                if lead.company:
                    _row("Employer", lead.company)
                if lead.city and lead.state:
                    _row("Location", f"{lead.city}, {lead.state}")
                if lead.zip_code:
                    _row("ZIP", lead.zip_code)
                if lead.estimated_wealth:
                    _row("Donation Amount", f"${lead.estimated_wealth:,.0f}")

            else:
                if lead.address:
                    addr = lead.address
                    if lead.unit_number:
                        addr += f", Unit {lead.unit_number}"
                    _row("Address", addr)
                if nbhd != "Other":
                    _row("Neighborhood", nbhd)
                if lead.building_type:
                    _row("Property Type", lead.building_type)
                if lead.year_built:
                    _row("Year Built", str(lead.year_built))
                if lead.building_area:
                    _row("Building Area", f"{lead.building_area:,} sq ft")
                if lead.lot_area:
                    _row("Lot Area", f"{lead.lot_area:,} sq ft")
                if lead.num_floors:
                    _row("Floors", str(lead.num_floors))
                if lead.zip_code:
                    _row("ZIP Code", lead.zip_code)
                if lead.deed_sale_amount:
                    _row("Last Sale Price", f"${lead.deed_sale_amount:,.0f}")
                if lead.deed_date:
                    _row("Last Sale Date", lead.deed_date)

            st.markdown("<div style='height:1.25rem;'></div>", unsafe_allow_html=True)

            # Outreach section
            st.markdown('<div class="section-label">Outreach</div>', unsafe_allow_html=True)

            if lead.outreach_draft:
                st.text_area(
                    "Outreach draft",
                    value=lead.outreach_draft,
                    height=130,
                    key=f"outreach_text_{selected_idx}",
                    label_visibility="collapsed",
                )
            elif is_llc:
                st.caption("LLC-owned — identify the principal before drafting outreach.")
            elif has_llm and st.session_state.get("service_description", ""):
                if st.button(
                    "Write Outreach Message",
                    type="primary",
                    use_container_width=True,
                    key=f"outreach_btn_{selected_idx}",
                ):
                    svc = st.session_state["service_description"]
                    with st.spinner("Crafting your message…"):
                        generate_outreach_for_lead(lead, svc, svc)
                    if lead.outreach_draft:
                        name_key = _make_name_key(lead.first_name, lead.last_name)
                        update_outreach(_db, name_key, "draft_ready", lead.outreach_draft)
                        st.rerun()
                    else:
                        st.warning("Rate limited — please wait a moment and try again.")
            else:
                st.caption("Add GROQ_API_KEY to .env to enable outreach generation.")

            # Search links
            st.markdown("<div style='height:0.5rem;'></div>", unsafe_allow_html=True)
            if not is_llc and lead.first_name:
                links = generate_search_links(
                    lead.first_name,
                    lead.last_name,
                    city=lead.city or "New York",
                    address=lead.address or "",
                )
                _lc1, _lc2, _lc3 = st.columns(3)
                _lc1.markdown(
                    f"<a href='{links['google']}' target='_blank' "
                    f"style='font-size:11px; color:#C8A96E; text-decoration:none; "
                    f"letter-spacing:0.06em;'>Google →</a>",
                    unsafe_allow_html=True,
                )
                _lc2.markdown(
                    f"<a href='{links['linkedin']}' target='_blank' "
                    f"style='font-size:11px; color:#C8A96E; text-decoration:none; "
                    f"letter-spacing:0.06em;'>LinkedIn →</a>",
                    unsafe_allow_html=True,
                )
                if links.get("maps"):
                    _lc3.markdown(
                        f"<a href='{links['maps']}' target='_blank' "
                        f"style='font-size:11px; color:#C8A96E; text-decoration:none; "
                        f"letter-spacing:0.06em;'>Maps →</a>",
                        unsafe_allow_html=True,
                    )
            elif lead.address:
                maps_url = (
                    f"https://www.google.com/maps/search/?api=1&query="
                    f"{quote_plus(lead.address + ' New York')}"
                )
                st.markdown(
                    f"<a href='{maps_url}' target='_blank' "
                    f"style='font-size:11px; color:#C8A96E; text-decoration:none; "
                    f"letter-spacing:0.06em;'>Google Maps →</a>",
                    unsafe_allow_html=True,
                )
