from __future__ import annotations

import errno
import os
from pathlib import PurePath

from ops import pebble


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
                'result': {'message': f'{path}: {message}', 'kind': 'generic-file-error'},
            }
            return pebble.APIError(body=body, code=code, status=status, message=message)

        @staticmethod
        def matches(error: pebble.Error) -> bool:
            return isinstance(error, pebble.APIError) and error.code == 400

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
        def matches(error: pebble.Error) -> bool:
            return isinstance(error, pebble.APIError) and error.code == 404


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
        def matches(error: pebble.Error) -> bool:
            return (
                isinstance(error, pebble.PathError)
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
        def matches(error: pebble.Error) -> bool:
            return isinstance(error, pebble.PathError) and error.kind == 'not-found'

    class Lookup:
        @staticmethod
        def from_exception(
            exception: LookupError | KeyError, path: PurePath | str, method: str
        ) -> pebble.PathError:
            # TODO: does anything raise LookupError? We don't catch it in _file_ops currently
            return pebble.PathError(kind='generic-file-error', message=f'{method} {path}: {exception}')

        @staticmethod
        def matches(error: pebble.Error) -> bool:
            return (
                isinstance(error, pebble.PathError)
                and error.kind == 'generic-file-error'
                and (
                    ('unknown user' in error.message or 'unknown group' in error.message)  # from pebble
                    or ('name not found' in error.message)  # from grp/pwd KeyError
                    # TODO: catch KeyError and raise something with a pebble-like message?
                )
            )

    class Permission:
        @staticmethod
        def from_exception(
            exception: PermissionError | KeyError, path: PurePath | str, method: str
        ) -> pebble.PathError:
            error_number = getattr(exception, 'errno', None)
            message = (
                f'[{error_number}, {os.strerror(error_number)}]'
                if error_number is not None
                else ' '.join(map(str, exception.args))
            )
            return pebble.PathError(kind='permission-denied', message=f'{method} {path}: {message}')

        @classmethod
        def matches(cls, error: pebble.Error) -> bool:
            return isinstance(error, pebble.PathError) and error.kind == 'permission-denied'

    class Generic:
        @staticmethod
        def from_path(path: PurePath | str, method: str, message: str) -> pebble.PathError:
            return pebble.PathError(kind='generic-file-error', message=f'{method} {path}: {message}')

        @staticmethod
        def matches(error: pebble.Error) -> bool:
            return (
                isinstance(error, pebble.PathError)
                and error.kind == 'generic-file-error'
                and not any(
                    e.matches(error)
                    for e
                    in (PathError.FileExists, PathError.RelativePath, PathError.Lookup)
                    # these also have kind 'generic-file-error'
                )
            )
