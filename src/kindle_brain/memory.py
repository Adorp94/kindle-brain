"""
Memory system for Kindle Brain.

Three layers inspired by ChatGPT's approach, tailored for a reading highlights app:

1. User Profile — Long-term facts (name, profession, interests, preferences)
   Extracted automatically after each conversation by Gemini Flash Lite.
   Injected into every chat prompt.

2. Conversation Summaries — Lightweight digest of past chats
   (user's question + key topics + books discussed).
   Last ~20 summaries injected for cross-chat continuity.

3. Reading Interests — Tracks which books/topics user asks about most.
   Used to enhance search relevance and personalization.

All stored in SQLite alongside existing kindle.db data.
"""

import json
from datetime import datetime, timezone

from google.genai import types

from kindle_brain.config import SUMMARY_MODEL, get_gemini_client
from kindle_brain.db import get_memory_connection


def get_memory_db():
    """Get or create the memory database."""
    conn = get_memory_connection()
    _create_tables(conn)
    return conn


def _create_tables(conn):
    """Create memory tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact TEXT NOT NULL UNIQUE,
            category TEXT NOT NULL DEFAULT 'general',
            confidence REAL NOT NULL DEFAULT 1.0,
            source_conversation TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL UNIQUE,
            user_query TEXT NOT NULL,
            summary TEXT NOT NULL,
            topics TEXT,
            books_mentioned TEXT,
            language TEXT DEFAULT 'es',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reading_interests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL UNIQUE,
            query_count INTEGER NOT NULL DEFAULT 1,
            last_query TEXT,
            books_related TEXT,
            first_asked TEXT NOT NULL,
            last_asked TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memories_category ON user_memories(category);
        CREATE INDEX IF NOT EXISTS idx_summaries_created ON conversation_summaries(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_interests_count ON reading_interests(query_count DESC);
    """)


# =============================================================================
# User Memory (Layer 1: Long-term facts)
# =============================================================================

def get_all_memories(conn=None) -> list[dict]:
    """Get all stored user memories."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    cursor = conn.execute(
        "SELECT id, fact, category, confidence, created_at, updated_at "
        "FROM user_memories ORDER BY category, created_at"
    )
    memories = [dict(row) for row in cursor.fetchall()]
    if own_conn:
        conn.close()
    return memories


def add_memory(fact: str, category: str = "general",
               confidence: float = 1.0, conversation_id: str = None,
               conn=None):
    """Add a new memory fact. Ignores duplicates."""
    import sqlite3
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO user_memories "
            "(fact, category, confidence, source_conversation, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (fact, category, confidence, conversation_id, now, now)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    if own_conn:
        conn.close()


def delete_memory(memory_id: int, conn=None):
    """Delete a memory by ID."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    conn.execute("DELETE FROM user_memories WHERE id = ?", (memory_id,))
    conn.commit()
    if own_conn:
        conn.close()


def format_memories_for_prompt(conn=None, max_facts: int = 30) -> str:
    """Format memories in telegraphic format for the system prompt.

    Uses compressed key: value format (~60% fewer tokens than full sentences).
    Caps at max_facts to prevent prompt bloat.
    """
    memories = get_all_memories(conn)
    if not memories:
        return ""

    # Group by category, limit total
    by_cat: dict[str, list[str]] = {}
    count = 0
    for m in memories:
        if count >= max_facts:
            break
        cat = m['category']
        if cat not in by_cat:
            by_cat[cat] = []
        by_cat[cat].append(m['fact'])
        count += 1

    # Telegraphic format: compact, token-efficient
    lines = ["PERFIL DEL USUARIO:"]
    for cat, facts in by_cat.items():
        joined = " | ".join(facts)
        lines.append(f"- {cat}: {joined}")

    return "\n".join(lines)


# =============================================================================
# Conversation Summaries (Layer 2: Cross-chat continuity)
# =============================================================================

def get_recent_summaries(limit: int = 20, conn=None) -> list[dict]:
    """Get the most recent conversation summaries."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    cursor = conn.execute(
        "SELECT conversation_id, user_query, summary, topics, books_mentioned, "
        "language, created_at FROM conversation_summaries "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    summaries = [dict(row) for row in cursor.fetchall()]
    if own_conn:
        conn.close()
    return summaries


def save_conversation_summary(conversation_id: str, user_query: str,
                               summary: str, topics: list[str] = None,
                               books_mentioned: list[str] = None,
                               language: str = "es", conn=None):
    """Save a conversation summary."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO conversation_summaries "
        "(conversation_id, user_query, summary, topics, books_mentioned, language, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (conversation_id, user_query, summary,
         json.dumps(topics or []), json.dumps(books_mentioned or []),
         language, now)
    )
    conn.commit()
    if own_conn:
        conn.close()


def format_summaries_for_prompt(conn=None, max_summaries: int = 15) -> str:
    """Format recent conversation summaries in compact format for the system prompt.

    Only includes user's query + topics (not full responses).
    Capped at max_summaries to prevent prompt bloat.
    """
    summaries = get_recent_summaries(limit=max_summaries, conn=conn)
    if not summaries:
        return ""

    lines = ["CONVERSACIONES RECIENTES:"]
    for s in summaries:
        ts = s['created_at'][:10]
        topics = json.loads(s['topics']) if s['topics'] else []
        topic_str = f" [{', '.join(topics)}]" if topics else ""
        lines.append(f"- {ts}: {s['user_query'][:80]}{topic_str}")

    return "\n".join(lines)


# =============================================================================
# Reading Interests (Layer 3: Topic tracking)
# =============================================================================

def track_interest(topic: str, query: str, books: list[str] = None, conn=None):
    """Track a reading interest/topic."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    now = datetime.now(timezone.utc).isoformat()
    books_json = json.dumps(books or [])

    # Try to update existing
    cursor = conn.execute(
        "UPDATE reading_interests SET query_count = query_count + 1, "
        "last_query = ?, books_related = ?, last_asked = ? WHERE topic = ?",
        (query, books_json, now, topic)
    )
    if cursor.rowcount == 0:
        conn.execute(
            "INSERT INTO reading_interests "
            "(topic, query_count, last_query, books_related, first_asked, last_asked) "
            "VALUES (?, 1, ?, ?, ?, ?)",
            (topic, query, books_json, now, now)
        )
    conn.commit()
    if own_conn:
        conn.close()


def get_top_interests(limit: int = 10, conn=None) -> list[dict]:
    """Get the most-queried topics."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()
    cursor = conn.execute(
        "SELECT topic, query_count, last_query, books_related, last_asked "
        "FROM reading_interests ORDER BY query_count DESC LIMIT ?",
        (limit,)
    )
    interests = [dict(row) for row in cursor.fetchall()]
    if own_conn:
        conn.close()
    return interests


# =============================================================================
# AI-powered memory extraction (runs after each conversation)
# =============================================================================

EXTRACT_PROMPT = """Analiza esta conversación entre un usuario y un asistente de lectura. Extrae información en formato JSON.

HECHOS YA CONOCIDOS DEL USUARIO (evita duplicados, detecta contradicciones):
{existing_memories}

CONVERSACIÓN:
Usuario: {user_message}

Respuesta del asistente (resumen): {assistant_summary}

Libros citados: {books_cited}

---

Responde SOLO con un JSON válido con esta estructura exacta:
{{
  "user_facts": [
    {{"fact": "dato sobre el usuario", "category": "profesion|intereses|preferencias|contexto_personal|metas", "confidence": 0.9, "replaces": null}}
  ],
  "conversation_summary": "resumen de 1-2 oraciones de lo que preguntó y qué encontró útil",
  "topics": ["tema1", "tema2"],
  "language": "es o en"
}}

Reglas:
- Solo extrae hechos EXPLÍCITOS que el usuario revela sobre sí mismo (profesión, situación, intereses, metas)
- NO inventes hechos. Si el usuario no revela nada personal, devuelve "user_facts": []
- NO dupliques hechos ya conocidos. Si el hecho ya existe en la lista anterior, NO lo incluyas
- Si un hecho nuevo CONTRADICE uno existente, inclúyelo con "replaces": "el hecho viejo exacto que reemplaza"
- confidence: 0.7-1.0. Solo incluye hechos con confidence >= 0.7
- Los temas deben ser conceptos clave (ej: "liderazgo", "diseño de producto", "estoicismo")
- El resumen debe capturar la INTENCIÓN del usuario, no el contenido de la respuesta
- Si el usuario hizo la pregunta en español, language = "es"; si en inglés, language = "en"
"""


def extract_memories_from_conversation(
    user_message: str,
    assistant_response: str,
    books_cited: list[str],
    conversation_id: str = None,
    gemini_client=None,
) -> dict:
    """
    Use Gemini Flash Lite to extract memories from a conversation.
    Returns the extracted data dict.
    """
    if gemini_client is None:
        gemini_client = get_gemini_client()

    # Truncate assistant response for the extraction prompt
    assistant_summary = assistant_response[:500] + "..." if len(assistant_response) > 500 else assistant_response

    # Get existing memories to avoid duplicates and detect contradictions
    conn = get_memory_db()
    existing = get_all_memories(conn)
    existing_str = "\n".join(f"- [{m['category']}] {m['fact']}" for m in existing) if existing else "(ninguno)"

    prompt = EXTRACT_PROMPT.format(
        user_message=user_message,
        assistant_summary=assistant_summary,
        books_cited=", ".join(books_cited) if books_cited else "ninguno",
        existing_memories=existing_str,
    )

    try:
        response = gemini_client.models.generate_content(
            model=SUMMARY_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=1024,
                response_mime_type="application/json",
            ),
        )

        result = json.loads(response.text)

        # Store user facts (with contradiction handling + confidence threshold)
        for fact_obj in result.get("user_facts", []):
            confidence = fact_obj.get("confidence", 1.0)
            if confidence < 0.7:
                continue  # Skip low-confidence facts

            # Handle contradictions: delete the old fact if a new one replaces it
            replaces = fact_obj.get("replaces")
            if replaces:
                for existing_mem in existing:
                    if existing_mem['fact'] == replaces:
                        delete_memory(existing_mem['id'], conn)
                        break

            add_memory(
                fact=fact_obj["fact"],
                category=fact_obj.get("category", "general"),
                confidence=confidence,
                conversation_id=conversation_id,
                conn=conn,
            )

        # Store conversation summary (conn already open from above)
        if result.get("conversation_summary"):
            save_conversation_summary(
                conversation_id=conversation_id or datetime.now(timezone.utc).isoformat(),
                user_query=user_message[:200],
                summary=result["conversation_summary"],
                topics=result.get("topics", []),
                books_mentioned=books_cited,
                language=result.get("language", "es"),
                conn=conn,
            )

        # Track reading interests
        for topic in result.get("topics", []):
            track_interest(
                topic=topic,
                query=user_message[:200],
                books=books_cited,
                conn=conn,
            )

        conn.close()
        return result

    except Exception as e:
        print(f"[Memory] Extraction failed: {e}")
        return {}


def build_memory_context(conn=None) -> str:
    """Build the complete memory context block to inject into the system prompt."""
    own_conn = conn is None
    if own_conn:
        conn = get_memory_db()

    parts = []

    # Layer 1: User profile
    profile = format_memories_for_prompt(conn)
    if profile:
        parts.append(profile)

    # Layer 2: Recent conversations
    summaries = format_summaries_for_prompt(conn)
    if summaries:
        parts.append(summaries)

    if own_conn:
        conn.close()

    if not parts:
        return ""

    return "\n\n".join(parts)
