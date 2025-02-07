"""This is the fileops package."""

from pathlib import Path as _Path

__version__ = (_Path(__file__).parent / '_version.txt').read_text()
