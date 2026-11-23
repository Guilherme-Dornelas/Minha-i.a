import unittest
from unittest.mock import Mock, patch

from guilherme_ai import tools
from guilherme_ai.tools import WebFetchError, web_fetch


class WebFetchTests(unittest.TestCase):
    def test_fetch_extracts_page_text_and_publication_date(self):
        body = (
            '<html><head><title>Matéria atual</title>'
            '<meta property="article:published_time" content="2026-11-19T10:00:00-03:00">'
            '<script>texto que não deve aparecer</script>'
            '<style>.hidden { display: none; }</style></head>'
            '<body><h1>Notícia confirmada</h1><p>Texto principal.</p></body></html>'
        ).encode()
        request_page = Mock(return_value=(
            200,
            {"content-type": "text/html; charset=utf-8"},
            body,
        ))
        with patch.object(
            tools,
            "_resolve_public_ips",
            return_value=["93.184.216.34"],
        ):
            result = web_fetch(
                "https://example.com/noticia",
                request_page=request_page,
            )

        self.assertEqual(result["title"], "Matéria atual")
        self.assertEqual(result["publishedAt"], "2026-11-19T10:00:00-03:00")
        self.assertIn("Notícia confirmada", result["content"])
        self.assertIn("Texto principal.", result["content"])
        self.assertNotIn("texto que não deve aparecer", result["content"])

    def test_fetch_blocks_private_addresses_and_redirects(self):
        with self.assertRaisesRegex(WebFetchError, "não público"):
            web_fetch("http://127.0.0.1/")

        def resolver(hostname: str, _port: int) -> list[str]:
            if hostname == "127.0.0.1":
                raise WebFetchError("A página aponta para um endereço de rede não público.")
            return ["93.184.216.34"]

        request_page = Mock(return_value=(
            302,
            {"location": "http://127.0.0.1/private"},
            b"",
        ))
        with patch.object(tools, "_resolve_public_ips", side_effect=resolver):
            with self.assertRaisesRegex(WebFetchError, "não público"):
                web_fetch("https://example.com/redirect", request_page=request_page)
        request_page.assert_called_once()

    def test_fetch_rejects_non_web_urls_and_oversized_pages(self):
        request_page = Mock(return_value=(
            200,
            {"content-type": "text/plain; charset=utf-8"},
            b"x" * (tools.WEB_FETCH_MAX_BYTES + 1),
        ))
        for url in (
            "file:///C:/Windows/win.ini",
            "http://user:pass@example.com/",
            "https://example.com:8443/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(WebFetchError):
                    web_fetch(url, request_page=request_page)

        with patch.object(
            tools,
            "_resolve_public_ips",
            return_value=["93.184.216.34"],
        ), self.assertRaisesRegex(WebFetchError, "excede o limite"):
            web_fetch("https://example.com/large", request_page=request_page)

    def test_fetch_reports_bad_content_and_http_errors(self):
        with patch.object(
            tools,
            "_resolve_public_ips",
            return_value=["93.184.216.34"],
        ):
            with self.assertRaisesRegex(WebFetchError, "HTTP 404"):
                web_fetch(
                    "https://example.com/missing",
                    request_page=Mock(return_value=(404, {}, b"")),
                )
            with self.assertRaisesRegex(WebFetchError, "HTML ou texto"):
                web_fetch(
                    "https://example.com/file",
                    request_page=Mock(return_value=(
                        200,
                        {"content-type": "application/pdf"},
                        b"%PDF",
                    )),
                )


if __name__ == "__main__":
    unittest.main()
