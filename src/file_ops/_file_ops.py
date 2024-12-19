from __future__ import annotations

import datetime
import fnmatch
import functools
import grp
import pwd
import shutil
import stat
from pathlib import Path, PurePath
from typing import BinaryIO, Callable, Iterable, ParamSpec, Protocol, TextIO, TypeVar, cast, overload

import ops


class FileOperationError(Exception):
    def __init__(self, exception: Exception):
        self.exception = exception
        super().__init__(type(exception), *exception.args)


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


P = ParamSpec("P")
T = TypeVar("T")
def wrap_exceptions(*exceptions: type[BaseException]) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorator(fn: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            try:
                return fn(*args, **kwargs)
            except exceptions as e:
                raise FileOperationError(e)
        return wrapper
    return decorator


_EXCEPTIONS = (
    ops.pebble.Error,
    FileNotFoundError,
)


class FileOps:
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

    @wrap_exceptions(ops.pebble.APIError, FileNotFoundError)
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
        if not ppath.exists():
            raise FileNotFoundError(f"{ppath} does not exist")  # pebble raises an APIError
        if itself or not ppath.is_dir():
            paths = [ppath]
        else:
            paths = ppath.iterdir()
        if pattern is not None:
            paths = [p for p in paths if fnmatch.fnmatch(str(p), pattern)]
        return [_path_to_fileinfo(p) for p in paths]

    @wrap_exceptions(ops.pebble.PathError, FileExistsError)
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
        # raise mismatch errors before creating directory
        user_arg = _get_user_arg(user=user, user_id=user_id)
        group_arg = _get_group_arg(group=group, group_id=group_id)
        directory = Path(path)
        directory.mkdir(
            parents=make_parents,
            mode=permissions if permissions is not None else 0o777,  # default mode value for Path.mkdir
            exist_ok=False,  # FileExistsError if exists -- pebble raises a pebble.PathError
        )
        try:
            _try_chown(directory, user_arg=user_arg, group_arg=group_arg)
        except FileOperationError:
            directory.rmdir()
            raise

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
        mode = permissions if permissions is not None else 0o777  # default mode value for Path.mkdir
        # TODO: does it make sense to apply all the permissions to the directory? probably for read/write, but what about execute?
        if make_dirs:
            ppath.parent.mkdir(parents=True, mode=mode)  # TODO: exist_ok behaviour?
            # TODO: do we need to chown any directories created?
        #TODO: else: error if not make_dirs and directory doesn't exist?
        ppath.write_bytes(source)
        _chown(ppath, user=user, user_id=user_id, group=group, group_id=group_id)
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
        raise NotImplementedError()


def _chown(path: Path, user: str | None, user_id: int | None, group: str | None, group_id: int | None) -> None:
    user_arg = _get_user_arg(user=user, user_id=user_id)
    group_arg = _get_group_arg(group=group, group_id=group_id)
    _try_chown(path, user_arg=user_arg, group_arg=group_arg)


@wrap_exceptions(
    KeyError,   # id not found
)
def _get_user_arg(user: str | None, user_id: int | None) -> str | int | None:
    user_arg: str | int | None = None
    if user_id is not None:
        user_arg = user_id
        if user is not None:
            if pwd.getpwuid(user_id).pw_name != user:
                raise FileOperationError(ValueError("If both user_id and user name are provided, they must match.")) # pebble.PathError
    elif user is not None:
        user_arg = user
    return user_arg


@wrap_exceptions(
    KeyError,   # id not found
)
def _get_group_arg(group: str | None, group_id: int | None) -> str | int | None:
    group_arg: str | int | None = None
    if group_id is not None:
        group_arg = group_id
        if group is not None:
            if grp.getgrgid(group_id).gr_name != group:
                raise FileOperationError(ValueError("If both groupd_id and groupd name are provided, they must match.")) # pebble.PathError
    elif group is not None:
        group_arg = group
    return group_arg


@wrap_exceptions(
    PermissionError,  # e.g. unprivileged user trying to chown as root, user/group doesn't exist
)
def _try_chown(path: Path | str, user_arg: int | str | None, group_arg: int | str | None) -> None:
    # chown -- pebble.PathError for permission denied
    if user_arg is not None and group_arg is not None:
        shutil.chown(path, user=user_arg, group=group_arg)
    elif user_arg is not None:
        shutil.chown(path, user=user_arg)
    elif group_arg is not None:
        shutil.chown(path, group=group_arg)


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
