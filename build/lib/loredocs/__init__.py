"""LoreDocs - Knowledge management MCP server for AI projects."""

from importlib.metadata import version as _v, PackageNotFoundError
try:
    __version__ = _v("loredocs")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
