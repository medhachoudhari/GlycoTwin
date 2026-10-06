"""Guards against dependency drift: every third-party import must be declared in both
pyproject.toml and requirements.txt (a fresh `pip install -e .` must run the code)."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT_TO_DIST = {"sklearn": "scikit-learn"}
STDLIB = set(sys.stdlib_module_names)


def _third_party_imports():
    found = set()
    for path in [*ROOT.glob("src/**/*.py"), *ROOT.glob("scripts/*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            found |= {n for n in names if n not in STDLIB and n != "glycotwin"}
    return {IMPORT_TO_DIST.get(n, n) for n in found}


def _declared(text):
    return {m.group(1).lower() for m in re.finditer(r'^\s*"?([A-Za-z][A-Za-z0-9_.-]*)\s*(?:[<>=!~]|"|,|$)', text, re.M)}


def test_every_third_party_import_is_declared_in_pyproject_and_requirements():
    needed = _third_party_imports()
    assert {"pandas", "numpy", "scipy", "scikit-learn", "xgboost"} <= needed     # sanity: scan found the real imports
    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps_block = py[py.index("dependencies = ["): py.index("]", py.index("dependencies = ["))]
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert needed <= _declared(deps_block), needed - _declared(deps_block)
    assert needed <= _declared(req), needed - _declared(req)
    assert "pytest" in _declared(req)


def test_no_backend_or_frontend_dependency_is_declared_before_its_phase():
    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert not any(x in py for x in ("fastapi", "sqlalchemy", "pydantic"))
