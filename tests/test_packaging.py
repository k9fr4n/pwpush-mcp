"""Guards on pyproject dependency bounds and source-file conventions."""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    tomllib = None  # type: ignore[assignment]

ROOT = Path(__file__).parent.parent
PYPROJECT = ROOT / "pyproject.toml"
SRC_DIR = ROOT / "src" / "pwpush_mcp"


def _dependencies(text: str) -> list[str]:
    if tomllib is not None:
        return list(tomllib.loads(text).get("project", {}).get("dependencies", []))
    m = re.search(r"dependencies\s*=\s*\[(.*?)\n\]", text, re.DOTALL)
    assert m
    entries = []
    for line in m.group(1).splitlines():
        line = re.sub(r"\s*#.*$", "", line).strip().rstrip(",").strip()
        if (line.startswith('"') and line.endswith('"')) or (
            line.startswith("'") and line.endswith("'")
        ):
            entries.append(line[1:-1])
    return entries


def _find(deps, prefix):
    return next((d for d in deps if d.lower().startswith(prefix.lower())), None)


class TestDependencyBounds:
    def setup_method(self):
        self.deps = _dependencies(PYPROJECT.read_text(encoding="utf-8"))

    def test_mcp_bounds(self):
        dep = _find(self.deps, "mcp")
        assert dep is not None, "mcp dependency missing"
        assert "<2.0" in dep or "<2" in dep, f"mcp needs an upper bound: {dep}"
        assert ">=1.2" in dep, f"mcp lost its lower bound: {dep}"

    def test_httpx_bounds(self):
        dep = _find(self.deps, "httpx")
        assert dep is not None, "httpx dependency missing"
        assert "<1.0" in dep or "<1" in dep, f"httpx needs an upper bound: {dep}"
        assert ">=0.27" in dep, f"httpx lost its lower bound: {dep}"

    def test_no_fastmcp_dependency(self):
        # The server now uses the low-level MCP SDK; fastmcp must be gone.
        assert _find(self.deps, "fastmcp") is None


class TestFutureAnnotations:
    def test_all_source_files_have_future_annotations(self):
        missing = [
            p.name
            for p in sorted(SRC_DIR.glob("*.py"))
            if "from __future__ import annotations" not in p.read_text(encoding="utf-8")
        ]
        assert not missing, f"missing `from __future__ import annotations`: {missing}"
