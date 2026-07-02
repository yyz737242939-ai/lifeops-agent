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
It can fetch declared Hugging Face sources with `fetch_news_source(source_id)`
and can run declared read-only helpers with `run_news_helper(helper_id,
arguments)`.

Recommended references:

- `briefing_policy`: default rules for concise Chinese AI briefings.
- `source_policy`: source and citation boundaries.
- `copyright_policy`: summary and quotation boundaries.
- `output_templates`: output shapes for briefings.
- `topic_agent_llm`: topic filters for agent, LLM, and multimodal requests.

Declared sources:

- `hf_daily_papers`: Hugging Face Daily Papers list.
- `hf_blog`: Hugging Face Blog list.

Declared helpers:

- `parse_hf_daily_papers`: parse fetched Papers HTML into structured items.
- `parse_hf_blog`: parse fetched Blog HTML into structured items.
- `rank_news_items`: rank structured items.
- `dedupe_news_items`: remove duplicate structured items.

## Hugging Face briefing workflow

When the user asks for a Hugging Face Papers, Blog, AI news, LLM news, agent
news, or multimodal news briefing:

1. Read the relevant references first:
   - `briefing_policy` for output requirements.
   - `source_policy` for source boundaries.
   - `copyright_policy` for summary limits.
   - `topic_agent_llm` when the user asks about agents, LLMs, or multimodal.
2. Fetch only declared sources:
   - `hf_daily_papers` for Papers requests.
   - `hf_blog` for Blog requests.
   - Fetch both when the user asks for papers and blogs or a general Hugging
     Face briefing.
3. Parse fetched HTML with helpers:
   - Use `parse_hf_daily_papers` for `hf_daily_papers` HTML.
   - Use `parse_hf_blog` for `hf_blog` HTML.
   - Use `dedupe_news_items` and `rank_news_items` when combining lists.
4. Answer in concise Chinese with paper/blog separation, titles, links,
   sources, topic labels, and short reasons. If only list pages were fetched,
   say the briefing is based on list-page visible information.

## Current boundaries

- Do not claim that Hugging Face content has been fetched unless
  `fetch_news_source` returns a successful observation.
- Do not invent paper or blog details.
- Read only declared references. Do not ask for arbitrary local files.
- Fetch only declared sources. Do not ask for arbitrary URLs.
- Use helpers for mechanical parsing, ranking, and dedupe instead of guessing
  structure from raw HTML.
- News briefing results belong to the current conversation. They are not
  long-term Memory and should not be saved unless the user explicitly asks to
  save a preference through Memory tools.
