import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guilherme_ai.database import connect_database, save_message
from guilherme_ai import web_worker


class WebWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "memory.db"

    def tearDown(self):
        self.temporary.cleanup()

    def _connect(self):
        return connect_database(self.database_path)

    def _run(self, payload):
        with patch.object(web_worker, "connect_database", side_effect=self._connect):
            return web_worker._run_action(payload)

    def test_existing_history_is_migrated_once_into_default_conversation(self):
        connection = self._connect()
        save_message(connection, "user", "Mensagem antiga")
        connection.close()

        first = self._run({"action": "conversations"})
        second = self._run({"action": "conversations"})

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        self.assertEqual(first[0]["is_default"], 1)
        self.assertEqual(
            self._run({"action": "messages", "conversationId": first[0]["id"]})[0]["content"],
            "Mensagem antiga",
        )

    def test_new_conversations_keep_their_own_history(self):
        self._run({"action": "conversations"})
        conversation = self._run({"action": "create_conversation"})
        self._run({
            "action": "save_chat",
            "conversationId": conversation["id"],
            "question": "Pergunta de teste",
            "answer": "Resposta de teste",
        })

        messages = self._run({
            "action": "messages",
            "conversationId": conversation["id"],
        })
        conversations = self._run({"action": "conversations"})

        self.assertEqual([message["content"] for message in messages], [
            "Pergunta de teste",
            "Resposta de teste",
        ])
        self.assertEqual(
            next(item["title"] for item in conversations if item["id"] == conversation["id"]),
            "Pergunta de teste",
        )

    def test_chat_can_disable_library_retrieval(self):
        self._run({"action": "conversations"})
        with patch.object(web_worker, "search_library", side_effect=AssertionError("not expected")):
            result = self._run({
                "action": "prepare_chat",
                "conversationId": 1,
                "question": "Pergunta geral",
                "useLibrary": False,
            })

        self.assertEqual(result["sources"], [])
        self.assertEqual(result["messages"][-1], {"role": "user", "content": "Pergunta geral"})


if __name__ == "__main__":
    unittest.main()
