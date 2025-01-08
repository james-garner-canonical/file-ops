import unittest.mock
import os
import pathlib
import socket
import string
import subprocess
from typing import TYPE_CHECKING

import file_ops
import ops
import pytest
from file_ops._file_ops import _path_to_fileinfo  # pyright: ignore[reportPrivateUsage]

if TYPE_CHECKING:
    from typing import Iterator


DEBUG: bool = True
"""Write debugging info to files during tests."""


# modes
# strings for nicer pytest output
BAD_PARENT_DIRECTORY_MODES_NO_CREATE: tuple[str | None, ...] = (
    '666',
    '644',  # pebble default for file push
    '600',
    '544',
    '500',
    '444',
    '400',
    '200',
    '100',
    '010',
    '007',
    '000',
)
BAD_PARENT_DIRECTORY_MODES_CREATE: tuple[str | None, ...] = (
    '344',
    '333',
    '300',
)
GOOD_PARENT_DIRECTORY_MODES: tuple[str | None, ...] = (
    None,
    '777',
    '766',
    '755',  # pebble default for mkdir
    '700',
)
_MODES: tuple[str | None, ...] = (*GOOD_PARENT_DIRECTORY_MODES, *BAD_PARENT_DIRECTORY_MODES_NO_CREATE, *BAD_PARENT_DIRECTORY_MODES_CREATE)
MODES: tuple[str | None, ...] = tuple(reversed(sorted(_MODES, key=str)))


@pytest.fixture
def container() -> ops.Container:
    class dummy_backend:
        class _juju_context:
            version = "9000"
    return ops.Container(
        name="test",
        backend=dummy_backend,  # pyright: ignore[reportArgumentType]
        pebble_client=ops.pebble.Client(socket_path=get_socket_path()),
    )


def get_socket_path() -> str:
    socket_path = os.getenv('PEBBLE_SOCKET')
    pebble_path = os.getenv('PEBBLE')
    if not socket_path and pebble_path:
        assert isinstance(pebble_path, str)
        socket_path = os.path.join(pebble_path, '.pebble.socket')
    assert socket_path, 'PEBBLE or PEBBLE_SOCKET must be set if RUN_REAL_PEBBLE_TESTS set'
    return socket_path


@pytest.fixture
def text_files() -> dict[str, str]:
    return {
        'foo.txt': string.ascii_lowercase,
        'bar.txt': string.ascii_uppercase * 2,
        'baz.txt': '',
    }


@pytest.fixture
def interesting_dir(tmp_path: pathlib.Path, text_files: dict[str, str]) -> 'Iterator[pathlib.Path]':
    (tmp_path / 'empty_dir').mkdir()
    empty_file = (tmp_path / 'empty_file.bin')
    empty_file.touch()
    (tmp_path / 'symlink.bin').symlink_to(empty_file)
    (tmp_path / 'symlink_dir').symlink_to(tmp_path / 'empty_dir')
    (tmp_path / 'symlink_rec').symlink_to(tmp_path)
    (tmp_path / 'binary_file.bin').write_bytes(bytearray(range(256)))
    for filename, contents in text_files.items():
        (tmp_path / filename).write_text(contents)
    sock = socket.socket(socket.AddressFamily.AF_UNIX)
    sock.bind(str(tmp_path / 'socket.socket'))
    # TODO: make block device?
    try:
        yield tmp_path
    finally:
        sock.shutdown(socket.SHUT_RDWR)
        sock.close()


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestListFiles:
    @staticmethod
    def test_ok(container: ops.Container, interesting_dir: pathlib.Path):
        with_container = file_ops.FileOps(container).list_files(interesting_dir)
        without_container = file_ops.FileOps().list_files(interesting_dir)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        write_for_debugging(
            'list_files_ok',
            with_container=with_container,
            without_container=without_container,
        )
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container

    @staticmethod
    @pytest.mark.parametrize(
        'pattern',
        [
            '*.csv',  # no matches
            '*.bin',
            '*.txt',
            '**.txt',
            '***.txt',
            '*',
            # matching the file socket.socket
            '*.socket',
            'socket.*',
            'socket.socket',
            '?ocket.socket',
            '[a-z]*.socket',
            '[a-z]ocket.*',
            '[a-z]oc*et.*c[b-m]?t',
        ],
    )
    def test_pattern_ok(container: ops.Container, interesting_dir: pathlib.Path, pattern: str):
        with_container = file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern)
        without_container = file_ops.FileOps().list_files(interesting_dir, pattern=pattern)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        write_for_debugging(
            f'list_files_pattern_ok_{"".join(c if c.isalnum() else "_" for c in pattern)}',
            with_container=with_container,
            without_container=without_container,
        )
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container

    @staticmethod
    def test_pattern_ok_text_files(container: ops.Container, interesting_dir: pathlib.Path, text_files: dict[str, str]):
        pattern = '*.txt'
        with_container = file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern)
        without_container = file_ops.FileOps().list_files(interesting_dir, pattern=pattern)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container
        # extra validation
        assert sorted(fileinfo.name for fileinfo in with_container) == sorted(text_files)

    @staticmethod
    def test_pattern_ok_no_match(container: ops.Container, interesting_dir: pathlib.Path):
        pattern = '*.nomatches'
        with_container = file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern)
        without_container = file_ops.FileOps().list_files(interesting_dir, pattern=pattern)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container
        # extra validation
        assert len(with_container) == 0

    @staticmethod
    def test_bad_pattern(container: ops.Container, interesting_dir: pathlib.Path):
        pattern = '[foo'
        with pytest.raises(ops.pebble.APIError) as exception_context:
            file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern)
        assert isinstance(exception_context.value, file_ops.ValueAPIError)
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().list_files(interesting_dir, pattern=pattern)
        assert isinstance(exception_context.value, file_ops.ValueAPIError)

    @staticmethod
    def test_bad_pattern_empty_dir(container: ops.Container, tmp_path: pathlib.Path):
        pattern = '[foo'
        with_container = file_ops.FileOps(container).list_files(tmp_path, pattern=pattern)
        without_container = file_ops.FileOps().list_files(tmp_path, pattern=pattern)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container

    @staticmethod
    def test_itself_ok(container: ops.Container, interesting_dir: pathlib.Path):
        with_container = file_ops.FileOps(container).list_files(interesting_dir, itself=True)
        without_container = file_ops.FileOps().list_files(interesting_dir, itself=True)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container

    @staticmethod
    def test_itself_pattern_ok(container: ops.Container, interesting_dir: pathlib.Path):
        pattern = '*'
        with_container = file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern)
        without_container = file_ops.FileOps().list_files(interesting_dir, pattern=pattern)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        write_for_debugging(
            'list_files_itself_pattern_ok',
            with_container=with_container,
            without_container=without_container,
        )
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container

    @staticmethod
    def test_itself_pattern_no_matches(container: ops.Container, interesting_dir: pathlib.Path):
        pattern = '*.nomatches'
        with_container = file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern)
        without_container = file_ops.FileOps().list_files(interesting_dir, pattern=pattern)
        with_container.sort(key=lambda fileinfo: fileinfo.name)
        without_container.sort(key=lambda fileinfo: fileinfo.name)
        write_for_debugging(
            'list_files_itself_pattern_no_matches',
            with_container=with_container,
            without_container=without_container,
        )
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert with_container == without_container

    @staticmethod
    def test_itself_bad_pattern(container: ops.Container, interesting_dir: pathlib.Path):
        pattern = '[foo'
        with pytest.raises(ops.pebble.APIError) as exception_context:
            file_ops.FileOps(container).list_files(interesting_dir, pattern=pattern, itself=True)
        assert isinstance(exception_context.value, file_ops.ValueAPIError)
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().list_files(interesting_dir, pattern=pattern, itself=True)
        assert isinstance(exception_context.value, file_ops.ValueAPIError)

    @staticmethod
    def test_target_doesnt_exist(container: ops.Container, tmp_path: pathlib.Path):
        path = (tmp_path / 'does/not/exist/')
        # with container
        with pytest.raises(ops.pebble.APIError) as exception_context:
            file_ops.FileOps(container).list_files(path)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundAPIError)
        # without container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().list_files(path)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundAPIError)


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestMakeDir:
    @staticmethod
    def test_ok(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        file_ops.FileOps(container).make_dir(directory)
        assert directory.exists()
        rmdir(directory)
        file_ops.FileOps().make_dir(directory)
        assert directory.exists()
        rmdir(directory)

    @staticmethod
    def test_directory_already_exists(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        pathlib.Path(directory).mkdir(exist_ok=True, parents=True)
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileExistsPathError)
        # without container
        with pytest.raises(FileExistsError) as exception_context:
            file_ops.FileOps().make_dir(directory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileExistsPathError)

    @staticmethod
    @pytest.mark.parametrize('mode', MODES)
    def test_permissions(container: ops.Container, tmp_path: pathlib.Path, mode: str | None):
        permissions = int(f'0o{mode}', base=8) if mode is not None else mode
        directory = tmp_path / 'directory'
        # container
        assert not directory.exists()
        file_ops.FileOps(container).make_dir(directory,make_parents=True, permissions=permissions)
        assert directory.exists()
        info_dir_c = _path_to_fileinfo(directory)
        # cleanup
        rmdir(directory)
        # no container
        assert not directory.exists()
        file_ops.FileOps().make_dir(directory,make_parents=True, permissions=permissions)
        assert directory.exists()
        info_dir = _path_to_fileinfo(directory)
        # cleanup
        rmdir(directory)
        # comparison
        write_for_debugging(
            f'make_dir_permissions_{mode}',
            info_dir_c=info_dir_c,
            info_dir=info_dir,
        )
        assert_fileinfo_eq(info_dir, info_dir_c)

    @staticmethod
    @pytest.mark.parametrize('mode', GOOD_PARENT_DIRECTORY_MODES)
    def test_subdirectory_make_parents(container: ops.Container, tmp_path: pathlib.Path, mode: str | None):
        permissions = int(f'0o{mode}', base=8) if mode is not None else mode
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        # container
        assert not subdirectory.exists()
        assert not directory.exists()
        file_ops.FileOps(container).make_dir(subdirectory,make_parents=True, permissions=permissions)
        assert directory.exists()
        assert subdirectory.exists()
        info_sub_c = _path_to_fileinfo(subdirectory)
        info_dir_c = _path_to_fileinfo(directory)
        # cleanup
        rmdir(subdirectory)
        rmdir(directory)
        # no container
        assert not subdirectory.exists()
        assert not directory.exists()
        file_ops.FileOps().make_dir(subdirectory,make_parents=True, permissions=permissions)
        assert directory.exists()
        assert subdirectory.exists()
        info_sub = _path_to_fileinfo(subdirectory)
        info_dir = _path_to_fileinfo(directory)
        # cleanup
        rmdir(subdirectory)
        rmdir(directory)
        # comparison
        write_for_debugging(
            f'make_dir_subdirectory_make_parents_{mode}',
            info_sub_c=info_sub_c,
            info_sub=info_sub,
            info_dir_c=info_dir_c,
            info_dir=info_dir,
        )
        assert_fileinfo_eq(info_sub, info_sub_c)
        assert_fileinfo_eq(info_dir, info_dir_c)

    @staticmethod
    @pytest.mark.parametrize('mode', BAD_PARENT_DIRECTORY_MODES_NO_CREATE)
    def test_subdirectory_make_parents_bad_permissions_no_create(container: ops.Container, tmp_path: pathlib.Path, mode: str | None):
        """The permissions are bad because they lack the execute permission.

        This means that directory is created without the ability to write to it,
        and subdirectory creation then fails with a permission error.
        """
        permissions = int(f'0o{mode}', base=8) if mode is not None else mode
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        # container
        assert not subdirectory.exists()
        assert not directory.exists()
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(subdirectory,make_parents=True, permissions=permissions)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert directory.exists()
        info_dir_c = _path_to_fileinfo(directory)
        os.chmod(directory, 0o755)
        assert not subdirectory.exists()
        # cleanup
        rmdir(directory)
        # no container
        assert not subdirectory.exists()
        assert not directory.exists()
        with pytest.raises(PermissionError) as exception_context:
            file_ops.FileOps().make_dir(subdirectory,make_parents=True, permissions=permissions)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert directory.exists()
        info_dir = _path_to_fileinfo(directory)
        os.chmod(directory, 0o755)
        assert not subdirectory.exists()
        # cleanup
        rmdir(directory)
        # comparison
        write_for_debugging(
            f'make_dir_subdirectory_make_parents_{mode}',
            info_dir_c=info_dir_c,
            info_dir=info_dir,
        )
        assert_fileinfo_eq(info_dir, info_dir_c)

    @staticmethod
    @pytest.mark.parametrize('mode', BAD_PARENT_DIRECTORY_MODES_CREATE)
    def test_subdirectory_make_parents_bad_permissions_create(container: ops.Container, tmp_path: pathlib.Path, mode: str | None):
        """The permissions are bad because they lack the read permission.

        Pebble must try some operation that requires read permissions on the parent directory
        after creating the file inside it.
        """
        permissions = int(f'0o{mode}', base=8) if mode is not None else mode
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        # container
        assert not subdirectory.exists()
        assert not directory.exists()
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(subdirectory,make_parents=True, permissions=permissions)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert directory.exists()
        info_dir_c = _path_to_fileinfo(directory)
        info_subdir_c = _path_to_fileinfo(subdirectory)
        os.chmod(directory, 0o755)
        assert subdirectory.exists()
        # cleanup
        rmdir(subdirectory)
        rmdir(directory)
        # no container
        assert not subdirectory.exists()
        assert not directory.exists()
        with pytest.raises(PermissionError) as exception_context:
            file_ops.FileOps().make_dir(subdirectory,make_parents=True, permissions=permissions)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert directory.exists()
        info_dir = _path_to_fileinfo(directory)
        info_subdir = _path_to_fileinfo(subdirectory)
        os.chmod(directory, 0o755)
        assert subdirectory.exists()
        # cleanup
        rmdir(subdirectory)
        rmdir(directory)
        # comparison
        write_for_debugging(
            f'make_dir_subdirectory_make_parents_{mode}',
            info_dir_c=info_dir_c,
            info_dir=info_dir,
            info_subdir_c=info_subdir_c,
            info_subdir=info_subdir,
        )
        assert_fileinfo_eq(info_dir, info_dir_c)
        assert_fileinfo_eq(info_subdir, info_subdir_c)

    @staticmethod
    @pytest.mark.parametrize('mode', BAD_PARENT_DIRECTORY_MODES_CREATE)
    def test_subdirectory_make_parents_bad_permissions_create_nested(container: ops.Container, tmp_path: pathlib.Path, mode: str | None):
        """The permissions are bad because they lack the read permission.

        Pebble must try some operation that requires read permissions on the parent directory
        after creating the file inside it.
        """
        permissions = int(f'0o{mode}', base=8) if mode is not None else mode
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        subsubdirectory = subdirectory / 'subsubdirectory'
        # container
        assert not subsubdirectory.exists()
        assert not subdirectory.exists()
        assert not directory.exists()
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(subdirectory,make_parents=True, permissions=permissions)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert directory.exists()
        info_dir_c = _path_to_fileinfo(directory)
        os.chmod(directory, 0o755)
        assert subdirectory.exists()
        info_subdir_c = _path_to_fileinfo(subdirectory)
        assert not subsubdirectory.exists()
        # cleanup
        rmdir(subdirectory)
        rmdir(directory)
        # no container
        assert not subsubdirectory.exists()
        assert not subdirectory.exists()
        assert not directory.exists()
        with pytest.raises(PermissionError) as exception_context:
            file_ops.FileOps().make_dir(subdirectory,make_parents=True, permissions=permissions)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert directory.exists()
        info_dir = _path_to_fileinfo(directory)
        os.chmod(directory, 0o755)
        assert subdirectory.exists()
        info_subdir = _path_to_fileinfo(subdirectory)
        assert not subsubdirectory.exists()
        # cleanup
        rmdir(subdirectory)
        rmdir(directory)
        # comparison
        write_for_debugging(
            f'make_dir_subdirectory_make_parents_{mode}',
            info_dir_c=info_dir_c,
            info_dir=info_dir,
            info_subdir_c=info_subdir_c,
            info_subdir=info_subdir,
        )
        assert_fileinfo_eq(info_dir, info_dir_c)
        assert_fileinfo_eq(info_subdir, info_subdir_c)

    @staticmethod
    @staticmethod
    def test_subdirectory_no_make_parents(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        # container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(subdirectory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        assert not subdirectory.exists()
        assert not directory.exists()
        # no container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().make_dir(subdirectory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        assert not subdirectory.exists()
        assert not directory.exists()

    @staticmethod
    def test_subdirectory_already_exists_make_parents(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        subdirectory.mkdir(parents=True)
        # with container
        file_ops.FileOps(container).make_dir(subdirectory, make_parents=True)
        # without container
        file_ops.FileOps().make_dir(subdirectory, make_parents=True)

    @staticmethod
    def test_subdirectory_already_exists_no_make_parents(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        subdirectory.mkdir(parents=True)
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(subdirectory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileExistsPathError)
        # without container
        with pytest.raises(FileExistsError) as exception_context:
            file_ops.FileOps().make_dir(subdirectory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileExistsPathError)

    @staticmethod
    def test_path_not_absolute(container: ops.Container):
        path = pathlib.Path('path.test')
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(path)
        assert isinstance(exception_context.value, file_ops.RelativePathError)
        with pytest.raises(file_ops.RelativePathError):
            file_ops.FileOps().make_dir(path)

    @staticmethod
    def test_chown_root_without_privileges(container: ops.Container, tmp_path: pathlib.Path):
        # TODO: what if we do have root privileges, like in ci?
        user_id = 0
        user_name = 'root'
        directory = tmp_path / 'directory'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user=user_name, user_id=user_id)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert not pathlib.Path(directory).exists()
        # without container
        with pytest.raises(PermissionError) as exception_context:
            file_ops.FileOps().make_dir(directory, user=user_name, user_id=user_id)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert not pathlib.Path(directory).exists()

    @staticmethod
    def test_chown_when_user_doesnt_exist(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: user that doesn't exist
        user_name = 'fake_user'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user=user_name)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.LookupPathError)
        assert not pathlib.Path(directory).exists()
        # without container
        with pytest.raises(LookupError) as exception_context:
            file_ops.FileOps().make_dir(directory, user=user_name)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.LookupPathError)
        assert not pathlib.Path(directory).exists()

    @staticmethod
    def test_chown_when_user_id_and_group_id_dont_exist(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user_id=9000, group_id=9001)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert not pathlib.Path(directory).exists()
        # without container
        with pytest.raises(PermissionError) as exception_context:
            file_ops.FileOps().make_dir(directory, user_id=9000, group_id=9001)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        assert not pathlib.Path(directory).exists()

    @staticmethod
    def test_chown_just_user(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: user that exists
        user_name = 'user'
        # with container
        file_ops.FileOps(container).make_dir(directory, user=user_name)
        assert directory.exists()
        rmdir(directory)
        # without container
        file_ops.FileOps().make_dir(directory, user=user_name)
        assert directory.exists()
        rmdir(directory)

    @staticmethod
    def test_chown_just_user_id(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: user that exists
        user_id = 1000
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user_id=user_id)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        # without container
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().make_dir(directory, user_id=user_id)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)

    @staticmethod
    def test_chown_just_group_name(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: user that exists
        group = 'user'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, group=group)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        # without container
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().make_dir(directory, group=group)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)

    @staticmethod
    def test_chown_just_group_id(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: user that exists
        group_id = 1000
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, group_id=group_id)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        # without container
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().make_dir(directory, group_id=group_id)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)

    @staticmethod
    def test_chown_just_group_args(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: user that exists
        group = 'user'
        group_id = 1000
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, group=group, group_id=group_id)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        # without container
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().make_dir(directory, group=group, group_id=group_id)
        assert not directory.exists()
        assert isinstance(exception_context.value, file_ops.ValuePathError)

    @staticmethod
    def test_chown_when_user_and_user_id_both_exist_but_dont_match(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        # TODO: find a user and user id combo or way to get it dynamically that
        # will exist at runtime but won't match
        user_id = 0
        user_name = 'user'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user=user_name, user_id=user_id)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        assert not pathlib.Path(directory).exists()
        # without container
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().make_dir(directory, user=user_name, user_id=user_id)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        assert not pathlib.Path(directory).exists()

    @staticmethod
    def test_chown_when_user_and_user_id_both_provided_but_at_least_one_doesnt_exist(container: ops.Container, tmp_path: pathlib.Path):
        # TODO: better way to make user and user_id
        user_id = 9000
        user_name = 'user-that-doesnt-exist-hopefully'
        directory = tmp_path / 'directory'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user=user_name, user_id=user_id)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.LookupPathError)
        assert not pathlib.Path(directory).exists()
        # without container
        with pytest.raises(LookupError) as exception_context:
            file_ops.FileOps().make_dir(directory, user=user_name, user_id=user_id)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.LookupPathError)
        assert not pathlib.Path(directory).exists()


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestRemovePath:
    @staticmethod
    def test_target_doesnt_exist(container: ops.Container, tmp_path: pathlib.Path):
        file = tmp_path / 'doesnt_exist'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        # without container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)

    @staticmethod
    def test_target_parent_doesnt_exist(container: ops.Container, tmp_path: pathlib.Path):
        file = tmp_path / 'does/not/exist'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        # without container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)

    @staticmethod
    def test_path_not_absolute(container: ops.Container):
        path = pathlib.Path('path.test')
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).remove_path(path)
        assert isinstance(exception_context.value, file_ops.RelativePathError)
        with pytest.raises(file_ops.RelativePathError):
            file_ops.FileOps().remove_path(path)


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestPush:
    @staticmethod
    def test_str_ok(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = 'hello world'
        # container
        assert not path.exists()
        file_ops.FileOps(container).push(path=path, source=contents)
        assert path.read_text() == contents
        path.unlink()
        # no container
        assert not path.exists()
        file_ops.FileOps().push(path=path, source=contents)
        assert path.read_text() == contents

    @staticmethod
    def test_bytes_ok(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = b'hello world'
        # container
        assert not path.exists()
        file_ops.FileOps(container).push(path=path, source=contents)
        assert path.read_bytes() == contents
        path.unlink()
        # no container
        assert not path.exists()
        file_ops.FileOps().push(path=path, source=contents)
        assert path.read_bytes() == contents

    @staticmethod
    def test_text_file_ok(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = 'hello world'
        source = tmp_path / 'source.test'
        source.write_text(contents)
        # container
        assert not path.exists()
        with source.open() as f:
            file_ops.FileOps(container).push(path=path, source=f)
        assert path.read_text() == contents
        path.unlink()
        # no container
        assert not path.exists()
        with source.open() as f:
            file_ops.FileOps().push(path=path, source=f)
        assert path.read_text() == contents

    @staticmethod
    def test_binary_file_ok(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = bytearray(range(256))
        source = tmp_path / 'source.test'
        source.write_bytes(contents)
        # container
        assert not path.exists()
        with source.open('rb') as f:
            file_ops.FileOps(container).push(path=path, source=f)
        assert path.read_bytes() == contents
        path.unlink()
        # no container
        assert not path.exists()
        with source.open('rb') as f:
            file_ops.FileOps().push(path=path, source=f)
        assert path.read_bytes() == contents

    @staticmethod
    def test_path_not_absolute(container: ops.Container):
        path = pathlib.Path('path.test')
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).push(path, source='')
        assert isinstance(exception_context.value, file_ops.RelativePathError)
        with pytest.raises(file_ops.RelativePathError):
            file_ops.FileOps().push(path, source='')

    @staticmethod
    @pytest.mark.parametrize('mode', MODES)
    def test_subdirectory_make_dirs(container: ops.Container, tmp_path: pathlib.Path, mode: str | None):
        permissions = int(f'0o{mode}', base=8) if mode is not None else mode
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        path = subdirectory / 'path.test'
        contents = 'hello world'
        # container
        assert not path.exists()
        assert not subdirectory.exists()
        assert not directory.exists()
        file_ops.FileOps(container).push(path=path, source=contents, make_dirs=True, permissions=permissions)
        assert directory.exists()
        assert subdirectory.exists()
        assert path.exists()
        info_pat_c = _path_to_fileinfo(path)
        info_sub_c = _path_to_fileinfo(subdirectory)
        info_dir_c = _path_to_fileinfo(directory)
        os.chmod(path, 0o400)
        assert path.read_text() == contents
        # cleanup
        path.unlink()
        rmdir(subdirectory)
        rmdir(directory)
        # no container
        assert not path.exists()
        assert not subdirectory.exists()
        assert not directory.exists()
        file_ops.FileOps().push(path=path, source=contents, make_dirs=True, permissions=permissions)
        assert directory.exists()
        assert subdirectory.exists()
        assert path.exists()
        info_pat = _path_to_fileinfo(path)
        info_sub = _path_to_fileinfo(subdirectory)
        info_dir = _path_to_fileinfo(directory)
        os.chmod(path, 0o400)
        assert path.read_text() == contents
        # cleanup
        path.unlink()
        rmdir(subdirectory)
        rmdir(directory)
        # comparison
        write_for_debugging(
            f'push_subdirectory_make_dirs_{mode}',
            info_pat_c=info_pat_c,
            info_pat=info_pat,
            info_sub_c=info_sub_c,
            info_sub=info_sub,
            info_dir_c=info_dir_c,
            info_dir=info_dir,
        )
        assert_fileinfo_eq(info_pat, info_pat_c)
        assert_fileinfo_eq(info_sub, info_sub_c)
        assert_fileinfo_eq(info_dir, info_dir_c)

    @staticmethod
    def test_subdirectory_no_make_dirs(container: ops.Container, tmp_path: pathlib.Path):
        directory = tmp_path / 'directory'
        subdirectory = directory / 'subdirectory'
        path = subdirectory / 'path.test'
        contents = 'hello world'
        # container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).push(path=path, source=contents)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        assert not path.exists()
        assert not subdirectory.exists()
        assert not directory.exists()
        # no container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().make_dir(subdirectory)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        assert not path.exists()
        assert not subdirectory.exists()
        assert not directory.exists()


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestPull:
    @staticmethod
    def test_str_ok(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = 'hello world'
        path.write_text(contents)
        # container
        f = file_ops.FileOps(container).pull(path)
        assert f.read() == contents
        # no container
        f = file_ops.FileOps().pull(path)
        assert f.read() == contents

    @staticmethod
    def test_bytes_ok(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = b'hello world'
        path.write_bytes(contents)
        # container
        f = file_ops.FileOps(container).pull(path, encoding=None)
        assert f.read() == contents
        # no container
        f = file_ops.FileOps().pull(path, encoding=None)
        assert f.read() == contents

    @staticmethod
    def test_str_bad_encoding_argument(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = 'hello world'
        path.write_text(contents)
        # container
        with pytest.raises(LookupError):
            file_ops.FileOps(container).pull(path, encoding='bad')
        # no container
        with pytest.raises(LookupError):
            file_ops.FileOps().pull(path, encoding='bad')

    @staticmethod
    def test_str_encoding_doesnt_match(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        contents = bytes(range(256))
        path.write_bytes(contents)
        # container
        f = file_ops.FileOps(container).pull(path, encoding='utf-8')
        with pytest.raises(UnicodeDecodeError):
            f.read()
        # no container
        f = file_ops.FileOps().pull(path, encoding='utf-8')
        with pytest.raises(UnicodeDecodeError):
            f.read()

    @staticmethod
    def test_target_doesnt_exist(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        # container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).pull(path)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        # no container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().pull(path)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)

    @staticmethod
    def test_no_permission(container: ops.Container, tmp_path: pathlib.Path):
        path = tmp_path / 'path.test'
        path.write_text('')
        os.chmod(path, 0)
        # container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).pull(path)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)
        # no container
        with pytest.raises(PermissionError) as exception_context:
            file_ops.FileOps().pull(path)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.PermissionPathError)

    @staticmethod
    def test_path_not_absolute(container: ops.Container):
        path = pathlib.Path('path.test')
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).pull(path)
        assert isinstance(exception_context.value, file_ops.RelativePathError)
        with pytest.raises(file_ops.RelativePathError):
            file_ops.FileOps().pull(path)


def fileinfo_eq(self: ops.pebble.FileInfo, other: ops.pebble.FileInfo, include_last_modified: bool = False) -> bool:
    return all(
        getattr(self, name) == getattr(other, name)
        for name in dir(self)
        if (
            not name.startswith('_')
            and (include_last_modified or name != "last_modified")
        )
    )


def assert_fileinfo_eq(self: ops.pebble.FileInfo, other: ops.pebble.FileInfo, include_last_modified: bool = False) -> None:
    for name in dir(self):
        if name.startswith('_'):
            continue
        if not include_last_modified and name == "last_modified":
            continue
        assert (name, getattr(self, name)) == (name, getattr(other, name))


def write_for_debugging(identifier: str, **kwargs: object):
    if DEBUG:
        out = pathlib.Path('.tmp') / f'{identifier}.py'
        out.parent.mkdir(exist_ok=True)
        out.write_text('\n'.join(f'{k} = {v}' for k, v in kwargs.items()))
        subprocess.run(['ruff', 'format', '--config', 'line-length=200', str(out)])


def rmdir(path: pathlib.Path) -> None:
    os.chmod(path, 0o755)
    path.rmdir()
