from __future__ import annotations

import datetime
import fnmatch
import grp
import io
import os
import pwd
import re
import shutil
import stat
import types
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path, PurePath
from typing import BinaryIO, Callable, Iterable, Iterator, Protocol, TextIO, Union, cast, overload

import ops

from . import _errors


class _FileOperationsProtocol(Protocol):
    def exists(self, path: str | PurePath) -> bool:
        ...

    def isdir(self, path: str | PurePath) -> bool:
        ...

    def list_files(
        self,
        path: str | PurePath,
        *,
        pattern: str | None = None,
        itself: bool = False,
    ) -> list[ops.pebble.FileInfo]:
        ...

    def make_dir(
        self,
        path: str | PurePath,
        *,
        make_parents: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ) -> None:
        ...

    def push_path(
        self,
        source_path: str | Path | Iterable[str | Path],
        dest_dir: str | PurePath,
    ) -> None:
        ...

    def pull_path(
        self,
        source_path: str | PurePath | Iterable[str | PurePath],
        dest_dir: str | Path,
    ) -> None:
        ...

    def remove_path(self, path: str | PurePath, *, recursive: bool = False) -> None:
        ...

    def push(
        self,
        path: str | PurePath,
        source: bytes | str | BinaryIO | TextIO,
        *,
        encoding: str = 'utf-8',
        make_dirs: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ) -> None:
        ...

    @overload
    def pull(self, path: str | PurePath, *, encoding: None) -> BinaryIO:
        ...
    @overload
    def pull(self, path: str | PurePath, *, encoding: str = 'utf-8') -> TextIO:
        ...
    def pull(
        self,
        path: str | PurePath,
        *,
        encoding: str | None = 'utf-8',
    ) -> BinaryIO | TextIO:
        ...


class FileOperations:
    _chunk_size = io.DEFAULT_BUFFER_SIZE
    # 8192 on my machine, which ops.pebble.Client._chunk_size hard codes

    def __init__(self, container: ops.Container | None = None) -> None:
        self._container = container

    def exists(self, path: str | PurePath) -> bool:
        if self._container is not None:
            return self._container.exists(path)
        return Path(path).exists()

    def isdir(self, path: str | PurePath) -> bool:
        if self._container is not None:
            return self._container.isdir(path)
        return Path(path).is_dir()

    def list_files(
        self,
        path: str | PurePath,
        *,
        pattern: str | None = None,
        itself: bool = False,
    ) -> list[ops.pebble.FileInfo]:
        if self._container is not None:
            return self._container.list_files(path, pattern=pattern, itself=itself)
        ppath = Path(path)
        if not ppath.is_absolute():
            raise _errors.PathError.RelativePath.from_path(path)
        if not ppath.exists():
            raise _errors.APIError.FileNotFound.from_path(path)
        if itself or not ppath.is_dir():
            paths = [ppath]
        else:
            paths = list(ppath.iterdir())
        if paths and pattern is not None:
            # validate pattern, but only if there are paths
            # TODO: look at how pebble validates the pattern and ensure we match
            try:
                re.compile(pattern.replace('*', '.*').replace('?', '.?'))
                # catch mismatched brackets etc
            except re.error:
                raise _errors.APIError.BadRequest.from_path(
                    path=path, message=f'syntax error in pattern "{pattern}"'
                )
            paths = [p for p in paths if fnmatch.fnmatch(str(p.name), pattern)]
        return [_path_to_fileinfo(p) for p in paths]

    def make_dir(
        self,
        path: str | PurePath,
        *,
        make_parents: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ) -> None:
        if self._container is not None:
            return self._container.make_dir(
                path,
                make_parents=make_parents,
                permissions=permissions,
                user_id=user_id,
                user=user,
                group_id=group_id,
                group=group,
            )
        directory = Path(path)
        if not directory.is_absolute():
            raise _errors.PathError.RelativePath.from_path(path=directory)
        _make_dir(
            path=directory,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
            make_parents=make_parents,
            mode=permissions if permissions is not None else 0o755,
        )

    def push_path(
        self,
        source_path: str | Path | Iterable[str | Path],
        dest_dir: str | PurePath,
    ) -> None:
        # TODO: tests and errors
        if self._container is not None:
            self._container.push_path(source_path=source_path, dest_dir=dest_dir)
        if hasattr(source_path, '__iter__') and not isinstance(source_path, str):
            source_paths = cast(Iterable[Union[str, Path]], source_path)
        else:
            source_paths = cast(Iterable[Union[str, Path]], [source_path])
        source_paths = [Path(p) for p in source_paths]
        dest_dir = Path(dest_dir)
        if not dest_dir.is_absolute():
            raise _errors.PathError.RelativePath.from_path(path=dest_dir)
        errors: list[tuple[str, Exception]] = []
        for path in source_paths:
            try:
                _copy(source=path, dest=dest_dir)
            except (OSError, ops.pebble.Error) as e:
                errors.append((str(path), e))
        if errors:
            raise ops.model.MultiPushPullError('failed to push one or more files', errors)

    def pull_path(
        self,
        source_path: str | PurePath | Iterable[str | PurePath],
        dest_dir: str | Path,
    ) -> None:
        # TODO: tests and errors
        if self._container is not None:
            self._container.pull_path(source_path=source_path, dest_dir=dest_dir)
        if hasattr(source_path, '__iter__') and not isinstance(source_path, str):
            source_paths = cast(Iterable[Union[str, Path]], source_path)
        else:
            source_paths = cast(Iterable[Union[str, Path]], [source_path])
        source_paths = [Path(p) for p in source_paths]
        dest_dir = Path(dest_dir)
        errors: list[tuple[str, Exception]] = []
        for path in source_paths:
            try:
                if not path.is_absolute():
                    raise _errors.PathError.RelativePath.from_path(path=path)
                _copy(source=path, dest=dest_dir)
            except (OSError, ops.pebble.Error) as e:
                errors.append((str(path), e))
        if errors:
            raise ops.model.MultiPushPullError('failed to pull one or more files', errors)

    def remove_path(self, path: str | PurePath, *, recursive: bool = False) -> None:
        if self._container is not None:
            return self._container.remove_path(path, recursive=recursive)
        ppath = Path(path)
        if not ppath.is_absolute():
            raise _errors.PathError.RelativePath.from_path(path=ppath)
        if not ppath.exists():
            raise _errors.PathError.FileNotFound.from_path(path=ppath, method='remove')
        _try_remove(ppath, recursive=recursive)

    def push(
        self,
        path: str | PurePath,
        source: bytes | str | BinaryIO | TextIO,
        *,
        encoding: str = 'utf-8',
        make_dirs: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ) -> None:
        if self._container is not None:
            return self._container.push(
                path=path,
                source=source,
                encoding=encoding,
                make_dirs=make_dirs,
                permissions=permissions,
                user_id=user_id,
                user=user,
                group_id=group_id,
                group=group,
            )
        ppath = Path(path)
        if not ppath.is_absolute():
            raise _errors.PathError.RelativePath.from_path(path=ppath)

        source_io: io.StringIO | io.BytesIO | BinaryIO | TextIO
        if isinstance(source, str):
            source_io = io.StringIO(source)
        elif isinstance(source, bytes):
            source_io = io.BytesIO(source)
        else:
            assert not isinstance(source, (bytearray, memoryview))
            source_io = source

        if make_dirs:
            # TODO: catch error here or make _make_dir raise the correct error internally
            _make_dir(
                ppath.parent,
                user=user,
                user_id=user_id,
                group=group,
                group_id=group_id,
                make_parents=True,
                mode=0o755,  # following pebble
            )

        with _ChownContext(
            path=ppath,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
            method='push',
            on_error=lambda: None,  # TODO: delete file on error? what about created directories? check pebble behaviour
        ):
            try:
                ppath.touch(mode=0o600)  # rw permissions to allow us to write the file
            except FileNotFoundError:
                raise _errors.PathError.FileNotFound.from_path(path, method='open')
            _write_chunked(path=ppath, source_io=source_io, chunk_size=self._chunk_size, encoding=encoding)
        os.chmod(ppath, mode=permissions if permissions is not None else 0o644)  # Pebble default

    @overload
    def pull(self, path: str | PurePath, *, encoding: None) -> BinaryIO:
        ...
    @overload
    def pull(self, path: str | PurePath, *, encoding: str = 'utf-8') -> TextIO:
        ...
    def pull(
        self,
        path: str | PurePath,
        *,
        encoding: str | None = 'utf-8',
    ) -> BinaryIO | TextIO:
        if self._container is not None:
            return self._container.pull(path, encoding=encoding)
        ppath = Path(path)
        if not ppath.is_absolute():
            raise _errors.PathError.RelativePath.from_path(path=ppath)
        try:
            f = ppath.open(
                mode='r' if encoding is not None else 'rb',
                encoding=encoding,
                newline='' if encoding is not None else None,
            )
        except PermissionError as e:
            raise _errors.PathError.Permission.from_exception(e, path=ppath, method='open')
        except FileNotFoundError as e:
            raise _errors.PathError.FileNotFound.from_path(path=ppath, method='stat')
        return cast('Union[TextIO, BinaryIO]', f)


class _ChownContext(AbstractContextManager['_ChownContext', None]):
    """Perform some user/group validation on init, and the rest+chown on exit.

    Matches pebble's order of operations so that the outcomes and errors are the same.
    """
    def __init__(
        self,
        path: Path,
        user: str | None,
        user_id: int | None,
        group: str | None,
        group_id: int | None,
        method: str,
        on_error: Callable[[], None],
    ):
        try:
            user_arg = self._get_user_arg(str_name=user, int_id=user_id)
            group_arg = self._get_group_arg(str_name=group, int_id=group_id)
        except KeyError as e:
            raise _errors.PathError.Lookup.from_exception(e, path=path, method=method)
        except ValueError as e:
            raise _errors.PathError.Generic.from_path(path=path, method=method, message=str(e))
        if user_arg is None and group_arg is not None:
            raise _errors.PathError.Generic.from_path(
                path=path,
                method=method,
                message='cannot look up user and group: must specify user, not just group',
            )
        if isinstance(user_arg, int) and group_arg is None:
            # TODO: patch pebble so that this isn't an error case
            raise _errors.PathError.Generic.from_path(
                path=path,
                method=method,
                message='cannot look up user and group: must specify group, not just UID',
            )
        self.path = path
        self.user_arg = user_arg
        self.group_arg = group_arg
        self.method = method
        self.on_error = on_error

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        if exc_type is not None:
            return
        try:
            self._try_chown(self.path, user=self.user_arg, group=self.group_arg)
        except KeyError as e:
            self.on_error()
            raise _errors.PathError.Lookup.from_exception(e, path=self.path, method=self.method)
        except PermissionError as e:
            self.on_error()
            raise _errors.PathError.Permission.from_exception(e, path=self.path, method=self.method)

    @staticmethod
    def _get_user_arg(str_name: str | None, int_id: int | None) -> str | int | None:
        if str_name is not None:
            if int_id is not None:
                info = pwd.getpwnam(str_name)  # KeyError if user doesn't exist
                info_id = info.pw_uid
                if info_id != int_id:
                    raise ValueError(
                        'If both user_id and user name are provided, they must match'
                        f' -- "{str_name}" has id {info_id} but {int_id} was provided.'
                    )
            return str_name
        if int_id is not None:
            return int_id
        return None

    @staticmethod
    def _get_group_arg(str_name: str | None, int_id: int | None) -> str | int | None:
        if str_name is not None:
            if int_id is not None:
                info = grp.getgrnam(str_name)  # KeyError if group doesn't exist
                info_id = info.gr_gid
                if info_id != int_id:
                    raise ValueError(
                        'If both group_id and group name are provided, they must match'
                        f' -- "{str_name}" has id {info_id} but {int_id} was provided.'
                    )
            return str_name
        if int_id is not None:
            return int_id
        return None

    @staticmethod
    def _try_chown(path: Path | str, user: int | str | None, group: int | str | None) -> None:
        # KeyError for user/group that doesn't exist, as pebble looks these up
        if isinstance(user, str):
            pwd.getpwnam(user)
        if isinstance(group, str):
            grp.getgrnam(group)
        # PermissionError for user_id/group_id that doesn't exist, as pebble tries to use these
        if isinstance(user, int):
            try:
                pwd.getpwuid(user)
            except KeyError as e:
                raise PermissionError(e)
        if isinstance(group, int):
            try:
                grp.getgrgid(group)
            except KeyError as e:
                raise PermissionError(e)
        # PermissionError for e.g. unprivileged user trying to chown as root
        if user is not None and group is not None:
            shutil.chown(path, user=user, group=group)
        elif user is not None:
            shutil.chown(path, user=user)
        elif group is not None:
            shutil.chown(path, group=group)


def _path_to_fileinfo(path: Path) -> ops.pebble.FileInfo:
    stat_result = path.lstat()  # lstat because pebble doesn't follow symlinks
    utcoffset = datetime.datetime.now().astimezone().utcoffset()
    timezone = datetime.timezone(utcoffset) if utcoffset is not None else datetime.timezone.utc
    filetype = _FT_MAP.get(stat.S_IFMT(stat_result.st_mode), ops.pebble.FileType.UNKNOWN)
    size = stat_result.st_size if filetype is ops.pebble.FileType.FILE else None
    return ops.pebble.FileInfo(
        path=str(path),
        name=path.name,
        type=filetype,
        size=size,
        permissions=stat.S_IMODE(stat_result.st_mode),
        last_modified=datetime.datetime.fromtimestamp(int(stat_result.st_mtime), tz=timezone),
        user_id=stat_result.st_uid,
        user=pwd.getpwuid(stat_result.st_uid).pw_name,
        group_id=stat_result.st_gid,
        group=grp.getgrgid(stat_result.st_gid).gr_name,
    )


_FT_MAP: dict[int, ops.pebble.FileType] = {
    stat.S_IFREG: ops.pebble.FileType.FILE,
    stat.S_IFDIR: ops.pebble.FileType.DIRECTORY,
    stat.S_IFLNK: ops.pebble.FileType.SYMLINK,
    stat.S_IFSOCK: ops.pebble.FileType.SOCKET,
    stat.S_IFIFO: ops.pebble.FileType.NAMED_PIPE,
    stat.S_IFBLK: ops.pebble.FileType.DEVICE,  # block device
    stat.S_IFCHR: ops.pebble.FileType.DEVICE,  # character device
}


def _make_dir(
    path: Path,
    user: str | None,
    user_id: int | None,
    group: str | None,
    group_id: int | None,
    make_parents: bool,
    mode: int,
):
    """As pathlib.Path.mkdir, but handles chown and propagates mode to parents."""
    with _ChownContext(
        path=path,
        user=user,
        user_id=user_id,
        group=group,
        group_id=group_id,
        method='mkdir',
        on_error=path.rmdir,
    ):
        try:
            os.mkdir(path)
            os.chmod(path, mode)  # separate chmod to bypass umask
        except FileNotFoundError:
            if not make_parents or path.parent == path:
                raise _errors.PathError.FileNotFound.from_path(path=path, method='mkdir')
            _make_dir(
                path.parent,
                user=user,
                user_id=user_id,
                group=group,
                group_id=group_id,
                make_parents=True,
                mode=mode,
            )
            try:
                os.mkdir(path)
                os.chmod(path, mode)
            except PermissionError as e:
                raise _errors.PathError.Permission.from_exception(e, path=path, method='mkdir')
            # PermissionError if we can't read the parent directory, following pebble
            if not os.access(path.parent, os.R_OK):
                raise _errors.PathError.Permission.from_exception(
                    PermissionError(f'cannot read: {path.parent} (created via make_parents/make_dirs)'),
                    path=path,
                    method='mkdir',
                )
        except PermissionError as e:
            raise _errors.PathError.Permission.from_exception(e, path=path, method='mkdir')
        except OSError:
            # FileExistsError -- following pathlib.Path.mkdir:
            # Cannot rely on checking for EEXIST, since the operating system
            # could give priority to other errors like EACCES or EROFS
            if not make_parents:
                raise _errors.PathError.FileExists.from_path(path=path, method='mkdir')


def _try_remove(path: Path, recursive: bool) -> None:
    if not path.is_dir():
        path.unlink()
        return
    try:
        path.rmdir()
    except OSError as e:
        assert e.errno == 39  # Directory not empty
        if not recursive:
            raise  # TODO: OSPathError? DirectoryNotEmptyError?
        for p in path.iterdir():
            _try_remove(p, recursive=True)


def _write_chunked(path: Path, source_io: BinaryIO | TextIO, chunk_size: int, encoding: str) -> None:
    with path.open('wb') as f:
        content: Union[str, bytes] = source_io.read(chunk_size)
        while content:
            if isinstance(content, str):
                content = content.encode(encoding)
            f.write(content)
            content = source_io.read(chunk_size)


def _copy(source: Path, dest: Path):
    assert dest.is_dir()
    if source.is_dir():
        shutil.copytree(src=source, dst=dest)
    else:
        shutil.copy2(src=source, dst=dest)


# type checking
def _type_check(_container: ops.Container):  # pyright: ignore[reportUnusedFunction]
    _f: _FileOperationsProtocol
    _f = FileOperations()
    _f = FileOperations(_container)
    _f = _container
