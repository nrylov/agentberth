from agentberth.examples import configs
from agentberth.schemas import AgentConfig
from runtime.packages import read_folder
from pathlib import Path


def test_bundled_examples_have_distinct_valid_tasks_and_available_tools():
    examples = list(configs())
    assert len(examples) == 3
    assert len({c["example_task"] for _, c in examples}) == 3
    for _slug, config in examples:
        validated = AgentConfig(**config)
        assert validated.provider == "openrouter"
        assert validated.example_task
        assert validated.model == ""  # Use the deployment's configured model.
        assert 1 <= validated.max_steps <= 12
        for ref in config["tools"]:
            package = read_folder(Path("tools/builtin") / ref["id"])
            assert package["manifest"]["version"] == ref["version"]


def test_legacy_agents_keep_compatible_empty_suggested_task():
    config = AgentConfig(name="Legacy", instructions="Help")
    assert config.example_task == ""


def test_output_allowance_is_bounded_and_backwards_compatible():
    import pytest
    from pydantic import ValidationError

    assert AgentConfig(name="Legacy", instructions="Help").max_output_tokens == 2048
    for limit in [255, 16385]:
        with pytest.raises(ValidationError):
            AgentConfig(name="Invalid", instructions="Help", max_output_tokens=limit)
    for _, config in configs():
        assert AgentConfig(**config).max_output_tokens == 8192


def test_legacy_fixture_tasks_are_scoped_and_distinct():
    from agentberth.examples import LEGACY_TASKS, legacy_task

    for prefix, (name, task) in LEGACY_TASKS.items():
        slug = prefix if prefix == "harbor-guide" else prefix + "12345678"
        assert legacy_task(slug, name) == task
        assert legacy_task(slug, "My custom agent") is None
    assert legacy_task("custom-agent", "Smoke test") is None
    assert "fixed demonstration" in legacy_task("tool-check-12345678", "Tool integration check", "demo")
    assert len({task for _, task in LEGACY_TASKS.values()}) == len(LEGACY_TASKS)
