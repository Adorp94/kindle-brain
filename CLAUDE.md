# Kindle Brain

Turn your Kindle highlights into a personal AI knowledge base. Enriched with **golden nuggets** (massive ~4,000-word context blocks from original book text), indexed with Gemini Embedding 2 for deep semantic search, and powered by Gemini Pro for reasoning across books.

## Quick Start

```bash
pip install -e .
kindle-brain setup                    # Interactive setup
kindle-brain enrich --rich-context    # Extract golden nuggets
kindle-brain generate                 # Generate markdown files
kindle-brain generate --catalog       # Compact catalog for Claude
kindle-brain serve                    # Start MCP server
```

## Architecture

### Two-Tier Catalog System
```
CATALOG.md (~48K chars) — compact: 1-sentence desc + tags + links per book
  → Claude reads ALL entries inline, reasons laterally
  → Identifies 5-8 relevant books
  → Calls read_book() for each
  → Each book .md has FULL fingerprint + highlights
  → Claude synthesizes with deep cross-book connections
```

### Golden Nuggets
Each highlight has a ~20,000 character context block (`rich_context`) extracted from the original book text, centered on the highlight and snapped to paragraph boundaries. Preserves the author's exact words, metaphors, and arguments.

### AI Stack (100% Gemini)
- **Embeddings**: `gemini-embedding-2-preview` (8K token window, 3072 dimensions)
- **Summaries**: `gemini-3.1-flash-lite-preview` — cheap ETL (1M context)
- **Chat**: `gemini-3.1-pro-preview` — deep reasoning (1M context)
- Config: `src/kindle_brain/config.py`

### Two Tiers
- **Basic**: Highlights from `My Clippings.txt` + LLM summaries (no Calibre needed)
- **Full**: Highlights + golden nuggets from book texts + vector search (requires Calibre)

## MCP Server

### Tools

| Tool | Description |
|------|-------------|
| `browse_library` | Compact catalog of all books (~48K chars, fits inline) |
| `read_book` | Full book file with fingerprint, highlights, chapter summaries |
| `get_library_stats` | Library statistics |

### Claude Desktop Config

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

## CLI

```bash
kindle-brain setup                    # Interactive first-time setup
kindle-brain sync                     # Sync from Kindle
kindle-brain sync --clippings-file f  # Sync from file
kindle-brain extract                  # Extract book texts (Calibre)
kindle-brain enrich --rich-context    # Golden nuggets (no API)
kindle-brain enrich                   # + LLM summaries (API)
kindle-brain generate                 # Book markdown files
kindle-brain generate --library-index # LIBRARY.md (API)
kindle-brain generate --catalog       # CATALOG.md (API)
kindle-brain generate --embed-fingerprints
kindle-brain index --full             # Vector index (API)
kindle-brain search "query"           # Semantic search
kindle-brain stats                    # Library stats
kindle-brain serve                    # MCP server (stdio)
```

## Package Structure

```
src/kindle_brain/
  cli.py              # Unified CLI
  paths.py            # Centralized path resolution
  config.py           # Model + system config
  db.py               # Database connection factory
  sync.py             # Clipping parser (Spanish + English)
  extract.py          # Calibre text extraction
  enrich.py           # Golden nuggets + summaries
  index.py            # ChromaDB vector indexing
  search.py           # Semantic search
  generate_md.py      # Markdown generation
  memory.py           # Memory system
  server/
    mcp_server.py     # MCP server
    api_server.py     # FastAPI server
```

## Data Location

Default: `~/.kindle-brain/` (override with `KINDLE_BRAIN_DATA` env var)

- `kindle.db` — main database
- `memory.db` — user memory
- `vectordb/` — ChromaDB index
- `book_texts/` — extracted book texts
- `books_md/` — markdown files (CATALOG.md, LIBRARY.md, per-book)
- `covers/` — book cover images

## Environment

Requires `GOOGLE_API_KEY` in `.env` for Gemini API access.
Get a free key at: https://aistudio.google.com/
