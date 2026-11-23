import hashlib
import json
import logging
import math
import re
import sqlite3
from pathlib import Path
from typing import Any

import requests

from .config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBED_BATCH_SIZE,
    EMBED_MODEL,
    EMBED_URL,
    KNOWLEDGE_DIR,
    MIN_SIMILARITY,
    TOP_K,
)

logger = logging.getLogger(__name__)


class DocumentError(Exception):
    """Raised when a library document cannot be read or indexed."""


def resolve_library_file(path: str | Path) -> Path:
    library_root = KNOWLEDGE_DIR.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = library_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(library_root)
    except ValueError as error:
        raise DocumentError("O arquivo deve estar dentro da pasta biblioteca.") from error
    if candidate.suffix.lower() not in {".txt", ".pdf"}:
        raise DocumentError("Formato não suportado. Use arquivos TXT ou PDF.")
    return candidate


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("O tamanho do trecho e a sobreposição são inválidos.")
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start, end)
            if boundary > start + size // 2:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(normalized):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _ocr_pdf(path: Path, page_numbers: list[int]) -> dict[int, str]:
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError as error:
        raise DocumentError(
            "OCR requer dependências opcionais. Instale com "
            "'.venv\\Scripts\\python.exe -m pip install -r requirements-ocr.txt' "
            "e instale o Tesseract OCR no sistema."
        ) from error

    try:
        document = pdfium.PdfDocument(str(path))
        pages = {}
        try:
            if len(page_numbers) > 100 or any(
                page_number < 0 or page_number >= len(document)
                for page_number in page_numbers
            ):
                raise DocumentError("O OCR aceita até 100 páginas válidas por vez.")
            for page_number in page_numbers:
                page = document[page_number]
                try:
                    bitmap = page.render(scale=2)
                    try:
                        image = bitmap.to_pil()
                        try:
                            pages[page_number] = pytesseract.image_to_string(image, lang="por+eng")
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        finally:
            document.close()
    except DocumentError:
        raise
    except pytesseract.TesseractNotFoundError as error:
        raise DocumentError(
            "Tesseract OCR não foi encontrado. Instale-o e adicione-o ao PATH."
        ) from error
    except Exception as error:
        raise DocumentError(f"Falha ao executar OCR local no PDF: {error}") from error
    return pages


def _read_document(path: Path, enable_ocr: bool = False) -> str:
    if path.suffix.lower() == ".txt":
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="cp1252")
            except UnicodeDecodeError as error:
                raise DocumentError("Não foi possível decodificar o arquivo TXT.") from error

    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise DocumentError(
            "Para importar PDFs, instale as dependências com "
            "'.venv\\Scripts\\python.exe -m pip install -r requirements.txt'."
        ) from error

    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise DocumentError("O PDF está protegido por senha e não pode ser indexado.")
        pages = [page.extract_text() or "" for page in reader.pages]
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError(f"Não foi possível ler o PDF: {error}") from error

    if enable_ocr:
        image_pages = [
            page_number for page_number, page_text in enumerate(pages)
            if not page_text.strip()
        ]
        if image_pages:
            recognized_pages = _ocr_pdf(path, image_pages)
            pages = [
                recognized_pages.get(page_number, page_text)
                for page_number, page_text in enumerate(pages)
            ]
    text = "\n".join(pages).strip()
    if not text:
        if not enable_ocr:
            raise DocumentError(
                "O PDF não contém texto extraível; pode ser digitalizado como imagem. "
                "Ative a opção de OCR para processá-lo localmente."
            )
        raise DocumentError("O OCR não encontrou texto legível no PDF.")
    return text


def _source_name(path: Path) -> str:
    return path.relative_to(KNOWLEDGE_DIR.resolve()).as_posix()


def _source_aliases(source: str) -> list[str]:
    normalized = source.replace("\\", "/").lstrip("/")
    windows_path = normalized.replace("/", "\\")
    legacy_project_path = f"biblioteca/{normalized}"
    return list(dict.fromkeys((
        normalized,
        windows_path,
        legacy_project_path,
        legacy_project_path.replace("/", "\\"),
    )))


def _legacy_project_aliases(source: str) -> list[str]:
    normalized = source.replace("\\", "/").lstrip("/")
    legacy_source = f"biblioteca/{normalized}"
    return list(dict.fromkeys((legacy_source, legacy_source.replace("/", "\\"))))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate_embeddings(
    texts: list[str],
    post: Any = requests.post,
) -> list[list[float]]:
    if not texts:
        return []
    response = post(
        EMBED_URL,
        json={"model": EMBED_MODEL, "input": texts, "keep_alive": "30s"},
        timeout=300,
    )
    response.raise_for_status()
    try:
        embeddings = response.json()["embeddings"]
        if len(embeddings) != len(texts):
            raise DocumentError("Ollama retornou uma quantidade inesperada de embeddings.")
        vectors = [[float(value) for value in embedding] for embedding in embeddings]
    except DocumentError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise DocumentError("Ollama retornou uma resposta de embeddings inválida.") from error
    for vector in vectors:
        if not vector or not all(math.isfinite(value) for value in vector):
            raise DocumentError("Ollama retornou um embedding vazio ou inválido.")
    return vectors


def _known_hash(connection: sqlite3.Connection, source: str) -> str | None:
    row = connection.execute(
        "SELECT sha256 FROM documentos WHERE fonte = ?", (source,)
    ).fetchone()
    return row["sha256"] if row else None


def _duplicate_source(connection: sqlite3.Connection, source: str, digest: str) -> str | None:
    row = connection.execute(
        "SELECT fonte FROM documentos WHERE sha256 = ? AND fonte != ? ORDER BY id LIMIT 1",
        (digest, source),
    ).fetchone()
    return str(row["fonte"]) if row else None


def index_document(
    connection: sqlite3.Connection,
    file_path: str | Path,
    force: bool = False,
    enable_ocr: bool = False,
) -> dict[str, Any]:
    path = resolve_library_file(file_path)
    if not path.is_file():
        raise DocumentError(f"Arquivo não encontrado: {path.name}")

    source = _source_name(path)
    digest = _sha256(path)
    if not force and _known_hash(connection, source) == digest:
        return {"source": source, "status": "unchanged", "chunks": 0}
    duplicate = _duplicate_source(connection, source, digest)
    if duplicate is not None:
        return {
            "source": source,
            "status": "duplicate",
            "duplicate_of": duplicate,
            "chunks": 0,
        }

    text = _read_document(path, enable_ocr=enable_ocr)
    chunks = split_text(text)
    if not chunks:
        raise DocumentError("O documento está vazio e não foi indexado.")

    embeddings = []
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        embeddings.extend(generate_embeddings(chunks[start:start + EMBED_BATCH_SIZE]))

    aliases = _source_aliases(source)
    placeholders = ", ".join("?" for _ in aliases)
    legacy_aliases = _legacy_project_aliases(source)
    with connection:
        connection.execute(f"DELETE FROM conhecimentos WHERE fonte IN ({placeholders})", aliases)
        connection.execute(
            f"DELETE FROM documentos WHERE fonte IN ({', '.join('?' for _ in legacy_aliases)})",
            legacy_aliases,
        )
        connection.executemany(
            """
            INSERT INTO conhecimentos (fonte, conteudo, embedding)
            VALUES (?, ?, ?)
            """,
            [
                (source, chunk, json.dumps(vector, separators=(",", ":")))
                for chunk, vector in zip(chunks, embeddings)
            ],
        )
        connection.execute(
            """
            INSERT INTO documentos (fonte, sha256, tipo, total_trechos, indexado_em)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(fonte) DO UPDATE SET
                sha256 = excluded.sha256,
                tipo = excluded.tipo,
                total_trechos = excluded.total_trechos,
                indexado_em = CURRENT_TIMESTAMP
            """,
            (source, digest, path.suffix.lower().lstrip("."), len(chunks)),
        )
    return {"source": source, "status": "indexed", "chunks": len(chunks)}


def index_library(connection: sqlite3.Connection, force: bool = False) -> list[dict[str, Any]]:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path for path in KNOWLEDGE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in {".txt", ".pdf"}
    )
    results = []
    for path in files:
        try:
            results.append(index_document(connection, path, force=force))
        except (DocumentError, OSError, requests.RequestException) as error:
            logger.exception("Falha ao indexar %s", path)
            results.append({
                "source": _source_name(path),
                "status": "error",
                "error": str(error),
            })
    return results


def list_documents(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT d.id, d.fonte, d.tipo, d.total_trechos, d.sha256, d.indexado_em,
               COUNT(k.id) AS trechos_atuais
        FROM documentos d
        LEFT JOIN conhecimentos k
          ON REPLACE(k.fonte, '\\', '/') = d.fonte
        GROUP BY d.id, d.fonte, d.tipo, d.total_trechos, d.sha256, d.indexado_em
        ORDER BY d.fonte
        """
    ).fetchall()
    return [dict(row) for row in rows]


def remove_document(connection: sqlite3.Connection, document_id: int) -> bool:
    row = connection.execute(
        "SELECT fonte FROM documentos WHERE id = ?", (document_id,)
    ).fetchone()
    if row is None:
        return False
    source = str(row["fonte"]).replace("\\", "/")
    relative_source = source.removeprefix("biblioteca/")
    candidate = (KNOWLEDGE_DIR / relative_source).resolve()
    try:
        candidate.relative_to(KNOWLEDGE_DIR.resolve())
    except ValueError as error:
        raise DocumentError("O registro está fora da biblioteca autorizada.") from error
    aliases = _source_aliases(relative_source)
    with connection:
        connection.execute(
            f"DELETE FROM conhecimentos WHERE fonte IN ({', '.join('?' for _ in aliases)})",
            aliases,
        )
        connection.execute("DELETE FROM documentos WHERE id = ?", (document_id,))
    return True


def cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    if len(vector_a) != len(vector_b) or not vector_a:
        return 0.0
    norm_a = math.sqrt(sum(value * value for value in vector_a))
    norm_b = math.sqrt(sum(value * value for value in vector_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    score = sum(a * b for a, b in zip(vector_a, vector_b)) / (norm_a * norm_b)
    return score if math.isfinite(score) else 0.0


def rank_chunks(
    query_embedding: list[float],
    rows: list[sqlite3.Row] | list[dict[str, Any]],
    top_k: int = TOP_K,
    minimum_score: float = MIN_SIMILARITY,
) -> list[dict[str, Any]]:
    if top_k < 1:
        raise ValueError("top_k deve ser pelo menos 1.")
    if not -1 <= minimum_score <= 1:
        raise ValueError("A similaridade mínima deve estar entre -1 e 1.")
    matches = []
    for row in rows:
        try:
            embedding = json.loads(row["embedding"])
            score = cosine_similarity(query_embedding, embedding)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise DocumentError(f"Embedding inválido no banco de dados: {error}") from error
        if score >= minimum_score:
            matches.append({
                "id": row["id"],
                "source": str(row["fonte"]).replace("\\", "/"),
                "content": row["conteudo"],
                "score": score,
            })
    matches.sort(key=lambda item: item["score"], reverse=True)
    selected = []
    selected_ids = set()
    per_source: dict[str, int] = {}
    for maximum_per_source in (1, 2):
        for match in matches:
            if (
                match["id"] in selected_ids
                or per_source.get(match["source"], 0) >= maximum_per_source
            ):
                continue
            selected.append(match)
            selected_ids.add(match["id"])
            per_source[match["source"]] = per_source.get(match["source"], 0) + 1
            if len(selected) == top_k:
                return selected
        if len(selected) >= top_k:
            break
    return selected


def search_library(
    connection: sqlite3.Connection,
    query: str,
    top_k: int = TOP_K,
    minimum_score: float = MIN_SIMILARITY,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT id, fonte, conteudo, embedding FROM conhecimentos"
    ).fetchall()
    if not rows:
        return []
    query_embedding = generate_embeddings([query])[0]
    return rank_chunks(query_embedding, rows, top_k, minimum_score)
