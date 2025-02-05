from __future__ import annotations

import errno
import io
import os
import pathlib
import typing
from typing import Sequence

from ops import pebble

from . import _chown_utils
from . import _errors

if typing.TYPE_CHECKING:
    from typing_extensions import Self, TypeAlias
    from _typeshed import ReadableBuffer
    import ops


DIR_DEFAULT_MODE = 0o777
# this is the default value from Path.mkdir
# TODO: check default value with pebble


# based on typeshed.stdlib.StrPath
# https://github.com/python/typeshed/blob/main/stdlib/_typeshed/__init__.pyi#L173
_StrPath: TypeAlias = 'str | _StrPathLike'


# based on typeshed.stdlib.os.PathLike
# https://github.com/python/typeshed/blob/main/stdlib/os/__init__.pyi#L877
class _StrPathLike(typing.Protocol):
    def __fspath__(self) -> str: ...


# based on typeshed.stdlib.pathlib.PurePath
# https://github.com/python/typeshed/blob/main/stdlib/pathlib.pyi#L29
class _PurePathProtocol(typing.Protocol):
    @property
    def parts(self) -> tuple[str, ...]: ...

    @property
    def drive(self) -> str: ...

    @property
    def root(self) -> str: ...

    @property
    def anchor(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def suffix(self) -> str: ...

    @property
    def suffixes(self) -> list[str]: ...

    @property
    def stem(self) -> str: ...

    # constructor isn't part of our protocol
    # def __new__(cls, *args: _StrPath, **kwargs: object) -> Self: ...  # version dependent
    # def __init__(self, *args): ...

    # def __reduce__(self): ...
    # ops.Container isn't pickleable, so:
    # a) this shouldn't be part of the protocol
    # b) at runtime ContainerPath should fail to pickle
    # we can implement this with a __reduce__ property that raises an AttributeError

    def __hash__(self) -> int: ...

    # def __fspath__(self) -> str: ...
    # NOTE: By excluding this from the protocol, we can make it a type checking
    # error to call (e.g.) open(...) on a fileops.pathlike.Protocol.
    # Unfortunately due to inheritance from PurePath in the current implementation,
    # it isn't a type error to call (e.g.) open(...) on a ContainerPath,
    # and PurePath provides an __fspath__ implementation that results in it
    # being treated like a regular path by open at runtime.
    # We can make it fail at runtime by (e.g.)
    # making a __fspath__ property that raises an AttributeError
    # but the type checker doesn't care about this it seems.
    # This is because pathlib.PurePath calls os.PathLike.register(PurePath)
    # -- that is because of the ABC, the type checker assumes the implementation is ok
    # It's not clear whether to
    # a) include or remove this method from the protocol
    # b) make it a runtime error to try to open a ContainerPath
    #    -- and use *self.parts for methods returning a ContainerPath

    def __lt__(self, other: Self) -> bool: ...

    def __le__(self, other: Self) -> bool: ...

    def __gt__(self, other: Self) -> bool: ...

    def __ge__(self, other: Self) -> bool: ...

    def __truediv__(self, key: _StrPath) -> Self: ...

    def __rtruediv__(self, key: _StrPath) -> Self: ...

    def __bytes__(self) -> bytes: ...

    def as_posix(self) -> str: ...

    def as_uri(self) -> str: ...

    def is_absolute(self) -> bool: ...

    def is_reserved(self) -> bool: ...

    def match(self, path_pattern: str) -> bool: ...  # signature extended in 3.12+

    # def full_match(self, pattern: str, * case_sensitive: bool = False) -> bool: ...  # 3.13+

    def relative_to(self, *other: _StrPath) -> Self: ...

    # def is_relative_to(self, other: _StrPath) -> Self: ...  # 3.9+

    def with_name(self, name: str) -> Self: ...

    def with_suffix(self, suffix: str) -> Self: ...

    # def with_stem(self, stem: str) -> Self: ...  # 3.9+

    def with_segments(self, *pathsegments: _StrPath) -> Self: ...  # 3.12+ for new subclassing machinery

    def joinpath(self, *other: _StrPath) -> Self: ...

    @property
    def parents(self) -> Sequence[Self]: ...

    @property
    def parent(self) -> Self: ...


class Protocol(_PurePathProtocol, typing.Protocol):
    # pull
    def read_text(
        self,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,
    ) -> str: ...

    def read_bytes(self) -> bytes: ...

    # push
    def write_bytes(
        self,
        data: bytes,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None: ...

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        # TODO: errors -- do we just suppress pebble errors here?
        # 'strict' -> raise ValueError for encoding error
        # 'ignore' -> just write stuff anyway, ignoring errors
        # None -> 'strict'
        newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None: ...

    # make_dir
    def mkdir(
        self,
        mode: int = 0o777,  # TODO: check default value with pebble
        parents: bool = False,
        exist_ok: bool = False,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None: ...

    # remove
    def rmdir(self) -> None: ...

    def unlink(self, missing_ok: bool = False) -> None: ...

    # list_files
    def iterdir(self) -> typing.Iterable[Self]: ...

    def glob(self, pattern: str, *, case_sensitive: bool = False) -> typing.Generator[Self]: ...

    def rglob(self, pattern: str, *, case_sensitive: bool = False) -> typing.Generator[Self]: ...

    def walk(
        self,
        top_down: bool = True,
        on_error: typing.Callable[[OSError], None] | None = None,
        follow_symlinks: bool = False,  # TODO: can we handle this?
    ) -> typing.Iterator[tuple[Self, list[str], list[str]]]: ...

    def lstat(self) -> os.stat_result: ...
    # NOTE: either no stat or no lstat -- I think lstat is the one that reflects pebble's list_files behaviour?

    def owner(self) -> str: ...

    def group(self) -> str: ...

    def exists(self) -> bool: ...  # TODO: follow_symlinks argument?

    def is_dir(self) -> bool: ...

    def is_file(self) -> bool: ...

    def is_mount(self) -> bool: ...

    def is_symlink(self) -> bool: ...

    def is_junction(self) -> bool: ...  # TODO: don't include in Protocol since it's always false in our case?

    def is_block_device(self) -> bool: ...  # TODO: pebble only tells us if it's a device, so maybe we provide is_device instead

    def is_char_device(self) -> bool: ...  # TODO: pebble only tells us if it's a device, so maybe we provide is_device instead

    def is_fifo(self) -> bool: ...

    def is_socket(self) -> bool: ...


class ContainerPath(type(pathlib.PurePath())):  # TODO: just inherit from PurePosixPath?
    """Path-like class that encapsulates an ops.Container for file operations.

    Uses the parent class's version of __str__ and __fspath__, which means that str(container_path)
    provides just the string representation of the filesystem path, and that methods like `open`
    will treat a ContainerPath like a local filesystem path.
    """

    def __new__(cls, *args: _StrPath, container: ops.Container) -> Self:
        # required for python < 3.12 subclassing of PurePath
        instance = super().__new__(cls, *args)  # set up path stuff in < 3.12
        return instance  # __init__ will be called with *args and container=...

    def __init__(self, *args: _StrPath, container: ops.Container) -> None:
        try:
            super().__init__(*args)  # set up path stuff in 3.12+
        except TypeError:
            super().__init__()  # this is just object.__init__
        self.container = container
        self._parents = tuple(type(self)(p, container=self.container) for p in super().parents)
        self._parent = self._parents[-1] if self._parents else self

    @property
    def parents(self) -> Sequence[Self]:
        return self._parents

    @property
    def parent(self) -> Self:
        return self._parent

    def __repr__(self) -> str:
        return f"{super().__repr__()[:-1]}, container=<ops.Container '{self.container.name}'>)"

    ####################################
    # methods that make a new instance #
    ####################################

    def __truediv__(self, key: _StrPath) -> Self:
        if isinstance(key, ContainerPath):
            if self.container != key.container:
                raise ValueError
        path = super().__truediv__(key)
        return type(self)(path, container=self.container)

    def __rtruediv__(self, key: _StrPath) -> Self:
        if isinstance(key, ContainerPath):
            if self.container != key.container:
                raise ValueError
        path = super().__rtruediv__(key)
        return type(self)(path, container=self.container)

    def relative_to(
        self, *other: _StrPath
        # we don't support the walk_up argument as it isn't available in python 3.8
    ) -> Self:
        for o in other:
            if isinstance(o, ContainerPath):
                if self.container != o.container:
                    raise ValueError
        path = super().relative_to(*other)
        return type(self)(path, container=self.container)

    def with_name(self, name: str) -> Self:
        path = super().with_name(name)
        return type(self)(path, container=self.container)

    def with_suffix(self, suffix: str) -> Self:
        path = super().with_suffix(suffix)
        return type(self)(path, container=self.container)

    def joinpath(self, *other: _StrPath) -> Self:
        for o in other:
            if isinstance(o, ContainerPath):
                if self.container != o.container:
                    raise ValueError
        path = super().joinpath(*other)
        return type(self)(path, container=self.container)

    def with_segments(self, *pathsegments: _StrPath) -> Self:
        # required for python 3.12+ subclassing of PurePath
        return type(self)(*pathsegments, container=self.container)

    ##############
    # comparison #
    ##############

    def __hash__(self) -> int:
        return hash((self.container.name, self.parts))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, type(self))
            and self.parts == other.parts
            and self.container.name == other.container.name
        )

    def __lt__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: Self
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__lt__(other.container.name)
        return super().__lt__(other)

    def __le__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: Self
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__le__(other.container.name)
        return super().__le__(other)

    def __gt__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: Self
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__gt__(other.container.name)
        return super().__gt__(other)

    def __ge__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: Self
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__ge__(other.container.name)
        return super().__ge__(other)

    ####################
    # Protocol methods #
    ####################

    def read_text(
        self,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,
    ) -> str:
        return self.container.pull(self).read()

    def read_bytes(self) -> bytes:
        return self.container.pull(self, encoding=None).read()

    # push
    def write_bytes(
        self,
        data: ReadableBuffer,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None:
        self.container.push(
            path=self,
            source=io.BytesIO(data),
            make_dirs=False,
            permissions=permissions,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
        )

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None:
        # newline:
        # None -> turn '\n' into os.linesep
        # '' | '\n' -> do nothing
        # '\r' | '\r\r' -> replace '\n' with this option
        self.container.push(
            path=self,
            source=io.StringIO(data, newline=newline),
            encoding=encoding if encoding is not None else 'utf-8',
            make_dirs=False,
            permissions=permissions,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
        )

    # make_dir
    def mkdir(
        self,
        mode: int = 0o777,  # TODO: check default value with pebble
        parents: bool = False,
        exist_ok: bool = False,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None:
        ...

    # remove
    def rmdir(self) -> None:
        if not self.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(self))
        try:
            self.container.remove_path(self, recursive=False)
        except pebble.Error as error:
            for error_kind in (
                _errors.API.BadRequest,
                _errors.API.FileNotFound,
                _errors.Path.FileExists,
                _errors.Path.RelativePath,
                _errors.Path.FileNotFound,
                _errors.Path.Lookup,
                _errors.Path.Permission,
                _errors.Path.Generic,
            ):
                if error_kind.matches(error):
                    raise error_kind.exception_from_error(error)
            raise

    def unlink(self, missing_ok: bool = False) -> None:
        if self.is_dir():
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(self))
        try:
            self.container.remove_path(self, recursive=False)
        except pebble.Error as error:
            if _errors.Path.FileNotFound.matches(error):
                if missing_ok:
                    return
                raise FileNotFoundError
                # or
                raise _errors.Path.FileNotFound.exception_from_error(error)
            for error_kind in []:
                if error_kind.matches(error):
                    raise error_kind.exception_from_error(error)
            raise

    # list_files
    def iterdir(self) -> typing.Generator[Self]:
        # python < 3.13 defers NotADirectoryError to iteration time, but python 3.13 raises on call
        if not self.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(self))
        file_infos = self.container.list_files(self)
        for f in file_infos:
            yield type(self)(f.path, container=self.container)

    def glob(self, pattern: str, *, case_sensitive: bool = False) -> typing.Generator[Self]: ...

    def rglob(self, pattern: str, *, case_sensitive: bool = False) -> typing.Generator[Self]: ...

    def walk(
        self,
        top_down: bool = True,
        on_error: typing.Callable[[OSError], object] | None = None,
        follow_symlinks: bool = False,
    ) -> typing.Iterator[tuple[Self, list[str], list[str]]]: ...

    def lstat(self) -> os.stat_result: ...

    def owner(self) -> str: ...

    def group(self) -> str: ...

    def exists(self) -> bool: ...

    def is_dir(self) -> bool:
        return self.container.isdir(self)

    def is_file(self) -> bool: ...

    def is_mount(self) -> bool: ...

    def is_symlink(self) -> bool: ...

    def is_junction(self) -> bool: ...  # TODO: don't include in Protocol since it's always false in our case?

    def is_block_device(self) -> bool: ...  # TODO: pebble only tells us if it's a device, so maybe we provide is_device instead

    def is_char_device(self) -> bool: ...  # TODO: pebble only tells us if it's a device, so maybe we provide is_device instead

    def is_fifo(self) -> bool: ...

    def is_socket(self) -> bool: ...



class LocalPath(type(pathlib.Path())):  # TODO: just inherit from PosixPath?
    def write_bytes(  # TODO: data type?
        self,
        data: ReadableBuffer,
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None:
        ...

    def write_text(  # TODO: use str instead of Literals?
        self,
        data: str,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        # TODO: errors -- can pebble handle this?
        # 'strict' -> raise ValueError for encoding error
        # 'ignore' -> just write stuff anyway, ignoring errors
        # None -> 'strict'
        newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,
        # TODO: newline -- what does ops.Container do currently?
        #       do we want to handle this if ops.Container doesn't?
        # None -> turn '\n' into os.linesep
        # '' | '\n' -> do nothing
        # '\r' | '\r\r' -> replace '\n' with this option
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None:
        super().write_text(data=data, encoding=encoding, errors=errors, newline=newline)
        self.chmod(mode=permissions if permissions is not None else 0o644)  # Pebble default TODO: what should default behaviour be?
        user_arg = _chown_utils.get_user_arg(str_name=user, int_id=user_id)
        group_arg = _chown_utils.get_group_arg(str_name=group, int_id=group_id)
        _chown_utils.try_chown(self, user=user_arg, group=group_arg)

    # make_dir
    def mkdir(
        self,
        mode: int = DIR_DEFAULT_MODE,
        parents: bool = False,
        exist_ok: bool = False,
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None:
        ...


def _type_check_1(  # pyright: ignore[reportUnusedFunction]
    _container_path: ContainerPath,
    _path: pathlib.Path,
    _pure_path: pathlib.PurePath,
    _local_path: LocalPath,
) -> None:
    _p: _PurePathProtocol
    _p = _container_path
    _p = _local_path
    _p = _path
    _p = _pure_path

    _pp: Protocol
    _pp = _container_path
    _pp = _local_path
    _pp = _path  # pyright: ignore[reportAssignmentType]
    # unfortunately Path will be incompatible too because of the extended
    # signatures of write_text/bytes and mkdir (user, user_id, ...)
    _pp = _pure_path  # pyright: ignore[reportAssignmentType]
    # we expect PurePath to be incompatible because it lacks read_text etc

    _ppp: pathlib.PurePath
    _ppp = _container_path
    _ppp = _local_path
    _ppp = _path
    _ppp = _pure_path

    _pppp: pathlib.Path
    _pppp = _container_path  # pyright: ignore[reportAssignmentType]
    # expected: ContainerPath doesn't implement all the Path methods
    _pppp = _local_path
    _pppp = _path
    _pppp = _pure_path  # pyright: ignore[reportAssignmentType]
    # we expect PurePath to be incompatible because it lacks read_text etc


_StrOrBytesPath: typing.TypeAlias = 'str | bytes | os.PathLike[str] | os.PathLike[bytes]'
def _type_check_2(  # pyright: ignore[reportUnusedFunction]
    _pure_path_protocol: _PurePathProtocol,
    _protocol: Protocol,
    _container_path: ContainerPath,
    _local_path: LocalPath,
    _path: pathlib.Path,
    _pure_path: pathlib.PurePath,
) -> None:
    _p: _StrOrBytesPath
    _pp: os.PathLike[str]
    open(_pure_path_protocol)  # pyright: ignore[reportArgumentType]
    _p = _pure_path_protocol  # pyright: ignore[reportAssignmentType]
    _pp = _pure_path_protocol  # pyright: ignore[reportAssignmentType]
    open(_protocol)  # pyright: ignore[reportArgumentType]
    _p = _protocol  # pyright: ignore[reportAssignmentType]
    _pp = _protocol  # pyright: ignore[reportAssignmentType]
    open(_container_path)
    _p = _container_path
    _pp = _container_path
    # it would be nice to make the above a type checking + runtime error
    # unfortunately ContainerPath passes type checking somehow because it inherits from PurePath
    open(_local_path)
    open(_path)
    open(_pure_path)


def _type_check_3():
    _pp: os.PathLike[str]
    class AnnoyingABCInheritance0(os.PathLike): ...
    f0 = AnnoyingABCInheritance0()
    class AnnoyingABCInheritance1(os.PathLike):
        def __fspath__(self, incompatible) -> str: ...
    f1 = AnnoyingABCInheritance1()
    class AnnoyingABCInheritance2(os.PathLike):
        def __fspath__(self) -> None: ...
    f2 = AnnoyingABCInheritance2()
    class Good:
        def __fspath__(self) -> str: ...
    g = Good()
    class Bad1(Good):
        def __fspath__(self, incompatible) -> str: ...
    b1 = Bad1()
    class Bad2(Good):
        def __fspath__(self) -> None: ...
    b2 = Bad2()
    _pp = f0  # argh!
    _pp = f1  # argh!
    _pp = f2  # argh!
    _pp = g
    _pp = b1
    _pp = b2
