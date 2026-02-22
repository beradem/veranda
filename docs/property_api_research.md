# Property Data API Research (Feb 2026)

Saved for future reference when we're ready to scale beyond county-specific scrapers.

## Summary

| Option | Owner Names | Free Tier | First Paid Tier | Notes |
|---|---|---|---|---|
| **RentCast** | Yes | 50 calls/mo | $74/mo (1K calls) | Best for MVP — clean API, good data |
| **Melissa Data** | Yes | 1,000 credits/mo | ~$5/1K credits | Generous free tier, property data is side product |
| **BatchData** | Yes + phone/email | $0.01/call | $500/mo (20K calls) | Skip-tracing add-on interesting for outreach |
| **ATTOM** | Yes | 5 counties only | ~$500+/mo | Gold standard but expensive |
| **Zillow** | No | N/A | N/A | API is dead |
| **RealtyMole** | N/A | N/A | N/A | Absorbed into RentCast |

## Recommendation for Scale Phase
- Start with RentCast ($74/mo) when ready to go nationwide
- Build with provider adapter pattern so APIs are swappable
- Evaluate BatchData for skip-tracing (owner phone/email) when outreach engine is built
- ATTOM for enterprise scale
