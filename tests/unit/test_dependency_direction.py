import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "smeargle"


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_only_facade_imports_oscal():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "facade.py":
            continue
        for module in _imports(path):
            if module == "oscal" or module.startswith("oscal."):
                offenders.append(f"{path.name} imports {module}")
    assert offenders == []
