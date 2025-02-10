from __future__ import annotations

import errno
import io
import os
import pathlib
import typing
from typing import Generator, Sequence

from ops import pebble

from . import _chown_utils, _errors

if typing.TYPE_CHECKING:
    import ops
    from _typeshed import ReadableBuffer
    from typing_extensions import Self, TypeAlias


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
class _PurePathSubset(typing.Protocol):
    """Defines the subset of pathlib.PurePath methods required."""

    # constructor isn't part of our protocol
    # ContainerPath constructor will differ from pathlib.Path constructor
    # def __new__(cls, *args: _StrPath, **kwargs: object) -> Self: ...
    # NOTE: __new__ signature is version dependent
    # def __init__(self, *args): ...

    def __hash__(self) -> int: ...
    # should ContainerPath be hashable? We can assume container names are unique, right?

    # def __reduce__(self): ...
    # ops.Container isn't pickleable, so:
    # a) this shouldn't be part of the protocol
    # b) at runtime ContainerPath should fail to pickle

    # comparison methods
    # ContainerPath comparison methods will return NotImplemented if other is not a
    # ContainerPath with the same container; otherwise the paths are compared
    def __lt__(self, other: Self) -> bool: ...
    def __le__(self, other: Self) -> bool: ...
    def __gt__(self, other: Self) -> bool: ...
    def __ge__(self, other: Self) -> bool: ...
    def __eq__(self, other: object, /) -> bool: ...

    # ContainerPath / (str or pathlib.Path), or (str or pathlib.Path) / containerPath
    # will result in a new ContainerPath with the same container.
    # ContainerPath / ContainerPath is an error if the containers are not the same,
    # otherwise it too results in a new ContainerPath with the same container.
    def __truediv__(self, key: _StrPath | Self) -> Self: ...
    def __rtruediv__(self, key: _StrPath | Self) -> Self: ...

    # def __fspath__(self) -> str: ...
    # we don't want ContainerPath to be path-like

    # def __bytes__(self) -> bytes: ...
    # we don't want ContainerPath to be mistakenly used like a pathlib.Path

    def as_posix(self) -> str: ...
    # we don't want ContainerPath to be mistakenly used like a pathlib.Path
    # but maybe this is explicit enough to be our way to a pathlib.Path?
    # e.g. def f(p: PathProtocol): pathlib.Path(p.as_posix())

    # def as_uri(self) -> str: ...
    # this doesn't seem useful and is potentially confusing,so it won't be implemented
    # likewise, this constructor (added in 3.13) won't be implemented
    # @classmethod
    # def from_uri(uri: str) -> Self: ...

    def is_absolute(self) -> bool: ...

    def is_reserved(self) -> bool: ...
    # this will always return False in ContainerPath, since we assume a Linux container

    def match(self, path_pattern: str) -> bool: ...
    # signature extended further in 3.12+
    # def match(self, pattern: str, * case_sensitive: bool = False) -> bool: ...
    # not part of the protocol but may eventually be provided on ContainerPath
    # to ease compatibility with pathlib.Path on 3.12+

    # def full_match(self, pattern: str, * case_sensitive: bool = False) -> bool: ...
    # 3.13+
    # not part of the protocol but may eventually be provided on ContainerPath
    # to ease compatibility with pathlib.Path on 3.13+

    def relative_to(self, other: _StrPath, /) -> Self: ...
    # Python 3.12 deprecates the below signature, to be dropped in 3.14
    # def relative_to(self, *other: _StrPath) -> Self: ...
    # to ease future compatibility, we'll just drop support for the old signature now
    #
    # Python 3.12 further modifies the signature with an additional keyword argument
    # def relative_to(self, other: _StrPath, walk_up: bool = False) -> Self: ...
    # this is not part of the protocol but may eventually be provided on ContainerPath
    # to ease compatibility with pathlib.Path on 3.12+

    # def is_relative_to(self, other: _StrPath) -> Self: ...  # 3.9+
    # not part of protocol but can be provided on ContainerPath implementation
    # to ease compatibility with pathlib.Path on 3.9+
    # could be added to the protocol if we're happy for LocalPath to double as backports

    def with_name(self, name: str) -> Self: ...

    def with_suffix(self, suffix: str) -> Self: ...

    # def with_stem(self, stem: str) -> Self: ...  # 3.9+
    # not part of protocol but can be provided on ContainerPath implementation
    # to ease compatibility with pathlib.Path on 3.9+
    # could be added to the protocol if we're happy for LocalPath to double as backports

    # def with_segments(self, *pathsegments: _StrPath) -> Self: ...
    # required for 3.12+ subclassing machinery
    # doesn't need to be in the protocol, nor to be implemented in ContainerPath

    def joinpath(self, *other: _StrPath) -> Self: ...

    @property
    def parents(self) -> Sequence[Self]: ...

    @property
    def parent(self) -> Self: ...

    @property
    def parts(self) -> tuple[str, ...]: ...

    @property
    def drive(self) -> str: ...  # will always be '' for Posix

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


class _ConcretePathSubset(typing.Protocol):
    """Defines the subset of pathlib.Path methods required.

    Note that the current idea is to extend the signatures of the file creation methods,
    to support setting ownership and permissions at file creation time, as that's when
    Pebble sets them. See _ConcretePathSubsetExtendedSignatures for details.
    """

    # pull
    def read_text(
        self,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        # newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,  # 3.13+
    ) -> str: ...

    def read_bytes(self) -> bytes: ...

    # push -- note that (e.g.) additional arguments are required to support setting
    # ownership and permission via pebble -- see _ConcretePathSubsetExtendedSignatures
    def write_bytes(
        self,
        data: bytes,
    ) -> int: ...  # NOTE: supposed to return the number of bytes written

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        # TODO: errors -- do we just suppress pebble errors here?
        # 'strict' -> raise ValueError for encoding error
        # 'ignore' -> just write stuff anyway, ignoring errors
        # None -> 'strict'
        # newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,  # 3.10+
    ) -> int: ...

    # make_dir -- note that (e.g.) additional arguments are required to support setting
    # ownership and permission via pebble -- see _ConcretePathSubsetExtendedSignatures
    def mkdir(
        self,
        mode: int = 0o777,  # TODO: check default value with pebble
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None: ...

    # remove
    def rmdir(self) -> None: ...

    def unlink(self, missing_ok: bool = False) -> None: ...

    # list_files
    def iterdir(self) -> typing.Iterable[Self]: ...

    def glob(
        self,
        pattern: str,  # support for _StrPath added in 3.13
        # *,
        # case_sensitive: bool = False,  # added in 3.12
        # recurse_symlinks: bool = False,  # added in 3.13
    ) -> Generator[Self]: ...

    def rglob(
        self,
        pattern: str,  # support for _StrPath added in 3.13
        # *,
        # case_sensitive: bool = False,  # added in 3.12
        # recurse_symlinks: bool = False,  # added in 3.13
    ) -> Generator[Self]: ...
        # NOTE: to ease implementation, this could be dropped from the v1 release

    # walk was only added in 3.12 -- let's not support this for now, as we'd need to
    # implement the walk logic for LocalPath as well as whatever we do for ContainerPath
    # (which will also be a bit trickier being unable to distinguish symlinks as dirs)
    # While Path.walk wraps os.walk, there are still ~30 lines of pathlib code we'd need
    # to vendor for LocalPath.walk
    # def walk(
    #     self,
    #     top_down: bool = True,
    #     on_error: typing.Callable[[OSError], None] | None = None,
    #     follow_symlinks: bool = False,  # NOTE: ContainerPath runtime error if True
    # ) -> typing.Iterator[tuple[Self, list[str], list[str]]]:
    #     # TODO: if we add a follow_symlinks option to Pebble's list_files API, we can
    #     #       then support follow_symlinks=True on supported Pebble (Juju) versions
    #     ...

    # def stat(self) -> os.stat_result: ...
    # stat follows symlinks to return information about the target
    # Pebble's list_files tells you if a file is a symlink, but not what the target is
    # TODO: support if we add follow_symlinks to Pebble's list_files API

    def lstat(self) -> os.stat_result: ...

    def owner(self) -> str: ...

    def group(self) -> str: ...

    # exists, is_dir and is_file are problematic, because they follow symlinks by default
    # and Pebble will only tell us if the file is a symlink - nothing about its target.
    #
    # Python 3.12 and 3.13 add keyword arguments to control this (defaulting to True)
    # The ContainerPath implementation should accept the follow_symlinks argument.
    # Maybe the LocalPath implementation should too, so that the protocol can as well?
    #
    # In the ContainerPath implementation, if follow_symlinks==True and the result type
    # is pebble.FileTypes.SYMLINK, then we'll raise a NotImplementedError at runtime.
    #
    # TODO: add to Pebble an optional eval/follow_symlinks arg for the list_files api,
    #       and then only raise NotImplementedError if follow_symlinks=True AND the
    #       result type is pebble.FileTypes.SYMLINK, AND the pebble version is too old

    def exists(self) -> bool:  # follow_symlinks=True added in 3.12
        """Whether this path exists.

        WARNING: ContainerPath may raise a NotImplementedError if the path is a symlink.
        """
        ...

    def is_dir(self) -> bool:  # follow_symlinks=True added in 3.13
        """Whether this path is a directory.

        WARNING: ContainerPath may raise a NotImplementedError if the path is a symlink.
        """
        ...

    def is_file(self) -> bool:  # follow_symlinks=True added in 3.13
        """Whether path is a regular file.

        WARNING: ContainerPath may raise a NotImplementedError if the path is a symlink.
        """
        ...

    def is_mount(self) -> bool: ...

    def is_symlink(self) -> bool: ...

    # def is_junction(self) -> bool: ...
    # 3.12
    # this will always be False in ContainerPath since we assume a Linux container

    def is_fifo(self) -> bool: ...

    def is_socket(self) -> bool: ...

    # is_block_device and is_char_device are problematic because pebble only tells us if
    # it's a device at all. We could add an is_device method, which locks us into using
    # LocalPath -- so maybe a module level is_device function would be better?
    # def is_block_device(self) -> bool: ...
    # def is_char_device(self) -> bool: ...

    ################################################################################
    # the following concrete methods are currently ruled out due to Pebble support #
    ################################################################################

    # def chmod
        # pebble sets mode on creation
        # can't provide a separate method
        # needs to be argument for other functions
        # (same treatment needed for chown)

    # link creation, modification, target retrieval
    # pebble doesn't support link manipulation
    # def hardlink_to
    # def symlink_to
    # def lchmod
    # def readlink
    # def resolve

    # def samefile
        # pebble doesn't return device and i-node number
        # can't provide the same semantics

    # def open
        # the semantics would be different due to needing to make a local copy

    # def touch
        # would have to pull down the existing file and push it back up just to set mtime

    ##################
    # relative paths #
    ##################

    # if we support relative paths, we'd need to implicitly call absolute before every
    # call that goes to pebble
    # I think it would be fine to v1 to only support absolute paths, raising an error
    # on file operations with relative paths
    # however, if we were willing to support the methods below, particularly cwd, then
    # we could support relative paths

    # the following methods would require us to either hardcode cwd or use a pebble.exec
    # def cwd
        # typically /root in container
        # do we need to query this each time? can we hardcode it?
    # def absolute
        # interpret relative to cwd

    # the following methods would require us to either hardcode home or use a pebble.exec
    # def home
        # typically /root in container
        # do we need to query this each time? can we hardcode it?
    # def expanduser
        # '~' in parts becomes self.home


class _ConcretePathSubsetExtendedSignatures(_ConcretePathSubset, typing.Protocol):
    # push
    def write_bytes(
        self,
        data: bytes,
        # extended with pebble args:
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> int: ...

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: typing.Literal['strict', 'ignore'] | None = None,
        # extended with pebble args:
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> int: ...

    # make_dir
    def mkdir(
        self,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
        # extended with pebble args:
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None: ...


class _CommonProtocol(_ConcretePathSubset, _PurePathSubset, typing.Protocol):
    """Using this protocol does not allow setting permissions and ownership on files.

    pathlib.Path is compatible with this protocol out of the box.

    Should this protocol be public? I don't think so -- users can write this instead:
    ContainerPath | pathlib.Path

    Do we want to recommend/support this typing? Maybe ... for example, we could provide
    module level write functions taking ContainerPath | pathlib.Path as alternatives to
    using LocalPath.
    """


class Protocol(_ConcretePathSubsetExtendedSignatures, _PurePathSubset, typing.Protocol):
    """Using this protocol allows setting permissions and ownership on file creation.

    pathlib.Path is not compatible with this protocol -- wrap with LocalPath.
    """


class ContainerPath(pathlib.PurePosixPath):
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
        if isinstance(key, ContainerPath) and self.container != key.container:
            raise ValueError
        path = super().__truediv__(key)
        return type(self)(path, container=self.container)

    def __rtruediv__(self, key: _StrPath) -> Self:
        if isinstance(key, ContainerPath) and self.container != key.container:
            raise ValueError
        path = super().__rtruediv__(key)
        return type(self)(path, container=self.container)

    def relative_to(
        self,
        *other: _StrPath,
        # we don't support the walk_up argument as it isn't available in python 3.8
    ) -> Self:
        for o in other:
            if isinstance(o, ContainerPath) and self.container != o.container:
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
            if isinstance(o, ContainerPath) and self.container != o.container:
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
        self,
        other: Self,
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__lt__(other.container.name)
        return super().__lt__(other)

    def __le__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        other: Self,
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__le__(other.container.name)
        return super().__le__(other)

    def __gt__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        other: Self,
        # PurePath has other: PurePath -- Path comparisons are only for the same kind of paths
    ) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        if self.container.name != other.container.name:
            return self.container.name.__gt__(other.container.name)
        return super().__gt__(other)

    def __ge__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        other: Self,
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
        # newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,  # 3.13+
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
    ) -> int:
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
        return 0

    def write_text(
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        # newline: typing.Literal['', '\n', '\r', '\r\n'] | None = None,  # 3.10+
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> int:
        # newline:
        # None -> turn '\n' into os.linesep
        # '' | '\n' -> do nothing
        # '\r' | '\r\r' -> replace '\n' with this option
        self.container.push(
            path=self,
            source=data,
            # source=io.StringIO(data, newline=newline),
            encoding=encoding if encoding is not None else 'utf-8',
            make_dirs=False,
            permissions=permissions,
            user=user,
            user_id=user_id,
            group=group,
            group_id=group_id,
        )
        return 0

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
                    raise  # error_kind.exception_from_error(error) from error
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
                raise FileNotFoundError from error
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
                    raise  # error_kind.exception_from_error(error) from error
            raise

    # list_files
    def iterdir(self) -> typing.Generator[Self]:
        # python < 3.13 defers NotADirectoryError to iteration time, but python 3.13 raises on call
        if not self.is_dir():
            raise NotADirectoryError(errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(self))
        file_infos = self.container.list_files(self)
        for f in file_infos:
            yield type(self)(f.path, container=self.container)

    def glob(
        self,
        pattern: str,
        # case_sensitive: bool = False,  # 3.12+
    ) -> typing.Generator[Self]: ...

    def rglob(
        self,
        pattern: str,
        # case_sensitive: bool = False,  # 3.12+
    ) -> typing.Generator[Self]: ...

    def walk(
        self,
        top_down: bool = True,
        on_error: typing.Callable[[OSError], object] | None = None,
        follow_symlinks: bool = False,
    ) -> typing.Iterator[tuple[Self, list[str], list[str]]]: ...

    def lstat(self) -> os.stat_result: ...

    def owner(self) -> str: ...

    def group(self) -> str: ...

    def exists(self, follow_symlinks: bool = True) -> bool:
        return self._file_matches(filetype=None, follow_symlinks=follow_symlinks)

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self._file_matches(pebble.FileType.DIRECTORY, follow_symlinks=follow_symlinks)

    def is_file(self, follow_symlinks: bool = True) -> bool:
        return self._file_matches(pebble.FileType.FILE, follow_symlinks=follow_symlinks)

    def _file_matches(
        self, filetype: pebble.FileType | None, follow_symlinks: bool = False,
    ) -> bool:
        info = self._get_fileinfo(follow_symlinks=follow_symlinks)
        if info is None:
            return False
        if follow_symlinks and info.type is pebble.FileType.SYMLINK:
            raise NotImplementedError()
        if filetype is None:
            return True
        return info.type is filetype

    def _get_fileinfo(self, follow_symlinks: bool = False) -> pebble.FileInfo | None:
        try:
            [info] = self.container.list_files(self.as_posix(), itself=True)
        except pebble.APIError as e:
            if _errors.API.FileNotFound.matches(e):
                return None
            raise
        return info

    def is_mount(self) -> bool: ...

    def is_symlink(self) -> bool: ...

    def is_fifo(self) -> bool: ...

    def is_socket(self) -> bool: ...


class LocalPath(pathlib.PosixPath):  # TODO: just inherit from PosixPath?
    def write_bytes(  # TODO: data type?
        self,
        data: ReadableBuffer,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> int:
        ...
        return 0

    def write_text(  # TODO: use str instead of Literals?
        self,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> int:
        super().write_text(data=data, encoding=encoding, errors=errors)
        self.chmod(mode=permissions if permissions is not None else 0o644)
        # 0o644 is Pebble default TODO: what should default behaviour be?
        user_arg = _chown_utils.get_user_arg(str_name=user, int_id=user_id)
        group_arg = _chown_utils.get_group_arg(str_name=group, int_id=group_id)
        _chown_utils.try_chown(self, user=user_arg, group=group_arg)
        return 0

    # make_dir
    def mkdir(
        self,
        mode: int = DIR_DEFAULT_MODE,
        parents: bool = False,
        exist_ok: bool = False,
        # pebble args
        permissions: int | None = None,
        user: str | None = None,
        user_id: int | None = None,
        group: str | None = None,
        group_id: int | None = None,
    ) -> None: ...


def _type_check_1(  # pyright: ignore[reportUnusedFunction]
    _container_path: ContainerPath,
    _path: pathlib.Path,
    _pure_path: pathlib.PurePath,
    _local_path: LocalPath,
) -> None:
    _p: _PurePathSubset
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

    _ppppp: _CommonProtocol
    _ppppp = _container_path
    _ppppp = _local_path
    _ppppp = _path
    _ppppp = _pure_path  # pyright: ignore[reportAssignmentType]
    # we expect PurePath to be incompatible because it lacks read_text etc


_StrOrBytesPath: TypeAlias = 'str | bytes | os.PathLike[str] | os.PathLike[bytes]'


def _type_check_2(  # pyright: ignore[reportUnusedFunction]
    _pure_path_protocol: _PurePathSubset,
    _protocol: Protocol,
    _container_path: ContainerPath,
    _local_path: LocalPath,
    _path: pathlib.Path,
    _pure_path: pathlib.PurePath,
) -> None:
    _p: _StrOrBytesPath
    _pp: os.PathLike[str]
    open(_pure_path_protocol)  # pyright: ignore[reportArgumentType] # noqa: SIM115
    _p = _pure_path_protocol  # pyright: ignore[reportAssignmentType]
    _pp = _pure_path_protocol  # pyright: ignore[reportAssignmentType]
    open(_protocol)  # pyright: ignore[reportArgumentType] # noqa: SIM115
    _p = _protocol  # pyright: ignore[reportAssignmentType]
    _pp = _protocol  # pyright: ignore[reportAssignmentType]
    open(_container_path)  # noqa: SIM115
    _p = _container_path
    _pp = _container_path
    # it would be nice to make the above a type checking + runtime error
    # unfortunately ContainerPath passes type checking somehow because it inherits from PurePath
    open(_local_path)  # noqa: SIM115
    open(_path)  # noqa: SIM115
    open(_pure_path)  # noqa: SIM115


def _type_check_3():  # pyright: ignore[reportUnusedFunction]
    _pp: os.PathLike[str]

    class AnnoyingABCInheritance0(os.PathLike[str]): ...

    f0 = AnnoyingABCInheritance0()  # pyright: ignore[reportAbstractUsage]

    class AnnoyingABCInheritance1(os.PathLike[str]):
        def __fspath__(self, incompatible: None) -> str: ...  # pyright: ignore[reportIncompatibleMethodOverride]

    f1 = AnnoyingABCInheritance1()

    class AnnoyingABCInheritance2(os.PathLike[str]):
        def __fspath__(self) -> None: ...  # pyright: ignore[reportIncompatibleMethodOverride]

    f2 = AnnoyingABCInheritance2()

    class Good:
        def __fspath__(self) -> str: ...

    g = Good()

    class Bad1(Good):
        def __fspath__(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, incompatible: None
        ) -> str: ...

    b1 = Bad1()

    class Bad2(Good):
        def __fspath__(self) -> None: ...  # pyright: ignore[reportIncompatibleMethodOverride]

    b2 = Bad2()
    _pp = f0  # argh!
    _pp = f1  # argh!
    _pp = f2  # argh!
    _pp = g
    _pp = b1  # pyright: ignore[reportAssignmentType]
    _pp = b2  # pyright: ignore[reportAssignmentType]
