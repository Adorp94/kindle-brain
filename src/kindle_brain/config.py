"""Centralized configuration for Kindle Brain.

Model config (static) + system config (from config.json).
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- AI Model Configuration ---

# Gemini Embedding 2 — 8,192 token window, multimodal capable
EMBEDDING_MODEL = "gemini-embedding-2-preview"

# Gemini 3.1 Flash Lite — cheap ETL (summaries, markdown), 1M context
SUMMARY_MODEL = "gemini-3.1-flash-lite-preview"

# Gemini 3.1 Pro — deep reasoning for chat, 1M context
CHAT_MODEL = "gemini-3.1-pro-preview"

# Embedding dimensions (Gemini Embedding 2 output)
EMBEDDING_DIMENSIONS = 3072

# ChromaDB collection name
COLLECTION_NAME = "kindle_golden_nuggets"

# Rich context window: ~20,000 characters ≈ 4,000-5,000 words
RICH_CONTEXT_CHARS = 20000

# Minimum overlap ratio to merge two nearby golden nugget blocks
MERGE_OVERLAP_RATIO = 0.5


# --- System Configuration ---

def get_system_config() -> dict:
    """Load system config from config.json in the data directory."""
    from kindle_brain.paths import config_path
    path = config_path()
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_system_config(config: dict):
    """Save system config to config.json in the data directory."""
    from kindle_brain.paths import config_path
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))


def get_gemini_client():
    """Get Google GenAI client."""
    api_key = os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return None
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except ImportError:
        print("Warning: google-genai package not installed")
        return None
