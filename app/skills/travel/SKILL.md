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
- Do not read or write SQLite, Context, or Memory directly. Future operations must go through Policy-authorized tools and the Tool System.
- Do not infer durable travel preferences from one request.

## Current workflow

1. Collect destination, dates, budget, travelers, preferences, and constraints.
2. Use the Policy-authorized fixture-backed calendar, weather, transport, lodging, and place read tools to obtain relevant candidates.
3. Compare candidates and surface missing, stale, conflicting, or partial information.
4. Build a draft itinerary without persisting it.
5. Save only through an explicitly authorized tool after user confirmation.

The current external-read tools return request-local typed observations and candidates. This Skill describes when they are useful; authorization still comes from Policy and the Tool System.
