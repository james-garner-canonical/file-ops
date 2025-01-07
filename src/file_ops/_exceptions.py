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

    def __str__(self) -> str:
        # manually avoid calling FileNotFoundError.__str__ since we have APIError.args
        return ops.pebble.APIError.__str__(self)

    @classmethod
    def _from_error(cls, error: ops.pebble.APIError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(
            body=error.body,
            code=error.code,
            status=error.status,
            message=error.message,
            file=str(path),
        )

    @classmethod
    def _from_path(cls, path: PurePath | str) -> Self:
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

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return isinstance(error, ops.pebble.APIError) and error.code == 404


class ValueAPIError(ops.pebble.APIError, builtins.ValueError):
    def __init__(self, body: dict[str, object], code: int, status: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.ValueError.__init__(self, message, file)
        ops.pebble.APIError.__init__(self, body=body, code=code, status=status, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.APIError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(
            body=error.body,
            code=error.code,
            status=error.status,
            message=error.message,
            file=str(path),
        )

    @classmethod
    def _from_path(cls, path: PurePath | str, message: str) -> Self:
        code = 400
        status = 'Bad Request'
        body: dict[str, object] = {
            'type': 'error',
            'status-code': code,
            'status': status,
            'result': {'message': message, 'kind': 'generic-file-error'},
        }
        return cls(body=body, code=code, status=status, message=message, file=str(path))

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return isinstance(error, ops.pebble.APIError) and error.code == 400


class FileNotFoundPathError(ops.pebble.PathError, builtins.FileNotFoundError):
    def __init__(self, kind: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.FileNotFoundError.__init__(self, errno.ENOENT, os.strerror(errno.ENOENT), file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(kind=error.kind, message=error.message, file=str(path))

    @classmethod
    def _from_path(cls, path: PurePath | str, method: str) -> Self:
        return cls(
            kind='not-found',
            message=f'{method} {path}: no such file or directory',
            file=str(path),
        )

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return isinstance(error, ops.pebble.PathError) and error.kind == 'not-found'


class FileExistsPathError(ops.pebble.PathError, builtins.FileExistsError):
    def __init__(self, kind: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.FileExistsError.__init__(self, errno.ENOENT, os.strerror(errno.ENOENT), file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(kind=error.kind, message=error.message, file=str(path))

    @classmethod
    def _from_path(cls, path: PurePath | str, method: str) -> Self:
        return cls(
            kind='generic-file-error',
            message=f'{method} {path}: file exists',
            file=str(path),
        )

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return (
            isinstance(error, ops.pebble.PathError)
            and error.kind == 'generic-file-error'
            and 'file exists' in error.message
        )


class LookupPathError(ops.pebble.PathError, builtins.LookupError):
    def __init__(self, kind: str, message: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.LookupError.__init__(self, message)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(kind=error.kind, message=error.message)

    @classmethod
    def _from_exception(
        cls, error: builtins.LookupError | builtins.KeyError, path: PurePath | str, method: str
    ) -> Self:
        return cls(
            kind='generic-file-error',
            message=f'{method} {path}: {error}',
        )

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return (
            isinstance(error, ops.pebble.PathError)
            and error.kind == 'generic-file-error'
            and ('unknown user' in error.message or 'unknown group' in error.message)
        )


class PermissionPathError(ops.pebble.PathError, builtins.PermissionError):
    def __init__(self, kind: str, message: str, error_number: int, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.PermissionError.__init__(self, error_number, os.strerror(error_number), file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(kind=error.kind, message=error.message, error_number=errno.EPERM, file=str(path))

    @classmethod
    def _from_exception(cls, error: builtins.PermissionError | builtins.KeyError, path: PurePath | str, method: str) -> Self:
        error_number = getattr(error, 'errno', None) or errno.EPERM
        return cls(
            kind='permission-denied',
            message=f'{method} {path}: {os.strerror(error_number)}',
            error_number=error_number,
            file=str(path),
        )

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return isinstance(error, ops.pebble.PathError) and error.kind == 'permission-denied'


class RelativePathError(ops.pebble.PathError):
    def __init__(self, kind: str, message: str):
        super().__init__(kind=kind, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(kind=error.kind, message=error.message)

    @classmethod
    def _from_path(cls, path: PurePath | str) -> Self:
        return cls(
            kind='generic-file-error',
            message=f'paths must be absolute, got "{path}"',
        )

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return (
            isinstance(error, ops.pebble.PathError)
            and error.kind == 'generic-file-error'
            and 'paths must be absolute' in error.message
        )


class ValuePathError(ops.pebble.PathError, builtins.ValueError):
    def __init__(self, kind: str, message: str, file: str):
        # both __init__ methods will call Exception.__init__ and set self.args
        # we want to have the pebble.Error version since we're using its repr etc
        builtins.ValueError.__init__(self, message, file)
        ops.pebble.PathError.__init__(self, kind=kind, message=message)

    @classmethod
    def _from_error(cls, error: ops.pebble.PathError, path: PurePath | str) -> Self:
        assert cls._matches(error), f'{cls.__name__} does not match {error!r} {error!s}'
        return cls(kind=error.kind, message=error.message, file=str(path))

    @classmethod
    def _from_path(cls, path: PurePath | str, method: str, message: str) -> Self:
        return cls(
            kind='generic-file-error',
            message=f'{method} {path}: {message}',
            file=str(path),
        )

    @classmethod
    def _matches(cls, error: ops.pebble.Error) -> bool:
        return (
            isinstance(error, ops.pebble.PathError)
            and error.kind == 'generic-file-error'
            and not any(
                e._matches(error)  # pyright: ignore[reportPrivateUsage]
                for e in (FileExistsPathError, LookupPathError, RelativePathError)
            )
        )
