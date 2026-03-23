---
name: kindle-brain
description: >
  Personal Kindle reading highlights knowledge base. Transforms your Kindle
  highlights into a searchable library that any AI agent can reason over.
  Use when the user asks about their books, highlights, reading notes,
  or wants insights synthesized across their personal reading library.
---

# Kindle Brain — Personal Reading Library

Your Kindle highlights enriched with golden nuggets (~4,000-word context blocks
from original book texts), semantic fingerprints, and chapter summaries.

## Workflow

1. **Read the catalog** to see all books:
   - `CATALOG.md` in your data directory (`~/.kindle-brain/books_md/` by default)
   - Or set `KINDLE_BRAIN_DATA` env var to point to your data
   - Fallback: `data/books_md/CATALOG.md` (if running from project directory)

2. **Identify 5-8 most relevant books** — think LATERALLY:
   - "entrepreneurship" → biographies (Shoe Dog, Elon Musk), not just business books
   - "leadership" → philosophy (Meditations, Principles), not just management guides
   - Narratives are often MORE relevant than self-help

3. **Read each relevant book** from the same `books_md/` directory
   - Each file has: semantic fingerprint, book summary, chapter summaries, all highlights
   - Golden nuggets in `<details>` blocks for deep context (~4,000 words each)

4. **Synthesize** across books using the reader's actual highlighted passages

## Setup

```bash
# Install
git clone https://github.com/Adorp94/kindle-brain.git
cd kindle-brain && pip install -e .

# First-time setup (auto-detects Kindle, Calibre, locale)
kindle-brain setup

# Enrich and generate
kindle-brain enrich --rich-context
kindle-brain enrich
kindle-brain generate
kindle-brain generate --library-index
kindle-brain generate --catalog
kindle-brain generate --embed-fingerprints
```

## MCP Server (for Claude Desktop / claude.ai)

Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "kindle-brain": {
      "command": "kindle-brain",
      "args": ["serve"]
    }
  }
}
```

Tools: `browse_library()`, `read_book(title)`, `get_library_stats()`
