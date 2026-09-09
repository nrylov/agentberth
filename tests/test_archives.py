import io
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from runtime.archives import process


@pytest.fixture
def workspace(tmp_path):
    return tmp_path, SimpleNamespace(workspace_path=lambda value: tmp_path / value)


@pytest.mark.parametrize("kind", ["zip", "tar", "tar.gz"])
def test_extract_supported_formats(workspace, kind):
    root, context = workspace
    path = root / ("input." + kind)
    data = b"\x00\xffbinary"
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("nested/data.bin", data)
    else:
        with tarfile.open(path, "w:gz" if kind == "tar.gz" else "w") as t:
            entry = tarfile.TarInfo("nested/data.bin")
            entry.size = len(data)
            t.addfile(entry, io.BytesIO(data))
    result = process({"path": path.name, "destination": "extracted"}, context)
    assert (root / "extracted/nested/data.bin").read_bytes() == data
    assert result["total_bytes"] == len(data)


@pytest.mark.parametrize("name", ["../escape", "/absolute", "nested/../../escape"])
def test_zip_traversal_rejected_atomically(workspace, name):
    root, context = workspace
    with zipfile.ZipFile(root / "bad.zip", "w") as z:
        z.writestr("valid.txt", b"valid")
        z.writestr(name, b"unsafe")
    with pytest.raises(ValueError):
        process({"path": "bad.zip", "destination": "extracted"}, context)
    assert not (root / "extracted").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "device"])
def test_tar_links_and_devices_rejected(workspace, kind):
    root, context = workspace
    with tarfile.open(root / "bad.tar", "w") as t:
        entry = tarfile.TarInfo("link")
        entry.type = {"symlink": tarfile.SYMTYPE, "hardlink": tarfile.LNKTYPE, "device": tarfile.CHRTYPE}[
            kind
        ]
        entry.linkname = "/etc/passwd"
        t.addfile(entry)
    with pytest.raises(ValueError):
        process({"path": "bad.tar", "destination": "extracted"}, context)


def test_archive_expansion_and_entry_limits(workspace):
    root, context = workspace
    with zipfile.ZipFile(root / "large.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.txt", b"a" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="expanded size"):
        process({"path": "large.zip", "destination": "extracted"}, context)
    with zipfile.ZipFile(root / "many.zip", "w") as z:
        for i in range(129):
            z.writestr(str(i), b"")
    with pytest.raises(ValueError, match="entry/depth"):
        process({"path": "many.zip", "destination": "extracted"}, context)


def test_pack_directory(workspace):
    from runtime.archives import pack

    root, context = workspace
    (root / "source").mkdir()
    (root / "source/data.bin").write_bytes(b"\x00\xff")
    assert pack({"path": "source", "destination": "bundle.zip"}, context)["file_count"] == 1
    with zipfile.ZipFile(root / "bundle.zip") as z:
        assert z.read("data.bin") == b"\x00\xff"
