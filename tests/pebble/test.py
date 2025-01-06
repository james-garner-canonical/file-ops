import os
import pathlib
import shutil

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

    def test_subdirectory_make_parents(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        subdirectory = directory / 'subdirectory'
        if directory.exists():
            directory.rmdir()
        # container
        file_ops.FileOps(container).make_dir(subdirectory, make_parents=True)
        assert subdirectory.exists()
        shutil.rmtree(directory)
        # no container
        file_ops.FileOps().make_dir(directory, make_parents=True)
        assert directory.exists()
        # cleanup
        shutil.rmtree(directory)

    def test_subdirectory_no_make_parents(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        subdirectory = directory / 'subdirectory'
        if directory.exists():
            directory.rmdir()
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

    def test_subdirectory_already_exists_make_parents(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        subdirectory = directory / 'subdirectory'
        subdirectory.mkdir(exist_ok=True, parents=True)
        # with container
        file_ops.FileOps(container).make_dir(subdirectory, make_parents=True)
        # without container
        file_ops.FileOps().make_dir(subdirectory, make_parents=True)
        # cleanup
        shutil.rmtree(directory)

    def test_subdirectory_already_exists_no_make_parents(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        subdirectory = directory / 'subdirectory'
        subdirectory.mkdir(exist_ok=True, parents=True)
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
        shutil.rmtree(directory)

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

    def test_chown_when_user_doesnt_exist(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_just_user(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
        # TODO: user that exists
        user_name = 'user'
        # with container
        file_ops.FileOps(container).make_dir(directory, user=user_name)
        assert directory.exists()
        directory.rmdir()
        # without container
        file_ops.FileOps().make_dir(directory, user=user_name)
        assert directory.exists()
        directory.rmdir()

    def test_just_user_id(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_just_group_name(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_just_group_id(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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

    def test_just_group_args(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test/tmpdir')
        if directory.exists():
            directory.rmdir()
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
    def test_target_doesnt_exist(self, container: ops.Container):
        file = '/does/not/exist'
        # with container
        with pytest.raises(ops.pebble.PathError) as exception_context:
            file_ops.FileOps(container).remove_path(file)
        print(exception_context.value)
        assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)
        # without container
        with pytest.raises(NotImplementedError) as exception_context:
            file_ops.FileOps().remove_path(file)
        print(exception_context.value)
        #assert isinstance(exception_context.value, file_ops.FileNotFoundPathError)


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestPull:
    def test_str_ok(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test')
        path = directory / 'path.test'
        contents = 'hello world'
        path.write_text(contents)
        # container
        f = file_ops.FileOps(container).pull(path)
        assert f.read() == contents
        # no container
        f = file_ops.FileOps().pull(path)
        assert f.read() == contents
        # cleanup
        path.unlink()

    def test_bytes_ok(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test')
        path = directory / 'path.test'
        contents = b'hello world'
        path.write_bytes(contents)
        # container
        f = file_ops.FileOps(container).pull(path, encoding=None)
        assert f.read() == contents
        # no container
        f = file_ops.FileOps().pull(path, encoding=None)
        assert f.read() == contents
        # cleanup
        path.unlink()

    def test_str_bad_encoding_argument(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test')
        path = directory / 'path.test'
        contents = 'hello world'
        path.write_text(contents)
        # container
        with pytest.raises(LookupError):
            file_ops.FileOps(container).pull(path, encoding='bad')
        # no container
        with pytest.raises(LookupError):
            file_ops.FileOps().pull(path, encoding='bad')
        # cleanup
        path.unlink()

    def test_str_encoding_doesnt_match(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test')
        path = directory / 'path.test'
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
        # cleanup
        path.unlink()

    def test_target_doesnt_exist(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test')
        path = directory / 'path.test'
        assert not path.exists()
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

    def test_no_permission(self, container: ops.Container):
        directory = pathlib.Path('/tmp/pebble-test')
        path = directory / 'path.test'
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
        # cleanup
        path.unlink()
