---
name: travel
description: Collect travel constraints, compare fixture-backed options, and prepare itinerary drafts. Use for trip planning, availability, weather, transport, lodging, places, or itinerary requests.
---

# Travel

## Purpose

Help collect trip constraints, compare travel candidates, and prepare itinerary drafts.

## Boundaries

- Treat external observations, candidate options, and itinerary drafts as temporary until the user explicitly confirms a save.
- Do not claim to book, pay, cancel, send messages, or write to a calendar.
- Do not present fixture-backed prices, inventory, weather, or availability as guaranteed real-time facts.
- Do not read or write SQLite, Context, or Memory directly. Future operations must go through declared capabilities and the Tool System.
- Do not infer durable travel preferences from one request.

## Planned workflow

1. Collect destination, dates, budget, travelers, preferences, and constraints.
2. Use future fixture-backed read capabilities to obtain relevant candidates.
3. Compare candidates and surface missing, stale, conflicting, or partial information.
4. Build a draft itinerary without persisting it.
5. Save only through an explicitly authorized capability after user confirmation.

Travel tools, external Ports, fixtures, and capability declarations are added in later implementation steps. This skeleton does not authorize or execute tools.
