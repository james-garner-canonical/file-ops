from pathlib import Path as _Path
from ._file_ops import FileOperationsProtocol, FileOperations

from ._exceptions import (
    FileExistsPathError,
    FileNotFoundPathError,
    LookupPathError,
    PermissionPathError,
    RelativePathError,
    ValueAPIError,
    ValuePathError,
)

__version__ = (_Path(__file__).parent / '_version.txt').read_text()

__all__ = [
    'FileOperationsProtocol',
    'FileOperations',
    'FileNotFoundPathError',
    'FileExistsPathError',
    'LookupPathError',
    'PermissionPathError',
    'RelativePathError',
    'ValueAPIError',
    'ValuePathError',
]
