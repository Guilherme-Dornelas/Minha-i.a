import logging
import sqlite3
from pathlib import Path

import requests

from .assistant import AssistantError, chat
from .config import EMBED_MODEL, KNOWLEDGE_DIR, MODEL
from .database import (
    add_memory,
    clear_history,
    connect_database,
    delete_all_memories,
    delete_memory,
    delete_note,
    list_memories,
    list_notes,
    save_note,
)
from .documents import DocumentError, index_document, index_library, list_documents, remove_document
from .tools import (
    ToolError,
    WebSearchError,
    create_registry,
    extract_authorized_filename,
)
from .voice import VoiceError, listen_once, speak

logger = logging.getLogger(__name__)
TOOL_REGISTRY = create_registry()


HELP = """
COMANDOS
  /ajuda                         Mostra esta ajuda.
  /indexar [arquivo]             Indexa TXT/PDF da biblioteca; sem nome, indexa todos.
  /reindexar                     Reconstrói os índices sem apagar os anteriores em caso de falha.
  /documentos                    Lista documentos e IDs para remoção.
  /remover ID                    Remove o índice após confirmação; não apaga o arquivo.
  /lembrar texto                 Salva uma memória pessoal.
  /memorias                      Lista memórias.
  /esquecer ID                   Exclui uma memória após confirmação.
  /esquecer tudo                 Exclui todas as memórias após confirmação.
  /limpar                        Limpa apenas o histórico de conversa após confirmação.
  /calc expressão                Calculadora aritmética segura.
  /hora                          Consulta data e hora locais.
  /pesquisar consulta            Pesquisa na internet via SearXNG local.
  /ferramentas                   Lista ferramentas locais disponíveis.
  /resumir assunto               Resume informações relevantes da biblioteca.
  /nota texto                    Salva uma nota.
  /notas                         Lista notas.
  /apagar-nota ID                Exclui uma nota após confirmação.
  /voz                           Grava uma pergunta de até 7 segundos e fala a resposta.
  /sair                          Encerra.
"""


def _confirm(prompt: str) -> bool:
    return input(f"{prompt} (s/N): ").strip().casefold() == "s"


def _show_documents(connection: sqlite3.Connection) -> None:
    documents = list_documents(connection)
    print("\n===== BIBLIOTECA =====")
    if not documents:
        print("Nenhum documento indexado.")
    for document in documents:
        print(
            f"ID {document['id']} | {document['fonte']} | "
            f"{document['tipo'].upper()} | {document['trechos_atuais']} trecho(s)"
        )


def _run_index(connection: sqlite3.Connection, command: str, force: bool = False) -> None:
    parts = command.split(maxsplit=1)
    if len(parts) == 1:
        results = index_library(connection, force=force)
    else:
        name = extract_authorized_filename(parts[1])
        results = [index_document(connection, name, force=force)]
    for result in results:
        if result["status"] == "error":
            print(f"Falha ao indexar {result['source']}: {result['error']}")
        elif result["status"] == "unchanged":
            print(f"Sem alterações: {result['source']}")
        elif result["status"] == "duplicate":
            print(f"{result['source']} já está indexado como {result['duplicate_of']}.")
        else:
            print(f"Indexado {result['source']}: {result['chunks']} trecho(s).")
    if not results:
        print(f"Nenhum TXT ou PDF encontrado em {KNOWLEDGE_DIR}.")


def _handle_command(connection: sqlite3.Connection, command: str) -> bool:
    lowered = command.casefold()
    if lowered in {"/sair", "/exit", "/quit"}:
        return False
    if lowered == "/ajuda":
        print(HELP)
    elif lowered == "/documentos":
        _show_documents(connection)
    elif lowered == "/indexar" or lowered.startswith("/indexar "):
        _run_index(connection, command)
    elif lowered == "/reindexar":
        _run_index(connection, "/indexar", force=True)
    elif lowered.startswith("/lembrar"):
        content = command[len("/lembrar"):].strip()
        try:
            memory_id = add_memory(connection, content)
            print(f"Memória {memory_id} salva.")
        except ValueError as error:
            print(error)
    elif lowered == "/memorias":
        memories = list_memories(connection)
        if not memories:
            print("Nenhuma memória cadastrada.")
        for memory in memories:
            print(f"ID {memory['id']} | {memory['created_at']} | {memory['content']}")
    elif lowered.startswith("/esquecer"):
        argument = command[len("/esquecer"):].strip()
        if argument.casefold() == "tudo":
            if _confirm("Apagar permanentemente todas as memórias?"):
                print(f"{delete_all_memories(connection)} memória(s) removida(s).")
            else:
                print("Operação cancelada.")
        else:
            try:
                memory_id = int(argument)
            except ValueError:
                print("Use /esquecer ID ou /esquecer tudo.")
            else:
                if _confirm(f"Apagar a memória {memory_id}?"):
                    print("Memória removida." if delete_memory(connection, memory_id) else "Memória não encontrada.")
                else:
                    print("Operação cancelada.")
    elif lowered == "/limpar":
        if _confirm("Limpar o histórico de conversas? As memórias serão mantidas."):
            print(f"{clear_history(connection)} mensagem(ns) removida(s).")
        else:
            print("Operação cancelada.")
    elif lowered.startswith("/calc"):
        try:
            print(TOOL_REGISTRY.run("calculadora", command[len("/calc"):].strip()))
        except ToolError as error:
            print(error)
    elif lowered == "/hora":
        print(TOOL_REGISTRY.run("data_hora"))
    elif lowered == "/pesquisar" or lowered.startswith("/pesquisar "):
        query = command[len("/pesquisar"):].strip()
        try:
            print(TOOL_REGISTRY.run("web_search", query))
        except (ToolError, WebSearchError) as error:
            print(f"Erro na pesquisa: {error}")
    elif lowered == "/ferramentas":
        for tool in TOOL_REGISTRY.available():
            print(f"{tool.name}: {tool.description}")
    elif lowered.startswith("/resumir "):
        subject = command[len("/resumir"):].strip()
        try:
            result = chat(
                connection,
                f"Faça um resumo fiel e organizado do que a biblioteca informa sobre: {subject}. "
                "Cite os marcadores de fonte fornecidos e diferencie conhecimento geral.",
                retrieval_query=subject,
            )
            print(f"\nGuilherme AI: {result.answer}")
            _show_sources(result.sources)
            _show_web_sources(result.web_sources)
        except (AssistantError, DocumentError, WebSearchError, requests.RequestException) as error:
            print(f"Erro ao resumir: {error}")
    elif lowered.startswith("/nota "):
        content = command[len("/nota"):].strip()
        try:
            print(f"Nota {save_note(connection, content)} salva.")
        except ValueError as error:
            print(error)
    elif lowered.startswith("/notas"):
        notes = list_notes(connection)
        if not notes:
            print("Nenhuma nota cadastrada.")
        for note in notes:
            print(f"ID {note['id']} | {note['created_at']} | {note['conteudo']}")
    elif lowered == "/nota":
        print("Use /nota texto para salvar ou /notas para listar.")
    elif lowered.startswith("/apagar-nota"):
        try:
            note_id = int(command[len("/apagar-nota"):].strip())
        except ValueError:
            print("Use /apagar-nota ID.")
        else:
            if _confirm(f"Apagar a nota {note_id}?"):
                print("Nota removida." if delete_note(connection, note_id) else "Nota não encontrada.")
            else:
                print("Operação cancelada.")
    elif lowered.startswith("/remover"):
        try:
            document_id = int(command[len("/remover"):].strip())
        except ValueError:
            print("Use /remover ID. Consulte os IDs em /documentos.")
        else:
            if _confirm(f"Remover o índice do documento {document_id}? O arquivo não será apagado."):
                print("Índice removido." if remove_document(connection, document_id) else "Documento não encontrado.")
            else:
                print("Operação cancelada.")
    elif lowered == "/voz":
        _voice_turn(connection)
    else:
        print("Comando desconhecido. Digite /ajuda.")
    return True


def _voice_turn(connection: sqlite3.Connection) -> None:
    try:
        question = listen_once()
        print(f"Você (voz): {question}")
        result = chat(connection, question)
        print(f"\nGuilherme AI: {result.answer}")
        _show_sources(result.sources)
        _show_web_sources(result.web_sources)
        speak(result.answer)
    except (VoiceError, AssistantError, DocumentError, WebSearchError, requests.RequestException) as error:
        print(f"Recurso de voz/conversa indisponível: {error}")
    except OSError as error:
        print(f"Falha de áudio ou arquivo: {error}")


def _show_sources(sources: list[dict]) -> None:
    if not sources:
        print("\nFontes: nenhum trecho atingiu a pontuação mínima.")
        return
    print("\nTrechos recuperados:")
    for index, source in enumerate(sources, start=1):
        print(f"[{index}] {source['source']} (similaridade {source['score']:.3f})")
        print(f"    {source['content']}")


def _show_web_sources(sources: list[dict[str, str]]) -> None:
    if not sources:
        return
    print("\nFontes da internet:")
    for index, source in enumerate(sources, start=1):
        print(f"[W{index}] {source['title']}")
        print(f"    {source['url']}")
        if source["description"]:
            print(f"    {source['description']}")


def run_cli() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    connection = connect_database()
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Guilherme AI 5.0 | chat: {MODEL} | embeddings: {EMBED_MODEL}")
    print("Execução local. Digite /ajuda para ver os comandos.")
    try:
        while True:
            try:
                prompt = input("\nVocê: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nEncerrando Guilherme AI.")
                break
            if not prompt:
                continue
            if prompt.startswith("/"):
                try:
                    if not _handle_command(connection, prompt):
                        break
                except (DocumentError, WebSearchError, OSError, requests.RequestException) as error:
                    logger.exception("Falha em comando da biblioteca.")
                    print(f"Erro: {error}")
                continue
            try:
                result = chat(connection, prompt)
                print(f"\nGuilherme AI: {result.answer}")
                _show_sources(result.sources)
                _show_web_sources(result.web_sources)
            except (AssistantError, DocumentError, WebSearchError, requests.RequestException) as error:
                print(f"Erro: {error}")
    finally:
        connection.close()
