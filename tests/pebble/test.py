import os
import pathlib

import file_ops
import ops
import pytest

import file_ops._exceptions


def get_socket_path() -> str:
    socket_path = os.getenv('PEBBLE_SOCKET')
    pebble_path = os.getenv('PEBBLE')
    if not socket_path and pebble_path:
        assert isinstance(pebble_path, str)
        socket_path = os.path.join(pebble_path, '.pebble.socket')
    assert socket_path, 'PEBBLE or PEBBLE_SOCKET must be set if RUN_REAL_PEBBLE_TESTS set'
    return socket_path


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


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestListFiles:
    def test_ok(self, container: ops.Container):
        """Test list_files in the pebble directory with some extras in there -- empty file, empty directory.

        This can sometimes fail if pebble writes to .pebble.state in between the two list_files executions lol
        But a convenient way to run tests with a socket ...
        TODO: a proper test data directory that we spin up a socket in
        TODO: a block device too I guess
        """
        # setup start
        directory = pathlib.Path('/tmp/pebble-test')
        (directory / 'empty_dir').mkdir(exist_ok=True, parents=True)
        (directory / 'empty_file').write_bytes(b'')
        py = directory / 'python3'
        if not py.exists():
            py.symlink_to('/usr/bin/python3')
        # setup end
        with_container = file_ops.FileOps(container).list_files(directory)
        without_container = file_ops.FileOps().list_files(directory)
        # debugging start
        pathlib.Path('tmp.py').write_text("\n".join([
            "'with_container'",
            str(with_container),
            "'without_container'",
            str(without_container),
        ]))
        import subprocess
        subprocess.run(['ruff', 'format', '--config', 'line-length=200', 'tmp.py'])
        # debugging end
        import unittest.mock
        def fileinfo_eq(self: ops.pebble.FileInfo, other: ops.pebble.FileInfo) -> bool:
            return all(
                getattr(self, name) == getattr(other, name)
                for name in dir(self)
                if not name.startswith('_')
            )
        with unittest.mock.patch.object(ops.pebble.FileInfo, '__eq__', fileinfo_eq):
            assert (
                sorted(with_container, key=lambda fileinfo: fileinfo.name)
                == sorted(without_container, key=lambda fileinfo: fileinfo.name)
            )

    def test_target_doesnt_exist(self, container: ops.Container):
        file = '/does/not/exist/'
        # with container
        with pytest.raises(ops.pebble.APIError) as exception_context:
            file_ops.FileOps(container).list_files(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundAPIError)
        # without container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().list_files(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundAPIError)


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestMakeDir:
    def test_ok(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
        file_ops.FileOps(container).make_dir(directory)
        assert directory.exists()
        directory.rmdir()
        file_ops.FileOps().make_dir(directory)
        assert directory.exists()
        directory.rmdir()

    def test_directory_already_exists(self, container: ops.Container):
        directory = '/tmp/pebble-test/tmpdir'
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

    def test_chown_root_without_privileges(self, container: ops.Container):
        # TODO: what if we do have root privileges, like in ci?
        user_id = 0
        user_name = 'root'
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_chown_when_user_id_doesnt_exist(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).make_dir(directory, user_id=9000)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        assert not pathlib.Path(directory).exists()
        # without container
        with pytest.raises(ValueError) as exception_context:
            file_ops.FileOps().make_dir(directory, user_id=9000)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.ValuePathError)
        assert not pathlib.Path(directory).exists()

    def test_chown_when_user_id_and_group_id_dont_exist(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_chown_when_user_and_user_id_both_exist_but_dont_match(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_chown_when_user_and_user_id_both_provided_but_at_least_one_doesnt_exist(self, container: ops.Container):
        # TODO: better way to make user and user_id
        user_id = 9000
        user_name = 'user-that-doesnt-exist-hopefully'
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestRemovePath:
    def test_target_doesnt_exist(self, container: ops.Container):
        file = '/does/not/exist'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        return
        # without container
        with pytest.raises(FileNotFoundError) as exception_context:
            file_ops.FileOps().remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
