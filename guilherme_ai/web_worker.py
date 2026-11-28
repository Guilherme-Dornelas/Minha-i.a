import json
import logging
import sys
from typing import Any

from .assistant import (
    AssistantError,
    _build_system_prompt,
    append_web_search_tool_result,
    classify_web_search_intent,
    fetch_relevant_web_pages,
    search_web_intent,
)
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
from .gmail import (
    GmailIntent,
    classify_gmail_intent,
    compose_email_draft,
    parse_gmail_api_message,
    validate_gmail_message_id,
)
from .tools import (
    ToolError,
    WebSearchError,
    WebFetchError,
    calculate,
    current_datetime,
    create_registry,
    extract_authorized_filename,
    web_fetch,
    web_search,
)

logger = logging.getLogger(__name__)
TOOL_REGISTRY = create_registry()


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
            provider TEXT CHECK(provider IN ('ollama', 'gemini') OR provider IS NULL),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS gmail_credentials (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            encrypted_payload TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    message_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(conversation_messages)")
    }
    if "provider" not in message_columns:
        connection.execute(
            "ALTER TABLE conversation_messages ADD COLUMN provider TEXT"
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

        if action == "gmail_parse_message":
            message = request.get("message")
            return parse_gmail_api_message(message)

        if action == "gmail_compose":
            prompt = request.get("prompt")
            original_message = request.get("originalMessage")
            if not isinstance(prompt, str):
                raise ValueError("Informe a solicitação para preparar o e-mail.")
            if original_message is not None and not isinstance(original_message, dict):
                raise ValueError("O contexto do e-mail original é inválido.")
            return compose_email_draft(prompt, original_message)

        if action == "gmail_credentials_load":
            row = connection.execute(
                "SELECT encrypted_payload FROM gmail_credentials WHERE id = 1"
            ).fetchone()
            return {"encryptedPayload": row["encrypted_payload"] if row else None}

        if action == "gmail_credentials_store":
            encrypted_payload = request.get("encryptedPayload")
            if (
                not isinstance(encrypted_payload, str)
                or not encrypted_payload
                or len(encrypted_payload) > 10_000
            ):
                raise ValueError("Credenciais Gmail criptografadas inválidas.")
            connection.execute(
                """
                INSERT INTO gmail_credentials (id, encrypted_payload)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    encrypted_payload = excluded.encrypted_payload,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (encrypted_payload,),
            )
            connection.commit()
            return {"stored": True}

        if action == "gmail_credentials_delete":
            connection.execute("DELETE FROM gmail_credentials WHERE id = 1")
            connection.commit()
            return {"deleted": True}

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
                SELECT id, role, content, provider, created_at
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
            include_private_context = request.get("includePrivateContext", True)
            if not isinstance(include_private_context, bool):
                raise ValueError("A autorização de contexto privado é inválida.")
            conversation_id = _conversation_id(request)
            _conversation_exists(connection, conversation_id)
            prompt = question.strip()
            search_intent = classify_web_search_intent(prompt)
            gmail_message_id = request.get("gmailMessageId")
            if gmail_message_id is not None:
                gmail_intent = GmailIntent(
                    "reply",
                    message_id=validate_gmail_message_id(gmail_message_id),
                    max_results=1,
                )
            else:
                gmail_intent = classify_gmail_intent(prompt)
            web_sources = search_web_intent(search_intent, search=web_search)
            web_pages, fetch_errors = fetch_relevant_web_pages(prompt, web_sources)
            sources = (
                search_library(connection, prompt)
                if use_library and include_private_context
                else []
            )
            memories = (
                relevant_memories(connection, prompt)
                if include_private_context
                else []
            )
            history = (
                connection.execute(
                    """
                    SELECT role, content FROM conversation_messages
                    WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
                    """,
                    (conversation_id, MAX_CONTEXT_MESSAGES),
                ).fetchall()
                if include_private_context
                else []
            )
            messages = [{
                "role": "system",
                "content": _build_system_prompt(
                    memories,
                    sources,
                    web_sources,
                    search_intent.resolved_dates,
                    web_pages,
                    fetch_errors,
                    search_intent.required,
                ),
            }]
            messages.extend(
                {"role": row["role"], "content": row["content"]}
                for row in reversed(history)
            )
            messages.append({"role": "user", "content": prompt})
            if web_sources or web_pages or fetch_errors:
                append_web_search_tool_result(
                    messages,
                    (search_intent.query, *search_intent.related_queries),
                    web_sources,
                    web_pages,
                    fetch_errors,
                )
            return {
                "conversationId": conversation_id,
                "question": prompt,
                "messages": messages,
                "sources": sources,
                "webSources": web_sources,
                "gmailIntent": {
                    "action": gmail_intent.action,
                    "query": gmail_intent.query,
                    "messageId": gmail_intent.message_id,
                    "maxResults": gmail_intent.max_results,
                },
            }

        if action == "save_chat":
            conversation_id = _conversation_id(request)
            conversation = _conversation_exists(connection, conversation_id)
            question = request.get("question")
            answer = request.get("answer")
            provider = request.get("provider", "ollama")
            if not isinstance(question, str) or not isinstance(answer, str) or not answer:
                raise ValueError("A resposta da conversa está incompleta.")
            if not isinstance(provider, str) or provider not in {"ollama", "gemini"}:
                raise ValueError("O provedor da resposta é inválido.")
            with connection:
                connection.executemany(
                    """
                    INSERT INTO conversation_messages
                        (conversation_id, role, content, provider)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        (conversation_id, "user", question, None),
                        (conversation_id, "assistant", answer, provider),
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
            enable_ocr = request.get("enableOcr", False)
            if not isinstance(enable_ocr, bool):
                raise ValueError("A opção de OCR é inválida.")
            return index_document(connection, filename, enable_ocr=enable_ocr)

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
            if not isinstance(name, str) or not isinstance(value, str):
                raise ValueError("Ferramenta desconhecida ou entrada inválida.")
            try:
                return {"result": TOOL_REGISTRY.execute(name, value)}
            except ToolError as error:
                raise ValueError(str(error)) from error

        if action == "analyze_spreadsheet":
            filename = request.get("filename")
            if not isinstance(filename, str):
                raise ValueError("Informe o nome do arquivo enviado.")
            return analyze_spreadsheet(filename)

        if action == "create_spreadsheet":
            filename = request.get("filename")
            columns = request.get("columns")
            rows = request.get("rows")
            sheets = request.get("sheets")
            if not isinstance(filename, str):
                raise ValueError("Informe o nome do arquivo para criar a planilha.")
            if sheets is not None:
                if not isinstance(sheets, list):
                    raise ValueError("As abas da planilha são inválidas.")
                return create_spreadsheet(filename, sheets=sheets)
            if not isinstance(columns, list) or not isinstance(rows, list):
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
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=True))
    except (ValueError, DocumentError) as error:
        print(json.dumps({"ok": False, "error": str(error), "status": 400}, ensure_ascii=True))
    except WebSearchError as error:
        print(json.dumps({"ok": False, "error": str(error), "status": 503}, ensure_ascii=True))
    except WebFetchError as error:
        print(json.dumps({"ok": False, "error": str(error), "status": 502}, ensure_ascii=True))
    except AssistantError as error:
        print(json.dumps({"ok": False, "error": str(error), "status": 502}, ensure_ascii=True))
    except Exception as error:
        logger.exception("Falha no worker web.")
        print(json.dumps({"ok": False, "error": str(error), "status": 500}, ensure_ascii=True))


if __name__ == "__main__":
    main()
