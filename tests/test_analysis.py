import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from guilherme_ai import analysis
from guilherme_ai.analysis import AnalysisError


class AnalysisTests(unittest.TestCase):
    def test_project_inventory_skips_dependencies_and_secret_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sample"
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "src").mkdir()
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "src" / "main.py").write_text("print('not read')", encoding="utf-8")
            (root / ".env").write_text("SECRET=hidden", encoding="utf-8")
            (root / "node_modules" / "pkg" / "index.js").write_text("", encoding="utf-8")

            result = analysis.analyze_project(str(root))

            self.assertEqual(result["filesAnalyzed"], 2)
            self.assertEqual(result["technologies"], ["Node.js"])
            self.assertEqual(result["extensions"], {".py": 1, ".json": 1})
            self.assertEqual(result["pythonFilesChecked"], 1)
            self.assertEqual(result["pythonSyntaxErrors"], [])
            self.assertEqual(result["sensitiveFilesSkipped"], 1)
            self.assertFalse(result["contentsSentToModel"])
            self.assertFalse(result["codeExecuted"])

    def test_project_analysis_reports_python_syntax_without_executing_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "sample"
            root.mkdir()
            (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            (root / "safe.py").write_text(
                "raise RuntimeError('this code must not run')\n",
                encoding="utf-8",
            )

            result = analysis.analyze_project(str(root))

            self.assertEqual(result["pythonFilesChecked"], 2)
            self.assertEqual(
                result["pythonSyntaxErrors"],
                [{"file": "broken.py", "line": 1, "message": "invalid syntax"}],
            )
            self.assertFalse(result["codeExecuted"])

    def test_project_analysis_rejects_non_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            file_path = Path(temporary) / "file.txt"
            file_path.write_text("text", encoding="utf-8")
            with self.assertRaises(AnalysisError):
                analysis.analyze_project(str(file_path))

    def test_csv_summary_reports_missing_values_and_duplicates(self):
        if importlib.util.find_spec("pandas") is None:
            self.skipTest("pandas é uma dependência do requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "report.csv").write_text(
                "name,value\nA,2\nA,2\nB,\n",
                encoding="utf-8",
            )
            with patch.object(analysis, "SPREADSHEET_DIR", directory):
                result = analysis.analyze_spreadsheet("report.csv")

        summary = result["sheets"][0]
        self.assertEqual(summary["rows"], 3)
        self.assertEqual(summary["duplicateRows"], 1)
        self.assertEqual(summary["missingByColumn"], {"value": 1})

    def test_created_workbook_is_not_overwritten_and_text_is_not_a_formula(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl é uma dependência do requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(analysis, "SPREADSHEET_DIR", directory):
                result = analysis.create_spreadsheet(
                    "safe.xlsx",
                    ["name", "value"],
                    [["=1+1", {"formula": "=SUM(B2:B8)"}]],
                )
                with self.assertRaises(AnalysisError):
                    analysis.create_spreadsheet("safe.xlsx", ["name"], [["replacement"]])
            workbook = openpyxl.load_workbook(directory / result["filename"], data_only=False)
            self.assertEqual(workbook.active["A2"].value, "'=1+1")
            self.assertEqual(workbook.active["B2"].value, "=SUM(B2:B8)")
            self.assertEqual(workbook.active.freeze_panes, "A2")
            self.assertEqual(workbook.active.auto_filter.ref, "A1:B2")
            self.assertEqual(result["sheets"], ["Dados"])
            self.assertEqual(result["charts"], 1)
            self.assertEqual(len(workbook.active._charts), 1)
            workbook.close()

    def test_created_workbook_supports_multiple_sheets_and_only_charts_categorical_data(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl é uma dependência do requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(analysis, "SPREADSHEET_DIR", directory):
                result = analysis.create_spreadsheet(
                    "multiple.xlsx",
                    sheets=[
                        {
                            "name": "Vendas",
                            "columns": ["Produto", "Valor"],
                            "rows": [["A", 10], ["B", 20]],
                        },
                        {
                            "name": "Observações",
                            "columns": ["Texto"],
                            "rows": [["Sem valores numéricos"]],
                        },
                    ],
                )
            workbook = openpyxl.load_workbook(directory / result["filename"])
            self.assertEqual(workbook.sheetnames, ["Vendas", "Observações"])
            self.assertEqual(len(workbook["Vendas"]._charts), 1)
            self.assertEqual(len(workbook["Observações"]._charts), 0)
            self.assertEqual(result["charts"], 1)
            workbook.close()

    def test_created_workbook_rejects_duplicate_sheet_names(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl é uma dependência do requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(analysis, "SPREADSHEET_DIR", Path(temporary)):
                with self.assertRaisesRegex(AnalysisError, "não podem se repetir"):
                    analysis.create_spreadsheet(
                        "duplicate.xlsx",
                        sheets=[
                            {"name": "Dados", "columns": ["a"], "rows": []},
                            {"name": "dados", "columns": ["b"], "rows": []},
                        ],
                    )

    def test_created_workbook_rejects_external_formula_functions(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("openpyxl é uma dependência do requirements.txt.")
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(analysis, "SPREADSHEET_DIR", Path(temporary)):
                with self.assertRaises(AnalysisError):
                    analysis.create_spreadsheet(
                        "unsafe.xlsx",
                        ["value"],
                        [[{"formula": '=HYPERLINK("https://example.com","click")'}]],
                    )


if __name__ == "__main__":
    unittest.main()
