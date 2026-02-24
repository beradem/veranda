"""Veranda — NYC Luxury Service Lead Generator.

A Streamlit dashboard that finds high-value NYC property owners from public
records and generates personalized outreach messages using Google Gemini.

Single-page layout:
1. Business Profile — describe your service and ideal client
2. Lead Criteria — pick neighborhoods, set value filters
3. Generate Leads — fetch properties, deduplicate, generate outreach
4. Results — table + paginated expandable cards with outreach messages
"""

import sys
import logging
import math

import streamlit as st
import pandas as pd

from src.engines.real_estate import fetch_properties, NEIGHBORHOOD_ZIP_CODES
from src.engines.outreach_generator import generate_outreach_for_lead, parse_lead_criteria, _get_llm_key
from src.engines.professional_mapping import generate_search_links
from src.engines.sec_edgar import fetch_insider_sales, configure_edgar
from src.engines.fec import fetch_fec_donors
from src.utils.pdf_extractor import extract_text_from_pdf
from src.models.lead import Lead, LeadSource

# Configure logging so we can see what the engines are doing
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

LEADS_PER_PAGE = 20

# --- Page Config ---
st.set_page_config(
    page_title="Veranda",
    page_icon="🏡",
    layout="wide",
)

# --- Minimal black & white theme + centered layout ---
st.markdown("""
<style>
    /* Remove top padding and header */
    .block-container { padding-top: 1rem !important; max-width: 75% !important; }
    header[data-testid="stHeader"] { display: none !important; }

    /* File uploader — compact */
    [data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] {
        padding: 8px 12px !important;
        min-height: 0 !important;
    }
    [data-testid="stFileUploader"] .stFileUploaderDropzoneInstructions div:last-child {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

st.title("Veranda")


# =========================================================================
# SHARED UTILITIES
# =========================================================================
def _deduplicate_leads(leads: list[Lead]) -> list[Lead]:
    """Remove duplicate leads, keeping the highest-value entry per person."""
    seen: dict[str, Lead] = {}
    for lead in leads:
        name_key = f"{lead.first_name}_{lead.last_name}".lower().strip("_")
        existing = seen.get(name_key)
        if existing is None or (lead.estimated_wealth or 0) > (existing.estimated_wealth or 0):
            seen[name_key] = lead
    return list(seen.values())


# =========================================================================
# SECTION 1: YOUR BUSINESS
# =========================================================================
st.header("Your Business")

service_description = st.text_area(
    "Tell us about your services and ideal customer",
    height=150,
    placeholder=(
        "Example: We are a boutique interior design firm specializing in "
        "pre-war brownstone renovations. Our ideal clients are owners of "
        "historic homes valued at $3M+ in the West Village, Tribeca, and "
        "Park Slope who want to modernize while preserving character."
    ),
    key="service_desc",
)

uploaded_pdf = st.file_uploader(
    "upload",
    type=["pdf"],
    key="pdf_upload",
    label_visibility="collapsed",
)

if uploaded_pdf is not None:
    extracted = extract_text_from_pdf(uploaded_pdf)
    if extracted:
        service_description = extracted
        st.caption(f"Using text from PDF ({len(extracted):,} characters)")
    else:
        st.warning("Could not extract text from this PDF.")

if not _get_llm_key():
    st.caption("Add GROQ_API_KEY to .env for AI-powered neighborhood selection")

# Centered generate button (sits right under the text box)
_, btn_col, _ = st.columns([1, 2, 1])
with btn_col:
    generate_btn = st.button(
        "Generate Leads",
        type="primary",
        key="generate_btn",
    )

if generate_btn:
    if not service_description.strip():
        st.warning("Please describe your business first.")
    else:
        try:
            # Phase 1: AI picks neighborhoods & settings
            with st.spinner("Analyzing your business profile..."):
                criteria = parse_lead_criteria(service_description.strip())

            selected_neighborhoods = criteria["neighborhoods"]
            min_market_value = criteria["min_value"]
            residential_only = criteria["residential_only"]
            individuals_only = criteria["individuals_only"]
            include_condos = criteria["include_condos"]

            st.info(
                f"Searching **{len(selected_neighborhoods)} neighborhoods** "
                f"({', '.join(selected_neighborhoods)}), "
                f"properties over **${min_market_value:,.0f}**"
            )

            zip_codes = []
            for name in selected_neighborhoods:
                zip_codes.extend(NEIGHBORHOOD_ZIP_CODES.get(name, []))

            # Phase 2: PLUTO house search + SEC insider sales
            with st.spinner(
                f"Searching NYC properties and SEC insider sales..."
            ):
                progress_cb = None
                if include_condos:
                    acris_status = st.empty()
                    acris_bar = st.progress(0, text="Preparing condo search...")

                    def progress_cb(completed: int, total: int) -> None:
                        pct = completed / total if total > 0 else 0
                        acris_bar.progress(
                            pct,
                            text=f"Scanning condo deed records... ({completed}/{total} building groups)",
                        )

                leads = fetch_properties(
                    zip_codes=zip_codes,
                    min_market_value=min_market_value,
                    limit=50_000,
                    residential_only=residential_only,
                    individuals_only=individuals_only,
                    include_condos=include_condos,
                    progress_callback=progress_cb,
                )

            # Clean up progress bar
            if include_condos:
                acris_bar.empty()
                acris_status.empty()

            # Phase 3: SEC EDGAR insider sales
            try:
                configure_edgar()
                sec_leads = fetch_insider_sales(lookback_days=30, max_filings=1_000)
                leads = leads + sec_leads
            except Exception as sec_exc:
                logger.warning("SEC EDGAR fetch failed: %s", sec_exc)

            # Phase 4: FEC campaign finance donors
            try:
                fec_leads = fetch_fec_donors(min_donation=2_500.0, lookback_days=180, max_results=0)
                leads = leads + fec_leads
            except Exception as fec_exc:
                logger.warning("FEC fetch failed: %s", fec_exc)

            leads = _deduplicate_leads(leads)
            st.session_state["leads"] = leads
            st.session_state["service_description"] = service_description.strip()
            st.session_state["search_done"] = True
            st.session_state["current_page"] = 0
        except Exception as exc:
            st.error(f"Error: {exc}")
            st.session_state["search_done"] = False



# =========================================================================
# SECTION 4: RESULTS
# =========================================================================
if st.session_state.get("search_done"):
    leads: list[Lead] = st.session_state.get("leads", [])

    if not leads:
        st.warning(
            "No properties found matching your criteria. "
            "Try lowering the minimum value or adding more neighborhoods."
        )
    else:
        st.divider()
        st.header("Results")

        # --- Metrics ---
        st.metric("Total Leads", len(leads))

        st.divider()

        # --- Results Table ---
        rows = []
        sorted_leads = sorted(leads, key=lambda l: l.estimated_wealth or 0, reverse=True)

        for lead in sorted_leads:
            is_llc = lead.company is not None and lead.first_name == ""
            owner_name = lead.full_name if not is_llc else lead.company

            if not is_llc and lead.first_name:
                links = generate_search_links(
                    lead.first_name,
                    lead.last_name,
                    city=lead.city or "New York",
                    address=lead.address or "",
                )
                google_link = links["google"]
                linkedin_link = links["linkedin"]
                maps_link = links["maps"]
            else:
                google_link = ""
                linkedin_link = ""
                if lead.address:
                    from urllib.parse import quote_plus
                    maps_link = f"https://www.google.com/maps/search/?api=1&query={quote_plus(lead.address + ' New York')}"
                else:
                    maps_link = ""

            # Build enriched data string — property details for real estate
            # leads, professional/sale details for SEC insider and FEC leads
            info_parts = []
            if lead.source == LeadSource.SEC_EDGAR:
                if lead.professional_title:
                    info_parts.append(lead.professional_title)
                if lead.company:
                    info_parts.append(lead.company)
                if lead.estimated_wealth:
                    info_parts.append(f"Insider sale ${lead.estimated_wealth:,.0f}")
                info_parts.append(lead.discovery_trigger)
            elif lead.source == LeadSource.FEC_CAMPAIGN_FINANCE:
                if lead.professional_title:
                    info_parts.append(lead.professional_title)
                if lead.company:
                    info_parts.append(lead.company)
                if lead.city and lead.state:
                    info_parts.append(f"{lead.city}, {lead.state}")
                if lead.estimated_wealth:
                    info_parts.append(f"Donated ${lead.estimated_wealth:,.0f}")
                info_parts.append(lead.discovery_trigger)
            else:
                if lead.address:
                    addr = lead.address
                    if lead.unit_number:
                        addr += f", Unit {lead.unit_number}"
                    info_parts.append(addr)
                if lead.building_type:
                    info_parts.append(lead.building_type)
                if lead.year_built:
                    info_parts.append(f"Built {lead.year_built}")
                if lead.building_area:
                    info_parts.append(f"{lead.building_area:,} sq ft")
                if lead.num_floors:
                    info_parts.append(f"{lead.num_floors} floors")
                if lead.estimated_wealth:
                    info_parts.append(f"Est. ${lead.estimated_wealth:,.0f}")
                if lead.deed_sale_amount:
                    sale_str = f"Last sale ${lead.deed_sale_amount:,.0f}"
                    if lead.deed_date:
                        sale_str += f" ({lead.deed_date})"
                    info_parts.append(sale_str)

            row = {
                "Name": owner_name,
                "Enriched User Data": " · ".join(info_parts) if info_parts else "—",
                "Map": maps_link,
                "Google": google_link,
                "LinkedIn": linkedin_link,
            }
            rows.append(row)

        df = pd.DataFrame(rows)

        # --- Search / filter ---
        search_query = st.text_input(
            "Search leads",
            placeholder="Type a name, address, or keyword to filter...",
            key="lead_search",
            label_visibility="collapsed",
        )

        if search_query.strip():
            q = search_query.strip().lower()
            mask = df.apply(
                lambda row: q in " ".join(str(v).lower() for v in row.values),
                axis=1,
            )
            filtered_df = df[mask]
        else:
            filtered_df = df

        st.dataframe(
            filtered_df,
            column_config={
                "Enriched User Data": st.column_config.TextColumn(),
                "Map": st.column_config.LinkColumn(display_text="Map"),
                "Google": st.column_config.LinkColumn(display_text="Search"),
                "LinkedIn": st.column_config.LinkColumn(display_text="Search"),
            },
            width="stretch",
            hide_index=True,
        )

        if search_query.strip():
            st.caption(f"{len(filtered_df)} of {len(df)} leads match \"{search_query.strip()}\"")

        # --- Paginated Lead Cards ---
        st.subheader("Lead Details")

        total_leads = len(sorted_leads)
        total_pages = max(1, math.ceil(total_leads / LEADS_PER_PAGE))
        current_page = st.session_state.get("current_page", 0)
        current_page = min(current_page, total_pages - 1)

        start_idx = current_page * LEADS_PER_PAGE
        end_idx = min(start_idx + LEADS_PER_PAGE, total_leads)
        page_leads = sorted_leads[start_idx:end_idx]

        st.caption(f"Showing {start_idx + 1}–{end_idx} of {total_leads}")

        has_gemini = _get_llm_key() is not None

        for i, lead in enumerate(page_leads):
            global_idx = start_idx + i  # index into sorted_leads
            is_llc = lead.company is not None and lead.first_name == ""
            label = lead.company if is_llc else lead.full_name
            badge = " [LLC]" if is_llc else ""
            value_str = f"${lead.estimated_wealth:,.0f}" if lead.estimated_wealth else "—"

            with st.expander(f"{label}{badge} — {value_str}"):
                detail_col1, detail_col2 = st.columns(2)

                with detail_col1:
                    if lead.source == LeadSource.SEC_EDGAR:
                        if lead.professional_title:
                            st.markdown(f"**Title:** {lead.professional_title}")
                        if lead.company:
                            st.markdown(f"**Company:** {lead.company}")
                        if lead.estimated_wealth:
                            st.markdown(f"**Insider Sale:** ${lead.estimated_wealth:,.0f}")
                        st.markdown(f"**Trigger:** {lead.discovery_trigger}")
                    elif lead.source == LeadSource.FEC_CAMPAIGN_FINANCE:
                        if lead.professional_title:
                            st.markdown(f"**Occupation:** {lead.professional_title}")
                        if lead.company:
                            st.markdown(f"**Employer:** {lead.company}")
                        if lead.city and lead.state:
                            st.markdown(f"**Location:** {lead.city}, {lead.state}")
                        if lead.zip_code:
                            st.markdown(f"**Zip:** {lead.zip_code}")
                        if lead.estimated_wealth:
                            st.markdown(f"**Donation:** ${lead.estimated_wealth:,.0f}")
                        st.markdown(f"**Trigger:** {lead.discovery_trigger}")
                    else:
                        if lead.address:
                            st.markdown(f"**Address:** {lead.address}")
                        if lead.unit_number:
                            st.markdown(f"**Unit:** {lead.unit_number}")
                        if lead.building_type:
                            st.markdown(f"**Type:** {lead.building_type}")
                        if lead.year_built:
                            st.markdown(f"**Year Built:** {lead.year_built}")
                        if lead.building_area:
                            st.markdown(f"**Building Size:** {lead.building_area:,} sq ft")
                        if lead.lot_area:
                            st.markdown(f"**Lot Size:** {lead.lot_area:,} sq ft")
                        if lead.num_floors:
                            st.markdown(f"**Floors:** {lead.num_floors}")
                        if lead.zip_code:
                            st.markdown(f"**Zip Code:** {lead.zip_code}")
                        if lead.deed_sale_amount:
                            st.markdown(f"**Last Sale Price:** ${lead.deed_sale_amount:,.0f}")
                        if lead.deed_date:
                            st.markdown(f"**Last Sale Date:** {lead.deed_date}")

                with detail_col2:
                    st.markdown(f"**Est. Value:** {value_str}")
                    if lead.source not in (LeadSource.SEC_EDGAR, LeadSource.FEC_CAMPAIGN_FINANCE):
                        st.markdown(f"**Trigger:** {lead.discovery_trigger}")

                    # Outreach: show if already generated, otherwise show button
                    if lead.outreach_draft:
                        st.markdown("**Outreach Message:**")
                        st.text_area(
                            "outreach",
                            value=lead.outreach_draft,
                            height=100,
                            key=f"outreach_text_{global_idx}",
                            label_visibility="collapsed",
                        )
                    elif is_llc:
                        st.caption(
                            "LLC-owned — outreach requires finding the person behind the entity."
                        )
                    elif has_gemini and st.session_state.get("service_description", ""):
                        if st.button("Write Outreach", key=f"outreach_{global_idx}"):
                            svc_desc = st.session_state["service_description"]
                            with st.spinner("Writing..."):
                                generate_outreach_for_lead(
                                    lead,
                                    svc_desc,
                                    svc_desc,
                                )
                            if lead.outreach_draft:
                                st.markdown("**Outreach Message:**")
                                st.text_area(
                                    "outreach",
                                    value=lead.outreach_draft,
                                    height=100,
                                    key=f"outreach_gen_{global_idx}",
                                    label_visibility="collapsed",
                                )
                            else:
                                st.warning("Rate limited — wait a minute and try again.")
                    elif not has_gemini:
                        st.caption("Add GROQ_API_KEY to .env to enable outreach.")

                    st.markdown("---")
                    if not is_llc and lead.first_name:
                        links = generate_search_links(
                            lead.first_name,
                            lead.last_name,
                            city=lead.city or "New York",
                            address=lead.address or "",
                        )
                        link_col1, link_col2, link_col3 = st.columns(3)
                        link_col1.markdown(f"[Google Search]({links['google']})")
                        link_col2.markdown(f"[LinkedIn Search]({links['linkedin']})")
                        if links["maps"]:
                            link_col3.markdown(f"[Google Maps]({links['maps']})")
                    elif lead.address:
                        from urllib.parse import quote_plus as _qp
                        maps_url = f"https://www.google.com/maps/search/?api=1&query={_qp(lead.address + ' New York')}"
                        st.markdown(f"[Google Maps]({maps_url})")

        # --- Pagination controls ---
        if total_pages > 1:
            st.divider()
            prev_col, info_col, next_col = st.columns([1, 2, 1])

            with prev_col:
                if st.button("Previous", disabled=(current_page == 0), width="stretch", key="prev_page"):
                    st.session_state["current_page"] = current_page - 1
                    st.rerun()

            with info_col:
                st.markdown(
                    f"<div style='text-align:center; padding:8px; color:#666;'>"
                    f"Page {current_page + 1} of {total_pages}</div>",
                    unsafe_allow_html=True,
                )

            with next_col:
                if st.button("Next", disabled=(current_page >= total_pages - 1), width="stretch", key="next_page"):
                    st.session_state["current_page"] = current_page + 1
                    st.rerun()
