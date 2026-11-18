import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from guilherme_ai import documents
from guilherme_ai.assistant import AssistantError, chat
from guilherme_ai.database import (
    add_memory,
    clear_history,
    connect_database,
    delete_all_memories,
    list_memories,
    load_history,
    save_message,
)
from guilherme_ai.documents import (
    DocumentError,
    cosine_similarity,
    rank_chunks,
    remove_document,
    resolve_library_file,
    split_text,
)
from guilherme_ai.tools import ToolError, calculate, extract_authorized_filename


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.connection = connect_database(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_history_clear_does_not_remove_memories(self):
        add_memory(self.connection, "Prefere respostas em português")
        save_message(self.connection, "user", "Olá")
        self.assertEqual(len(load_history(self.connection)), 1)
        self.assertEqual(clear_history(self.connection), 1)
        self.assertEqual(load_history(self.connection), [])
        self.assertEqual(len(list_memories(self.connection)), 1)

    def test_legacy_rows_survive_database_initialization(self):
        self.connection.execute(
            "INSERT INTO conhecimentos (fonte, conteudo, embedding) VALUES (?, ?, ?)",
            ("biblioteca\\legado.txt", "conteúdo", "[1,0]"),
        )
        self.connection.commit()
        from guilherme_ai.database import initialize_database

        initialize_database(self.connection)
        row = self.connection.execute(
            "SELECT fonte, conteudo, embedding FROM conhecimentos"
        ).fetchone()
        self.assertEqual(tuple(row), ("biblioteca\\legado.txt", "conteúdo", "[1,0]"))
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM documentos").fetchone()[0],
            1,
        )

    def test_delete_all_memories(self):
        add_memory(self.connection, "Uma")
        add_memory(self.connection, "Duas")
        self.assertEqual(delete_all_memories(self.connection), 2)


class DocumentTests(unittest.TestCase):
    def test_chunking_has_overlap_and_respects_limits(self):
        text = "palavra " * 300
        chunks = split_text(text, size=100, overlap=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 100 for chunk in chunks))

    def test_cosine_and_threshold_ranking(self):
        self.assertEqual(cosine_similarity([0, 0], [1, 0]), 0)
        self.assertTrue(math.isclose(cosine_similarity([1, 0], [1, 0]), 1))
        rows = [
            {"id": 1, "fonte": "a.txt", "conteudo": "match", "embedding": "[1,0]"},
            {"id": 2, "fonte": "b.txt", "conteudo": "miss", "embedding": "[0,1]"},
        ]
        results = rank_chunks([1, 0], rows, minimum_score=0.6)
        self.assertEqual([result["id"] for result in results], [1])

    def test_ranking_prefers_source_diversity_without_duplicate_chunks(self):
        rows = [
            {"id": 1, "fonte": "a.txt", "conteudo": "first", "embedding": "[1,0]"},
            {"id": 2, "fonte": "a.txt", "conteudo": "second", "embedding": "[0.99,0.01]"},
            {"id": 3, "fonte": "b.txt", "conteudo": "other", "embedding": "[0.9,0.1]"},
        ]
        results = rank_chunks([1, 0], rows, top_k=4, minimum_score=0.5)
        self.assertEqual([item["id"] for item in results], [1, 3, 2])

    def test_library_path_rejects_parent_directory(self):
        with patch.object(documents, "KNOWLEDGE_DIR", Path("biblioteca")):
            with self.assertRaises(DocumentError):
                resolve_library_file("../outside.txt")

    def test_removing_document_keeps_the_source_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            source_file = library / "safe.txt"
            source_file.write_text("conteúdo", encoding="utf-8")
            connection = connect_database(":memory:")
            connection.execute(
                "INSERT INTO documentos (fonte, tipo, total_trechos) VALUES (?, ?, ?)",
                ("safe.txt", "txt", 1),
            )
            document_id = connection.execute(
                "SELECT id FROM documentos WHERE fonte = 'safe.txt'"
            ).fetchone()["id"]
            connection.execute(
                "INSERT INTO conhecimentos (fonte, conteudo, embedding) VALUES (?, ?, ?)",
                ("safe.txt", "conteúdo", "[1,0]"),
            )
            connection.commit()
            with patch.object(documents, "KNOWLEDGE_DIR", library):
                self.assertTrue(remove_document(connection, document_id))
            self.assertTrue(source_file.exists())
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM conhecimentos").fetchone()[0],
                0,
            )
            connection.close()

    def test_image_only_pdf_is_reported_without_ocr(self):
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            path = library / "scan.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with path.open("wb") as file:
                writer.write(file)
            with patch.object(documents, "KNOWLEDGE_DIR", library):
                with self.assertRaisesRegex(DocumentError, "OCR não é executado"):
                    documents._read_document(path)

    def test_index_failure_preserves_previous_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / "biblioteca"
            library.mkdir()
            file_path = library / "nota.txt"
            file_path.write_text("conteúdo novo", encoding="utf-8")
            connection = connect_database(":memory:")
            connection.execute(
                "INSERT INTO conhecimentos (fonte, conteudo, embedding) VALUES (?, ?, ?)",
                ("nota.txt", "conteúdo anterior", "[1,0]"),
            )
            connection.commit()
            with patch.object(documents, "KNOWLEDGE_DIR", library), patch.object(
                documents, "generate_embeddings", side_effect=DocumentError("falhou")
            ):
                with self.assertRaises(DocumentError):
                    documents.index_document(connection, file_path)
            row = connection.execute(
                "SELECT conteudo FROM conhecimentos WHERE fonte = 'nota.txt'"
            ).fetchone()
            self.assertEqual(row["conteudo"], "conteúdo anterior")
            connection.close()

    def test_reindex_replaces_legacy_windows_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            file_path = library / "nota.txt"
            file_path.write_text("conteúdo novo", encoding="utf-8")
            connection = connect_database(":memory:")
            connection.execute(
                "INSERT INTO conhecimentos (fonte, conteudo, embedding) VALUES (?, ?, ?)",
                ("biblioteca\\nota.txt", "conteúdo anterior", "[1,0]"),
            )
            connection.commit()
            from guilherme_ai.database import initialize_database

            initialize_database(connection)
            with patch.object(documents, "KNOWLEDGE_DIR", library), patch.object(
                documents, "generate_embeddings", return_value=[[1.0, 0.0]]
            ):
                result = documents.index_document(connection, file_path)
            self.assertEqual(result["status"], "indexed")
            rows = connection.execute(
                "SELECT fonte, conteudo FROM conhecimentos"
            ).fetchall()
            self.assertEqual([tuple(row) for row in rows], [("nota.txt", "conteúdo novo")])
            documents_list = documents.list_documents(connection)
            self.assertEqual(len(documents_list), 1)
            self.assertEqual(documents_list[0]["fonte"], "nota.txt")
            connection.close()

    def test_identical_files_are_not_indexed_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary)
            (library / "first.txt").write_text("same content", encoding="utf-8")
            (library / "second.txt").write_text("same content", encoding="utf-8")
            connection = connect_database(":memory:")
            with patch.object(documents, "KNOWLEDGE_DIR", library), patch.object(
                documents, "generate_embeddings", return_value=[[1.0, 0.0]]
            ) as embed:
                first = documents.index_document(connection, "first.txt")
                second = documents.index_document(connection, "second.txt")
            self.assertEqual(first["status"], "indexed")
            self.assertEqual(second["status"], "duplicate")
            self.assertEqual(second["duplicate_of"], "first.txt")
            embed.assert_called_once()
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM conhecimentos").fetchone()[0],
                1,
            )
            connection.close()


class CalculatorTests(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(calculate("2 + 3 * (4 - 1)"), 11)
        self.assertEqual(calculate("2 ** 3"), 8)

    def test_rejects_code_and_oversized_exponents(self):
        for expression in ("__import__('os').system('whoami')", "2 ** 101"):
            with self.subTest(expression=expression):
                with self.assertRaises(ToolError):
                    calculate(expression)

    def test_rejects_paths_outside_the_library(self):
        for path in ("../outside.txt", "C:outside.txt", "C:\\outside.txt"):
            with self.subTest(path=path):
                with self.assertRaises(ToolError):
                    extract_authorized_filename(path)


class AssistantTests(unittest.TestCase):
    def test_chat_persists_response_and_returns_sources(self):
        connection = connect_database(":memory:")
        source = {"source": "a.txt", "content": "texto", "score": 0.8}
        response = Mock()
        response.json.return_value = {"message": {"content": "Resposta [1]"}}
        response.raise_for_status.return_value = None
        with patch("guilherme_ai.assistant.search_library", return_value=[source]), patch(
            "guilherme_ai.assistant.relevant_memories", return_value=[]
        ):
            result = chat(connection, "pergunta", post=Mock(return_value=response))
        self.assertEqual(result.answer, "Resposta [1]")
        self.assertEqual(result.sources, [source])
        self.assertEqual([item["role"] for item in load_history(connection)], ["user", "assistant"])
        connection.close()

    def test_chat_can_use_a_separate_retrieval_query(self):
        connection = connect_database(":memory:")
        response = Mock()
        response.json.return_value = {"message": {"content": "Resumo"}}
        response.raise_for_status.return_value = None
        with patch("guilherme_ai.assistant.search_library", return_value=[]) as search, patch(
            "guilherme_ai.assistant.relevant_memories", return_value=[]
        ):
            chat(
                connection,
                "Faça um resumo sobre santidade divina.",
                post=Mock(return_value=response),
                retrieval_query="santidade divina",
            )
        search.assert_called_once_with(connection, "santidade divina")
        connection.close()

    def test_chat_does_not_persist_failed_requests(self):
        connection = connect_database(":memory:")
        with patch("guilherme_ai.assistant.search_library", return_value=[]), patch(
            "guilherme_ai.assistant.relevant_memories", return_value=[]
        ):
            with self.assertLogs("guilherme_ai.assistant", level="ERROR"):
                with self.assertRaises(AssistantError):
                    chat(
                        connection,
                        "pergunta",
                        post=Mock(side_effect=requests.ConnectionError("fora")),
                    )
        self.assertEqual(load_history(connection), [])
        connection.close()


if __name__ == "__main__":
    unittest.main()
