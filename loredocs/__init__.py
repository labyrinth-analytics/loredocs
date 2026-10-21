"""LoreDocs - Knowledge management MCP server for AI projects."""

from importlib.metadata import version as _v, PackageNotFoundError
from pathlib import Path

def _get_version():
    """Get version from pyproject.toml when available, fallback to importlib.metadata."""
    try:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            import tomllib
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)
                if "project" in data and "version" in data["project"]:
                    return data["project"]["version"]
    except Exception:
        pass

    try:
        return _v("loredocs")
    except PackageNotFoundError:
        return "0.0.0-dev"

__version__ = _get_version()
