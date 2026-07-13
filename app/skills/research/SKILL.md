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
- Do not claim that a source was fetched, parsed, or saved unless the corresponding tool returns a successful result or evidence.
- Do not read or write SQLite, Context, or Memory directly. Operations must go through Policy-authorized tools and the Tool System.
- Do not fetch arbitrary URLs. External reads are limited to declared source IDs.

## Planned workflow

1. Clarify the research topic and expected output when needed.
2. Use Policy-authorized read tools to obtain source material.
3. Compare, deduplicate, rank, and summarize results with source references.
4. Keep the result temporary unless an explicitly authorized save tool succeeds.

## Declared sources

- `hf_daily_papers`: Hugging Face Daily Papers list page.
- `hf_blog`: Hugging Face Blog list page.

The source declarations are metadata only and do not perform network access. Fetch, parse, rank, temporary brief build, and confirmed Source/Brief/Note writes are executable only through their registered Tools. References are added in later implementation steps. This Skill does not authorize tools or bypass confirmation.
