from __future__ import annotations

import grp
import pwd
import shutil
from pathlib import Path, PurePath
from typing import BinaryIO, Iterable, Protocol, TextIO, overload

import ops


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
        if ppath.is_dir():
            if pattern is not None:
                paths = ppath.glob(pattern)
            else:
                paths = ppath.iterdir()
        else:
            if pattern is not None:
                raise Exception()
            if not ppath.exists():
                raise Exception()
            paths = [ppath]
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
        ppath = Path(path)
        mode = permissions if permissions is not None else 0o777  # default mode value for Path.mkdir
        ppath.mkdir(parents=make_parents, mode=mode, exist_ok=False)  # pathlib.PathError / pebble.PathError if exists
        # user_arg
        user_arg: str | int | None = None
        if user_id is not None:
            user_arg = user_id
            if user is not None:
                if pwd.getpwuid(user_id).pw_name != user:
                    ... # pebble.PathError?
        elif user is not None:
            user_arg = user
            if user_id is not None:
                if pwd.getpwnam(user).pw_uid != user_id:
                    ... # pebble.PathError?
        # group_arg
        group_arg: str | int | None = None
        if group_id is not None:
            group_arg = group_id
            if group is not None:
                if grp.getgrgid(group_id).gr_name != group:
                    ... # pebble.PathError?
        elif group is not None:
            group_arg = group
            if group_id is not None:
                if grp.getgrnam(group).gr_gid != group_id:
                    ... # pebble.PathError?
        # chown
        if user_arg is not None and group_arg is not None:
            shutil.chown(ppath, user=user_arg, group=group_arg)
        elif user_arg is not None:
            shutil.chown(ppath, user=user_arg)
        elif group_arg is not None:
            shutil.chown(ppath, group=group_arg)



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


# type checking
def _type_check(_container: ops.Container):
    _f: FileOpsProtocol
    _f = FileOps()
    _f = FileOps(_container)
    _f = _container
