import json
import unittest
from unittest.mock import Mock, patch

import requests

from guilherme_ai import tools
from guilherme_ai.assistant import (
    AssistantError,
    WebSearchIntent,
    classify_web_search_intent,
    search_web_intent,
)
from guilherme_ai.tools import ToolError, WebSearchError, web_search


class WebSearchTests(unittest.TestCase):
    def test_search_requests_json_and_returns_limited_safe_results(self):
        response = Mock()
        response.json.return_value = {
            "results": [
                {
                    "title": "Resultado 1",
                    "url": "https://example.com/1",
                    "content": "Descrição 1",
                },
                {
                    "title": "URL inválida",
                    "url": "javascript:alert(1)",
                    "content": "Não deve ser exibida.",
                },
                {
                    "title": "Duplicado",
                    "url": "https://example.com/1",
                    "content": "Mesmo destino.",
                },
                {
                    "title": "Resultado 2",
                    "url": "http://example.org/2",
                    "description": "Descrição 2",
                },
            ],
        }
        response.raise_for_status.return_value = None
        get = Mock(return_value=response)

        with patch.object(tools, "SEARXNG_SEARCH_URL", "http://127.0.0.1:8080/search"):
            result = web_search("  consulta atual  ", max_results=2, get=get)

        self.assertEqual(result, [
            {
                "title": "Resultado 1",
                "url": "https://example.com/1",
                "description": "Descrição 1",
            },
            {
                "title": "Resultado 2",
                "url": "http://example.org/2",
                "description": "Descrição 2",
            },
        ])
        get.assert_called_once_with(
            "http://127.0.0.1:8080/search",
            params={"q": "consulta atual", "format": "json"},
            timeout=tools.WEB_SEARCH_TIMEOUT_SECONDS,
        )

    def test_search_rejects_invalid_queries_and_result_limits(self):
        for query, limit in (
            ("", 5),
            ("x" * 501, 5),
            ("consulta", 0),
            ("consulta", 11),
            ("consulta", True),
        ):
            with self.subTest(query_length=len(query), limit=limit):
                with self.assertRaises(ToolError):
                    web_search(query, limit, get=Mock())

    def test_search_reports_timeout_connection_and_invalid_json(self):
        for failure, expected in (
            (requests.Timeout("timeout"), "excedeu o tempo limite"),
            (requests.ConnectionError("offline"), "conectar ao SearXNG"),
        ):
            with self.subTest(failure=failure):
                with self.assertRaisesRegex(WebSearchError, expected):
                    web_search("consulta", get=Mock(side_effect=failure))

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"unexpected": []}
        with self.assertRaisesRegex(WebSearchError, "formato de resultados inválido"):
            web_search("consulta", get=Mock(return_value=response))

    def test_structured_router_searches_current_questions_and_skips_stable_ones(self):
        for route_data, question, expected_required in (
            (
                {"search_required": True, "query": "presidente atual do Brasil"},
                "Quem é o presidente atual do Brasil?",
                True,
            ),
            (
                {"search_required": False, "query": "2 + 2"},
                "Quanto é 2 + 2?",
                False,
            ),
        ):
            response = Mock()
            response.json.return_value = {
                "message": {"content": json.dumps(route_data)},
            }
            response.raise_for_status.return_value = None
            with self.subTest(question=question):
                result = classify_web_search_intent(
                    question,
                    post=Mock(return_value=response),
                )
                self.assertEqual(result.required, expected_required)

    def test_explicit_latest_cue_overrides_router_false_negative(self):
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "search_required": False,
                    "query": "última versão de Python",
                }),
            },
        }
        response.raise_for_status.return_value = None

        result = classify_web_search_intent(
            "Qual é a versão mais recente do Python?",
            post=Mock(return_value=response),
        )

        self.assertTrue(result.required)
        self.assertEqual(
            result.query,
            "Qual é a versão mais recente do Python?",
        )

    def test_relative_weekday_forces_search_with_sao_paulo_date(self):
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "search_required": False,
                    "query": "influenciador morreu quinta-feira",
                }),
            },
        }
        response.raise_for_status.return_value = None
        resolved_dates = ("Quinta considerada = 19/11/2026",)
        with patch(
            "guilherme_ai.assistant.current_datetime_context",
            return_value="2026-11-20T21:05-03:00 [America/Sao_Paulo]",
        ), patch(
            "guilherme_ai.assistant.resolve_relative_dates",
            return_value=resolved_dates,
        ):
            result = classify_web_search_intent(
                "Quem foi o influenciador que morreu na quinta-feira?",
                post=Mock(return_value=response),
            )

        self.assertTrue(result.required)
        self.assertIn("19/11/2026", result.query)
        self.assertEqual(result.resolved_dates, resolved_dates)

    def test_related_searches_merge_and_deduplicate_results(self):
        first = {"title": "Um", "url": "https://example.com/1", "description": "A"}
        duplicate = {"title": "Duplicado", "url": first["url"], "description": "B"}
        second = {"title": "Dois", "url": "https://example.org/2", "description": "C"}
        search = Mock(side_effect=[[first, duplicate], [second]])

        results = search_web_intent(
            WebSearchIntent(
                required=True,
                query="influenciador morreu",
                related_queries=("influenciador filha notícia",),
            ),
            search=search,
        )

        self.assertEqual(results, [first, second])
        self.assertEqual(
            [call.args[0] for call in search.call_args_list],
            ["influenciador morreu", "influenciador filha notícia"],
        )

    def test_classifier_validates_and_keeps_related_queries(self):
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "search_required": True,
                    "query": "influenciador morreu quinta-feira",
                    "related_queries": ["influenciador brasileiro filha"],
                }),
            },
        }
        response.raise_for_status.return_value = None

        with patch("guilherme_ai.assistant.resolve_relative_dates", return_value=()):
            intent = classify_web_search_intent(
                "Quem morreu na quinta-feira?",
                post=Mock(return_value=response),
            )

        self.assertEqual(intent.query, "influenciador morreu quinta-feira")
        self.assertEqual(intent.related_queries, ("influenciador brasileiro filha",))

    def test_classifier_receives_current_local_datetime(self):
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": json.dumps({
                    "search_required": False,
                    "query": "",
                }),
            },
        }
        response.raise_for_status.return_value = None
        post = Mock(return_value=response)

        with patch(
            "guilherme_ai.assistant.current_datetime_context",
            return_value="2026-11-20T21:05-03:00 [America/Sao_Paulo]",
        ):
            classify_web_search_intent("Quanto é 2 + 2?", post=post)

        classifier_prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("2026-11-20T21:05-03:00", classifier_prompt)

    def test_router_rejects_malformed_structured_output(self):
        response = Mock()
        response.json.return_value = {
            "message": {"content": '{"search_required":"yes","query":"x"}'},
        }
        response.raise_for_status.return_value = None

        with self.assertRaisesRegex(AssistantError, "campos inválidos"):
            classify_web_search_intent(
                "Pergunta",
                post=Mock(return_value=response),
            )


if __name__ == "__main__":
    unittest.main()
