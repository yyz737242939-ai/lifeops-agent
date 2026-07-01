---
name: news
description: Prepare AI news briefings from declared read-only sources. Use for Hugging Face papers, blog posts, AI research news, LLM or agent news summaries, and source-linked briefing requests.
---

# News

Use this skill for AI news briefing requests, especially Hugging Face Papers,
Hugging Face Blog, AI research updates, LLM news, agent news, and concise
source-linked summaries.

This first version only provides the Skill entry point and routing rules. It
does not expose network reading, references, or helper tools yet.

## Current boundaries

- Do not claim that Hugging Face content has been fetched unless a future
  source-reading tool returns a successful observation.
- Do not invent paper or blog details.
- Keep the user-facing answer clear about whether it is based on available
  runtime data or a missing source-reading capability.
- News briefing results belong to the current conversation. They are not
  long-term Memory and should not be saved unless the user explicitly asks to
  save a preference through Memory tools.
