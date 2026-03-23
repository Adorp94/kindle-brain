#!/usr/bin/env python3
"""
FastAPI backend for the Kindle Brain app.
Chat uses Gemini Pro with file-based tools (browse_library, read_book)
to navigate and reason across the user's personal reading library.
"""

import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from sse_starlette.sse import EventSourceResponse

from scripts.config import CHAT_MODEL, SUMMARY_MODEL
from scripts.memory import (
    build_memory_context, extract_memories_from_conversation,
    get_all_memories, add_memory, delete_memory,
    get_recent_summaries, get_top_interests, get_memory_db,
)

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "data" / "kindle.db"
BOOKS_MD_DIR = PROJECT_DIR / "data" / "books_md"

app = FastAPI(title="Kindle Brain", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve book covers as static files: /covers/{book_id}.jpg
COVERS_DIR = PROJECT_DIR / "data" / "covers"
if COVERS_DIR.exists():
    app.mount("/covers", StaticFiles(directory=str(COVERS_DIR)), name="covers")

# Clients (lazy init)
_gemini_client = None


def get_gemini():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
    return _gemini_client


def get_db():
    conn = sqlite3.Connection(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================================
# File-based library tools (same as MCP server)
# =============================================================================

def _create_library_tools():
    """Create browse_library and read_book tools for Gemini function calling.

    Returns (browse_fn, read_fn, books_read_list, tool_calls_log).
    books_read_list accumulates titles of books that were read.
    tool_calls_log records each tool invocation for UI display.
    """
    books_read = []
    tool_calls = []  # [{tool, args, summary}]

    def browse_library() -> str:
        """Browse the compact catalog of all books in the personal Kindle library.

        ALWAYS call this tool FIRST. Returns a compact index where each book has:
        a personalized description, semantic tags, and cross-book links.

        Think LATERALLY when matching books to questions:
        - "entrepreneurship" → Shoe Dog, Elon Musk, Zero to One, Alibaba, DREAM BIG
        - "leadership" → Meditations, Principles, Steve Jobs, The Hard Thing
        - Biographies and narratives are often MORE relevant than self-help

        Identify 5-8 relevant books, then call read_book() for each one.

        Returns:
            The full text of CATALOG.md covering all books.
        """
        catalog_path = BOOKS_MD_DIR / "CATALOG.md"
        if not catalog_path.exists():
            return "CATALOG.md not found. Run: kindle-brain generate --catalog"
        content = catalog_path.read_text(encoding='utf-8')
        tool_calls.append({"tool": "browse_library", "args": None, "summary": f"Read catalog ({len(content)} chars)"})
        return content

    def read_book(book_title: str) -> str:
        """Read a book's full file with fingerprint, highlights, and chapter summaries.

        Each book file contains: semantic fingerprint (what this reader highlighted most),
        book summary, chapter summaries, and all highlights organized by chapter.

        Call browse_library first to identify which books to read.

        Args:
            book_title: Partial title to match (case-insensitive).

        Returns:
            The book's markdown content with highlights and summaries.
        """
        if not BOOKS_MD_DIR.exists():
            return "Books directory not found."

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

        # Strip golden nuggets for lighter response
        content = re.sub(
            r'<details>\s*<summary>Golden Nugget \(context\)</summary>\s*.*?\s*</details>\s*',
            '', content, flags=re.DOTALL
        )

        books_read.append(matches[0].stem)
        tool_calls.append({"tool": "read_book", "args": book_title, "summary": f"Read {matches[0].stem} ({len(content)} chars)"})
        return content

    return browse_library, read_book, books_read, tool_calls


# =============================================================================
# System prompt
# =============================================================================

SYSTEM_PROMPT = """Eres un asistente de lectura profunda con acceso a la biblioteca personal del usuario.

Tienes dos herramientas:
1. browse_library() — Lee el catálogo compacto de TODOS los libros. SIEMPRE llama esto PRIMERO.
2. read_book(book_title) — Lee el archivo completo de un libro con highlights y resúmenes de capítulos.

ESTRATEGIA:
1. Llama browse_library() para ver todos los libros disponibles con descripciones y tags.
2. Identifica 5-8 libros relevantes pensando LATERALMENTE — una biografía puede enseñar sobre filosofía, un libro de negocios puede enseñar sobre relaciones.
3. Llama read_book() para cada libro relevante.
4. Sintetiza las ideas conectando highlights de múltiples libros.

SÍNTESIS:
- **Usa las palabras exactas del autor** — cita textualmente cuando sea poderoso.
- **Conecta ideas entre libros** — si múltiples autores tocan el mismo tema, conéctalos.
- **Cita siempre la fuente** — formato: (*Libro — Autor, p. X*) en cursiva.
- **Responde en el idioma del usuario**.
- **Sé profundo** — conecta 3-5+ fuentes con profundidad.

FORMATO:
- Párrafos claros y separados.
- **Negritas** para ideas clave, *cursivas* para citas.
- Encabezados (## o ###) cuando toque múltiples temas.
- Bloques de cita (> ) para citas textuales impactantes.
- Fuentes en cursiva: (*Steve Jobs — Walter Isaacson, p. 450*)

MEMORIA:
- Usa el perfil del usuario para personalizar respuestas.
- No menciones que "tienes memoria" — úsala naturalmente."""


def get_system_prompt_with_memory() -> str:
    """Build the full system prompt with memory context."""
    parts = [SYSTEM_PROMPT]
    memory_context = build_memory_context()
    if memory_context:
        parts.append(memory_context)
    return "\n\n".join(parts)


# =============================================================================
# Chat endpoints
# =============================================================================

@app.post("/chat")
async def chat(body: dict):
    """Chat with Gemini Pro using file-based library tools."""
    import asyncio

    message = body.get("message", "")
    if not message:
        return {"error": "message is required"}

    conversation_id = body.get("conversation_id")
    system_prompt = get_system_prompt_with_memory()
    gemini = get_gemini()

    browse_library, read_book, books_read, tool_calls = _create_library_tools()

    def _generate():
        return gemini.models.generate_content(
            model=CHAT_MODEL,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[browse_library, read_book],
                temperature=1.0,
                max_output_tokens=8192,
            ),
        )

    response = await asyncio.to_thread(_generate)

    sources = [{'book_title': title, 'author': '', 'page': None,
                'highlight': f'Read full book', 'score': None}
               for title in books_read]

    asyncio.create_task(asyncio.to_thread(
        extract_memories_from_conversation,
        message, response.text or "", books_read,
        conversation_id, gemini,
    ))

    return {"response": response.text, "sources": sources}


@app.post("/chat/stream")
async def chat_stream(body: dict):
    """Streaming chat with file-based library tools.

    Phase 1: Flash Lite with browse_library + read_book tools to gather context.
    Phase 2: Pro streams the synthesis with thinking/reasoning.
    """
    import asyncio
    import json

    message = body.get("message", "")
    if not message:
        return {"error": "message is required"}

    conversation_id = body.get("conversation_id")

    async def event_generator():
        gemini = get_gemini()

        # Phase 1: Flash Lite reads catalog + relevant books via tools
        browse_library, read_book, books_read, tool_calls = _create_library_tools()

        retrieval_prompt = (
            "You are a research librarian. The user asked a question about their reading library.\n\n"
            "1. Call browse_library() to see all available books.\n"
            "2. Identify 5-8 books most relevant to the question — think LATERALLY.\n"
            "3. Call read_book() for each relevant book.\n"
            "4. After reading all books, briefly list what you found.\n\n"
            f"User's question: {message}"
        )

        def _retrieve():
            return gemini.models.generate_content(
                model=SUMMARY_MODEL,
                contents=retrieval_prompt,
                config=types.GenerateContentConfig(
                    tools=[browse_library, read_book],
                    temperature=0.3,
                    max_output_tokens=512,
                ),
            )

        retrieval_response = await asyncio.to_thread(_retrieve)

        # Emit tool call events so the UI can show what happened
        for tc in tool_calls:
            yield {"event": "tool_call", "data": json.dumps(tc, ensure_ascii=False)}

        # Collect the book contents that were read
        # The tools already executed and books_read has the list
        book_contents = []
        for title in books_read:
            # Read the file content for the synthesis prompt
            for f in BOOKS_MD_DIR.glob("*.md"):
                if f.name in {"LIBRARY.md", "CATALOG.md"}:
                    continue
                if title.lower() in f.stem.lower():
                    content = f.read_text(encoding='utf-8')
                    # Strip golden nuggets for lighter context
                    content = re.sub(
                        r'<details>\s*<summary>Golden Nugget \(context\)</summary>\s*.*?\s*</details>\s*',
                        '', content, flags=re.DOTALL
                    )
                    book_contents.append(content)
                    break

        # Send sources (books that were read)
        sources = [{'book_title': title, 'author': '', 'page': None,
                    'highlight': f'Read full book', 'score': None}
                   for title in books_read]
        yield {"event": "sources", "data": json.dumps(sources, ensure_ascii=False)}

        # Phase 2: Stream synthesis with Pro
        context_block = "\n\n---\n\n".join(book_contents)
        synthesis_prompt = (
            f"CONTEXTO DE LA BIBLIOTECA ({len(books_read)} libros leídos):\n\n"
            f"{context_block}\n\n"
            f"---\n\n"
            f"PREGUNTA DEL USUARIO: {message}"
        )
        system_prompt = get_system_prompt_with_memory()

        queue = asyncio.Queue()
        collected_text = []

        async def run_in_thread():
            def _stream():
                response = gemini.models.generate_content_stream(
                    model=CHAT_MODEL,
                    contents=synthesis_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=1.0,
                        max_output_tokens=8192,
                        thinking_config=types.ThinkingConfig(
                            thinking_level="high",
                            include_thoughts=True,
                        ),
                    ),
                )
                for chunk in response:
                    try:
                        for part in chunk.candidates[0].content.parts:
                            if part.thought:
                                text = part.text or ""
                                if text.strip():
                                    asyncio.run_coroutine_threadsafe(
                                        queue.put(("thinking", text)), loop
                                    )
                            elif part.text:
                                asyncio.run_coroutine_threadsafe(
                                    queue.put(("token", part.text)), loop
                                )
                    except (AttributeError, IndexError):
                        if chunk.text:
                            asyncio.run_coroutine_threadsafe(
                                queue.put(("token", chunk.text)), loop
                            )
                asyncio.run_coroutine_threadsafe(
                    queue.put(None), loop
                )

            loop = asyncio.get_event_loop()
            await asyncio.to_thread(_stream)

        stream_task = asyncio.create_task(run_in_thread())

        while True:
            item = await queue.get()
            if item is None:
                break
            event_type, text = item
            if event_type == "token":
                collected_text.append(text)
            safe_text = text.replace("\n", "\\n")
            yield {"event": event_type, "data": safe_text}

        await stream_task
        yield {"event": "done", "data": ""}

        # Extract memories in background
        full_response = "".join(collected_text)
        asyncio.create_task(asyncio.to_thread(
            extract_memories_from_conversation,
            message, full_response, books_read,
            conversation_id, gemini,
        ))

    return EventSourceResponse(event_generator())


# =============================================================================
# Highlight explain endpoint
# =============================================================================

@app.get("/highlights/{highlight_id}/explain")
async def explain_highlight(highlight_id: int):
    """Explain a highlight using its golden nugget context and chapter summary.

    Uses Gemini Flash Lite for a brief, contextual explanation of what the
    author was discussing when the reader highlighted this passage.
    """
    import asyncio

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.text, c.rich_context, c.surrounding_context,
               c.page, c.note_text,
               b.title as book_title, b.author, b.summary as book_summary,
               ch.title as chapter_title, ch.summary as chapter_summary,
               ch.chapter_number
        FROM clippings c
        JOIN books b ON c.book_id = b.id
        LEFT JOIN chapters ch ON c.chapter_id = ch.id
        WHERE c.id = ?
    """, (highlight_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return {"error": "Highlight not found"}

    highlight_text = row['text']
    context = row['rich_context'] or row['surrounding_context'] or ''
    chapter_title = row['chapter_title'] or ''
    chapter_summary = row['chapter_summary'] or ''
    book_title = row['book_title']
    author = row['author'] or ''

    # Build prompt with available context
    context_parts = []
    context_parts.append(f"Book: {book_title} by {author}")

    if chapter_title:
        context_parts.append(f"Chapter: {chapter_title}")
    if chapter_summary:
        context_parts.append(f"Chapter summary: {chapter_summary}")

    if context:
        # Use first 8000 chars of golden nugget (enough for context, saves tokens)
        # Clean up highlight markers
        clean_context = context.replace("«««", "[HIGHLIGHTED: ").replace("»»»", "]")
        if len(clean_context) > 8000:
            # Center on the highlight markers
            marker_pos = clean_context.find("[HIGHLIGHTED:")
            if marker_pos > 0:
                start = max(0, marker_pos - 3000)
                end = min(len(clean_context), marker_pos + 5000)
                clean_context = clean_context[start:end]
            else:
                clean_context = clean_context[:8000]
        context_parts.append(f"Surrounding text from the book:\n{clean_context}")

    context_block = "\n\n".join(context_parts)

    prompt = f"""The reader highlighted this passage and wants to understand why it matters.

{context_block}

HIGHLIGHTED PASSAGE: "{highlight_text}"

Explain briefly (2-3 sentences) what the author was discussing when the reader highlighted this.
Focus on: what argument or idea the author was building, and why this specific passage captures something important.
Write in the same language as the highlighted text. Be concise and insightful, not generic."""

    gemini = get_gemini()

    def _explain():
        response = gemini.models.generate_content(
            model=SUMMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=300,
            ),
        )
        return response.text.strip()

    explanation = await asyncio.to_thread(_explain)

    return {
        "highlight_id": highlight_id,
        "highlight": highlight_text,
        "book_title": book_title,
        "chapter": chapter_title,
        "explanation": explanation,
    }


# =============================================================================
# Library endpoints (unchanged)
# =============================================================================

@app.get("/books")
async def books():
    """List all books with highlight counts."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            b.id, b.title, b.author, b.summary,
            COUNT(c.id) as highlight_count,
            SUM(CASE WHEN c.rich_context IS NOT NULL THEN 1 ELSE 0 END) as golden_nuggets,
            MIN(c.date) as first_highlight,
            MAX(c.date) as last_highlight
        FROM books b
        LEFT JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
        GROUP BY b.id
        HAVING highlight_count > 0
        ORDER BY highlight_count DESC
    """)

    results = []
    for row in cursor.fetchall():
        book_id = row['id']
        has_cover = (COVERS_DIR / f"{book_id}.jpg").exists()
        results.append({
            'id': book_id,
            'title': row['title'],
            'author': row['author'],
            'summary': row['summary'],
            'highlight_count': row['highlight_count'],
            'golden_nuggets': row['golden_nuggets'],
            'first_highlight': row['first_highlight'][:10] if row['first_highlight'] else None,
            'last_highlight': row['last_highlight'][:10] if row['last_highlight'] else None,
            'has_cover': has_cover,
        })

    conn.close()
    return results


@app.get("/books/{book_id}/highlights")
async def book_highlights(book_id: int):
    """Get all highlights from a specific book."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT b.title, b.author, b.summary
        FROM books b WHERE b.id = ?
    """, (book_id,))
    book = cursor.fetchone()
    if not book:
        return {"error": "Book not found"}

    cursor.execute("""
        SELECT
            c.id, c.text, c.surrounding_context, c.rich_context,
            c.page, c.date, c.note_text,
            ch.title as chapter_title, ch.chapter_number
        FROM clippings c
        LEFT JOIN chapters ch ON c.chapter_id = ch.id
        WHERE c.book_id = ? AND c.type = 'highlight'
        ORDER BY c.position_start
    """, (book_id,))

    highlights = []
    for row in cursor.fetchall():
        highlights.append({
            'id': row['id'],
            'text': row['text'],
            'rich_context': row['rich_context'],
            'surrounding_context': row['surrounding_context'],
            'page': row['page'],
            'date': row['date'][:10] if row['date'] else None,
            'note': row['note_text'],
            'chapter': row['chapter_title'],
            'chapter_number': row['chapter_number'],
        })

    conn.close()
    return {
        'book': {'title': book['title'], 'author': book['author'], 'summary': book['summary']},
        'highlight_count': len(highlights),
        'highlights': highlights,
    }


@app.get("/search")
async def search(
    q: str = Query(..., description="Search query"),
    top: int = Query(10, ge=1, le=50),
    book: str | None = Query(None, description="Filter by book title"),
):
    """Semantic search across all highlights."""
    try:
        import chromadb
        from chromadb.config import Settings
        from scripts.config import EMBEDDING_MODEL, COLLECTION_NAME

        VECTORDB_DIR = PROJECT_DIR / "vectordb"
        chroma = chromadb.PersistentClient(
            path=str(VECTORDB_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
        collection = chroma.get_collection(COLLECTION_NAME)
    except Exception:
        return {"error": "Vector index not available. Run: kindle-brain index"}

    gemini = get_gemini()
    response = gemini.models.embed_content(model=EMBEDDING_MODEL, contents=q)
    query_embedding = response.embeddings[0].values

    where = {"book_title": {"$eq": book}} if book else None
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top,
        where=where,
        include=["metadatas", "distances"]
    )

    if not results['ids'][0]:
        return []

    conn = get_db()
    cursor = conn.cursor()
    output = []
    for i, clip_id in enumerate(results['ids'][0]):
        cursor.execute("""
            SELECT c.text, c.page, c.date,
                   b.title as book_title, b.author,
                   ch.title as chapter_title
            FROM clippings c
            JOIN books b ON c.book_id = b.id
            LEFT JOIN chapters ch ON c.chapter_id = ch.id
            WHERE c.id = ?
        """, (clip_id,))
        row = cursor.fetchone()
        if row:
            output.append({
                'score': round(1 - results['distances'][0][i], 4),
                'highlight': row['text'],
                'book_title': row['book_title'],
                'author': row['author'],
                'page': row['page'],
                'chapter': row['chapter_title'],
            })
    conn.close()
    return output


@app.get("/stats")
async def stats():
    """Library statistics."""
    conn = get_db()
    cursor = conn.cursor()
    s = {}
    cursor.execute("SELECT COUNT(*) FROM books")
    s['total_books'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM clippings WHERE type = 'highlight'")
    s['total_highlights'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM clippings WHERE rich_context IS NOT NULL")
    s['golden_nuggets'] = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM clippings WHERE type = 'note'")
    s['total_notes'] = cursor.fetchone()[0]
    cursor.execute("SELECT MIN(date), MAX(date) FROM clippings WHERE date IS NOT NULL")
    dr = cursor.fetchone()
    s['date_range'] = {'first': dr[0][:10] if dr[0] else None, 'last': dr[1][:10] if dr[1] else None}
    cursor.execute("""
        SELECT b.title, COUNT(c.id) as cnt
        FROM books b JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
        GROUP BY b.id ORDER BY cnt DESC LIMIT 10
    """)
    s['top_books'] = [{'title': r[0], 'highlights': r[1]} for r in cursor.fetchall()]
    conn.close()
    return s


# =============================================================================
# Memory endpoints
# =============================================================================

@app.get("/memory")
async def get_memories():
    conn = get_memory_db()
    result = {
        "memories": get_all_memories(conn),
        "recent_conversations": get_recent_summaries(limit=20, conn=conn),
        "top_interests": get_top_interests(limit=15, conn=conn),
    }
    conn.close()
    return result


@app.post("/memory")
async def add_memory_endpoint(body: dict):
    fact = body.get("fact", "").strip()
    category = body.get("category", "general")
    if not fact:
        return {"error": "fact is required"}
    add_memory(fact=fact, category=category)
    return {"status": "ok"}


@app.delete("/memory/{memory_id}")
async def delete_memory_endpoint(memory_id: int):
    delete_memory(memory_id)
    return {"status": "ok"}


if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8765)
