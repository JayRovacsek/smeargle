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
                yield alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module or "", node.level


def test_domain_imports_nothing_project_internal_pydantic_or_io():
    paths = list(DOMAIN.rglob("*.py"))
    assert paths, f"no domain modules found under {DOMAIN}"
    for path in paths:
        for module, level in _imported_modules(ast.parse(path.read_text())):
            if level:
                assert level == 1, f"{path.name} imports {module} (relative level {level})"
                continue
            root = module.split(".")[0]
            assert root not in FORBIDDEN_THIRD_PARTY, f"{path.name} imports {module}"
            assert root not in FORBIDDEN_IO, f"{path.name} imports {module}"
            if module.startswith("smeargle"):
                assert module == "smeargle.domain" or module.startswith("smeargle.domain."), (
                    f"{path.name} imports {module}"
                )
