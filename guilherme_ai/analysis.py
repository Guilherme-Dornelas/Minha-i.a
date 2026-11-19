import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPREADSHEET_DIR = PROJECT_ROOT / "data" / "spreadsheets"
MAX_SPREADSHEET_BYTES = 20 * 1024 * 1024
MAX_PROJECT_FILES = 2000
MAX_PROJECT_FILE_BYTES = 1024 * 1024
IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".cache",
    "coverage",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    "secrets",
    "credentials",
    "certs",
}
SENSITIVE_FILENAMES = {
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.json",
}
MANIFEST_NAMES = {
    "package.json": "Node.js",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java",
    "build.gradle": "Java/Kotlin",
    "composer.json": "PHP",
    "gemfile": "Ruby",
    "dockerfile": "Docker",
}
_CELL_REFERENCE = r"\$?[A-Z]{1,3}\$?\d{1,7}"
_VALUE = rf"(?:{_CELL_REFERENCE}|\d+(?:\.\d+)?)"
_SAFE_FORMULA = re.compile(
    rf"=(?:{_VALUE}(?:[+\-*/]{_VALUE})+|"
    rf"(?:SUM|AVERAGE|MIN|MAX|COUNT|COUNTA)\({_CELL_REFERENCE}(?::{_CELL_REFERENCE})?\))",
    re.IGNORECASE,
)


class AnalysisError(ValueError):
    """Raised when a local analysis input is invalid or unavailable."""


def _spreadsheet_path(filename: str) -> Path:
    if not filename or Path(filename).name != filename or filename in {".", ".."}:
        raise AnalysisError("Informe somente o nome do arquivo enviado.")
    if Path(filename).suffix.lower() not in {".csv", ".xlsx"}:
        raise AnalysisError("Formato não suportado. Use CSV ou XLSX.")
    path = (SPREADSHEET_DIR / filename).resolve()
    try:
        path.relative_to(SPREADSHEET_DIR.resolve())
    except ValueError as error:
        raise AnalysisError("O arquivo está fora da pasta de análise autorizada.") from error
    if not path.is_file():
        raise AnalysisError(f"Arquivo não encontrado: {filename}")
    if path.stat().st_size > MAX_SPREADSHEET_BYTES:
        raise AnalysisError("O arquivo excede o limite de 20 MB.")
    return path


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _dataframe_summary(frame: Any, sheet: str) -> dict[str, Any]:
    import pandas as pd

    sample = frame.head(5).where(pd.notna(frame.head(5)), None)
    sample_rows = [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in sample.to_dict(orient="records")
    ]
    numeric = {}
    for column in frame.select_dtypes(include="number").columns[:20]:
        values = frame[column].dropna()
        if not values.empty:
            numeric[str(column)] = {
                "min": _json_value(values.min()),
                "max": _json_value(values.max()),
                "mean": _json_value(values.mean()),
            }
    return {
        "sheet": sheet,
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
        "columnNames": [str(column) for column in frame.columns[:100]],
        "missingByColumn": {
            str(column): int(count)
            for column, count in frame.isna().sum().items()
            if count > 0
        },
        "duplicateRows": int(frame.duplicated().sum()),
        "numericSummary": numeric,
        "sample": sample_rows,
        "truncated": int(frame.shape[0]) >= 100_000,
    }


def analyze_spreadsheet(filename: str) -> dict[str, Any]:
    path = _spreadsheet_path(filename)
    try:
        import pandas as pd
    except ImportError as error:
        raise AnalysisError(
            "Análise de planilhas requer dependências opcionais. "
            "Instale com 'python -m pip install -r requirements-analysis.txt'."
        ) from error

    try:
        if path.suffix.lower() == ".csv":
            try:
                frame = pd.read_csv(path, nrows=100_000, encoding="utf-8-sig")
            except UnicodeDecodeError:
                frame = pd.read_csv(path, nrows=100_000, encoding="cp1252")
            summaries = [_dataframe_summary(frame, path.name)]
        else:
            try:
                workbook = pd.ExcelFile(path, engine="openpyxl")
            except ImportError as error:
                raise AnalysisError(
                    "Para XLSX, instale openpyxl com requirements-analysis.txt."
                ) from error
            with workbook:
                sheet_names = workbook.sheet_names
                if len(sheet_names) > 20:
                    raise AnalysisError("O limite é de 20 abas por arquivo.")
                summaries = [
                    _dataframe_summary(
                        pd.read_excel(workbook, sheet_name=sheet, nrows=100_000),
                        sheet,
                    )
                    for sheet in sheet_names
                ]
    except AnalysisError:
        raise
    except Exception as error:
        raise AnalysisError(f"Não foi possível analisar a planilha: {error}") from error

    return {"filename": path.name, "sheets": summaries}


def create_spreadsheet(
    filename: str,
    columns: list[str],
    rows: list[list[Any]],
) -> dict[str, str]:
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.lower() != ".xlsx"
        or len(filename) > 150
    ):
        raise AnalysisError("Use um nome simples terminado em .xlsx.")
    if not 1 <= len(columns) <= 50 or len(rows) > 5000:
        raise AnalysisError("A planilha aceita de 1 a 50 colunas e até 5.000 linhas.")
    if any(not isinstance(column, str) or not column.strip() or len(column) > 100 for column in columns):
        raise AnalysisError("Os nomes das colunas devem ser textos de até 100 caracteres.")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise AnalysisError("Cada linha precisa conter o mesmo número de valores das colunas.")

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError as error:
        raise AnalysisError(
            "Criação de planilhas requer openpyxl. Instale requirements-analysis.txt."
        ) from error

    SPREADSHEET_DIR.mkdir(parents=True, exist_ok=True)
    path = _spreadsheet_path_for_new_file(filename)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Dados"
    sheet.append(columns)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="334D72")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row in rows:
        safe_row = []
        for value in row:
            if value is None or isinstance(value, (bool, int, float)):
                safe_row.append(value)
            elif (
                isinstance(value, dict)
                and set(value) == {"formula"}
                and isinstance(value["formula"], str)
                and _SAFE_FORMULA.fullmatch(value["formula"])
            ):
                safe_row.append(value["formula"].upper())
            elif isinstance(value, str) and len(value) <= 10_000:
                safe_row.append("'" + value if value.startswith(("=", "+", "-", "@")) else value)
            else:
                raise AnalysisError(
                    "As células devem ser textos curtos, números, vazias ou fórmulas permitidas."
                )
        sheet.append(safe_row)

    try:
        with path.open("xb") as file:
            workbook.save(file)
    except FileExistsError as error:
        raise AnalysisError("Já existe uma planilha com esse nome; o arquivo original foi mantido.") from error
    return {"filename": path.name}


def _spreadsheet_path_for_new_file(filename: str) -> Path:
    if not filename or Path(filename).name != filename or not re.fullmatch(
        r"[\w .-]+\.xlsx", filename, flags=re.IGNORECASE
    ):
        raise AnalysisError("O nome da planilha contém caracteres não permitidos.")
    path = (SPREADSHEET_DIR / filename).resolve()
    try:
        path.relative_to(SPREADSHEET_DIR.resolve())
    except ValueError as error:
        raise AnalysisError("O arquivo está fora da pasta de análise autorizada.") from error
    return path


def analyze_project(directory: str) -> dict[str, Any]:
    if not isinstance(directory, str) or not directory.strip():
        raise AnalysisError("Informe o caminho da pasta do projeto.")
    root = Path(directory).expanduser()
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise AnalysisError("A pasta informada não existe ou não pode ser acessada.") from error
    if not root.is_dir() or root == Path(root.anchor):
        raise AnalysisError("Selecione uma pasta de projeto, não uma unidade ou arquivo.")

    extension_counts: Counter[str] = Counter()
    manifests: set[str] = set()
    files_seen = 0
    skipped_sensitive = 0
    capped = False

    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = [
            name for name in directories
            if name.casefold() not in IGNORED_DIRECTORIES
            and not (current_path / name).is_symlink()
        ]
        for filename in filenames:
            file_path = current_path / filename
            lower_name = filename.casefold()
            if (
                lower_name.startswith(".env")
                or lower_name.endswith((".pem", ".key", ".p12", ".pfx"))
                or lower_name in SENSITIVE_FILENAMES
            ):
                skipped_sensitive += 1
                continue
            if file_path.is_symlink():
                continue
            files_seen += 1
            if files_seen > MAX_PROJECT_FILES:
                capped = True
                break
            try:
                if file_path.stat().st_size > MAX_PROJECT_FILE_BYTES:
                    continue
            except OSError:
                continue
            extension = file_path.suffix.lower() or "[sem extensão]"
            extension_counts[extension] += 1
            manifest = MANIFEST_NAMES.get(lower_name)
            if manifest:
                manifests.add(manifest)
        if capped:
            break

    recommendations = []
    root_files = {item.name.casefold() for item in root.iterdir() if item.is_file()}
    if not any(name.startswith("readme") for name in root_files):
        recommendations.append("Adicionar um README com instruções de instalação e execução.")
    if "package.json" in root_files and not any(
        name in root_files for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock")
    ):
        recommendations.append("Avaliar adicionar um arquivo de lock das dependências Node.")
    if not any(name in root_files for name in ("tests", "test")):
        recommendations.append("Verificar se há testes automatizados para as funcionalidades principais.")

    return {
        "directory": root.name,
        "filesAnalyzed": min(files_seen, MAX_PROJECT_FILES),
        "capped": capped,
        "technologies": sorted(manifests),
        "extensions": dict(extension_counts.most_common(12)),
        "recommendations": recommendations,
        "sensitiveFilesSkipped": skipped_sensitive,
        "contentsSentToModel": False,
        "codeExecuted": False,
    }
