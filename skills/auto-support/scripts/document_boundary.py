"""Filesystem checks shared by retrieval and the public-document tool hook."""
import os
import stat


def single_link_regular(status):
    return stat.S_ISREG(status.st_mode) and status.st_nlink == 1


def allowed_document(path, *, missing_ok=False, directory=False):
    """Reject unsafe inodes; propagate unavailable metadata for caller-specific handling."""
    try:
        status = os.stat(path)
    except FileNotFoundError:
        # A missing hook target cannot disclose contents; retrieval requires existence.
        if missing_ok:
            return True
        raise
    if directory and stat.S_ISDIR(status.st_mode):
        return True
    return single_link_regular(status)
