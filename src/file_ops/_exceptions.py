from __future__ import annotations

import builtins
import errno
import os
from pathlib import PurePath
from typing import TYPE_CHECKING

import ops

if TYPE_CHECKING:
    from typing_extensions import Self


class FileNotFoundAPIError(ops.pebble.APIError, builtins.FileNotFoundError):
    def __init__(self, body: dict[str, object], code: int, status: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.FileNotFoundError.__init__(self, errno.ENOENT, os.strerror(errno.ENOENT), file)
        ops.pebble.APIError.__init__(self, body=body, code=code, status=status, message=message)

    @classmethod
    def from_error(cls, error: ops.pebble.APIError, path: PurePath | str) -> Self:
        assert error.code == 404
        return cls(
            body=error.body,
            code=error.code,
            status=error.status,
            message=error.message,
            file=str(path),
        )

    @classmethod
    def from_path(cls, path: PurePath | str) -> Self:
        method = 'stat'
        code = 404
        status = 'Not Found'
        message = f'{method} {path}: no such file or directory'
        body: dict[str, object] = {
            'type': 'error',
            'status-code': code,
            'status': status,
            'result': {'message': message, 'kind': 'not-found'},
        }
        return cls(body=body, code=code, status=status, message=message, file=str(path))


class FileNotFoundPathError(ops.pebble.PathError, builtins.FileNotFoundError):
    def __init__(self, kind: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.FileNotFoundError.__init__(self, errno.ENOENT, os.strerror(errno.ENOENT), file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls.matches(error)
        return cls(kind=error.kind, message=error.message, file=str(path))

    @classmethod
    def from_path(cls, path: PurePath | str, method: str) -> Self:
        return cls(
            kind='not-found',
            message=f'{method} {path}: no such file or directory',
            file=str(path),
        )

    @classmethod
    def matches(cls, error: ops.pebble.PathError) -> bool:
        return error.kind == 'not-found'


class FileExistsPathError(ops.pebble.PathError, builtins.FileExistsError):
    def __init__(self, kind: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.FileExistsError.__init__(self, errno.ENOENT, os.strerror(errno.ENOENT), file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls.matches(error)
        return cls(kind=error.kind, message=error.message, file=str(path))

    @classmethod
    def from_path(cls, path: PurePath | str, method: str) -> Self:
        return cls(
            kind='generic-file-error',
            message=f'{method} {path}: file exists',
            file=str(path),
        )

    @classmethod
    def matches(cls, error: ops.pebble.PathError) -> bool:
        return error.kind == 'generic-file-error' and 'file exists' in error.message


class PermissionPathError(ops.pebble.PathError, builtins.PermissionError):
    def __init__(self, kind: str, message: str, error_number: int, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.PermissionError.__init__(self, error_number, os.strerror(error_number), file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls.matches(error)
        return cls(kind=error.kind, message=error.message, error_number=errno.EPERM, file=str(path))

    @classmethod
    def from_exception(cls, error: builtins.PermissionError | builtins.KeyError, path: PurePath | str, method: str) -> Self:
        error_number = getattr(error, 'errno', None) or errno.EPERM
        return cls(
            kind='permission-error',
            message=f'{method} {path}: {os.strerror(error_number)}',
            error_number=error_number,
            file=str(path),
        )

    @classmethod
    def matches(cls, error: ops.pebble.PathError) -> bool:
        return error.kind == 'permission-denied'


class ValuePathError(ops.pebble.PathError, builtins.ValueError):
    def __init__(self, kind: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.ValueError.__init__(self, message, file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls.matches(error)
        return cls(kind=error.kind, message=error.message, file=str(path))

    @classmethod
    def matches(cls, error: ops.pebble.PathError) -> bool:
        return error.kind == 'generic-file-error' and not FileExistsPathError.matches(error)
