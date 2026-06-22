---
name: activity
description: Recommend activities, breaks, exercise, or recovery options that fit energy, mood, time, cost, location, and the user's goal.
---

# Activity

Use `recommend_activities` for activity ideas, recovery options, breaks, or
non-work activities.

- Pass through known energy, mood, time, budget, location, and goal constraints.
- Do not invent activities outside the returned catalog.
- When other skills are loaded, combine their constraints with the activity
  request instead of treating the recommendation in isolation.

## Context references

- Use the summary when a few top recommendations are sufficient.
- Call `read_context_ref` only when the user asks to expand the full referenced
  recommendation set or needs exact omitted activity fields.
