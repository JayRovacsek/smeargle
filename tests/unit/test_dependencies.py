import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "smeargle"
DOMAIN = SRC / "domain"
FORBIDDEN_IO = ("httpx", "socket", "subprocess", "urllib", "requests")
FORBIDDEN_THIRD_PARTY = ("pydantic",)


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_domain_imports_nothing_project_internal_pydantic_or_io():
    for path in DOMAIN.glob("*.py"):
        for module in _imported_modules(ast.parse(path.read_text())):
            root = module.split(".")[0]
            assert root not in FORBIDDEN_THIRD_PARTY, f"{path.name} imports {module}"
            assert root not in FORBIDDEN_IO, f"{path.name} imports {module}"
            if module.startswith("smeargle"):
                assert module == "smeargle.domain" or module.startswith("smeargle.domain."), (
                    f"{path.name} imports {module}"
                )
