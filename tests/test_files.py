import base64

import pytest
from pydantic import ValidationError

from agentberth.schemas import RunInput, RunResult
from runtime import main
from runtime.files import MAX_FILE_BYTES, validate_name


def file(name="sample.bin", data=b"\x00\xff\x80"):
    return {"name": name, "content_base64": base64.b64encode(data).decode()}


@pytest.mark.parametrize("name", ["../x", "/x", "a/../x", "a//x", ".hidden", "a\\x", "a\nx", "a/"])
def test_reject_unsafe_names(name):
    with pytest.raises(ValueError):
        validate_name(name)


def test_input_validation_and_binary_roundtrip():
    value = RunInput(input="Read files", files=[file()])
    assert value.files[0].bytes_value() == b"\x00\xff\x80"
    for files in (
        [file(), file()],
        [file("a"), file("a/b")],
        [file(data=b"x" * (MAX_FILE_BYTES + 1))],
        [file(str(i), b"x" * MAX_FILE_BYTES) for i in range(5)],
        [{"name": "a", "content_base64": "!bad!"}],
    ):
        with pytest.raises(ValidationError):
            RunInput(input="Read files", files=files)


def test_legacy_and_binary_results():
    result = RunResult(output="Done", artifacts=[{"name": "a.txt", "content": "héllo"}, file()])
    assert result.artifacts[0].bytes_value() == "héllo".encode()
    assert result.artifacts[1].bytes_value() == b"\x00\xff\x80"
    with pytest.raises(ValidationError):
        RunResult(output="Done", artifacts=[{**file(), "content": "also text"}])


def test_stage_and_collect_binary_without_reexporting_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "WORKSPACE", tmp_path)
    main.stage_files({"spec": {"files": [file("nested/sample.bin")]}})
    assert (tmp_path / "inputs/nested/sample.bin").read_bytes() == b"\x00\xff\x80"
    assert main.artifacts() == []
    (tmp_path / "result.bin").write_bytes(b"\xff\x00")
    (tmp_path / "link.bin").symlink_to(tmp_path / "inputs/nested/sample.bin")
    result = main.artifacts()
    assert len(result) == 1
    assert base64.b64decode(result[0]["content_base64"]) == b"\xff\x00"
    (tmp_path / "too-large.bin").write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="limits exceeded"):
        main.artifacts()
