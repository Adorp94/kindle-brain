# Kindle Brain

Turn your Kindle highlights into a personal AI knowledge base. Enriched with **golden nuggets** (massive ~4,000-word context blocks from original book text), with semantic fingerprints and chapter summaries for structured navigation.

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
Each highlight has a ~20,000 character context block (`rich_context`) extracted from the original book text, centered on the highlight and snapped to paragraph boundaries. Preserves the author's exact words, metaphors, and arguments. Stored in `<details>` blocks — stripped by default in MCP responses, available on request.

### AI Stack
- **ETL (Gemini)**: `gemini-3.1-flash-lite-preview` for summaries, fingerprints, catalog compression. `gemini-embedding-2-preview` for vector embeddings.
- **Chat (Claude)**: Anthropic API with tool use for the macOS app chat interface.
- **Config**: `src/kindle_brain/config.py` (models), `src/kindle_brain/paths.py` (all paths)

### Two Tiers
- **Basic**: Highlights from `My Clippings.txt` + LLM summaries (no Calibre needed)
- **Full**: Highlights + golden nuggets from book texts + vector search (requires Calibre)

## MCP Server

| Tool | Description |
|------|-------------|
| `browse_library` | Compact catalog of all books (~48K chars, fits inline) |
| `read_book` | Full book file with fingerprint, highlights, chapter summaries |
| `get_library_stats` | Library statistics |

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

## macOS App (SwiftUI)

Xcode project at `app/KindleBrain/`. MVVM architecture.

### Chat Interface — Claude API with Tool Use
The chat view uses the **Anthropic API** directly from Swift with tool use. When the user asks a question:
1. App sends message to Claude API with tool definitions (`browse_library`, `read_book`, `get_library_stats`)
2. Claude responds with `tool_use` blocks when it needs to read books
3. App executes tools locally (reads markdown files from `books_md/`)
4. App returns `tool_result` to Claude
5. Claude synthesizes and streams the final response

Swift SDK: [SwiftAnthropic](https://github.com/jamesrochabrun/SwiftAnthropic) or [SwiftClaude](https://github.com/GeorgeLyon/SwiftClaude)

### Views
- **Chat view**: Streaming SSE responses from Claude with thinking/reasoning display, source citations, stop button
- **Library view**: Book cover grid, book detail with highlights, search within highlights, copy button
- **Memory view**: Browse/delete user memories, conversation summaries, reading interests

### Key Files
- `Services/APIService.swift` — Claude API integration + tool execution
- `Services/ServerManager.swift` — data directory management
- `ViewModels/ChatViewModel.swift` — chat state, streaming, tool loop
- `Models/Models.swift` — data models

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
  paths.py            # Centralized path resolution (~/.kindle-brain/)
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
    mcp_server.py     # MCP server (for Claude Desktop / claude.ai)
    api_server.py     # FastAPI server (legacy, optional)

app/KindleBrain/      # macOS SwiftUI app (Claude API + tool use)
```

## Data Location

Default: `~/.kindle-brain/` (override with `KINDLE_BRAIN_DATA` env var)

- `kindle.db` — main database (highlights, books, chapters)
- `memory.db` — user memory (profile, conversation summaries)
- `vectordb/` — ChromaDB index (optional)
- `book_texts/` — extracted book texts
- `books_md/` — markdown files (CATALOG.md, LIBRARY.md, per-book)
- `covers/` — book cover images

## Environment

- `GOOGLE_API_KEY` — Gemini API (summaries, embeddings). Free at https://aistudio.google.com/
- `ANTHROPIC_API_KEY` — Claude API (macOS app chat). From https://console.anthropic.com/
