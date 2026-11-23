import ast
import codecs
import http.client
import ipaddress
import json
import math
import operator
import re
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

import requests

from .config import (
    WEB_FETCH_MAX_BYTES,
    WEB_FETCH_MAX_CHARS,
    WEB_FETCH_MAX_REDIRECTS,
    WEB_FETCH_TIMEOUT_SECONDS,
    SEARXNG_SEARCH_URL,
    WEB_SEARCH_MAX_ALLOWED_RESULTS,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_TIMEOUT_SECONDS,
)
from .time_context import current_datetime_context


class ToolError(ValueError):
    """Raised for invalid or unsafe tool input."""


class WebSearchError(RuntimeError):
    """Raised when the local SearXNG service is unavailable or returns invalid data."""


class WebFetchError(RuntimeError):
    """Raised when a page cannot be fetched safely or parsed."""


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def calculate(expression: str) -> float:
    if len(expression) > 200:
        raise ToolError("A expressão é muito longa.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ToolError("Expressão matemática inválida.") from error

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = float(node.value)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ToolError("O expoente não pode ser maior que 100 em módulo.")
            value = _BINARY_OPERATORS[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            value = _UNARY_OPERATORS[type(node.op)](evaluate(node.operand))
        else:
            raise ToolError("A calculadora aceita apenas operações aritméticas.")
        if not math.isfinite(value) or abs(value) > 1e100:
            raise ToolError("O resultado está fora do limite permitido.")
        return value

    try:
        return evaluate(tree)
    except (ArithmeticError, OverflowError) as error:
        raise ToolError(f"Não foi possível calcular: {error}") from error


def current_datetime() -> str:
    return current_datetime_context()


def web_search(
    query: str,
    max_results: int = WEB_SEARCH_MAX_RESULTS,
    *,
    get: Callable[..., requests.Response] = requests.get,
) -> list[dict[str, str]]:
    normalized_query = query.strip() if isinstance(query, str) else ""
    if not normalized_query or len(normalized_query) > 500:
        raise ToolError("A pesquisa precisa ter entre 1 e 500 caracteres.")
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= WEB_SEARCH_MAX_ALLOWED_RESULTS
    ):
        raise ToolError(
            f"A quantidade de resultados deve estar entre 1 e "
            f"{WEB_SEARCH_MAX_ALLOWED_RESULTS}."
        )

    try:
        response = get(
            SEARXNG_SEARCH_URL,
            params={"q": normalized_query, "format": "json"},
            timeout=WEB_SEARCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout as error:
        raise WebSearchError("A pesquisa no SearXNG excedeu o tempo limite.") from error
    except requests.RequestException as error:
        raise WebSearchError("Não foi possível conectar ao SearXNG local.") from error
    except (TypeError, ValueError) as error:
        raise WebSearchError("O SearXNG retornou uma resposta JSON inválida.") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise WebSearchError("O SearXNG retornou um formato de resultados inválido.")

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        url = item.get("url")
        description = item.get("content", item.get("description", ""))
        if not all(isinstance(value, str) for value in (title, url, description)):
            continue
        title = title.strip()
        url = url.strip()
        description = description.strip()
        try:
            parsed_url = urlsplit(url)
        except ValueError:
            continue
        if (
            not title
            or not url
            or len(url) > 2048
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or url in seen_urls
        ):
            continue
        seen_urls.add(url)
        results.append({
            "title": title[:300],
            "url": url,
            "description": description[:1600],
        })
        if len(results) >= max_results:
            break
    return results


class _PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.published_at = ""
        self._in_title = False
        self._suppressed: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): value or "" for key, value in attrs}
        if tag in {"script", "style", "noscript", "svg"}:
            self._suppressed.append(tag)
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and not self.published_at:
            key = (
                attributes.get("property", "")
                or attributes.get("name", "")
                or attributes.get("itemprop", "")
            ).casefold()
            if key in {
                "article:published_time",
                "date",
                "datepublished",
                "publishdate",
                "pubdate",
                "parsely-pub-date",
            }:
                self.published_at = attributes.get("content", "")[:100]

    def handle_endtag(self, tag: str) -> None:
        if tag in self._suppressed:
            for index in range(len(self._suppressed) - 1, -1, -1):
                if self._suppressed[index] == tag:
                    del self._suppressed[index:]
                    break
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value or self._suppressed:
            return
        if self._in_title:
            self.title_parts.append(value)
        else:
            self.text_parts.append(value)


def _validate_fetch_url(url: str) -> tuple[str, str, int, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise WebFetchError("A URL da página é inválida.") from error
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or (scheme == "http" and port not in {None, 80})
        or (scheme == "https" and port not in {None, 443})
        or any(ord(character) < 32 for character in url)
    ):
        raise WebFetchError("A URL precisa usar HTTP(S) público, sem credenciais ou porta não padrão.")
    resolved_port = port or (443 if scheme == "https" else 80)
    request_target = parsed.path or "/"
    if parsed.query:
        request_target += f"?{parsed.query}"
    return scheme, hostname, resolved_port, request_target


def _resolve_public_ips(hostname: str, port: int) -> list[str]:
    try:
        ipaddress.ip_address(hostname)
        addresses = [hostname]
    except ValueError:
        try:
            records = socket.getaddrinfo(
                hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as error:
            raise WebFetchError("Não foi possível resolver o endereço da página.") from error
        addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses:
        raise WebFetchError("O endereço da página não tem IP público.")
    for address in addresses:
        try:
            parsed_address = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as error:
            raise WebFetchError("O endereço da página resolveu para um IP inválido.") from error
        if not parsed_address.is_global:
            raise WebFetchError("A página aponta para um endereço de rede não público.")
    return addresses


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, hostname: str, address: str, port: int, timeout: float) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int, timeout: float) -> None:
        super().__init__(hostname, port=port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except OSError:
            raw_socket.close()
            raise


def _request_public_page(url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
    scheme, hostname, port, request_target = _validate_fetch_url(url)
    addresses = _resolve_public_ips(hostname, port)
    connection_type = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
    connection = connection_type(hostname, addresses[0], port, timeout)
    host_header = hostname
    if port != (443 if scheme == "https" else 80):
        host_header = f"{hostname}:{port}"
    try:
        connection.request(
            "GET",
            request_target,
            headers={
                "Host": host_header,
                "User-Agent": "GuilhermeAI/1.0 (local web reader)",
                "Accept": "text/html, application/xhtml+xml, text/plain;q=0.9",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        headers = {key.casefold(): value for key, value in response.getheaders()}
        content_length = headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > WEB_FETCH_MAX_BYTES:
            raise WebFetchError("A página excede o limite de tamanho permitido.")
        if headers.get("content-encoding", "identity").casefold() not in {"", "identity"}:
            raise WebFetchError("A página retornou uma codificação não permitida.")
        body = response.read(WEB_FETCH_MAX_BYTES + 1)
        if len(body) > WEB_FETCH_MAX_BYTES:
            raise WebFetchError("A página excede o limite de tamanho permitido.")
        return response.status, headers, body
    except (OSError, http.client.HTTPException, ssl.SSLError) as error:
        raise WebFetchError("Não foi possível abrir a página com segurança.") from error
    finally:
        connection.close()


def _decode_page(body: bytes, content_type: str) -> str:
    match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", content_type, re.IGNORECASE)
    encoding = match.group(1) if match else "utf-8"
    try:
        codecs.lookup(encoding)
    except LookupError:
        encoding = "utf-8"
    return body.decode(encoding, errors="replace")


def web_fetch(
    url: str,
    *,
    request_page: Callable[[str, float], tuple[int, dict[str, str], bytes]] = _request_public_page,
) -> dict[str, str]:
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise ToolError("Informe uma URL HTTP(S) válida.")
    current_url = url.strip()
    started_at = time.monotonic()

    for redirect_count in range(WEB_FETCH_MAX_REDIRECTS + 1):
        _, hostname, port, _ = _validate_fetch_url(current_url)
        _resolve_public_ips(hostname, port)
        remaining = WEB_FETCH_TIMEOUT_SECONDS - (time.monotonic() - started_at)
        if remaining <= 0:
            raise WebFetchError("A leitura da página excedeu o tempo limite.")
        status, headers, body = request_page(current_url, remaining)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location or redirect_count == WEB_FETCH_MAX_REDIRECTS:
                raise WebFetchError("A página excedeu o limite de redirecionamentos.")
            current_url = urljoin(current_url, location)
            continue
        if status < 200 or status >= 300:
            raise WebFetchError(f"A página respondeu com HTTP {status}.")
        if len(body) > WEB_FETCH_MAX_BYTES:
            raise WebFetchError("A página excede o limite de tamanho permitido.")

        content_type = headers.get("content-type", "").casefold()
        if not any(
            content_type.startswith(allowed)
            for allowed in ("text/html", "application/xhtml+xml", "text/plain")
        ):
            raise WebFetchError("A URL não retornou uma página HTML ou texto simples.")
        text = _decode_page(body, content_type)
        parser = _PageTextParser()
        if content_type.startswith("text/plain"):
            parser.text_parts = [text]
        else:
            parser.feed(text)
        content = re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()
        title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
        if not content:
            raise WebFetchError("A página não contém texto legível.")
        return {
            "title": title[:300] or urlsplit(current_url).hostname or current_url,
            "url": current_url,
            "publishedAt": parser.published_at,
            "content": content[:WEB_FETCH_MAX_CHARS],
        }
    raise WebFetchError("Não foi possível concluir a leitura da página.")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[str], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"A ferramenta '{tool.name}' já está registrada.")
        self._tools[tool.name] = tool

    def run(self, name: str, argument: str = "") -> str:
        try:
            tool = self._tools[name]
        except KeyError as error:
            raise ToolError(f"Ferramenta desconhecida: {name}") from error
        return tool.handler(argument)

    def available(self) -> list[Tool]:
        return list(self._tools.values())


def create_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("calculadora", "Avalia expressões aritméticas seguras.", lambda value: str(calculate(value))))
    registry.register(Tool("data_hora", "Consulta a data e o horário locais.", lambda _: current_datetime()))
    registry.register(Tool(
        "web_search",
        "Pesquisa informações atuais usando o SearXNG local.",
        lambda query: "\n".join(
            f"{item['title']}\n{item['url']}\n{item['description']}"
            for item in web_search(query)
        ) or "Nenhum resultado foi encontrado.",
    ))
    registry.register(Tool(
        "web_fetch",
        "Abre uma página HTTP(S) pública e extrai texto com proteção contra SSRF.",
        lambda url: json.dumps(web_fetch(url), ensure_ascii=False),
    ))
    return registry


def extract_authorized_filename(argument: str) -> str:
    name = argument.strip()
    path = Path(name)
    if (
        not name
        or path.is_absolute()
        or path.drive
        or ":" in name
        or re.search(r"(^|[\\/])\.\.([\\/]|$)", name)
    ):
        raise ToolError("Informe apenas um nome de arquivo dentro da biblioteca.")
    return name
