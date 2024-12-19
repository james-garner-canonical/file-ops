from pathlib import Path as _Path
from ._file_ops import FileOpsProtocol, FileOps, FileOperationError


__version__ = (_Path(__file__).parent / '_version.txt').read_text()

__all__ = [
    "FileOpsProtocol",
    "FileOps",
    "FileOperationError",
]
