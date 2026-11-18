import re
import sqlite3
from pathlib import Path

from .config import (
    DATABASE,
    KNOWLEDGE_DIR,
    MAX_CONTEXT_MEMORIES,
    MAX_CONTEXT_MESSAGES,
    MAX_MEMORIES,
)


def connect_database(path: Path | str = DATABASE) -> sqlite3.Connection:
    database_path = Path(path)
    if str(path) != ":memory:":
        database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    initialize_database(connection)
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS memorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS conhecimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fonte TEXT NOT NULL,
            conteudo TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fonte TEXT NOT NULL UNIQUE,
            sha256 TEXT,
            tipo TEXT NOT NULL DEFAULT 'txt',
            total_trechos INTEGER NOT NULL DEFAULT 0,
            indexado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conteudo TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    # Register legacy sources without touching their existing text or embeddings.
    legacy_sources = connection.execute(
        "SELECT DISTINCT fonte FROM conhecimentos"
    ).fetchall()
    for row in legacy_sources:
        source = str(row["fonte"]).replace("\\", "/")
        connection.execute(
            """
            INSERT OR IGNORE INTO documentos (fonte, tipo, total_trechos)
            SELECT ?, ?, COUNT(*)
            FROM conhecimentos
            WHERE REPLACE(fonte, '\\', '/') = ?
            """,
            (source, Path(source).suffix.lstrip(".").lower() or "txt", source),
        )

    documents = connection.execute("SELECT id, fonte FROM documentos").fetchall()
    normalized_sources = {
        str(row["fonte"]).replace("\\", "/")
        for row in documents
    }
    for row in documents:
        source = str(row["fonte"]).replace("\\", "/")
        if (
            source.startswith("biblioteca/")
            and source.removeprefix("biblioteca/") in normalized_sources
        ):
            connection.execute("DELETE FROM documentos WHERE id = ?", (row["id"],))
    connection.commit()


def save_message(connection: sqlite3.Connection, role: str, content: str) -> None:
    connection.execute(
        "INSERT INTO mensagens (role, content) VALUES (?, ?)",
        (role, content),
    )
    connection.commit()


def load_history(
    connection: sqlite3.Connection,
    limit: int = MAX_CONTEXT_MESSAGES,
) -> list[dict[str, str]]:
    rows = connection.execute(
        "SELECT role, content FROM mensagens ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]


def clear_history(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM mensagens")
    connection.commit()
    return cursor.rowcount


def list_memories(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT id, content, created_at FROM memorias ORDER BY id"
    ).fetchall()


def add_memory(connection: sqlite3.Connection, content: str) -> int:
    value = content.strip()
    if not value:
        raise ValueError("A memória não pode estar vazia.")
    if len(value) > 500:
        raise ValueError("A memória deve ter no máximo 500 caracteres.")

    count = connection.execute("SELECT COUNT(*) FROM memorias").fetchone()[0]
    if count >= MAX_MEMORIES:
        raise ValueError(f"O limite de {MAX_MEMORIES} memórias foi atingido.")

    cursor = connection.execute("INSERT INTO memorias (content) VALUES (?)", (value,))
    connection.commit()
    return int(cursor.lastrowid)


def delete_memory(connection: sqlite3.Connection, memory_id: int) -> bool:
    cursor = connection.execute("DELETE FROM memorias WHERE id = ?", (memory_id,))
    connection.commit()
    return cursor.rowcount > 0


def delete_all_memories(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("DELETE FROM memorias")
    connection.commit()
    return cursor.rowcount


def relevant_memories(
    connection: sqlite3.Connection,
    query: str,
    limit: int = MAX_CONTEXT_MEMORIES,
) -> list[str]:
    rows = connection.execute(
        "SELECT content FROM memorias ORDER BY id DESC LIMIT ?",
        (MAX_MEMORIES,),
    ).fetchall()
    memories = [row["content"] for row in rows]
    terms = {
        term for term in re.findall(r"\w+", query.casefold())
        if len(term) > 2
    }
    ranked = []
    for position, memory in enumerate(memories):
        memory_terms = set(re.findall(r"\w+", memory.casefold()))
        overlap = len(terms & memory_terms)
        if overlap:
            ranked.append((overlap, position, memory))
    if ranked:
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [memory for _, _, memory in ranked[:limit]]
    return memories[:limit]


def save_note(connection: sqlite3.Connection, content: str) -> int:
    value = content.strip()
    if not value:
        raise ValueError("A nota não pode estar vazia.")
    cursor = connection.execute("INSERT INTO notas (conteudo) VALUES (?)", (value,))
    connection.commit()
    return int(cursor.lastrowid)


def list_notes(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT id, conteudo, created_at FROM notas ORDER BY id DESC"
    ).fetchall()


def delete_note(connection: sqlite3.Connection, note_id: int) -> bool:
    cursor = connection.execute("DELETE FROM notas WHERE id = ?", (note_id,))
    connection.commit()
    return cursor.rowcount > 0
