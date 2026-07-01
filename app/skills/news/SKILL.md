---
name: news
description: Prepare AI news briefings from declared read-only sources. Use for Hugging Face papers, blog posts, AI research news, LLM or agent news summaries, and source-linked briefing requests.
---

# News

Use this skill for AI news briefing requests, especially Hugging Face Papers,
Hugging Face Blog, AI research updates, LLM news, agent news, and concise
source-linked summaries.

This skill can read declared references on demand with
`read_skill_reference(ref_id)`.

Recommended references:

- `briefing_policy`: default rules for concise Chinese AI briefings.
- `source_policy`: source and citation boundaries.
- `copyright_policy`: summary and quotation boundaries.
- `output_templates`: output shapes for briefings.
- `topic_agent_llm`: topic filters for agent, LLM, and multimodal requests.

This version does not expose network reading or helper tools yet.

## Current boundaries

- Do not claim that Hugging Face content has been fetched unless a future
  source-reading tool returns a successful observation.
- Do not invent paper or blog details.
- Read only declared references. Do not ask for arbitrary local files.
- Keep the user-facing answer clear about whether it is based on available
  runtime data or a missing source-reading capability.
- News briefing results belong to the current conversation. They are not
  long-term Memory and should not be saved unless the user explicitly asks to
  save a preference through Memory tools.
