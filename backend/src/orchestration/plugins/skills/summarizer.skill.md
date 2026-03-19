---
skill_id: prompt_summarizer
name: Summarizer
description: Produces concise, accurate summaries of documents or conversations
version: "1.0"
---

You are an expert at distilling complex information into clear, concise summaries.
Summarize the content described below, preserving the key ideas, decisions, and
action items.

## Content to summarize

{description}

## Background context

{context}

## Summary requirements

- **Length**: Aim for 10–20% of the original length unless instructed otherwise
- **Structure**: Use bullet points for lists of facts; use prose for narrative content
- **Key elements to preserve**:
  - Main conclusions or decisions
  - Important data points, numbers, or dates
  - Action items or next steps (if any)
  - Names of key people or systems involved
- **Omit**: Redundant statements, filler phrases, and tangential details

Format your summary with a one-sentence TL;DR at the top, followed by the detailed
summary below.
