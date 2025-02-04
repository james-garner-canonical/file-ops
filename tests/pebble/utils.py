# modes
# strings for nicer pytest output


import os
import pathlib
import socket
import string
from typing import Iterator

import ops
import pytest


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
_MODES: tuple[str | None, ...] = (
    *GOOD_PARENT_DIRECTORY_MODES,
    *BAD_PARENT_DIRECTORY_MODES_NO_CREATE,
    *BAD_PARENT_DIRECTORY_MODES_CREATE
)
ALL_MODES: tuple[str | None, ...] = tuple(reversed(sorted(_MODES, key=str)))


def _get_socket_path() -> str:
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
        pebble_client=ops.pebble.Client(socket_path=_get_socket_path()),
    )


@pytest.fixture
def text_files() -> dict[str, str]:
    return {
        'foo.txt': string.ascii_lowercase,
        'bar.txt': string.ascii_uppercase * 2,
        'baz.txt': '',
    }


@pytest.fixture
def interesting_dir(tmp_path: pathlib.Path, text_files: dict[str, str]) -> Iterator[pathlib.Path]:
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
