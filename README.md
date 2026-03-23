<p align="center">
  <img src="public/kindle-brain.png" alt="Kindle Brain" width="128" height="128">
</p>

<h1 align="center">Kindle Brain</h1>

<p align="center">
  Turn your Kindle highlights into a personal AI knowledge base.<br>
  Ask Claude questions and get answers synthesized across all your books.
</p>

---

```
You: "What do my books say about persistence and founding companies?"

Claude reads your catalog → identifies Shoe Dog, Zero to One, Elon Musk,
The War of Art, The Almanack of Naval Ravikant → reads your actual
highlighted passages → synthesizes across 5+ books with your personal angle
```

## How It Works

You connect your Kindle highlights to Claude through an MCP server. When you ask a question, Claude follows this workflow:

1. **Browse the catalog** — reads `CATALOG.md`, a compact index of all your books (~48K chars). Each book has a one-sentence personalized description, semantic tags, and cross-book links. Claude reads all entries in one call and reasons *laterally* — a Nike biography is relevant to "entrepreneurship", a philosophy book to "leadership under pressure".

2. **Identify relevant books** — Claude picks 5-8 books that connect to your question, including unexpected ones that keyword search would miss.

3. **Read each book** — calls `read_book()` for each selected title. Each file contains a semantic fingerprint (what YOU highlighted most, not a generic summary), chapter summaries, and all your highlighted passages organized by chapter.

4. **Synthesize** — Claude weaves together insights from across your reading, grounded in the actual passages you found important.

## Why Not RAG?

We started with a traditional RAG pipeline — ChromaDB vector search with Gemini embeddings. It worked, but we kept hitting the same problem: **vector search returns isolated snippets ranked by similarity, stripped of all structure.**

When you ask "what do my books say about finding your own path?", RAG gives you 10 fragments from 10 books, ranked by cosine distance. Claude sees disconnected quotes without knowing which chapter they came from, what the author was arguing, or which passages the reader highlighted *around* them.

The file-based approach gives Claude what RAG can't:

- **Full chapter structure** — Claude sees how an author builds an argument across sections, not just one decontextualized quote
- **Your reading pattern** — which chapters you highlighted heavily (10+ highlights) vs barely touched (1-2) reveals what *you* found important
- **The semantic fingerprint** — a personalized profile of what you took from each book, generated from your actual highlights. Claude knows you read *Shoe Dog* for "radical momentum" and the "entrepreneurial monk" archetype, not because a generic summary says it's about Nike
- **Cross-book reasoning** — with full book files loaded, Claude can connect a concept from Antifragile with a story from Shoe Dog using the *author's own words* and your highlighted passages
- **Chapter summaries as scaffolding** — even chapters you didn't highlight get a summary, so Claude understands the book's full architecture

The tradeoff is clear: RAG is faster and cheaper (embed once, query in milliseconds), but the file-based approach produces dramatically better answers because Claude reasons over *structured context* instead of *isolated fragments*.

Vector search is still available as an optional module (`kindle-brain index`, `kindle-brain search`) for quick lookups, but it's not the primary interface.

### Why a two-tier catalog?

The full library index (`LIBRARY.md`, ~274K chars) is too large for a single MCP tool response. Claude.ai dumps it to a file and falls back to keyword search — defeating the purpose.

The solution is two tiers:
- **CATALOG.md** (~48K chars) — compact, fits inline. LLM-compressed descriptions with semantic tags like "gladiator entrepreneurs", "radical momentum", "barbell strategy" — real concepts from each book's vocabulary, not generic keywords.
- **Per-book files** — full fingerprint + all highlights + chapter summaries. Claude reads these after identifying relevant books from the catalog.

This lets Claude read ALL 114+ books in one call, then drill into specific books for depth.

### Why chapter summaries?

Kindle highlights are scattered across a book without structure. Chapter summaries provide the **missing scaffolding** — they tell Claude what the author is arguing in each section, so highlights can be understood in context rather than as isolated quotes.

A highlight like *"Start small and monopolize"* means one thing in isolation. With the chapter summary explaining Thiel's argument about niche markets and scaling, Claude can explain the *strategy* behind the quote.

### Why semantic fingerprints?

Each book has a "fingerprint" — not a generic book description, but a **personalized reading profile**:

- **What this reader highlighted most** — the themes YOU cared about (not what a reviewer would say)
- **These highlights help answer** — questions your highlights can address
- **Key highlighted ideas** — the specific concepts you marked
- **Connects to** — which other books in YOUR library connect to these themes

This is generated by Gemini Flash Lite from your actual highlights. It means Claude knows that when you read *Shoe Dog*, you focused on "radical momentum" and the "entrepreneurial monk" archetype — not just that it's a Nike memoir.

### What are golden nuggets?

Each highlight has a **~4,000-word context block** extracted from the original book text, centered on your highlighted passage and snapped to paragraph boundaries. The highlight is marked with delimiters (`«««highlight»»»`) inside the full surrounding text.

This preserves the author's exact words, metaphors, and arguments — not just the snippet you highlighted.

Golden nuggets are stored in collapsible `<details>` blocks in each book's markdown file. By default, `read_book()` strips them to keep responses lightweight (~50K chars per book). They're used by the **"Explain highlight"** feature in the macOS app — when you tap the lightbulb icon on any highlight, the golden nugget + chapter summary are sent to Gemini Flash Lite for a brief contextual explanation of what the author was arguing.

Golden nuggets require Calibre (to extract book text). Without Calibre, you still get highlights + summaries — but the deep context is missing.

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/Adorp94/kindle-brain.git
cd kindle-brain
pip install -e .

# 2. Interactive setup (detects Kindle, Calibre, locale, API key)
kindle-brain setup
# Or point to a clippings file directly:
kindle-brain setup --clippings-file "/path/to/My Clippings.txt"

# 3. Enrich your highlights
kindle-brain enrich --rich-context    # Extract golden nuggets (local, no API)
kindle-brain enrich                   # Generate summaries (Gemini API)

# 4. Generate files for Claude
kindle-brain generate                 # Book markdown files
kindle-brain generate --library-index # Semantic fingerprints (Gemini API)
kindle-brain generate --catalog       # Compact catalog (Gemini API)
kindle-brain generate --embed-fingerprints

# 5. Connect to Claude
kindle-brain serve
```

## Connect to Claude

### Claude Desktop (MCP Connector)

Add to your config (Settings > Developer > Edit Config):

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

Restart Claude Desktop. You'll see the three tools appear: `browse_library`, `read_book`, `get_library_stats`. Ask any question about your books and Claude will automatically use the connector.

### Claude Code (Skill)

If you're working inside the cloned repo, the skill at `.claude/skills/kindle-brain/SKILL.md` auto-triggers when you ask about your books.

### Any AI Agent (skills.sh)

Install across Claude Code, Cursor, Copilot, and 20+ other agents:

```bash
npx skills add Adorp94/kindle-brain
```

## Two Tiers

| | Basic | Full |
|---|---|---|
| **Requirements** | `My Clippings.txt` + Gemini API key | + [Calibre](https://calibre-ebook.com/) + ebook files on Kindle |
| **What you get** | Highlights + summaries + fingerprints + catalog | + golden nuggets (~4K-word context per highlight) |
| **Claude sees** | Your highlights organized by chapter with summaries | + the author's full argument surrounding each highlight |
| **Explain highlight** | Basic (highlight text only) | Full (uses golden nugget context for rich explanations) |

The setup wizard auto-detects your tier based on whether Calibre is installed.

## MCP Server Tools

| Tool | Description |
|------|-------------|
| `browse_library()` | Returns compact catalog of all books. Always call first. |
| `read_book(title, include_nuggets?)` | Returns a book's fingerprint + highlights + chapter summaries. |
| `get_library_stats()` | Library statistics. |

## CLI Commands

```bash
kindle-brain setup              # Interactive first-time setup
kindle-brain sync               # Sync from connected Kindle
kindle-brain sync --clippings-file f  # Sync from exported file
kindle-brain extract            # Extract book texts (requires Calibre)
kindle-brain enrich             # Context enrichment + LLM summaries
kindle-brain generate           # Generate markdown files
kindle-brain stats              # Library statistics
kindle-brain serve              # Start MCP server (stdio)
```

## The Enrichment Pipeline

```
My Clippings.txt
  │
  ▼
sync ─────────── Parse highlights into SQLite (Spanish + English)
  │
  ▼
extract ─────── Convert ebooks to plain text via Calibre (optional)
  │               Detect chapters automatically
  ▼
enrich ──────── Fuzzy-match each highlight in book text
  │               Extract ~20K char golden nugget centered on highlight
  │               Snap to paragraph boundaries
  │               Generate book + chapter summaries (Gemini Flash Lite)
  ▼
generate ────── Create per-book .md files (highlights + summaries)
  │               Generate LIBRARY.md (semantic fingerprints, Gemini)
  │               Compress to CATALOG.md (~48K chars, Gemini)
  │               Embed fingerprints into each book file
  ▼
serve ─────────  MCP server: browse_library → read_book → Claude synthesizes
```

## Architecture

```
src/kindle_brain/
  cli.py              # Unified CLI
  paths.py            # Centralized path resolution (~/.kindle-brain/)
  config.py           # Gemini model config + system config
  db.py               # SQLite connection factory
  sync.py             # Kindle clipping parser (Spanish + English)
  extract.py          # Calibre text extraction
  enrich.py           # Golden nuggets + LLM summaries
  generate_md.py      # Markdown + catalog generation
  memory.py           # User memory system (3 layers)
  server/
    mcp_server.py     # MCP server (primary interface for Claude)
    api_server.py     # FastAPI server (for macOS app)
```

### AI Stack

| Model | Use |
|-------|-----|
| `gemini-3.1-pro-preview` | Chat reasoning in macOS app (tool use + synthesis) |
| `gemini-3.1-flash-lite-preview` | Summaries, fingerprints, catalog compression, highlight explanations |
| `gemini-embedding-2-preview` | Optional vector embeddings for CLI search |

### Data Location

Default: `~/.kindle-brain/` (override with `KINDLE_BRAIN_DATA` env var)

```
~/.kindle-brain/
  kindle.db         # Main database (highlights, books, chapters)
  memory.db         # User memory (profile, conversation summaries)
  config.json       # System config (tier, locale, paths)
  book_texts/       # Extracted plain text from ebooks
  books_md/         # Markdown files (CATALOG.md, LIBRARY.md, per-book)
  covers/           # Book cover images (optional)
```

## macOS App (SwiftUI)

Native macOS app at `app/KindleBrain/` with:

- **Chat view** — Streaming Gemini Pro responses with tool use (browse_library, read_book), thinking display, tool call visibility
- **Library view** — Book cover grid, highlights with search, **lightbulb "Explain" button** on each highlight (uses golden nugget context + chapter summary)
- **Memory view** — User profile, conversation summaries, reading interests

## Languages

Supports Kindle clippings in **English** and **Spanish**. Locale is auto-detected from your `My Clippings.txt` file.

## Requirements

- Python 3.11+
- [Gemini API key](https://aistudio.google.com/) (free tier available)
- [Calibre](https://calibre-ebook.com/) (optional, for golden nuggets)

## License

MIT
