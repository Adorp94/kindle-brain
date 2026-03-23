#!/usr/bin/env python3
"""
FastAPI backend for the Kindle Brain app.
Chat endpoint retrieves golden nuggets and uses Gemini Pro for deep reasoning.
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import chromadb
import uvicorn
from chromadb.config import Settings
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from sse_starlette.sse import EventSourceResponse

from scripts.config import EMBEDDING_MODEL, CHAT_MODEL, SUMMARY_MODEL, COLLECTION_NAME
from scripts.memory import (
    build_memory_context, extract_memories_from_conversation,
    get_all_memories, add_memory, delete_memory,
    get_recent_summaries, get_top_interests, get_memory_db,
)

load_dotenv()

PROJECT_DIR = Path(__file__).parent.parent
DB_PATH = PROJECT_DIR / "data" / "kindle.db"
VECTORDB_DIR = PROJECT_DIR / "vectordb"

app = FastAPI(title="Kindle Brain", version="1.0.0")

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
_chroma_client = None


def get_gemini():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))
    return _gemini_client


def get_chroma():
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(VECTORDB_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
    return _chroma_client


def get_db():
    conn = sqlite3.Connection(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def diversify_results(
    results: list[dict], max_per_book: int = 2, max_total: int = 10
) -> list[dict]:
    """Cap results per book and apply greedy diversity selection.

    Ensures no single book dominates the results. Picks the best result from
    each book first, then fills remaining slots round-robin.
    """
    if not results:
        return []

    # Group by book
    by_book: dict[str, list[dict]] = {}
    for r in results:
        key = r.get('book_title', '')
        by_book.setdefault(key, []).append(r)

    # Sort each book's results by score descending
    for key in by_book:
        by_book[key].sort(key=lambda x: x.get('score', 0), reverse=True)

    # Greedy round-robin: pick best from each book, then second-best, etc.
    diverse = []
    for round_idx in range(max_per_book):
        for key in by_book:
            if round_idx < len(by_book[key]) and len(diverse) < max_total:
                diverse.append(by_book[key][round_idx])

    # Sort final list by score descending
    diverse.sort(key=lambda x: x.get('score', 0), reverse=True)
    return diverse[:max_total]


def _create_search_tool():
    """Create a search tool callable for Gemini function calling + a results collector.

    Returns (search_function, collected_results_list).
    The search function can be passed directly to Gemini's tools parameter.
    The collected list accumulates all results across multiple tool calls.
    """
    collected = []
    seen_ids = set()

    def search_kindle_library(query: str, top_k: int = 8, book_title: str = "") -> list[dict]:
        """Search the user's Kindle highlights library by semantic similarity.

        Returns highlights with rich context (~4000 words) from the original book text.
        The library contains ~7000 highlights from ~114 books in Spanish and English,
        read between 2018 and 2026.

        STRATEGY: Call this tool multiple times with DIFFERENT approaches:
        1. First, do a broad search on the core theme.
        2. Then, do TARGETED searches within specific books that you know are relevant
           (from the book catalog). Use the book_title parameter to search within a
           specific book. This is critical for narrative/biography books like Shoe Dog,
           Elon Musk, Steve Jobs, etc. whose stories don't match generic keyword searches.
        3. Each call should target a distinct concept or book.

        Args:
            query: Natural language search query
            top_k: Maximum results to return per search (default 8)
            book_title: Optional — filter results to a specific book title.
                Use this to search WITHIN a known relevant book (e.g. "Shoe Dog",
                "Elon Musk", "Zero to One"). Partial match supported.

        Returns:
            List of highlights with book info, relevance score, and rich context.
        """
        gemini = get_gemini()
        chroma = get_chroma()

        try:
            collection = chroma.get_collection(COLLECTION_NAME)
        except Exception:
            return []

        response = gemini.models.embed_content(
            model=EMBEDDING_MODEL, contents=query,
        )
        query_embedding = response.embeddings[0].values

        # Build metadata filter for book-targeted search
        where = None
        if book_title:
            where = {"book_title": {"$contains": book_title}}

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2,  # fetch extra for diversity filtering
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        if not results['ids'][0]:
            return []

        conn = get_db()
        cursor = conn.cursor()

        nuggets = []
        for i, clip_id in enumerate(results['ids'][0]):
            if clip_id in seen_ids:
                continue
            cursor.execute("""
                SELECT c.text, c.rich_context, c.surrounding_context,
                       c.page, b.title as book_title, b.author,
                       b.summary as book_summary,
                       ch.title as chapter_title, ch.summary as chapter_summary
                FROM clippings c
                JOIN books b ON c.book_id = b.id
                LEFT JOIN chapters ch ON c.chapter_id = ch.id
                WHERE c.id = ?
            """, (clip_id,))

            row = cursor.fetchone()
            if row:
                nugget = {
                    'clip_id': clip_id,
                    'highlight': row['text'],
                    'context': row['rich_context'] or row['surrounding_context'] or '',
                    'book_title': row['book_title'],
                    'author': row['author'] or '',
                    'page': row['page'],
                    'chapter': row['chapter_title'] or '',
                    'score': round(1 - results['distances'][0][i], 4),
                }
                # Add book and chapter summaries for intellectual context
                if row['book_summary']:
                    nugget['book_summary'] = row['book_summary']
                if row['chapter_summary']:
                    nugget['chapter_summary'] = row['chapter_summary']
                nuggets.append(nugget)

        conn.close()

        # Diversify: max 2 per book per search call
        diverse = diversify_results(nuggets, max_per_book=2, max_total=top_k)
        for n in diverse:
            seen_ids.add(n.pop('clip_id'))
        collected.extend(diverse)
        return diverse

    return search_kindle_library, collected


# =============================================================================
# Book catalog for agentic retrieval
# =============================================================================

_book_catalog_cache = None


def get_book_catalog() -> str:
    """Load book titles, authors, and theme summaries for the retrieval prompt.

    Cached after first call. Includes a one-line theme description from the
    book summary so the model knows WHAT each book is about, not just the title.
    This lets it craft targeted searches like 'Phil Knight perseverance Nike'
    instead of generic 'entrepreneurship' queries.
    """
    global _book_catalog_cache
    if _book_catalog_cache is not None:
        return _book_catalog_cache

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.title, b.author, b.summary, COUNT(c.id) as highlights
        FROM books b
        JOIN clippings c ON b.id = c.book_id AND c.type = 'highlight'
        GROUP BY b.id
        HAVING highlights > 0
        ORDER BY highlights DESC
    """)
    lines = []
    for row in cursor.fetchall():
        author = f" by {row['author']}" if row['author'] else ""
        # Extract first sentence of summary as theme hint
        summary = row['summary'] or ''
        theme = ''
        if summary:
            # Get first meaningful sentence (skip markdown headers)
            for sent in summary.replace('###', '').replace('**', '').split('.'):
                sent = sent.strip().lstrip('#').strip()
                if len(sent) > 30:
                    theme = f" — {sent.strip()[:120]}"
                    break
        lines.append(f"- {row['title']}{author} [{row['highlights']}h]{theme}")
    conn.close()

    _book_catalog_cache = "\n".join(lines)
    return _book_catalog_cache


# =============================================================================
# System prompts
# =============================================================================

# For /chat endpoint: model has the search tool and decides how to use it
SYSTEM_PROMPT = """Eres un asistente de lectura profunda con acceso a la biblioteca personal del usuario — ~7,000 highlights de ~114 libros leídos entre 2018 y 2026.

Tienes una herramienta de búsqueda (search_kindle_library) que busca en la biblioteca por similitud semántica. Cada resultado incluye el subrayado original y un bloque masivo de contexto (~4,000 palabras) del libro — las palabras exactas del autor, con el subrayado marcado entre ««« y »»».

ESTRATEGIA DE BÚSQUEDA (MUY IMPORTANTE):
- Para preguntas complejas, filosóficas o que tocan múltiples temas: busca 2-4 veces con queries MUY DISTINTOS que apunten a diferentes ángulos, conceptos o tradiciones intelectuales.
- Después de cada búsqueda, revisa los resultados. Si solo aparecen 1-2 libros, busca otra vez con un ángulo completamente diferente.
- Para preguntas simples (sobre un libro/autor específico, saludos): una búsqueda basta.
- Busca en el mismo idioma que la pregunta del usuario.

SÍNTESIS:
1. **Usa las palabras exactas del autor** — cita textualmente cuando sea poderoso.
2. **Conecta ideas entre libros** — si múltiples autores tocan el mismo tema desde ángulos distintos, conéctalos. Las ideas más valiosas aparecen en múltiples tradiciones.
3. **Contextualiza para el usuario** — explica por qué es relevante para su pregunta.
4. **Cita siempre la fuente** — formato: (*Libro — Autor, p. X*) en cursiva.
5. **Responde en el idioma del usuario**.
6. **Sé profundo, no superficial** — una buena respuesta conecta 3-5+ fuentes con profundidad.
7. **Busca el meta-patrón** — encuentra la idea profunda que conecta todas las fuentes, el insight que trasciende libros individuales.

FORMATO:
- Párrafos claros y separados. NUNCA un solo bloque de texto largo.
- **Negritas** para ideas clave, *cursivas* para citas del autor.
- Encabezados (## o ###) cuando toque múltiples temas.
- Bloques de cita (> ) para citas textuales impactantes.
- Fuentes en cursiva: (*Steve Jobs — Walter Isaacson, p. 450*)
- No incluyas los marcadores ««« ni »»» en tu respuesta.

MEMORIA Y PERSONALIZACIÓN:
- Usa el perfil del usuario para personalizar respuestas.
- Referencia conversaciones pasadas cuando sea relevante.
- No menciones que "tienes memoria" — úsala naturalmente.
- Si el usuario dice "recuerda que..." o "olvida que...", confirma y ajusta."""

# For streaming Phase 2: model receives pre-retrieved nuggets (no tool access)
SYNTHESIS_PROMPT = """Eres un asistente de lectura profunda. Recibes golden nuggets (bloques masivos de contexto original) de la biblioteca personal del usuario — ~7,000 highlights de ~114 libros leídos entre 2018 y 2026.

Los golden nuggets contienen las palabras exactas del autor, con el subrayado marcado entre ««« y »»». Han sido recuperados desde múltiples ángulos de búsqueda para darte perspectivas diversas.

Tu trabajo:
1. **Usa las palabras exactas del autor** — cita textualmente cuando sea poderoso.
2. **Conecta ideas entre libros** — si múltiples autores tocan el mismo tema desde ángulos distintos, conéctalos.
3. **Contextualiza para el usuario** — explica por qué es relevante para su pregunta.
4. **Cita siempre la fuente** — formato: (*Libro — Autor, p. X*) en cursiva.
5. **Responde en el idioma del usuario**.
6. **Sé profundo** — conecta 3-5+ fuentes con profundidad. DEBES referenciar ideas de al menos 4-5 libros diferentes si el contexto los provee.
7. **Busca el meta-patrón** — la idea profunda que conecta todas las fuentes, el insight que trasciende libros individuales.

FORMATO:
- Párrafos claros y separados. NUNCA un solo bloque de texto largo.
- **Negritas** para ideas clave, *cursivas* para citas del autor.
- Encabezados (## o ###) cuando toque múltiples temas.
- Bloques de cita (> ) para citas textuales impactantes.
- Fuentes en cursiva: (*Steve Jobs — Walter Isaacson, p. 450*)
- No incluyas ««« ni »»» en tu respuesta.

MEMORIA Y PERSONALIZACIÓN:
- Usa el perfil del usuario para personalizar respuestas.
- Referencia conversaciones pasadas cuando sea relevante.
- No menciones que "tienes memoria" — úsala naturalmente."""

# Prompt template for Flash Lite to orchestrate retrieval (Phase 1 of streaming)
_RETRIEVAL_TEMPLATE = (
    "You are a research librarian. Search the user's Kindle highlights library "
    "to find the most relevant and DIVERSE passages for their question.\n\n"
    "IMPORTANT — Here are ALL the books in the library:\n{book_catalog}\n\n"
    "Strategy:\n"
    "1. Scan the book list and identify 5-8 books that likely contain relevant insights. "
    "Think broadly — biographies, philosophy, business, psychology, self-development.\n"
    "2. Do ONE broad search on the core theme of the question.\n"
    "3. Then do 2-3 TARGETED searches within specific books using the book_title parameter. "
    "This is CRITICAL for narrative/biography books (Shoe Dog, Elon Musk, Steve Jobs, "
    "The Dream Machine, etc.) whose stories don't match generic keyword searches.\n"
    "   Example: search(query='founding a company perseverance', book_title='Shoe Dog')\n"
    "   Example: search(query='product vision and design', book_title='Steve Jobs')\n"
    "   Example: search(query='building wealth ownership', book_title='Almanack of Naval')\n"
    "4. Prioritize the most highlighted books (shown in brackets) — they contain the "
    "deepest engagement from the reader.\n\n"
    "After searching, briefly list what you found.\n\n"
    "User's question: {question}"
)


def build_retrieval_prompt(question: str) -> str:
    """Build the retrieval prompt with the book catalog injected."""
    return _RETRIEVAL_TEMPLATE.format(
        book_catalog=get_book_catalog(),
        question=question,
    )


def get_system_prompt_with_memory(use_synthesis: bool = False) -> str:
    """Build the full system prompt with memory context and book catalog."""
    base = SYNTHESIS_PROMPT if use_synthesis else SYSTEM_PROMPT

    parts = [base]

    # Add book catalog so the model knows what's available to search
    if not use_synthesis:
        catalog = get_book_catalog()
        parts.append(
            f"LIBROS DISPONIBLES EN LA BIBLIOTECA:\n{catalog}\n\n"
            "Usa esta lista para planificar búsquedas que toquen libros diversos y relevantes. "
            "Busca por nombres de autores, conceptos específicos de cada libro, o vocabulario "
            "único de cada obra para obtener resultados de fuentes variadas."
        )

    memory_context = build_memory_context()
    if memory_context:
        parts.append(memory_context)

    return "\n\n".join(parts)


def build_chat_prompt(message: str, nuggets: list[dict]) -> str:
    """Build the user prompt with retrieved golden nuggets + intellectual context."""
    context_parts = []
    seen_book_summaries = set()  # avoid repeating same book summary

    for i, n in enumerate(nuggets, 1):
        source = f"{n['book_title']} — {n['author']}"
        if n['page']:
            source += f" (p. {n['page']})"
        if n['chapter']:
            source += f" | {n['chapter']}"

        parts = [f"--- Fuente {i}: {source} (relevancia: {n['score']}) ---"]

        # Add book summary once per book (trimmed)
        book_key = n['book_title']
        if n.get('book_summary') and book_key not in seen_book_summaries:
            seen_book_summaries.add(book_key)
            # First 300 chars of summary — enough for theme
            summary = n['book_summary'][:300].rsplit('.', 1)[0] + '.'
            parts.append(f"Sobre este libro: {summary}")

        # Add chapter summary if available (trimmed)
        if n.get('chapter_summary'):
            ch_summary = n['chapter_summary'][:200].rsplit('.', 1)[0] + '.'
            parts.append(f"Contexto del capítulo: {ch_summary}")

        parts.append(f"Subrayado: {n['highlight']}")
        parts.append(f"\nContexto original:\n{n['context']}")

        context_parts.append("\n".join(parts))

    context_block = "\n\n".join(context_parts)

    unique_books = len(set(n['book_title'] for n in nuggets))

    return (
        f"CONTEXTO DE LA BIBLIOTECA ({len(nuggets)} golden nuggets de {unique_books} libros diferentes):\n\n"
        f"{context_block}\n\n"
        f"---\n\n"
        f"PREGUNTA DEL USUARIO: {message}"
    )


@app.post("/chat")
async def chat(body: dict):
    """Chat endpoint: Gemini Pro with agentic function calling.

    The model autonomously decides what to search, can search multiple times,
    sees intermediate results, and synthesizes across all findings.
    """
    import asyncio

    message = body.get("message", "")
    if not message:
        return {"error": "message is required"}

    conversation_id = body.get("conversation_id")
    system_prompt = get_system_prompt_with_memory()
    gemini = get_gemini()

    # Create search tool with results collector
    search_tool, collected = _create_search_tool()

    def _generate():
        return gemini.models.generate_content(
            model=CHAT_MODEL,
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[search_tool],
                temperature=1.0,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(thinking_level="high"),
            ),
        )

    response = await asyncio.to_thread(_generate)

    # Build sources from all tool calls
    seen = set()
    sources = []
    for n in collected:
        key = (n['book_title'], n['highlight'][:80])
        if key not in seen:
            seen.add(key)
            sources.append({
                'book_title': n['book_title'],
                'author': n['author'],
                'page': n['page'],
                'highlight': n['highlight'][:200],
                'score': n['score'],
            })

    # Extract memories in background
    books_cited = list(set(n['book_title'] for n in collected))
    asyncio.create_task(asyncio.to_thread(
        extract_memories_from_conversation,
        message, response.text or "", books_cited,
        conversation_id, gemini,
    ))

    return {
        "response": response.text,
        "sources": sources,
    }


@app.post("/chat/stream")
async def chat_stream(body: dict):
    """Streaming chat with agentic retrieval.

    Phase 1: Flash Lite with function calling orchestrates diverse retrieval.
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

        # Phase 1: Agentic retrieval via Flash Lite with function calling
        search_tool, collected = _create_search_tool()

        retrieval_prompt = build_retrieval_prompt(message)

        def _retrieve():
            return gemini.models.generate_content(
                model=SUMMARY_MODEL,
                contents=retrieval_prompt,
                config=types.GenerateContentConfig(
                    tools=[search_tool],
                    temperature=0.3,
                    max_output_tokens=512,
                ),
            )

        await asyncio.to_thread(_retrieve)

        # Apply final diversity pass on all collected results
        nuggets = diversify_results(collected, max_per_book=3, max_total=15)

        # Send sources
        sources = [
            {
                'book_title': n['book_title'],
                'author': n['author'],
                'page': n['page'],
                'highlight': n['highlight'][:200],
                'score': n['score'],
            }
            for n in nuggets
        ]
        yield {"event": "sources", "data": json.dumps(sources, ensure_ascii=False)}

        # Phase 2: Stream synthesis with Pro
        prompt = build_chat_prompt(message, nuggets)
        system_prompt = get_system_prompt_with_memory(use_synthesis=True)

        queue = asyncio.Queue()
        collected_text = []

        async def run_in_thread():
            def _stream():
                response = gemini.models.generate_content_stream(
                    model=CHAT_MODEL,
                    contents=prompt,
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
        books_cited = list(set(n['book_title'] for n in nuggets))
        asyncio.create_task(asyncio.to_thread(
            extract_memories_from_conversation,
            message, full_response, books_cited,
            conversation_id, gemini,
        ))

    return EventSourceResponse(event_generator())


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
    """Semantic search across all highlights with diversity."""
    gemini = get_gemini()
    chroma = get_chroma()

    try:
        collection = chroma.get_collection(COLLECTION_NAME)
    except Exception:
        return []

    response = gemini.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=q,
    )
    query_embedding = response.embeddings[0].values

    where = {"book_title": {"$eq": book}} if book else None

    # Fetch more than requested so diversity filter has room to work
    fetch_k = top * 2 if not book else top

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=fetch_k,
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
            SELECT c.text, c.page, c.date, c.note_text,
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
                'date': row['date'][:10] if row['date'] else None,
            })

    conn.close()

    # Apply diversity cap unless filtering by a single book
    if not book:
        output = diversify_results(output, max_per_book=3, max_total=top)

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
    s['date_range'] = {
        'first': dr[0][:10] if dr[0] else None,
        'last': dr[1][:10] if dr[1] else None,
    }

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
    """Get all user memories, recent summaries, and top interests."""
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
    """Manually add a memory fact."""
    fact = body.get("fact", "").strip()
    category = body.get("category", "general")
    if not fact:
        return {"error": "fact is required"}
    add_memory(fact=fact, category=category)
    return {"status": "ok", "fact": fact, "category": category}


@app.delete("/memory/{memory_id}")
async def delete_memory_endpoint(memory_id: int):
    """Delete a memory by ID."""
    delete_memory(memory_id)
    return {"status": "ok"}


if __name__ == '__main__':
    uvicorn.run(app, host="127.0.0.1", port=8765)
