# Files, archives, and GUI/API parity

## Run-scoped input files

In **Agents**, enter a task, choose **Attach files**, and run the agent. Uploads belong only to that run. They are staged at `inputs/<name>` inside its fresh sandbox. Files are not inherited by the agent configuration or another run. The picker clears after acceptance. Starting another run, including from history, requires reattachment.

The API temporarily stores input bytes while the run is queued/running. Every terminal transition (completed, failed, cancelled, timed out, or worker-restart failure) removes those bytes from the run record, and sandbox teardown removes the working copies. History retains filenames and sizes. Original-input download links work only while a run is active and return 410 after it ends. This is application-level expiry, not a guarantee of forensic erasure from PostgreSQL backups or storage. Tool responses, model context, and deliberately generated outputs can contain information derived from inputs and follow their normal retention.

Limits for both GUI and API:

- Up to **8 input files**, **1 MiB per file**, **4 MiB total decoded bytes**.
- Use relative names up to 150 characters: letters, numbers, spaces, underscores, dots, and hyphens. Hidden paths, absolute paths, parent traversal, duplicates, and file/directory collisions are rejected.
- The GUI uses local basenames; API clients can specify nested paths such as `batch/data.csv`.
- Input bytes use `content_base64` in the JSON request. Uploads are submitted atomically with the task; there is no shared upload library or multipart endpoint.
- Base64 adds roughly one-third transport overhead. Run submission and internal result bodies allow 6,000,000 bytes; other requests retain the 600,000-byte limit.

The model receives the filenames and uses tools to read the contents. Uploading a PDF/image does not automatically enable PDF parsing, OCR, or a multimodal model request; supply an appropriate tool for the desired format. Python includes its standard library, which handles CSV, JSON, ZIP, and TAR.

## Archives

Attach `.zip`, `.tar`, `.tar.gz`, or `.tgz` like any other file. At acceptance the platform automatically includes the published bundled `archive@1.0.0` tool if an archive tool is not already selected. It counts toward the 12-tool limit. The runtime calls it **before the agent starts**, extracting each archive into `inputs/extracted/<zero-based upload index>/`. Activity shows the extraction and resulting paths. Agent defaults are unchanged; run detail records the pinned tool.

Extraction allows at most **128 entries**, **12 path components**, **4 MiB per extracted file**, and **16 MiB total per archive**. It rejects unsafe/hidden paths, duplicate paths, symbolic/hard links, devices, encrypted ZIPs, and unsupported ZIP compression. It does not recursively extract nested archives. The extraction is published only after validation succeeds; an invalid archive fails the run and its uploads expire. Extracted files are also ephemeral and are excluded from automatic output collection.

## Output files

Ask the agent to save deliverables outside `inputs/`, for example `results/summary.csv`. The runtime collects up to **8 regular files**, **1 MiB each**, **4 MiB total**. Text and binary contents are supported. Hidden files/directories and symlinks are excluded; the scan is bounded to 200 entries. Exceeding collection limits fails the run with an explanatory event instead of silently truncating a file.

The **Result → Output files** section provides individual downloads. Multiple outputs also get **Download all as ZIP**, preserving relative paths. The API exposes the same link as `artifacts_archive_url` on run detail; individual metadata includes each artifact ID, name, and byte size. Outputs remain available after the input files expire. Existing UTF-8 artifacts from older versions remain downloadable.

## Runnable example: no model credits

From the repository root, create an input:

```bash
mkdir -p work
python3 - <<'PY'
from pathlib import Path
Path('work/scores.csv').write_text('name,score\nAda,10\nLin,20\n')
PY
python3 scripts/run_files.py \
  --agent harbor-guide \
  --task 'Demonstrate the file workflow.' \
  --file work/scores.csv \
  --output-dir work/demo-downloads
```

The deterministic demo lists the upload in `report.md`; it does not interpret your requested analysis. The script uses only public API calls, waits for completion, and downloads outputs. Use a new output directory on each invocation. For a custom administration key, set `AGENTBERTH_ADMIN_KEY` in your shell. The default local key requires no setup.

## Real CSV analysis with a configured agent

Create an agent in the GUI named **CSV analyst**, slug `csv-analyst`, provider **OpenRouter**, with Python and the default file tools enabled. Then run:

```bash
python3 scripts/run_files.py \
  --agent csv-analyst \
  --task 'Read inputs/scores.csv with Python. Calculate the mean score. Save summary.json and summary.md outside inputs/.' \
  --file work/scores.csv \
  --output-dir work/csv-downloads
```

This spends model credits. The equivalent GUI action is to select that agent, paste the same task, attach `scores.csv`, and click **Run agent**. Multiple outputs will also have a ZIP download link.

To try archive input:

```bash
python3 - <<'PY'
from zipfile import ZipFile
with ZipFile('work/scores.zip', 'w') as archive:
    archive.write('work/scores.csv', 'scores.csv')
PY
python3 scripts/run_files.py \
  --agent csv-analyst \
  --task 'Read inputs/extracted/0/scores.csv. Save summary.json and summary.md outside inputs/.' \
  --file work/scores.zip \
  --output-dir work/archive-downloads
```

## Raw API example

Prepare a JSON body without relying on platform-specific `base64` command flags:

```bash
python3 - <<'PY'
import base64, json
from pathlib import Path
body = {
    'input': 'Read inputs/scores.csv and save summary.json and summary.md.',
    'files': [{'name': 'scores.csv', 'content_base64': base64.b64encode(Path('work/scores.csv').read_bytes()).decode()}],
}
Path('work/request.json').write_text(json.dumps(body))
PY
curl --fail-with-body http://localhost:8080/v1/deployments/csv-analyst/runs \
  -H "Authorization: Bearer ${AGENTBERTH_ADMIN_KEY:-agentberth-local}" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: csv-upload-001' \
  --data-binary @work/request.json
```

Copy the returned ID, then inspect the run:

```bash
RUN_ID='paste-returned-id'
curl --fail-with-body "http://localhost:8080/v1/runs/$RUN_ID" \
  -H "Authorization: Bearer ${AGENTBERTH_ADMIN_KEY:-agentberth-local}"
```

After completion, use an artifact ID from `artifacts` or the ZIP endpoint:

```bash
ARTIFACT_ID='paste-artifact-id'
curl --fail-with-body "http://localhost:8080/v1/runs/$RUN_ID/artifacts/$ARTIFACT_ID" \
  -H "Authorization: Bearer ${AGENTBERTH_ADMIN_KEY:-agentberth-local}" \
  -o work/summary.json
curl --fail-with-body "http://localhost:8080/v1/runs/$RUN_ID/artifacts.zip" \
  -H "Authorization: Bearer ${AGENTBERTH_ADMIN_KEY:-agentberth-local}" \
  -o work/outputs.zip
```

Filename, bytes, task, and tool overrides participate in idempotency. Reusing the same key with changed files returns 409. Retrying an identical completed request returns the original run and does not recreate its expired uploads. A new task requires a new key and fresh file bytes. The local `work/request.json` and original files are client-side files; the platform does not delete those.

## GUI/API parity

| Capability | GUI | Public API |
|---|---|---|
| Create/update agent | Configure agent | `POST /v1/agents`, `PUT /v1/agents/{slug}` |
| Submit task and attachments | Task + Attach files | `POST /v1/deployments/{slug}/runs` with `files` |
| Per-run tool overrides | Tool selection | `additional_tools`, `disabled_tools` |
| Archive input | Attach supported archive | Same `files` field; same automatic tool resolution |
| Activity and cancellation | Activity / Cancel | SSE `/events`, `POST /cancel` |
| Input metadata and temporary download | Input files | Run `files` metadata and `/files/{index}` until expiry |
| Output download | Output files | `/artifacts/{artifact_id}` |
| Combined output ZIP | Download all as ZIP | `/artifacts.zip` / `artifacts_archive_url` |
| Tool create/import/export/test/publish/delete | Tools | [Tool registry endpoints](api.md#tool-registry) |
| Provider and worker status | Settings | `GET /v1/settings` |
| Provider credentials | Managed in `.env` | No credential-writing endpoint |
| Theme preference | Top-bar switch | Browser-only preference |

Repository reload is currently API/CLI-only. The GUI cannot set custom idempotency keys or nested attachment paths. Browser controls call the public API; no separate execution path exists. New workflow features should document their GUI and API equivalents here and add integration coverage where behavior is shared.
