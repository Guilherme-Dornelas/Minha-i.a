import base64
import json
import unittest
from unittest.mock import Mock

from guilherme_ai.gmail import (
    classify_gmail_intent,
    compose_email_draft,
    has_gmail_cue,
    parse_gmail_api_message,
)
from guilherme_ai.assistant import AssistantError


def _encoded_body(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


class GmailTests(unittest.TestCase):
    def test_detects_natural_gmail_requests(self):
        self.assertTrue(has_gmail_cue("Liste meus últimos dez e-mails recebidos."))
        self.assertTrue(has_gmail_cue("Responda ao último email."))
        self.assertFalse(has_gmail_cue("Explique como funciona o correio aéreo."))

    def test_structured_intent_uses_native_gmail_filter_and_validates_ids(self):
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "action": "list",
                    "query": "in:inbox",
                    "message_id": "",
                    "max_results": 10,
                }),
            },
        }
        response.raise_for_status.return_value = None
        intent = classify_gmail_intent(
            "Liste meus últimos dez e-mails recebidos.",
            post=Mock(return_value=response),
        )
        self.assertEqual(intent.action, "list")
        self.assertEqual(intent.query, "in:inbox")
        self.assertEqual(intent.max_results, 10)

        response.json.return_value["message"]["content"] = json.dumps({
            "action": "read",
            "query": "",
            "message_id": "../injected",
            "max_results": 1,
        })
        with self.assertRaisesRegex(AssistantError, "identificador"):
            classify_gmail_intent(
                "Leia este e-mail",
                post=Mock(return_value=response),
            )

    def test_parser_decodes_headers_and_prefers_plain_text(self):
        encoded_subject = base64.b64encode("Notícias à".encode()).decode()
        message = {
            "id": "abc123",
            "threadId": "thread123",
            "internalDate": "1795132800000",
            "labelIds": ["INBOX", "UNREAD"],
            "snippet": "Prévia",
            "payload": {
                "headers": [
                    {"name": "From", "value": "=?UTF-8?B?QW5h?= <ana@example.com>"},
                    {"name": "To", "value": "user@example.com"},
                    {"name": "Subject", "value": f"=?UTF-8?B?{encoded_subject}?="},
                    {"name": "Message-ID", "value": "<message@example.com>"},
                    {"name": "References", "value": "<previous@example.com>"},
                ],
                "mimeType": "multipart/alternative",
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": _encoded_body(
                            "<p>Texto HTML que deve ser ignorado.</p>"
                        )},
                    },
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _encoded_body("Texto simples da mensagem.")},
                    },
                    {
                        "mimeType": "text/plain",
                        "headers": [{"name": "Content-Disposition", "value": "attachment"}],
                        "body": {"data": _encoded_body("anexo ignorado")},
                    },
                ],
            },
        }
        parsed = parse_gmail_api_message(message)
        self.assertEqual(parsed["from"], "Ana <ana@example.com>")
        self.assertEqual(parsed["fromAddress"], "ana@example.com")
        self.assertEqual(parsed["subject"], "Notícias à")
        self.assertEqual(parsed["body"], "Texto simples da mensagem.")
        self.assertEqual(parsed["threadId"], "thread123")
        self.assertTrue(parsed["unread"])
        self.assertEqual(parsed["messageId"], "<message@example.com>")
        self.assertEqual(parsed["references"], "<previous@example.com>")
        self.assertNotIn("Texto HTML", parsed["body"])
        self.assertNotIn("anexo ignorado", parsed["body"])

    def test_parser_strips_active_html_when_plain_text_is_missing(self):
        message = {
            "id": "abc",
            "payload": {
                "headers": [],
                "mimeType": "text/html",
                "body": {"data": _encoded_body(
                    "<p>Conteúdo visível</p><script>prompt('x')</script>"
                    "<style>.x{display:none}</style>"
                )},
            },
        }
        parsed = parse_gmail_api_message(message)
        self.assertEqual(parsed["body"], "Conteúdo visível")

    def test_email_composition_returns_reviewable_fields_without_sending(self):
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "to": "",
                    "cc": "",
                    "bcc": "",
                    "subject": "Agradecimento",
                    "body": "Agradeço pela oportunidade.",
                }),
            },
        }
        response.raise_for_status.return_value = None
        post = Mock(return_value=response)
        draft = compose_email_draft(
            "Escreva um e-mail profissional agradecendo pela oportunidade.",
            post=post,
        )
        self.assertEqual(draft["to"], "")
        self.assertEqual(draft["subject"], "Agradecimento")
        self.assertIn("Agradeço", draft["body"])
        self.assertNotIn("send", str(post.call_args.kwargs["json"]).casefold())


if __name__ == "__main__":
    unittest.main()
