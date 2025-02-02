from pathlib import Path as _Path
from ._containerlike import FileOperations

__version__ = (_Path(__file__).parent / '_version.txt').read_text()

__all__ = [
    'FileOperations',
]
