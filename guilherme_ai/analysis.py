import ast
import math
import os
import re
import tokenize
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPREADSHEET_DIR = PROJECT_ROOT / "data" / "spreadsheets"
MAX_SPREADSHEET_BYTES = 20 * 1024 * 1024
MAX_PROJECT_FILES = 2000
MAX_PROJECT_FILE_BYTES = 1024 * 1024
MAX_PROJECT_PYTHON_BYTES = 16 * 1024 * 1024
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
            "Instale com 'python -m pip install -r requirements.txt'."
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
                    "Para XLSX, instale as dependências de requirements.txt."
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
    columns: list[str] | None = None,
    rows: list[list[Any]] | None = None,
    sheets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if (
        not filename
        or Path(filename).name != filename
        or Path(filename).suffix.lower() != ".xlsx"
        or len(filename) > 150
    ):
        raise AnalysisError("Use um nome simples terminado em .xlsx.")
    if sheets is None:
        if columns is None or rows is None:
            raise AnalysisError("Informe colunas e linhas para criar a planilha.")
        sheets = [{"name": "Dados", "columns": columns, "rows": rows}]
    if not isinstance(sheets, list) or not 1 <= len(sheets) <= 20:
        raise AnalysisError("A planilha aceita de 1 a 20 abas.")

    normalized_sheets: list[tuple[str, list[str], list[list[Any]]]] = []
    sheet_names: set[str] = set()
    total_cells = 0
    for item in sheets:
        if not isinstance(item, dict):
            raise AnalysisError("Cada aba deve conter nome, colunas e linhas.")
        name = item.get("name")
        sheet_columns = item.get("columns")
        sheet_rows = item.get("rows")
        if not isinstance(name, str):
            raise AnalysisError("Cada aba precisa de um nome válido de até 31 caracteres.")
        normalized_name = name.strip()
        if (
            not normalized_name
            or len(normalized_name) > 31
            or re.search(r"[\[\]:*?/\\]", normalized_name)
            or normalized_name.startswith("'")
            or normalized_name.endswith("'")
        ):
            raise AnalysisError("Cada aba precisa de um nome válido de até 31 caracteres.")
        if normalized_name.casefold() in sheet_names:
            raise AnalysisError("Os nomes das abas não podem se repetir.")
        sheet_names.add(normalized_name.casefold())
        if not isinstance(sheet_columns, list) or not isinstance(sheet_rows, list):
            raise AnalysisError("Cada aba deve conter listas de colunas e linhas.")
        if not 1 <= len(sheet_columns) <= 50 or len(sheet_rows) > 5000:
            raise AnalysisError("Cada aba aceita de 1 a 50 colunas e até 5.000 linhas.")
        if any(
            not isinstance(column, str) or not column.strip() or len(column) > 100
            for column in sheet_columns
        ):
            raise AnalysisError("Os nomes das colunas devem ser textos de até 100 caracteres.")
        if any(
            not isinstance(row, list) or len(row) != len(sheet_columns)
            for row in sheet_rows
        ):
            raise AnalysisError("Cada linha precisa conter o mesmo número de valores das colunas.")
        total_cells += len(sheet_columns) * (len(sheet_rows) + 1)
        if total_cells > 250_000:
            raise AnalysisError("A planilha excede o limite de 250.000 células.")
        normalized_sheets.append((normalized_name, sheet_columns, sheet_rows))

    try:
        from openpyxl import Workbook
        from openpyxl.chart import BarChart, Reference
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as error:
        raise AnalysisError(
            "Criação de planilhas requer openpyxl. Instale requirements.txt."
        ) from error

    SPREADSHEET_DIR.mkdir(parents=True, exist_ok=True)
    path = _spreadsheet_path_for_new_file(filename)

    workbook = Workbook()
    workbook.remove(workbook.active)
    chart_count = 0
    for name, sheet_columns, sheet_rows in normalized_sheets:
        sheet = workbook.create_sheet(name)
        sheet.append(sheet_columns)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="334D72")
        sheet.freeze_panes = "A2"

        for row in sheet_rows:
            safe_row = []
            for value in row:
                if value is None or isinstance(value, (bool, int)):
                    safe_row.append(value)
                elif isinstance(value, float) and math.isfinite(value):
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
                        "As células devem ser textos curtos, números finitos, vazias ou fórmulas permitidas."
                    )
            sheet.append(safe_row)

        sheet.auto_filter.ref = sheet.dimensions

        if sheet_rows:
            category_column = next(
                (
                    index for index in range(len(sheet_columns))
                    if any(isinstance(row[index], str) and row[index].strip() for row in sheet_rows)
                ),
                None,
            )
            numeric_columns = [
                index for index in range(len(sheet_columns))
                if any(
                    (isinstance(row[index], (int, float)) and not isinstance(row[index], bool))
                    or (
                        isinstance(row[index], dict)
                        and set(row[index]) == {"formula"}
                        and isinstance(row[index]["formula"], str)
                        and _SAFE_FORMULA.fullmatch(row[index]["formula"])
                    )
                    for row in sheet_rows
                )
            ][:3]
            if category_column is not None and numeric_columns:
                chart = BarChart()
                chart.type = "bar"
                chart.style = 10
                chart.title = "Resumo dos dados"
                chart.x_axis.title = "Valores"
                chart.y_axis.title = sheet_columns[category_column]
                for index in numeric_columns:
                    chart.add_data(
                        Reference(
                            sheet,
                            min_col=index + 1,
                            min_row=1,
                            max_row=len(sheet_rows) + 1,
                        ),
                        titles_from_data=True,
                    )
                chart.set_categories(
                    Reference(
                        sheet,
                        min_col=category_column + 1,
                        min_row=2,
                        max_row=len(sheet_rows) + 1,
                    )
                )
                chart.width = 18
                chart.height = 10
                sheet.add_chart(chart, f"{get_column_letter(len(sheet_columns) + 2)}2")
                chart_count += 1

    try:
        with path.open("xb") as file:
            workbook.save(file)
    except FileExistsError as error:
        raise AnalysisError("Já existe uma planilha com esse nome; o arquivo original foi mantido.") from error
    return {
        "filename": path.name,
        "sheets": [name for name, _, _ in normalized_sheets],
        "charts": chart_count,
    }


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
    python_files_checked = 0
    python_files_skipped = 0
    python_bytes_checked = 0
    python_syntax_errors: list[dict[str, Any]] = []
    python_errors_truncated = False

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
                file_size = file_path.stat().st_size
            except OSError:
                continue
            if file_size > MAX_PROJECT_FILE_BYTES:
                continue
            extension = file_path.suffix.lower() or "[sem extensão]"
            extension_counts[extension] += 1
            manifest = MANIFEST_NAMES.get(lower_name)
            if manifest:
                manifests.add(manifest)
            if extension == ".py":
                if python_bytes_checked + file_size > MAX_PROJECT_PYTHON_BYTES:
                    python_files_skipped += 1
                    continue
                python_bytes_checked += file_size
                python_files_checked += 1
                relative_path = file_path.relative_to(root).as_posix()
                try:
                    with tokenize.open(file_path) as source_file:
                        ast.parse(source_file.read(), filename=relative_path)
                except SyntaxError as error:
                    if len(python_syntax_errors) < 100:
                        python_syntax_errors.append({
                            "file": relative_path,
                            "line": error.lineno,
                            "message": error.msg,
                        })
                    else:
                        python_errors_truncated = True
                except (OSError, UnicodeError, ValueError):
                    if len(python_syntax_errors) < 100:
                        python_syntax_errors.append({
                            "file": relative_path,
                            "line": None,
                            "message": "O arquivo Python não pôde ser lido ou decodificado.",
                        })
                    else:
                        python_errors_truncated = True
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
        "pythonFilesChecked": python_files_checked,
        "pythonFilesSkipped": python_files_skipped,
        "pythonSyntaxErrors": python_syntax_errors,
        "pythonSyntaxErrorsTruncated": python_errors_truncated,
        "sensitiveFilesSkipped": skipped_sensitive,
        "contentsSentToModel": False,
        "codeExecuted": False,
    }
