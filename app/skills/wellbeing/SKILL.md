---
name: wellbeing
description: Record and inspect sleep, mood, energy, stress, recovery, and daily capacity. Use when wellbeing state should be saved or considered during planning.
---

# Wellbeing

Use daily state tools for sleep, energy, mood, recovery, tiredness, stress, and
current capacity.

- Record concrete state only when the user explicitly asks to save or update it.
- Treat state supplied only for advice or planning as temporary context.
- Use `get_daily_state` for one date and `list_daily_logs` for recent trends.
- Reduce workload and prefer shorter work blocks after low energy or poor sleep.
- Do not infer a diagnosis from wellbeing records.

## Context references

- Use the summary for broad sleep, mood, or energy trends.
- Call `read_context_ref` when exact dates, notes, or individual daily records
  omitted from the summary are needed.
