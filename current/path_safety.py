"""Standard-library-only link boundaries for template initialization and packaging."""
import os
from pathlib import Path


def reject_link_ancestors(path: Path) -> None:
    path = path.absolute()
    for cursor in [path, *path.parents]:
        try:
            info = cursor.lstat()
        except FileNotFoundError:
            continue
        if cursor.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SystemExit('Symlink/junction/reparse point forbidden: ' + str(cursor) + ' -> ' + str(cursor.resolve()))


def ordinary_tree_files(root: Path, excluded_dirs=(), excluded_suffixes=()):
    reject_link_ancestors(root)
    def failed(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=failed):
        for name in list(dirs):
            path = Path(directory) / name
            reject_link_ancestors(path)
            if name in excluded_dirs:
                dirs.remove(name)
        for name in files:
            path = Path(directory) / name
            reject_link_ancestors(path)
            if path.suffix not in excluded_suffixes:
                yield path
