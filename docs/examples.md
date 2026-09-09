# Example agents

New and existing installations receive three OpenRouter examples at API startup. They use the deployment's configured model (`LLM_MODEL`) and require `LLM_API_KEY`; merely opening or selecting an example does not call the model. Each example allows up to 10 model calls, 8,192 output tokens per model call, and 240 seconds per run. **Configure → Maximum output tokens per model call** controls the allowance (256–16,384); existing agents default to 2,048. Larger allowances can increase cost.

| Agent | Example workflow | Outputs |
| --- | --- | --- |
| Sales data auditor | Validate embedded CSV, remove duplicates/invalid rows, retain refunds, calculate and verify regional totals | `cleaned.csv`, `summary.json`, `audit.md` |
| Project dependency planner | Validate a dependency graph, compute earliest start/finish and critical path, evaluate a two-day delay | `schedule.csv`, `checks.json`, `plan.md` with a Mermaid diagram |
| Release notes editor | Convert rough notes into customer-facing release notes and a QA checklist, keeping planned features separate | `release-notes.md`, `qa-checklist.md` |

All inputs are included in their suggested tasks, so no downloads or uploads are needed to try them. Tools use Python's standard library and workspace files; they have no direct internet access. The analyst examples exercise multiple tool calls and machine-readable outputs, rather than relying only on a text answer. Multiple output files can be downloaded together as ZIP.

## Try an example

1. Refresh the console after updating the deployment.
2. Select an example under **Agents**. Its suggested task appears in the playground.
3. Optionally edit it, then select **Run agent**. Open **Result** to inspect and download the files.

Switching agents keeps a separate prompt draft for each agent for the current page session. Refreshing clears these unsaved drafts. Attachments and the active result view are cleared when switching agents, so they are not accidentally carried into another agent's task. Existing runs remain in Run history. Use **Use suggested task** to restore the example prompt.

**Configure → Suggested task** lets you save your own prompt for any agent. The API field is `example_task` in agent creation/update requests and `config.example_task` in agent responses. It defaults to an empty string for older agents. An agent without a suggestion starts with an empty task on first selection, rather than borrowing another agent's task. Opening a historical run still displays that run's actual input. The scheduling form also loads the selected agent's suggested task.

The bundled configurations live in `services/agentberth/examples.py`. They are inserted only when the slug does not exist; restarting or upgrading never overwrites your edits. Example source updates therefore affect new installations/new slugs, not existing customized agents.

**Harbor guide** remains a no-credit, deterministic demonstration. Older entries such as Smoke test, Tool integration check, Recovery test, and Scheduled report example are integration-test fixtures, not different AI capabilities. Demo-provider agents always execute the fixed demonstration regardless of the prompt. They are retained to preserve existing runs and references.

## Verify the analytical examples

From the repository root:

```bash
python3 scripts/example_agents.py --live
```

For Kubernetes, with port-forwarding running:

```bash
python3 scripts/example_agents.py --live \
  --base-url http://127.0.0.1:8081 \
  --admin-key-file work/kubernetes-admin-key \
  --output-dir work/agent-examples-kubernetes
```

This deliberately requires `--live` because it spends OpenRouter credits. It submits the saved suggested task for the auditor and planner, waits for completion, downloads individual files and their ZIP, and verifies the key calculations:

- Auditor: five valid rows with net revenue **425.75** (North **100.50**, South **125.25**, West **200**).
- Planner: baseline finish on working day **10**, delayed finish on day **12**.

Outputs are kept under `work/agent-examples/<agent>/<run-id>/`. The script reports model-call counts and provider-reported cost. Model outputs can vary; this is an opt-in live check, not a deterministic CI test. If you customize the saved tasks, update the expected checks accordingly.

## API invocation

List agents with `GET /v1/agents`, take the desired agent's `config.example_task`, and submit it as `input` to `POST /v1/deployments/{slug}/runs`. Suggested tasks are UI defaults only: run submission still requires an explicit input, preventing accidental execution of a saved prompt. All requests require the administration bearer key. See [API documentation](api.md) and [scheduling](scheduling.md) to reuse these tasks in schedules.
