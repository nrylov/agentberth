from pathlib import Path

import pytest

from runtime import tools


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    return tmp_path


def test_files_and_python_share_workspace(workspace):
    tools.execute("write_file", {"path": "data.txt", "content": "21"}, ["write_file"])
    result = tools.execute("python", {"code": "print(int(open('data.txt').read()) * 2)"}, ["python"])
    assert result == {"exit_code": 0, "output": "42\n"}
    assert tools.execute("read_file", {"path": "data.txt"}, ["read_file"]) == {"content": "21"}


@pytest.mark.parametrize("path", ["../escape.txt", "/etc/passwd", "."])
def test_file_tool_rejects_escape(workspace, path):
    with pytest.raises(ValueError, match="inside the workspace"):
        tools.workspace_path(path)


def test_file_tool_rejects_symlink_escape(workspace):
    (workspace / "escape").symlink_to(Path("/etc"))
    with pytest.raises(ValueError):
        tools.workspace_path("escape/passwd")


def test_disabled_tool_cannot_execute(workspace):
    with pytest.raises(ValueError, match="not enabled"):
        tools.execute("python", {"code": "print(42)"}, [])


def test_python_does_not_inherit_provider_secrets(workspace, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-secret")
    monkeypatch.setenv("RUN_TOKEN", "test-run-token")
    result = tools.execute(
        "python", {"code": "import os; print(os.getenv('LLM_API_KEY'), os.getenv('RUN_TOKEN'))"}, ["python"]
    )
    assert result["output"] == "None None\n"


def test_output_is_bounded(workspace):
    result = tools.execute("python", {"code": "print('x' * 20000)"}, ["python"])
    assert len(result["output"]) == 8000
