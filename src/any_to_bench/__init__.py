"""any-to-bench: convert any exam materials into a machine-gradable benchmark."""

from importlib.metadata import PackageNotFoundError, version


def tool_version() -> str:
    """The installed package version; the single source of truth for provenance.

    Falls back to "0.0.0+unknown" when running from a tree that was never
    installed, so a manifest never silently claims a wrong release.
    """
    try:
        return version("any-to-bench")
    except PackageNotFoundError:  # pragma: no cover — only outside an install
        return "0.0.0+unknown"


__version__ = tool_version()
