import hashlib
import logging
from pathlib import Path

import requests
import streamlit as st

from guilherme_ai.assistant import AssistantError, chat
from guilherme_ai.config import EMBED_MODEL, KNOWLEDGE_DIR, MODEL, OLLAMA_BASE_URL
from guilherme_ai.database import (
    add_memory,
    clear_history,
    connect_database,
    delete_all_memories,
    delete_memory,
    delete_note,
    list_memories,
    list_notes,
    load_history,
    save_note,
)
from guilherme_ai.documents import (
    DocumentError,
    index_document,
    index_library,
    list_documents,
    remove_document,
)


st.set_page_config(page_title="Guilherme AI", page_icon="🧠", layout="wide")
logging.basicConfig(level=logging.WARNING)


connection = connect_database()
st.title("Guilherme AI")
st.caption(f"Assistente local · modelo {MODEL} · embeddings {EMBED_MODEL}")
try:
    health = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
    health.raise_for_status()
    installed_models = {model["name"].split(":")[0] for model in health.json().get("models", [])}
    missing_models = {MODEL, EMBED_MODEL} - installed_models
    if missing_models:
        st.warning(f"Ollama conectado; confira os modelos: {', '.join(sorted(missing_models))}.")
    else:
        st.success("Ollama conectado e modelos configurados encontrados.")
except (requests.RequestException, ValueError, KeyError, TypeError) as error:
    st.error(f"Ollama indisponível: {error}")

chat_tab, library_tab, memory_tab, tools_tab = st.tabs(
    ["Conversa", "Biblioteca", "Memórias", "Ferramentas e notas"]
)

with chat_tab:
    st.subheader("Conversa")
    history = load_history(connection)
    for message in history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    question = st.chat_input("Escreva sua pergunta")
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Consultando o modelo local e a biblioteca..."):
                try:
                    result = chat(connection, question)
                    st.markdown(result.answer)
                    if result.sources:
                        with st.expander(f"Fontes consultadas ({len(result.sources)})"):
                            for index, source in enumerate(result.sources, start=1):
                                st.markdown(
                                    f"**[{index}] {source['source']}** "
                                    f"— similaridade {source['score']:.3f}"
                                )
                                st.write(source["content"])
                    else:
                        st.info(
                            "Nenhum trecho da biblioteca atingiu a similaridade mínima. "
                            "A resposta não deve ser interpretada como baseada nos documentos."
                        )
                except (AssistantError, DocumentError, OSError) as error:
                    st.error(str(error))

    if st.button("Limpar histórico", key="clear_history"):
        if st.session_state.get("confirm_clear_history"):
            count = clear_history(connection)
            st.session_state.pop("confirm_clear_history", None)
            st.success(f"{count} mensagem(ns) removida(s). As memórias foram mantidas.")
            st.rerun()
        else:
            st.session_state["confirm_clear_history"] = True
            st.warning("Clique novamente em 'Limpar histórico' para confirmar.")

with library_tab:
    st.subheader("Biblioteca de documentos")
    uploaded_files = st.file_uploader(
        "Importe arquivos TXT ou PDF",
        type=["txt", "pdf"],
        accept_multiple_files=True,
        max_upload_size=20,
    )
    if uploaded_files and st.button("Salvar e indexar"):
        for uploaded in uploaded_files:
            filename = Path(uploaded.name).name
            destination = KNOWLEDGE_DIR / filename
            contents = uploaded.getvalue()
            content_hash = hashlib.sha256(contents).hexdigest()
            confirmation_key = f"confirm_upload_{filename}"
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and destination.read_bytes() != contents:
                    if st.session_state.get(confirmation_key) != content_hash:
                        st.session_state[confirmation_key] = content_hash
                        st.warning(
                            f"{filename} já existe com outro conteúdo. Clique novamente em "
                            "'Salvar e indexar' para confirmar a substituição."
                        )
                        continue
                destination.write_bytes(contents)
                st.session_state.pop(confirmation_key, None)
                result = index_document(connection, destination)
                if result["status"] == "unchanged":
                    st.info(f"{result['source']}: sem alterações.")
                elif result["status"] == "duplicate":
                    st.info(
                        f"{result['source']} já está indexado como {result['duplicate_of']}."
                    )
                else:
                    st.success(f"{result['source']}: {result['chunks']} trecho(s) indexado(s).")
            except (DocumentError, OSError) as error:
                st.error(f"{uploaded.name}: {error}")

    if st.button("Atualizar índice dos documentos"):
        for result in index_library(connection):
            if result["status"] == "error":
                st.error(f"{result['source']}: {result['error']}")
            elif result["status"] == "indexed":
                st.success(f"{result['source']}: {result['chunks']} trecho(s).")
            else:
                st.info(f"{result['source']}: sem alterações.")

    documents = list_documents(connection)
    if documents:
        st.dataframe(
            [
                {
                    "ID": item["id"],
                    "Arquivo": item["fonte"],
                    "Tipo": item["tipo"].upper(),
                    "Trechos": item["trechos_atuais"],
                    "Indexado em": item["indexado_em"],
                }
                for item in documents
            ],
            use_container_width=True,
            hide_index=True,
        )
        selected_id = st.selectbox(
            "Documento cujo índice deseja remover",
            options=[item["id"] for item in documents],
            format_func=lambda value: next(
                f"{value}: {item['fonte']}" for item in documents if item["id"] == value
            ),
        )
        if st.button("Remover índice", key="remove_document"):
            if st.session_state.get("confirm_remove_document") == selected_id:
                try:
                    remove_document(connection, selected_id)
                    st.session_state.pop("confirm_remove_document", None)
                    st.success("Índice removido. O arquivo original foi mantido.")
                    st.rerun()
                except DocumentError as error:
                    st.error(str(error))
            else:
                st.session_state["confirm_remove_document"] = selected_id
                st.warning("Clique novamente para confirmar. O arquivo não será apagado.")
    else:
        st.info("Nenhum documento indexado.")

with memory_tab:
    st.subheader("Memórias pessoais")
    memory_text = st.text_input("Nova memória (até 500 caracteres)", max_chars=500)
    if st.button("Salvar memória"):
        try:
            memory_id = add_memory(connection, memory_text)
            st.success(f"Memória {memory_id} salva.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

    memories = list_memories(connection)
    for memory in memories:
        column, delete_column = st.columns([5, 1])
        column.write(f"**{memory['id']}** · {memory['content']}")
        if delete_column.button("Excluir", key=f"delete_memory_{memory['id']}"):
            confirmation_key = f"confirm_memory_{memory['id']}"
            if st.session_state.get(confirmation_key):
                delete_memory(connection, memory["id"])
                st.session_state.pop(confirmation_key, None)
                st.rerun()
            else:
                st.session_state[confirmation_key] = True
                st.warning(f"Clique novamente para excluir a memória {memory['id']}.")

    if st.button("Excluir todas as memórias", key="delete_all_memories"):
        if st.session_state.get("confirm_delete_all_memories"):
            count = delete_all_memories(connection)
            st.session_state.pop("confirm_delete_all_memories", None)
            st.success(f"{count} memória(s) removida(s).")
            st.rerun()
        else:
            st.session_state["confirm_delete_all_memories"] = True
            st.warning("Clique novamente para confirmar a exclusão permanente.")

with tools_tab:
    st.subheader("Notas")
    note_text = st.text_area("Nova nota")
    if st.button("Salvar nota"):
        try:
            note_id = save_note(connection, note_text)
            st.success(f"Nota {note_id} salva.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))

    for note in list_notes(connection):
        column, delete_column = st.columns([5, 1])
        column.write(f"**{note['id']}** · {note['conteudo']}")
        if delete_column.button("Excluir", key=f"delete_note_{note['id']}"):
            confirmation_key = f"confirm_note_{note['id']}"
            if st.session_state.get(confirmation_key):
                delete_note(connection, note["id"])
                st.session_state.pop(confirmation_key, None)
                st.rerun()
            else:
                st.session_state[confirmation_key] = True
                st.warning(f"Clique novamente para excluir a nota {note['id']}.")

    st.divider()
    st.subheader("Calculadora segura")
    expression = st.text_input("Expressão aritmética")
    if st.button("Calcular"):
        from guilherme_ai.tools import ToolError, calculate

        try:
            st.write(calculate(expression))
        except ToolError as error:
            st.error(str(error))

connection.close()
