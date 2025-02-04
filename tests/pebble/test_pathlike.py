
# pyright: reportPrivateUsage=false
from __future__ import annotations

import unittest.mock
import os
import pathlib
import subprocess

import ops
import pytest
from file_operations import _errors
from file_operations import _fileinfo
from file_operations._pathlike import ContainerPath, LocalPath

from utils import (
    ALL_MODES,
    BAD_PARENT_DIRECTORY_MODES_CREATE,
    BAD_PARENT_DIRECTORY_MODES_NO_CREATE,
    GOOD_PARENT_DIRECTORY_MODES,
    container,  #pyright: ignore[reportUnusedImport]
    interesting_dir,  #pyright: ignore[reportUnusedImport]
    text_files,  #pyright: ignore[reportUnusedImport]
)


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
