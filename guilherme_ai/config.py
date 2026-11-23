import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE = Path(os.environ.get("GUILHERME_AI_DATABASE", PROJECT_ROOT / "memory.db"))
KNOWLEDGE_DIR = Path(os.environ.get("GUILHERME_AI_LIBRARY", PROJECT_ROOT / "biblioteca"))
VOICE_MODEL_DIR = Path(os.environ.get(
    "GUILHERME_AI_VOICE_MODEL",
    PROJECT_ROOT / "models" / "vosk-model-small-pt-0.3",
))

OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"
EMBED_URL = f"{OLLAMA_BASE_URL}/api/embed"
SEARXNG_SEARCH_URL = os.environ.get(
    "SEARXNG_URL",
    "http://127.0.0.1:8080/search",
).rstrip("/")
MODEL = os.environ.get("GUILHERME_AI_MODEL", "guilherme-ai")
EMBED_MODEL = os.environ.get("GUILHERME_AI_EMBED_MODEL", "nomic-embed-text")
WEB_SEARCH_TIMEOUT_SECONDS = 8
WEB_SEARCH_MAX_RESULTS = 5
WEB_SEARCH_MAX_ALLOWED_RESULTS = 10
WEB_FETCH_TIMEOUT_SECONDS = 8
WEB_FETCH_MAX_BYTES = 1_000_000
WEB_FETCH_MAX_CHARS = 12_000
WEB_FETCH_MAX_REDIRECTS = 3

MAX_CONTEXT_MESSAGES = 6
MAX_CONTEXT_MEMORIES = 5
MAX_MEMORIES = 10
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
TOP_K = 4
try:
    MIN_SIMILARITY = float(os.environ.get("GUILHERME_AI_MIN_SIMILARITY", "0.60"))
except ValueError as error:
    raise ValueError("GUILHERME_AI_MIN_SIMILARITY deve ser um número entre -1 e 1.") from error
if not -1 <= MIN_SIMILARITY <= 1:
    raise ValueError("GUILHERME_AI_MIN_SIMILARITY deve estar entre -1 e 1.")
EMBED_BATCH_SIZE = 16
