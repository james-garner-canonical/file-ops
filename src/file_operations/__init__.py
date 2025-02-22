from pathlib import Path as _Path
from ._file_operations import FileOperations

__version__ = (_Path(__file__).parent / '_version.txt').read_text()

__all__ = [
    'FileOperations',
]
