---
name: kindle-brain
description: >
  Personal Kindle reading highlights knowledge base.
  Use when the user asks about their books, highlights, reading notes,
  or wants insights/advice that could be answered by their personal library.
  Triggers on: "my books", "my highlights", "what did I read", "what do my books say",
  reading recommendations from their own library, cross-book synthesis.
---

# Kindle Brain — Personal Reading Library

Personal Kindle highlights with rich context from original book texts.

## Workflow

1. Read the catalog to see all books:
   - If `KINDLE_BRAIN_DATA` env var is set: `$KINDLE_BRAIN_DATA/books_md/CATALOG.md`
   - Otherwise: `~/.kindle-brain/books_md/CATALOG.md`
   - Fallback: `data/books_md/CATALOG.md` (if running from project directory)

2. Identify 5-8 most relevant books — think LATERALLY:
   - "entrepreneurship" → Shoe Dog, Elon Musk, Zero to One, Alibaba, DREAM BIG
   - "leadership" → Meditations, Principles, Steve Jobs, The Hard Thing
   - Biographies and narratives are often MORE relevant than self-help

3. Read each relevant book file from the same `books_md/` directory

4. Synthesize across books using the reader's actual highlighted passages

5. For deep context, look inside `<details>` blocks (golden nuggets, ~4000 words)

## Setup (for new users)

If no data exists yet:
```bash
pip install -e .
kindle-brain setup
kindle-brain enrich --rich-context
kindle-brain generate
kindle-brain generate --library-index
kindle-brain generate --catalog
kindle-brain generate --embed-fingerprints
```
