from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema.exceptions import SchemaError

from runtime.packages import digest, read_folder, validate_package
from runtime import tools

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return read_folder(ROOT / "tools/examples/summarize-csv")


def test_discovery_does_not_execute_handler(tmp_path):
    p = sample()
    marker = tmp_path / "executed"
    p["handler"] = f"open({str(marker)!r}, 'w').write('bad')\ndef run(arguments, context):\n    return {{}}\n"
    validate_package(p)
    assert not marker.exists()


def test_hash_covers_code_manifest_and_fixtures():
    p = sample()
    for field, value in [
        ("handler", p["handler"] + "\n"),
        ("manifest", {**p["manifest"], "description": "Changed"}),
        ("tests", []),
    ]:
        changed = deepcopy(p)
        changed[field] = value
        assert digest(p) != digest(changed)
    assert digest(p) == digest(dict(reversed(list(p.items()))))


def test_external_schema_references_are_rejected():
    p = sample()
    p["manifest"]["input_schema"]["properties"]["path"] = {"$ref": "https://example.com/schema.json"}
    with pytest.raises(ValueError, match="references"):
        validate_package(p)


def test_invalid_schema_rejected():
    p = sample()
    p["manifest"]["input_schema"]["properties"]["path"] = {"type": "not-a-json-type"}
    with pytest.raises(SchemaError):
        validate_package(p)


def test_fixture_path_cannot_escape():
    p = sample()
    p["tests"][0]["files"] = {"../escape": "data"}
    with pytest.raises(ValueError, match="relative"):
        validate_package(p)


def test_custom_tool_executes_and_validates_output(tmp_path, monkeypatch):
    p = sample()
    (tmp_path / "data.csv").write_text("a,b\n1,2\n3,4\n")
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    package = {**p, "sha256": digest(p)}
    assert tools.execute("summarize_csv", {"path": "data.csv"}, [package]) == {
        "row_count": 2,
        "columns": ["a", "b"],
    }
    with pytest.raises(ValueError, match="input schema"):
        tools.execute("summarize_csv", {"wrong": "data.csv"}, [package])
    p["handler"] = 'def run(arguments, context):\n    return {"row_count": "wrong", "columns": []}\n'
    with pytest.raises(ValueError, match="output does not match"):
        tools.execute("summarize_csv", {"path": "data.csv"}, [{**p, "sha256": digest(p)}])


def test_tampering_is_rejected(tmp_path, monkeypatch):
    p = sample()
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    package = {**p, "sha256": digest(p)}
    package["handler"] += "\n# changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        tools.execute("summarize_csv", {"path": "x.csv"}, [package])


def test_execution_timeout(tmp_path, monkeypatch):
    p = sample()
    p["handler"] = "def run(arguments, context):\n    while True: pass\n"
    p["manifest"]["limits"]["timeout_seconds"] = 1
    monkeypatch.setattr(tools, "WORKSPACE", tmp_path)
    with pytest.raises(ValueError, match="execution timeout"):
        tools.execute("summarize_csv", {"path": "x.csv"}, [{**p, "sha256": digest(p)}])


def test_fixture_runner_does_not_treat_exceptions_as_passing_results(monkeypatch):
    from runtime import main

    monkeypatch.setattr(main, "event", lambda *args: None)

    def fail(*args):
        raise ValueError("handler failed")

    monkeypatch.setattr(main, "execute", fail)
    p = sample()
    package = {**p, "sha256": digest(p)}
    assert main.tool("summarize_csv", {"path": "x.csv"}, [package]) == {"error": "handler failed"}
    with pytest.raises(ValueError, match="handler failed"):
        main.tool("summarize_csv", {"path": "x.csv"}, [package], fail_on_error=True)
