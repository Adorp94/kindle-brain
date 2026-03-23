"""
MCP Server for Kindle Brain — File-based knowledge system.

Exposes structured markdown files (CATALOG.md + per-book files) for
intelligent navigation by Claude. No embeddings or vector search —
the LLM reads actual text and reasons over it directly.
"""

import logging
import re

from mcp.server.fastmcp import FastMCP

from kindle_brain.db import get_connection
from kindle_brain.paths import books_md_dir, db_path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

BOOKS_MD_DIR = books_md_dir()

mcp = FastMCP(
    "kindle-clippings",
    description="Personal Kindle reading highlights from 2018-2026. ~7000 highlights from 114 books. "
                "WORKFLOW: ALWAYS start with browse_library to see the compact catalog of all 114 books, "
                "identify 5-8 relevant books (think LATERALLY — biographies teach about leadership, "
                "philosophy books teach about business), then call read_book for each one."
)


@mcp.tool()
def browse_library() -> str:
    """
    Browse the compact catalog of all 114 books in the personal Kindle library.

    ALWAYS call this tool FIRST. Returns CATALOG.md — a compact index (~40K chars)
    where each book has: a personalized 1-sentence description, semantic tags,
    and cross-book links.

    Think LATERALLY when matching books to questions:
    - "entrepreneurship" → Shoe Dog, Elon Musk, Zero to One, Alibaba, DREAM BIG
    - "leadership" → Meditations, Principles, Steve Jobs, The Hard Thing
    - Biographies and narratives are often MORE relevant than self-help books

    Identify 5-8 relevant books, then call read_book() for each one.

    Returns:
        The full text of CATALOG.md covering all 114 books.
    """
    catalog_path = BOOKS_MD_DIR / "CATALOG.md"
    if not catalog_path.exists():
        return "CATALOG.md not found. Run: python scripts/generate_md.py --catalog"
    return catalog_path.read_text(encoding='utf-8')


@mcp.tool()
def read_book(
    book_title: str,
    include_nuggets: bool = False
) -> str:
    """
    Read a book's full file with fingerprint, highlights, and chapter summaries.

    Each book file contains: semantic fingerprint (what this reader highlighted most,
    cross-book connections), book summary, chapter summaries, and all highlights
    organized by chapter. Golden nuggets (large ~4000-word context blocks from
    the original book) are included only if requested.

    Call browse_library first to identify which books to read.

    Args:
        book_title: Partial title to match (case-insensitive). Matched against
                    markdown filenames in data/books_md/.
        include_nuggets: If True, include golden nugget context blocks (~4000
                        words each). If False (default), strip them for a
                        lighter response focused on highlights and summaries.

    Returns:
        The book's markdown content, or an error if no match found.
    """
    if not BOOKS_MD_DIR.exists():
        return "Books markdown directory not found. Run: python scripts/generate_md.py"

    # Find matching file (skip index files)
    search = book_title.lower()
    skip_files = {"LIBRARY.md", "CATALOG.md"}
    matches = []
    for f in BOOKS_MD_DIR.glob("*.md"):
        if f.name in skip_files:
            continue
        if search in f.stem.lower():
            matches.append(f)

    if not matches:
        available = [f.stem for f in BOOKS_MD_DIR.glob("*.md") if f.name not in skip_files]
        return f"No book found matching '{book_title}'. Available: {', '.join(sorted(available)[:20])}"

    if len(matches) > 1:
        return f"Multiple matches: {', '.join(f.stem for f in matches)}. Be more specific."

    content = matches[0].read_text(encoding='utf-8')

    if not include_nuggets:
        # Strip <details> blocks (golden nuggets) for lightweight response
        content = re.sub(
            r'<details>\s*<summary>Golden Nugget \(context\)</summary>\s*.*?\s*</details>\s*',
            '',
            content,
            flags=re.DOTALL
        )

    return content


@mcp.tool()
def get_library_stats() -> dict:
    """
    Get statistics about the Kindle highlights library.

    Returns:
        Statistics including total books, highlights, golden nuggets coverage,
        and most highlighted books.
    """
    db = db_path()
    if not db.exists():
        return {"error": "Database not found."}

    try:
        conn = get_connection(row_factory=True)
        cursor = conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) FROM books")
        stats['total_books'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM clippings WHERE type = 'highlight'")
        stats['total_highlights'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM clippings WHERE rich_context IS NOT NULL")
        stats['golden_nuggets'] = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(date), MAX(date) FROM clippings WHERE date IS NOT NULL")
        date_range = cursor.fetchone()
        stats['reading_period'] = {
            'first_highlight': date_range[0][:10] if date_range[0] else None,
            'last_highlight': date_range[1][:10] if date_range[1] else None
        }

        cursor.execute("""
            SELECT b.title, COUNT(c.id) as count
            FROM books b
            JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
            GROUP BY b.id ORDER BY count DESC LIMIT 10
        """)
        stats['most_highlighted_books'] = [
            {'title': row[0], 'highlights': row[1]}
            for row in cursor.fetchall()
        ]

        conn.close()
        return stats

    except Exception as e:
        logger.error(f"Stats error: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="stdio")
