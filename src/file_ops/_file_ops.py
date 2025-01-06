# pyright: reportPrivateUsage=false

from __future__ import annotations

import datetime
import fnmatch
import grp
import io
import os
import pwd
import shutil
import stat
from contextlib import AbstractContextManager
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Protocol, cast, overload

import ops

from ._exceptions import (
    FileExistsPathError,
    FileNotFoundAPIError,
    FileNotFoundPathError,
    LookupPathError,
    PermissionPathError,
    RelativePathError,
    ValuePathError,
)

if TYPE_CHECKING:
    import types
    from typing import BinaryIO, Callable, Iterable, TextIO, Union


class FileOpsProtocol(Protocol):
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


class FileOps:
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
            try:
                return self._container.list_files(path, pattern=pattern, itself=itself)
            except ops.pebble.APIError as e:
                raise FileNotFoundAPIError._from_error(e, path=path)
        ppath = Path(path)
        if not ppath.exists():
            raise FileNotFoundAPIError._from_path(path)
        if itself or not ppath.is_dir():
            paths = [ppath]
        else:
            paths = ppath.iterdir()
        if pattern is not None:
            paths = [p for p in paths if fnmatch.fnmatch(str(p), pattern)]
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
            try:
                return self._container.make_dir(
                    path,
                    make_parents=make_parents,
                    permissions=permissions,
                    user_id=user_id,
                    user=user,
                    group_id=group_id,
                    group=group,
                )
            except ops.pebble.PathError as e:
                for error in (
                    FileExistsPathError,
                    FileNotFoundPathError,
                    LookupPathError,
                    PermissionPathError,
                    RelativePathError,
                    ValuePathError,
                ):
                    if error._matches(e):
                        raise error._from_error(e, path=path)
                raise
        directory = Path(path)
        if not directory.is_absolute():
            raise RelativePathError._from_path(path=directory)
        with _Chown(
            path=directory,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
            method='mkdir',
            on_error=directory.rmdir,
        ):
            try:
                directory.mkdir(
                    parents=make_parents,
                    mode=permissions if permissions is not None else 0o755,  # Pebble default
                    # https://ops.readthedocs.io/en/latest/reference/pebble.html#ops.pebble.Client.make_dir
                    exist_ok=make_parents,
                )
            except FileExistsError:
                raise FileExistsPathError._from_path(path=path, method='mkdir')
            except FileNotFoundError:
                raise FileNotFoundPathError._from_path(path=path, method='mkdir')
        return
        # raise mismatch errors before creating directory
        try:
            user_arg = _get_user_arg(str_name=user, int_id=user_id)
            group_arg = _get_group_arg(str_name=group, int_id=group_id)
        except KeyError as e:
            raise LookupPathError._from_exception(e, path=path, method='mkdir')
        except ValueError as e:
            raise ValuePathError._from_path(path=path, method='mkdir', message=str(e))
        if user_arg is None and group_arg is not None:
            raise ValuePathError._from_path(
                path=path,
                method='mkdir',
                message='cannot look up user and group: must specify user, not just group',
            )
        if isinstance(user_arg, int) and group_arg is None:
            # TODO: patch pebble so that this isn't an error case
            raise ValuePathError._from_path(
                path=path,
                method='mkdir',
                message='cannot look up user and group: must specify group, not just UID',
            )
        directory = Path(path)
        try:
            directory.mkdir(
                parents=make_parents,
                mode=permissions if permissions is not None else 0o755,  # Pebble default
                # https://ops.readthedocs.io/en/latest/reference/pebble.html#ops.pebble.Client.make_dir
                exist_ok=make_parents,
            )
        except FileExistsError:
            raise FileExistsPathError._from_path(path=path, method='mkdir')
        except FileNotFoundError:
            raise FileNotFoundPathError._from_path(path=path, method='mkdir')
        try:
            _try_chown(directory, user=user_arg, group=group_arg)
        except KeyError as e:
            directory.rmdir()
            raise LookupPathError._from_exception(e, path=path, method='mkdir')
        except PermissionError as e:
            directory.rmdir()
            raise PermissionPathError._from_exception(e, path=path, method='mkdir')

    def push_path(
        self,
        source_path: str | Path | Iterable[str | Path],
        dest_dir: str | PurePath,
    ) -> None:
        raise NotImplementedError()

    def pull_path(
        self,
        source_path: str | PurePath | Iterable[str | PurePath],
        dest_dir: str | Path,
    ) -> None:
        raise NotImplementedError()

    def remove_path(self, path: str | PurePath, *, recursive: bool = False) -> None:
        if self._container is not None:
            try:
                return self._container.remove_path(path, recursive=recursive)
            except ops.pebble.PathError as e:
                for error in (FileNotFoundPathError, RelativePathError, ValuePathError):
                    if error._matches(e):
                        raise error._from_error(e, path=path)
                raise
        ppath = Path(path)
        if not ppath.is_absolute():
            raise RelativePathError._from_path(path=ppath)
        raise NotImplementedError()

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
            try:
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
            except ops.pebble.PathError as e:
                for error in (RelativePathError,):
                    if error._matches(e):
                        raise error._from_error(e, path=path)
                raise

        ppath = Path(path)
        if not ppath.is_absolute():
            raise RelativePathError._from_path(path=ppath)

        source_io: io.StringIO | io.BytesIO | BinaryIO | TextIO
        if isinstance(source, str):
            source_io = io.StringIO(source)
        elif isinstance(source, bytes):
            source_io = io.BytesIO(source)
        else:
            assert not isinstance(source, (bytearray, memoryview))
            source_io = source

        mode = permissions if permissions is not None else 0o644  # Pebble default
        if make_dirs:
            ppath.parent.mkdir(parents=True, exist_ok=True, mode=mode)
            # TODO: check the permissions on the directories pebble creates and ensure we match

        with _Chown(
            path=ppath,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
            method='push',
            on_error=lambda: None,
        ):
            with ppath.open('wb') as f:
                content: Union[str, bytes] = source_io.read(self._chunk_size)
                while content:
                    if isinstance(content, str):
                        content = content.encode(encoding)
                    f.write(content)
                    content = source_io.read(self._chunk_size)
        os.chmod(ppath, mode)
        return

        # TODO: better to do this the other way round?
        # wrap actual str/bytes in appropriate reader class?
        # wrap readers in a reader class that encodes what you read if it's a str?
        # read and write to the file in chunks instead of all at once?
        # but if we have the actual content just write it all at once?
        try:
            source.read  # type: ignore
        except AttributeError:
            source = cast('bytes | str', source)
        else:
            source = cast('BinaryIO | TextIO', source)
            source = source.read()
        if isinstance(source, str):
            source = source.encode(encoding=encoding)
        mode = permissions if permissions is not None else 0o644  # Pebble default
        # https://ops.readthedocs.io/en/latest/reference/pebble.html#ops.pebble.Client.push
        # TODO: does it make sense to apply all the permissions to the directory? probably for read/write, but what about execute?
        if make_dirs:
            ppath.parent.mkdir(parents=True, exist_ok=True, mode=mode)
            # TODO: do we need to chown any directories created?
        #TODO: else: error if not make_dirs and directory doesn't exist?
        ppath.write_bytes(source)
        # TODO: correct and test chown error handling following make_dir
        user_arg = _get_user_arg(str_name=user, int_id=user_id)
        group_arg = _get_group_arg(str_name=group, int_id=group_id)
        _try_chown(ppath, user=user_arg, group=group_arg)
        # TODO: chmod

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
            try:
                return self._container.pull(path, encoding=encoding)
            except ops.pebble.PathError as e:
                for error in(FileNotFoundPathError, PermissionPathError, RelativePathError):
                    if error._matches(e):
                        raise error._from_error(e, path=path)
                raise
        ppath = Path(path)
        if not ppath.is_absolute():
            raise RelativePathError._from_path(path=ppath)
        try:
            f = ppath.open(
                mode='r' if encoding is not None else 'rb',
                encoding=encoding,
                newline='' if encoding is not None else None,
            )
        except PermissionError as e:
            raise PermissionPathError._from_exception(e, path=ppath, method='pull')
        except FileNotFoundError as e:
            raise FileNotFoundPathError._from_path(path=ppath, method='pull')
        return cast('Union[TextIO, BinaryIO]', f)


class _Chown(AbstractContextManager['_Chown', None]):
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
            user_arg = _get_user_arg(str_name=user, int_id=user_id)
            group_arg = _get_group_arg(str_name=group, int_id=group_id)
        except KeyError as e:
            raise LookupPathError._from_exception(e, path=path, method='mkdir')
        except ValueError as e:
            raise ValuePathError._from_path(path=path, method='mkdir', message=str(e))
        if user_arg is None and group_arg is not None:
            raise ValuePathError._from_path(
                path=path,
                method='mkdir',
                message='cannot look up user and group: must specify user, not just group',
            )
        if isinstance(user_arg, int) and group_arg is None:
            # TODO: patch pebble so that this isn't an error case
            raise ValuePathError._from_path(
                path=path,
                method='mkdir',
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
            _try_chown(self.path, user=self.user_arg, group=self.group_arg)
        except KeyError as e:
            self.on_error()
            raise LookupPathError._from_exception(e, path=self.path, method=self.method)
        except PermissionError as e:
            self.on_error()
            raise PermissionPathError._from_exception(e, path=self.path, method=self.method)


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


# type checking
def _type_check(_container: ops.Container):  # pyright: ignore[reportUnusedFunction]
    _f: FileOpsProtocol
    _f = FileOps()
    _f = FileOps(_container)
    _f = _container
