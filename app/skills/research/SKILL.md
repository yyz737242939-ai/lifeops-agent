---
name: research
description: Research trusted sources, organize personal knowledge, and prepare source-linked briefings. Use for research questions, saved notes and sources, or Hugging Face Papers and Blog briefings.
---

# Research

## Purpose

Help with source-backed research, personal knowledge organization, and research brief drafts.

## Boundaries

- Treat fetched source material and generated brief drafts as request-local unless the user explicitly asks to save selected results.
- Do not treat a model summary as source provenance.
- Do not claim that a source was fetched, parsed, or saved unless the corresponding future tool returns successful evidence.
- Do not read or write SQLite, Context, or Memory directly. Future operations must go through declared capabilities and the Tool System.
- Do not fetch arbitrary URLs. Future external reads are limited to declared source IDs.

## Planned workflow

1. Clarify the research topic and expected output when needed.
2. Use declared read capabilities to obtain source material.
3. Compare, deduplicate, rank, and summarize results with source references.
4. Keep the result temporary unless an explicitly authorized save capability succeeds.

The source manifest, helpers, references, and executable capabilities are added in later implementation steps. This skeleton does not authorize or execute tools.
