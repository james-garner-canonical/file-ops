from __future__ import annotations

import builtins
import errno
import os
from pathlib import PurePath
from typing import TYPE_CHECKING

import ops
import ops.pebble as pebble

if TYPE_CHECKING:
    from typing_extensions import Self


class APIError:
    class BadRequest:
        @staticmethod
        def from_path(path: PurePath | str, message: str) -> pebble.APIError:
            code = 400
            status = 'Bad Request'
            body: dict[str, object] = {
                'type': 'error',
                'status-code': code,
                'status': status,
                'result': {'message': message, 'kind': 'generic-file-error'},
            }
            return pebble.APIError(body=body, code=code, status=status, message=message)

        @staticmethod
        def matches(error: ops.pebble.Error) -> bool:
            return isinstance(error, ops.pebble.APIError) and error.code == 400

    class FileNotFound:
        @staticmethod
        def from_path(path: PurePath | str) -> pebble.APIError:
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
            return pebble.APIError(body=body, code=code, status=status, message=message)

        @staticmethod
        def matches(error: ops.pebble.Error) -> bool:
            return isinstance(error, ops.pebble.APIError) and error.code == 404


class PathError:
    class FileExists:
        @staticmethod
        def from_path(path: PurePath | str, method: str) -> pebble.PathError:
            return pebble.PathError(kind='generic-file-error', message=f'{method} {path}: file exists')

        @staticmethod
        def matches(error: pebble.Error) -> bool:
            return (
                isinstance(error, pebble.PathError)
                and error.kind == 'generic-file-error'
                and 'file exists' in error.message
            )

    class RelativePath:
        @staticmethod
        def from_path(path: PurePath | str) -> pebble.PathError:
            return pebble.PathError(
                kind='generic-file-error',
                message=f'paths must be absolute, got "{path}"',
            )

        @staticmethod
        def matches(error: ops.pebble.Error) -> bool:
            return (
                isinstance(error, ops.pebble.PathError)
                and error.kind == 'generic-file-error'
                and 'paths must be absolute' in error.message
            )

    class FileNotFound:
        @staticmethod
        def from_path(path: PurePath | str, method: str) -> pebble.PathError:
            return pebble.PathError(
                kind='not-found',
                message=f'{method} {path}: no such file or directory',
            )

        @staticmethod
        def matches(error: ops.pebble.Error) -> bool:
            return isinstance(error, ops.pebble.PathError) and error.kind == 'not-found'

    class Lookup:
        @staticmethod
        def from_exception(
            exception: builtins.LookupError | builtins.KeyError, path: PurePath | str, method: str
        ) -> pebble.PathError:
            # TODO: does anything raise LookupError? We don't catch it in _file_ops currently
            return pebble.PathError(kind='generic-file-error', message=f'{method} {path}: {exception}')

        @staticmethod
        def matches(error: ops.pebble.Error) -> bool:
            return (
                isinstance(error, ops.pebble.PathError)
                and error.kind == 'generic-file-error'
                and (
                    ('unknown user' in error.message or 'unknown group' in error.message)  # from pebble
                    or ('name not found' in error.message)  # from grp/pwd KeyError
                    # TODO: catch KeyError and raise something with a pebble-like message?
                )
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
                e.matches(error)
                for e
                in (PathError.FileExists, PathError.RelativePath, PathError.Lookup)
            )
        )
