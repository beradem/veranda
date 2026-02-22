Veranda
TLDR: Veranda is an AI-driven outbound marketing agent designed for hyper-localized luxury services. It automates the identification of high-net-worth (HNW) leads through lifestyle signals and orchestrates "white-glove" personalized outreach to drive premium lead generation and conversion.

Opportunity
Luxury service providers (interior designers, concierge doctors, high-end contractors) currently rely on fragmented, manual, or "low-signal" marketing.
The Gap: Standard lead-gen tools (Facebook Ads, generic SEO) attract low-intent or non-qualified leads, which dilutes the brand and wastes time for high-value founders.
The Solution: Veranda bridges the gap between public wealth signals (real estate, professional status, lifestyle events) and automated personal outreach. It allows luxury brands to be "first to the door" when a high-value prospect experiences a life event that triggers a need for their service.

Ideal Customer
Veranda targets small-to-mid-sized luxury service firms with high average order values ($10k - $500k+) who value discretion and personal touch:
Home Services: Luxury roofers, landscape architects, interior designers, custom pool builders.
Health & Wellness: Concierge physicians, private physical therapists, elite personal trainers, longevity coaches.
Elite Experiences: Luxury travel curators, private art consultants, VIP sports/event hospitality providers.
Demographic Target: "The Suburban Matriarch" (affluent homeowners) and "The Metropolitan Professional" (HNW individuals in urban centers).

Frontend Product Requirements for Services Owner
The frontend must feel like a "Command Center" that empowers a busy founder to approve high-IQ work without getting into the weeds.
Campaign Builder (The "Set & Forget" Input):
Fields for Target Geography (Zip codes or neighborhoods).
Persona Text Input (e.g., "Recently moved," "High-income executives," "Large estate owners").
Value Prop Input: A text area for the owner to describe their unique service "edge."
The "Luxe-Lead" Review Table:
A clean list of identified prospects including Name, Estimated Wealth/Income, Age, and Discovery Trigger (e.g., "Recently purchased $4M home").
A "Preview Outreach" button for every lead to see the AI-generated personal note.
Master "Review & Send All" Control:
A top-level toggle to bulk-approve all leads that pass a certain confidence score, allowing for 1-click execution of the entire daily batch.
Relationship Timeline: * A simple view showing the status of the "Conversation" (Sent, Opened, Replied, Booked).

Technical Product Requirements for Data Sourcing
Veranda does not rely on static databases; it uses "Agentic Scrapers" to synthesize live data from the public internet.

1. Real Estate Signal Engine
The Logic: Instead of a generic Zillow scraper (which has high bot-detection), Veranda will use a Geospatial Tax-Record Agent.
Source: We will target County Tax Assessor portals directly via their public search interfaces.
Pointed Feature: We will use the EdgarTools AI Skill or a similar custom skill to navigate these forms.
Claude Code Feasibility: High Confidence. * One-Shot: "Claude, use playwright to navigate the [Town Name] Tax Assessor site, search for properties with an assessed value over $2M, and return a CSV of the owner names and mailing addresses."

2. The "Liquidity Event" Monitor (SEC EDGAR)
The Logic: This is our most powerful data source. We monitor SEC Form 4 filings (Insider Trading) to find individuals who just sold millions in stock.
Source: SEC.gov EDGAR API (Free and Public).
Pointed Feature: We will install the EdgarTools library directly into the Claude Code environment.
Claude Code Feasibility: Highest Confidence. * One-Shot: "Claude, use edgartools to find every executive who sold more than $5M in stock in the last 30 days living in [Target City]. Cross-reference these names with our Property Tax list."

3. Professional Mapping & Identity Stitching
The Logic: Veranda will "stitch" the name from the property record to a professional identity using Search Dorks.
Source: Google Search API (via Claude's built-in web_fetch or Google Search tools).
The "Stitch" Logic: 1. Search: "[Owner Name]" + "[City]" + LinkedIn. 2. Extract Title (e.g., "VP of Sales at Google"). 3. Use a verified API (like Apollo or Hunter.io) to find the email.
Claude Code Feasibility: High Confidence.
One-Shot: "Claude, take this list of names, find their LinkedIn headlines using web_fetch, and use the Apollo API to get their verified professional emails."

4. AI Copy-Orchestrator:
An LLM (GPT-4o or Claude 3.5 Sonnet) prompt-engineered with a "High-Touch/Low-Pressure" tone.
It must ingest the "Discovery Trigger" (e.g., a specific home feature or job change) to ensure the first sentence of the email is an observation, not a pitch.

