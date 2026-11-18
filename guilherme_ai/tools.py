import ast
import math
import operator
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


class ToolError(ValueError):
    """Raised for invalid or unsafe tool input."""


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
    return datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")


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
