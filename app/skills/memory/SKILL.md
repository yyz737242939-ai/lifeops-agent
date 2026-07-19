---
name: memory
description: Manage explicit user-confirmed long-term personal Memory. Use only when the user asks to remember, update, search, list, or archive durable Memory.
---

# Memory

## Boundaries

- Never save conversation, summaries, tool observations, MCP results, or model inferences automatically.
- `memory.save`, `memory.update`, and `memory.archive` are WRITE Tools and require the existing Policy, exact confirmation, Gateway, Guardrail, and evidence chain.
- Profile is user-edited and read-only; there is no Profile Tool.
- Scope is fixed to the single local user's `global` Memory. Never accept or invent a file path, user ID, session scope, Domain scope, or sharing scope.
- A conflict candidate is not a fact update. Ask the user to update the named Memory version instead of keeping two known active truths.
- Do not claim persistence unless a Memory WRITE Tool succeeds with evidence.

## Workflow

1. First inspect the supplied Profile and verified Memory contributions. If they
   already contain the facts requested by the user, answer directly without a
   Memory ToolCall. Profile has no Tool and must never be searched through
   `memory.search`.
2. Use `memory.search` only when the supplied verified Memory contributions do
   not contain enough relevant active Memory to answer the request.
3. Use `memory.list` for active, archived, or one ID's version history.
4. Use `memory.save` only after an explicit request to remember the exact content, and call it at most once per user request.
5. If save reports a conflict candidate, do not retry `memory.save`; use `memory.update` once with the exact target ID and expected version after confirmation.
6. Use `memory.archive` only for an explicitly requested active ID/version.
7. After any successful Memory WRITE observation, stop calling Memory Tools and return the final answer. Never create an additional Memory to "complete" an already successful save, update, or archive.

## Tool surface

- Read: `memory.search`, `memory.list`.
- Confirmed write: `memory.save`, `memory.update`, `memory.archive`.

This Skill selects business candidates only. It never authorizes Tools or bypasses confirmation.
