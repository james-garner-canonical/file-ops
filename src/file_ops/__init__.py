from pathlib import Path as _Path
from ._file_ops import FileOpsProtocol, FileOps

from ._exceptions import (
    FileExistsPathError,
    FileNotFoundAPIError,
    FileNotFoundPathError,
    LookupPathError,
    PermissionPathError,
    RelativePathError,
    ValuePathError,
)

__version__ = (_Path(__file__).parent / '_version.txt').read_text()

__all__ = [
    'FileOpsProtocol',
    'FileOps',
    'FileNotFoundAPIError',
    'FileNotFoundPathError',
    'FileExistsPathError',
    'LookupPathError',
    'PermissionPathError',
    'RelativePathError',
    'ValuePathError',
]
