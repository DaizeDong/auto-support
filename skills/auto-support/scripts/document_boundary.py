"""Filesystem checks shared by retrieval and the public-document tool hook."""
import os
import stat


def single_link_regular(status):
    return stat.S_ISREG(status.st_mode) and status.st_nlink == 1


def allowed_document(path, *, missing_ok=False, directory=False):
    """Deny inode aliases and nonregular reads without opening their contents."""
    try:
        status = os.stat(path)
    except FileNotFoundError:
        # A missing hook target cannot disclose contents; retrieval requires existence.
        return missing_ok
    except OSError:
        return False
    if directory and stat.S_ISDIR(status.st_mode):
        return True
    return single_link_regular(status)
