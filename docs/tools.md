# Agentberth Tool Package v1

Tools are independent versioned packages. Agents reference default versions; a run can add published tools or disable inherited ones without changing the agent.

## Where tools live

```text
tools/
  builtin/
    python/
      tool.json
      handler.py
      tests.json
    read-file/
      tool.json
      handler.py
      tests.json
    write-file/
      tool.json
      handler.py
      tests.json
  examples/
    summarize-csv/
      tool.json
      handler.py
      tests.json
```

Repository folders are the source of truth for bundled defaults. They are copied into the platform image and discovered at API startup. Imported/UI-created packages live in the persistent PostgreSQL registry. The same format is used for both.

Discovery validates manifests, Python syntax, fixture structure, and schemas. It never imports a handler or executes its top-level code in the API process. An invalid bundled package or an existing ID/version with a different hash fails startup visibly; no version is silently replaced. Reloading all packages is transactional.

Bundled packages are trusted repository code and register as published. Imported packages start as drafts, including packages created in the console. Examples are not loaded automatically.

## Try the example

From the repository root, with the Compose stack running:

```bash
python3 scripts/tools.py import tools/examples/summarize-csv
python3 scripts/tools.py test summarize-csv 1.0.0
python3 scripts/tools.py publish summarize-csv 1.0.0
```

The test command submits an isolated container run and waits for its fixtures to pass. It does not call an LLM. In the console, **Tools** shows the draft, test status, source, fixtures, publication action, and export action. The test's activity is available in run history. Tool-test runs currently use the seeded Harbor guide record for their workspace association, but execute the package fixtures rather than the demo agent.

Select **Report writer**, expand **Tools for this run**, and add `summarize-csv@1.0.0`. Ask a real-provider agent:

> Write a CSV file containing two rows, then use summarize_csv to report its row count and column names.

The deterministic demo does not choose arbitrary tools; use the package test action to exercise a custom tool without model credits.

## Package manifest

`tool.json` contains exactly these fields:

```json
{
  "format_version": 1,
  "id": "summarize-csv",
  "version": "1.0.0",
  "name": "summarize_csv",
  "description": "Count data rows and list columns in a CSV workspace file.",
  "runtime": "python",
  "entrypoint": "handler.py:run",
  "input_schema": {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
    "additionalProperties": false
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "row_count": {"type": "integer", "minimum": 0},
      "columns": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["row_count", "columns"],
    "additionalProperties": false
  },
  "limits": {"timeout_seconds": 10, "max_output_bytes": 8192}
}
```

- `id`: stable registry identity, 2–48 lowercase letters/numbers/hyphens, starting with a letter.
- `version`: explicit `major.minor.patch`, without prerelease labels or leading zeros.
- `name`: model-facing Python-style function identifier, up to 64 characters. IDs may contain hyphens; function names may not.
- `input_schema` and `output_schema`: JSON Schema Draft 2020-12 object schemas. References (`$ref`, `$dynamicRef`, `$recursiveRef`) are unsupported, so validation never fetches schemas from the network. Nested schemas are limited to depth 20.
- `runtime` and `entrypoint`: fixed to `python` and `handler.py:run` in v1. Custom dependencies and other runtimes are not supported yet.
- Limits: 1–30 seconds per invocation; 128–32,000 bytes of JSON result.

Each package is limited to 100 KB; handler source is limited to 32 KB. The combined selected packages are limited to 400 KB and 12 tools per run.

## Handler contract

`handler.py` exports a synchronous function:

```python
import csv


def run(arguments, context):
    with context.workspace_path(arguments["path"]).open(
        newline="", encoding="utf-8"
    ) as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        count = sum(1 for _ in reader)
    return {"row_count": count, "columns": columns}
```

Use the Python standard library. `context.workspace_path(relative_path)` rejects path traversal and symlink escapes in file-tool helpers. `context.run_python(code)` provides the existing bounded Python command helper used by the bundled Python tool.

Inputs are validated before invocation; returned objects are validated against the output schema. Results must be JSON-serializable objects. Each call materializes its pinned source under temporary storage and imports it in a new subprocess inside the run sandbox. The subprocess does not inherit provider credentials or the run bearer token in its environment. Its process group is terminated after the call.

Calls share the run's workspace. Files saved there can become artifacts under the existing text-file limits. Handler source and helper request/result files live in separate temporary storage and are not exported as artifacts. Log output is captured within bounded temporary storage; failures surface diagnostics in run events. Large argument/result previews are truncated in events, while the bounded full result is available to the model.

Python code can inspect its own container. Workspace helpers, tool selection, and subprocess environments do not create separate security boundaries between tools in the same sandbox.

## Fixtures

`tests.json` is an array of 1–10 fixtures:

```json
[
  {
    "name": "Two data rows",
    "arguments": {"path": "sample.csv"},
    "expected": {"row_count": 2, "columns": ["name", "score"]},
    "files": {"sample.csv": "name,score\nAda,10\nLin,20\n"}
  }
]
```

Each fixture gets a separate temporary workspace populated with its UTF-8 input files. The runner checks the exact returned JSON value against `expected`. Fixture inputs and expected outputs must themselves conform to the schemas. Any handler error, schema mismatch, timeout, or unequal result fails the test run. Fixture workspaces are removed afterward.

A draft can only be published after its latest associated sandbox test run completes successfully for that exact package hash. Published versions remain published if you rerun their tests and observe a later failure; the UI shows that failure for investigation. Tests demonstrate behavior on supplied examples, not security or general correctness.

## Versioning and snapshots

Both imported drafts and published packages are immutable once registered. To fix a draft or change a published tool, create a new version. The console's **New version** action prepares an incremented patch version. Re-importing identical content at the same version is idempotent; changed content returns HTTP 409.

SHA-256 covers the manifest, handler source, and fixtures using canonical JSON serialization. Whitespace inside the source string affects the hash. Formatting a handler therefore requires a version bump. Reformatting the manifest JSON alone does not change the hash.

At run acceptance, the registry resolves all selected published versions and embeds complete packages and hashes in the run snapshot. The model gateway advertises exactly those schemas. The runtime verifies the package hash before execution. A new publication or reload cannot alter an accepted run. Run detail responses expose resolved tool IDs, versions, names, and hashes.

Pre-registry agent defaults are automatically migrated from the three legacy string names to builtin `1.0.0` references. Queued legacy runs receive equivalent builtin package snapshots during startup. Previously completed legacy runs retain their original records and have no package hashes.

## Per-run selection

```json
{
  "input": "Write a CSV and summarize it.",
  "additional_tools": [{"id": "summarize-csv", "version": "1.0.0"}],
  "disabled_tools": ["python"]
}
```

Send this body to an existing deployment's run endpoint. `disabled_tools` contains registry IDs of inherited tools. Additions must be published. Duplicate IDs or conflicting model-facing names are rejected. To use another version of an inherited tool for one run, disable its ID and add the desired explicit version. Agent defaults do not change.

Idempotency includes run-specific tool selections. A key reused with different selections returns 409. Existing no-override request keys remain compatible with the previous release.

## Import and export

The folder format has three files. The transport format is a JSON envelope:

```json
{"manifest": {"...": "contents of tool.json"}, "handler": "contents of handler.py", "tests": []}
```

The example above illustrates the envelope only; a real package needs the complete manifest and at least one fixture. UI import/export uses a `.tool.json` envelope. The CLI reads/writes the standard folder layout:

```bash
python3 scripts/tools.py export summarize-csv 1.0.0 work/exported-csv-tool
```

The export command refuses to overwrite an existing directory. Set `AGENTBERTH_ADMIN_KEY` in the command environment if you use a custom administration key. `--base-url` goes before the subcommand. No CLI command executes source on the host; source execution happens only through the sandbox test/run APIs.

## Development reload

Normal deployment bundles defaults into the image. After adding a new package/version, rebuild with `docker compose up --build -d`.

For a mounted development folder, use `compose.tools-dev.yaml`:

```bash
docker compose -f compose.yaml -f compose.tools-dev.yaml up -d
python3 scripts/tools.py reload
```

This mounts only `tools/builtin` read-only into the API. Reload is explicit and transactional, not a file watcher. Increment the version when changing contents. Imported packages remain in the database. Removing a repository folder does not delete an already registered version.

LLM-assisted draft generation is future work. It will produce this same package format and use the same validation, test, and publication path.

### Retaining bundled versions

Directory names are organizational; identity comes from the manifest. To ship multiple versions, put each in a separate immediate child directory under `tools/builtin` (for example `python-v1` and `python-v2`). Keep the original builtin `1.0.0` compatibility packages available in distributions while the seeded/default configurations reference them. Existing databases retain old versions, but a fresh installation cannot recover versions omitted from its image.

Package snapshots pin source and schemas, not the entire Python/runtime image. Platform/runtime upgrades may affect helper behavior; record deployment versions when comparing results. Fully pinned runtime-image provenance belongs in the deployment/backend follow-up.
