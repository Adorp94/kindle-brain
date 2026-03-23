#!/usr/bin/env python3
"""
Centralized model configuration for the Kindle Highlights system.
All AI model IDs in one place.
"""

# Gemini Embedding 2 — 8,192 token window, multimodal capable
EMBEDDING_MODEL = "gemini-embedding-2-preview"

# Gemini 3.1 Flash Lite — cheap ETL (summaries, markdown), 1M context
SUMMARY_MODEL = "gemini-3.1-flash-lite-preview"

# Gemini 3.1 Pro — deep reasoning for chat, abstracción filosófica, 1M context
CHAT_MODEL = "gemini-3.1-pro-preview"

# Embedding dimensions (Gemini Embedding 2 output)
EMBEDDING_DIMENSIONS = 3072

# ChromaDB collection name
COLLECTION_NAME = "kindle_golden_nuggets"
