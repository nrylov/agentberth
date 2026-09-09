"""Bounded ZIP/TAR inspection and extraction inside a run workspace."""

from pathlib import Path
import shutil
import os
import stat
import tarfile
import tempfile
import zipfile

from runtime.files import validate_name

MAX_ENTRIES = 128
MAX_EXPANDED = 16 * 1024 * 1024
MAX_MEMBER = 4 * 1024 * 1024


def is_archive(name):
    return name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))


def process(arguments, context):
    source = context.workspace_path(arguments["path"])
    destination = context.workspace_path(arguments["destination"])
    if destination.exists():
        raise ValueError("Archive destination must be a new directory.")
    if not source.is_file() or source.is_symlink():
        raise ValueError("Archive must be a regular workspace file.")
    total = 0
    members = []
    names = set()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".extract-") as temporary:
        root = Path(temporary)

        def unpack(name, size, directory, reader):
            nonlocal total
            name = validate_name(name.rstrip("/"))
            if len(name.split("/")) > 12 or name in names or len(names) >= MAX_ENTRIES:
                raise ValueError("Archive has duplicate paths or exceeds entry/depth limits.")
            names.add(name)
            target = root / name
            if directory:
                target.mkdir(parents=True, exist_ok=True)
                return
            if size > MAX_MEMBER or total + size > MAX_EXPANDED:
                raise ValueError("Archive exceeds expanded size limits (4 MiB per file, 16 MiB total).")
            target.parent.mkdir(parents=True, exist_ok=True)
            with reader() as stream, target.open("xb") as output:
                count = 0
                while chunk := stream.read(65536):
                    count += len(chunk)
                    total += len(chunk)
                    if count > MAX_MEMBER or total > MAX_EXPANDED:
                        raise ValueError("Archive exceeds expanded size limits.")
                    output.write(chunk)
            members.append({"path": str(destination / name), "size": count})

        if source.name.lower().endswith(".zip"):
            with zipfile.ZipFile(source) as archive:
                for entry in archive.infolist():
                    mode = entry.external_attr >> 16
                    if (
                        entry.flag_bits & 1
                        or stat.S_ISLNK(mode)
                        or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                    ):
                        raise ValueError("Encrypted archives, links, and special files are not supported.")
                    unpack(entry.filename, entry.file_size, entry.is_dir(), lambda e=entry: archive.open(e))
        else:
            # Streaming mode avoids loading an unbounded member table into memory.
            with tarfile.open(source, mode="r|*") as archive:
                for entry in archive:
                    if not (entry.isfile() or entry.isdir()):
                        raise ValueError("Archive links and special files are not supported.")
                    unpack(entry.name, entry.size, entry.isdir(), lambda e=entry: archive.extractfile(e))
        # Only publish the extraction after every member passed validation.
        shutil.move(str(root), str(destination))
    return {"files": members, "total_bytes": total}


def pack(arguments, context):
    source = context.workspace_path(arguments["path"])
    destination = context.workspace_path(arguments["destination"])
    if not source.is_dir() or destination.exists() or destination.is_relative_to(source):
        raise ValueError("Pack a directory into a new ZIP path outside that directory.")
    names, total = [], 0
    scanned = 0
    for directory, folders, files in os.walk(source, followlinks=False):
        scanned += len(folders) + len(files)
        if scanned > MAX_ENTRIES:
            raise ValueError("Archive creation exceeds entry limits.")
        for name in folders + files:
            if (Path(directory) / name).is_symlink():
                raise ValueError("Archive creation does not include symlinks.")
        for filename in sorted(files):
            path = Path(directory) / filename
            name = validate_name(str(path.relative_to(source)))
            total += path.stat().st_size
            if total > MAX_EXPANDED or path.stat().st_size > MAX_MEMBER:
                raise ValueError("Archive creation exceeds size limits.")
            names.append((path, name))
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name in names:
                archive.write(path, name)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {"path": arguments["destination"], "file_count": len(names)}
