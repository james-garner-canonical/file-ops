from __future__ import annotations

import grp
import pathlib
import pwd
import shutil


def get_user_arg(str_name: str | None, int_id: int | None) -> str | int | None:
    if str_name is not None:
        if int_id is not None:
            info = pwd.getpwnam(str_name)  # KeyError if user doesn't exist
            info_id = info.pw_uid
            if info_id != int_id:
                raise ValueError(
                    'If both user_id and user name are provided, they must match'
                    f' -- "{str_name}" has id {info_id} but {int_id} was provided.'
                )
        return str_name
    if int_id is not None:
        return int_id
    return None


def get_group_arg(str_name: str | None, int_id: int | None) -> str | int | None:
    if str_name is not None:
        if int_id is not None:
            info = grp.getgrnam(str_name)  # KeyError if group doesn't exist
            info_id = info.gr_gid
            if info_id != int_id:
                raise ValueError(
                    'If both group_id and group name are provided, they must match'
                    f' -- "{str_name}" has id {info_id} but {int_id} was provided.'
                )
        return str_name
    if int_id is not None:
        return int_id
    return None


def try_chown(path: pathlib.Path | str, user: int | str | None, group: int | str | None) -> None:
    # KeyError for user/group that doesn't exist, as pebble looks these up
    if isinstance(user, str):
        pwd.getpwnam(user)
    if isinstance(group, str):
        grp.getgrnam(group)
    # PermissionError for user_id/group_id that doesn't exist, as pebble tries to use these
    if isinstance(user, int):
        try:
            pwd.getpwuid(user)
        except KeyError as e:
            raise PermissionError(e) from e
    if isinstance(group, int):
        try:
            grp.getgrgid(group)
        except KeyError as e:
            raise PermissionError(e) from e
    # PermissionError for e.g. unprivileged user trying to chown as root
    if user is not None and group is not None:
        shutil.chown(path, user=user, group=group)
    elif user is not None:
        shutil.chown(path, user=user)
    elif group is not None:
        shutil.chown(path, group=group)
