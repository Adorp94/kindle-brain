# Kindle Brain

Turn your Kindle highlights into a personal AI knowledge base. Ask Claude questions and get answers synthesized across all your books.

```
You: "What do my books say about persistence and founding companies?"

Claude reads your catalog → identifies Shoe Dog, Zero to One, Elon Musk,
The War of Art, The Almanack of Naval Ravikant → reads your actual
highlighted passages → synthesizes across 5+ books with your personal angle
```

## How It Works

Your Kindle highlights are enriched with **golden nuggets** — massive ~4,000-word context blocks extracted from the original book text around each highlight. These preserve the author's exact words, metaphors, and arguments.

A **two-tier catalog system** lets Claude navigate your entire library:

1. **CATALOG.md** (~48K chars) — compact LLM-generated descriptions + semantic tags for every book, fits inline in one MCP call
2. **Per-book files** — full fingerprint + highlights + chapter summaries for deep reading

Claude reads the catalog, identifies 5-8 relevant books laterally (a Nike biography is relevant to "entrepreneurship", a philosophy book to "leadership under pressure"), then drills into each book's highlights to synthesize across your reading.

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/Adorp94/kindle-brain.git
cd kindle-brain
pip install -e .

# 2. Interactive setup (detects Kindle, Calibre, API key)
kindle-brain setup
# Or with a clippings file directly:
kindle-brain setup --clippings-file "/path/to/My Clippings.txt"

# 3. Enrich and generate
kindle-brain enrich --rich-context    # Extract golden nuggets (no API)
kindle-brain enrich                   # Generate summaries (Gemini API)
kindle-brain generate                 # Book markdown files
kindle-brain generate --library-index # Semantic fingerprints (API)
kindle-brain generate --catalog       # Compact catalog (API)
kindle-brain generate --embed-fingerprints

# 4. Connect to Claude
kindle-brain serve                    # Start MCP server
```

Add to Claude Desktop (Settings > Developer > Edit Config):

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

## Two Tiers

| | Basic | Full |
|---|---|---|
| **Requirements** | `My Clippings.txt` + Gemini API key | + Calibre + ebook files on Kindle |
| **Highlights** | Yes | Yes |
| **Book/chapter summaries** | Yes (LLM-generated) | Yes |
| **Golden nuggets** | No | Yes (~4,000-word context per highlight) |
| **Vector search** | No | Yes (ChromaDB + Gemini Embedding 2) |
| **Setup time** | ~5 min | ~15 min |

The setup wizard auto-detects your tier.

## CLI Commands

```bash
kindle-brain setup              # Interactive first-time setup
kindle-brain sync               # Sync from connected Kindle
kindle-brain sync --clippings-file f  # Sync from exported file
kindle-brain extract            # Extract book texts (Calibre)
kindle-brain enrich             # Context + summaries
kindle-brain generate           # Markdown files
kindle-brain index              # Vector index (optional)
kindle-brain search "query"     # Semantic search
kindle-brain stats              # Library statistics
kindle-brain serve              # MCP server (stdio)
```

## Architecture

```
src/kindle_brain/
  cli.py              # Unified CLI with 9 subcommands
  paths.py            # Centralized path resolution (~/.kindle-brain/)
  config.py           # Gemini model config + system config
  db.py               # SQLite connection factory
  sync.py             # Kindle clipping parser (Spanish + English)
  extract.py          # Calibre text extraction
  enrich.py           # Golden nuggets + LLM summaries
  index.py            # ChromaDB vector indexing
  search.py           # Semantic search
  generate_md.py      # Markdown + catalog generation
  memory.py           # User memory system (3 layers)
  server/
    mcp_server.py     # MCP server (browse_library, read_book, get_library_stats)
    api_server.py     # FastAPI server (optional, for custom UIs)
```

### AI Stack (100% Gemini)

- **Embeddings**: `gemini-embedding-2-preview` (8K tokens, 3072 dimensions)
- **Summaries**: `gemini-3.1-flash-lite-preview` (cheap ETL, 1M context)
- **Chat**: `gemini-3.1-pro-preview` (deep reasoning, 1M context)

### Data

Default location: `~/.kindle-brain/` (override with `KINDLE_BRAIN_DATA` env var)

## Languages

Supports Kindle clippings in **English** and **Spanish**. Locale is auto-detected from your `My Clippings.txt` file.

## Requirements

- Python 3.11+
- [Gemini API key](https://aistudio.google.com/) (free tier available)
- [Calibre](https://calibre-ebook.com/) (optional, for golden nuggets)

## License

MIT
