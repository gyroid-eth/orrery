"""Recognize Windows drives from the mount namespace of a WSL process."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MOUNTINFO = Path("/proc/self/mountinfo")
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


def running_in_wsl() -> bool:
    return sys.platform == "linux" and "microsoft" in os.uname().release.lower()


def drvfs_metadata(path: Path, device: int) -> bool | None:
    """Return whether the active DrvFs mount has Linux metadata enabled."""
    if not running_in_wsl():
        return None
    device_id = f"{os.major(device)}:{os.minor(device)}"
    matches = []
    try:
        mountinfo = MOUNTINFO.read_text(encoding="utf-8", errors="surrogateescape")
        for line in mountinfo.split("\n"):
            left, separator, right = line.partition(" - ")
            fields, filesystem = left.split(" "), right.split(" ")
            if not separator or len(fields) < 6 or len(filesystem) != 3:
                continue
            mount = Path(_MOUNT_ESCAPE.sub(lambda match: chr(int(match[1], 8)), fields[4]))
            if not mount.is_absolute() or not path.is_relative_to(mount):
                continue
            fs_type, _, fs_options = filesystem
            drvfs = fs_type == "drvfs" or (
                fs_type == "9p" and any(option.split(";", 1)[0] == "aname=drvfs"
                                        for option in fs_options.split(","))
            )
            options = re.split("[;,]", fields[5] + "," + fs_options)
            metadata = any(option.split("=", 1)[0] == "metadata"
                           for option in options) if drvfs else None
            matches.append((len(mount.parts), fields[2], metadata))
    except OSError:
        return None
    if not matches:
        return None
    depth = max(item[0] for item in matches)
    active = {metadata for length, mounted_device, metadata in matches
              if length == depth and mounted_device == device_id}
    return active.pop() if len(active) == 1 else None
