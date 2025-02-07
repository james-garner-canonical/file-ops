# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
import pathlib

import ops
import pytest
from utils import (
    container,  # pyright: ignore[reportUnusedImport]  # noqa: F401
    interesting_dir,  # pyright: ignore[reportUnusedImport]  # noqa: F401
    text_files,  # pyright: ignore[reportUnusedImport]  # noqa: F401
)

from file_operations._pathlike import ContainerPath, LocalPath

DEBUG: bool = True
"""Write debugging info to files during tests."""


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestIterDir:
    @staticmethod
    def test_ok(container: ops.Container, interesting_dir: pathlib.Path):
        local_path = LocalPath(interesting_dir)
        local_list = list(local_path.iterdir())
        local_set = {str(p) for p in local_list}
        assert len(local_list) == len(local_set)
        container_path = ContainerPath(interesting_dir, container=container)
        container_list = list(container_path.iterdir())
        container_set = {str(p) for p in container_list}
        assert len(container_list) == len(container_set)
        assert local_set == container_set

    @staticmethod
    def test_given_not_a_directory_when_iterdir_then_raises(
        container: ops.Container, interesting_dir: pathlib.Path
    ):
        path = interesting_dir / 'empty_file.bin'
        local_path = LocalPath(path)
        with pytest.raises(NotADirectoryError) as ctx:
            next(local_path.iterdir())
        print(ctx.value)
        container_path = ContainerPath(path, container=container)
        with pytest.raises(NotADirectoryError) as ctx:
            next(container_path.iterdir())
        print(ctx.value)
