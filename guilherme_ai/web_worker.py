import json
import logging
import sys
from typing import Any

from .assistant import _build_system_prompt
from .analysis import analyze_project, analyze_spreadsheet, create_spreadsheet
from .config import MAX_CONTEXT_MESSAGES
from .database import (
    add_memory,
    connect_database,
    delete_memory,
    delete_note,
    list_memories,
    list_notes,
    relevant_memories,
    save_note,
)
from .documents import (
    DocumentError,
    index_document,
    index_library,
    list_documents,
    remove_document,
    search_library,
)
from .tools import calculate, current_datetime, extract_authorized_filename

logger = logging.getLogger(__name__)


def _ensure_web_schema(connection: Any) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'Nova conversa',
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS one_default_conversation
            ON conversations(is_default) WHERE is_default = 1;
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO conversations (title, is_default)
        SELECT 'Conversa anterior', 1
        WHERE NOT EXISTS (SELECT 1 FROM conversations WHERE is_default = 1)
        """
    )
    if cursor.rowcount:
        conversation_id = int(cursor.lastrowid)
        legacy_messages = connection.execute(
            "SELECT role, content, created_at FROM mensagens ORDER BY id"
        ).fetchall()
        connection.executemany(
            """
            INSERT INTO conversation_messages
                (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [
                (conversation_id, row["role"], row["content"], row["created_at"])
                for row in legacy_messages
                if row["role"] in {"user", "assistant"}
            ],
        )
    connection.commit()


def _serialize_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _conversation_id(request: dict[str, Any]) -> int:
    value = request.get("conversationId")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Identificador de conversa inválido.")
    return value


def _conversation_exists(connection: Any, conversation_id: int) -> Any:
    conversation = connection.execute(
        "SELECT id, is_default, title FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if conversation is None:
        raise ValueError("Conversa não encontrada.")
    return conversation


def _run_action(request: dict[str, Any]) -> Any:
    connection = connect_database()
    try:
        _ensure_web_schema(connection)
        action = request.get("action")

        if action == "conversations":
            return _serialize_rows(connection.execute(
                """
                SELECT id, title, is_default, created_at, updated_at
                FROM conversations ORDER BY updated_at DESC, id DESC
                """
            ).fetchall())

        if action == "create_conversation":
            cursor = connection.execute(
                "INSERT INTO conversations (title) VALUES ('Nova conversa')"
            )
            connection.commit()
            return {"id": int(cursor.lastrowid), "title": "Nova conversa"}

        if action == "messages":
            conversation_id = _conversation_id(request)
            _conversation_exists(connection, conversation_id)
            return _serialize_rows(connection.execute(
                """
                SELECT id, role, content, created_at
                FROM conversation_messages
                WHERE conversation_id = ? ORDER BY id
                """,
                (conversation_id,),
            ).fetchall())

        if action == "delete_conversation":
            conversation_id = _conversation_id(request)
            conversation = _conversation_exists(connection, conversation_id)
            if conversation["is_default"]:
                raise ValueError("A conversa anterior não pode ser excluída.")
            connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            connection.commit()
            return {"deleted": True}

        if action == "prepare_chat":
            question = request.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError("A pergunta não pode estar vazia.")
            use_library = request.get("useLibrary", True)
            if not isinstance(use_library, bool):
                raise ValueError("O modo da biblioteca é inválido.")
            conversation_id = _conversation_id(request)
            _conversation_exists(connection, conversation_id)
            prompt = question.strip()
            sources = search_library(connection, prompt) if use_library else []
            memories = relevant_memories(connection, prompt)
            history = connection.execute(
                """
                SELECT role, content FROM conversation_messages
                WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
                """,
                (conversation_id, MAX_CONTEXT_MESSAGES),
            ).fetchall()
            messages = [{"role": "system", "content": _build_system_prompt(memories, sources)}]
            messages.extend(
                {"role": row["role"], "content": row["content"]}
                for row in reversed(history)
            )
            messages.append({"role": "user", "content": prompt})
            return {
                "conversationId": conversation_id,
                "question": prompt,
                "messages": messages,
                "sources": sources,
            }

        if action == "save_chat":
            conversation_id = _conversation_id(request)
            conversation = _conversation_exists(connection, conversation_id)
            question = request.get("question")
            answer = request.get("answer")
            if not isinstance(question, str) or not isinstance(answer, str) or not answer:
                raise ValueError("A resposta da conversa está incompleta.")
            with connection:
                connection.executemany(
                    """
                    INSERT INTO conversation_messages
                        (conversation_id, role, content)
                    VALUES (?, ?, ?)
                    """,
                    (
                        (conversation_id, "user", question),
                        (conversation_id, "assistant", answer),
                    ),
                )
                title = conversation["title"]
                if title in {"Nova conversa", "Conversa anterior"} and not conversation["is_default"]:
                    title = question[:64].strip() or "Nova conversa"
                connection.execute(
                    """
                    UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (title, conversation_id),
                )
                if conversation["is_default"]:
                    connection.executemany(
                        "INSERT INTO mensagens (role, content) VALUES (?, ?)",
                        (("user", question), ("assistant", answer)),
                    )
            return {"saved": True}

        if action == "memories":
            return _serialize_rows(list_memories(connection))

        if action == "add_memory":
            content = request.get("content")
            if not isinstance(content, str):
                raise ValueError("Informe o texto da memória.")
            return {"id": add_memory(connection, content)}

        if action == "delete_memory":
            memory_id = request.get("id")
            if isinstance(memory_id, bool) or not isinstance(memory_id, int) or memory_id < 1:
                raise ValueError("Identificador de memória inválido.")
            if not delete_memory(connection, memory_id):
                raise ValueError("Memória não encontrada.")
            return {"deleted": True}

        if action == "notes":
            return _serialize_rows(list_notes(connection))

        if action == "add_note":
            content = request.get("content")
            if not isinstance(content, str):
                raise ValueError("Informe o texto da nota.")
            return {"id": save_note(connection, content)}

        if action == "delete_note":
            note_id = request.get("id")
            if isinstance(note_id, bool) or not isinstance(note_id, int) or note_id < 1:
                raise ValueError("Identificador de nota inválido.")
            if not delete_note(connection, note_id):
                raise ValueError("Nota não encontrada.")
            return {"deleted": True}

        if action == "documents":
            return [dict(document) for document in list_documents(connection)]

        if action == "index_document":
            filename = extract_authorized_filename(str(request.get("filename", "")))
            return index_document(connection, filename)

        if action == "reindex_library":
            return index_library(connection, force=True)

        if action == "remove_document":
            document_id = request.get("id")
            if isinstance(document_id, bool) or not isinstance(document_id, int) or document_id < 1:
                raise ValueError("Identificador de documento inválido.")
            if not remove_document(connection, document_id):
                raise ValueError("Documento não encontrado.")
            return {"removed": True}

        if action == "execute_tool":
            name = request.get("name")
            value = request.get("input", "")
            if name == "calculator" and isinstance(value, str):
                return {"result": calculate(value)}
            if name == "datetime":
                return {"result": current_datetime()}
            raise ValueError("Ferramenta desconhecida ou entrada inválida.")

        if action == "analyze_spreadsheet":
            filename = request.get("filename")
            if not isinstance(filename, str):
                raise ValueError("Informe o nome do arquivo enviado.")
            return analyze_spreadsheet(filename)

        if action == "create_spreadsheet":
            filename = request.get("filename")
            columns = request.get("columns")
            rows = request.get("rows")
            if (
                not isinstance(filename, str)
                or not isinstance(columns, list)
                or not isinstance(rows, list)
            ):
                raise ValueError("Informe nome, colunas e linhas para criar a planilha.")
            return create_spreadsheet(filename, columns, rows)

        if action == "analyze_project":
            directory = request.get("directory")
            if not isinstance(directory, str):
                raise ValueError("Informe o caminho da pasta do projeto.")
            return analyze_project(directory)

        raise ValueError("Ação desconhecida.")
    finally:
        connection.close()


def main() -> None:
    try:
        request = json.loads(sys.stdin.readline())
        if not isinstance(request, dict):
            raise ValueError("Requisição inválida.")
        result = _run_action(request)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except (ValueError, DocumentError) as error:
        print(json.dumps({"ok": False, "error": str(error), "status": 400}, ensure_ascii=False))
    except Exception as error:
        logger.exception("Falha no worker web.")
        print(json.dumps({"ok": False, "error": str(error), "status": 500}, ensure_ascii=False))


if __name__ == "__main__":
    main()
