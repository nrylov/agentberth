import { useState } from "react";
import { Code2, Download, Plus, Play, Upload, Trash2 } from "lucide-react";

export type ToolRef = { id: string; version: string };
export type ToolRecord = {
  tool_id: string;
  version: string;
  name: string;
  sha256: string;
  status: string;
  origin: string;
  test_run_id: string | null;
  test_status: string | null;
  manifest: { description: string; [key: string]: unknown };
};
export const refKey = (ref: ToolRef) => `${ref.id}@${ref.version}`;
type Package = {
  manifest: Record<string, unknown>;
  handler: string;
  tests: unknown[];
};
type Api = <T>(path: string, options?: RequestInit) => Promise<T>;
const example: Package = {
  manifest: {
    format_version: 1,
    id: "echo-value",
    version: "1.0.0",
    name: "echo_value",
    description: "Return the supplied value.",
    runtime: "python",
    entrypoint: "handler.py:run",
    input_schema: {
      type: "object",
      properties: { value: { type: "string" } },
      required: ["value"],
      additionalProperties: false,
    },
    output_schema: {
      type: "object",
      properties: { value: { type: "string" } },
      required: ["value"],
      additionalProperties: false,
    },
    limits: { timeout_seconds: 10, max_output_bytes: 8192 },
  },
  handler:
    'def run(arguments, context):\n    return {"value": arguments["value"]}\n',
  tests: [
    {
      name: "Echo a value",
      arguments: { value: "hello" },
      expected: { value: "hello" },
      files: {},
    },
  ],
};

export function ToolsView({
  tools,
  api,
  refresh,
  onRun,
}: {
  tools: ToolRecord[];
  api: Api;
  refresh: () => Promise<void>;
  onRun: (id: string) => Promise<void>;
}) {
  const [selected, setSelected] = useState<ToolRecord | null>(null);
  const [manifest, setManifest] = useState("");
  const [handler, setHandler] = useState("");
  const [fixtures, setFixtures] = useState("");
  const [editing, setEditing] = useState(false);
  const [shown, setShown] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const current =
    tools.find(
      (t) => t.tool_id === selected?.tool_id && t.version === selected.version,
    ) || selected;
  function load(p: Package, edit: boolean) {
    setConfirmDelete(false);
    setManifest(JSON.stringify(p.manifest, null, 2));
    setHandler(p.handler);
    setFixtures(JSON.stringify(p.tests, null, 2));
    setEditing(edit);
    setShown(true);
    setError("");
  }
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function open(t: ToolRecord) {
    await action(async () => {
      const p = await api<Package>(
        `/v1/tools/${t.tool_id}/${t.version}/export`,
      );
      setSelected(t);
      load(p, false);
    });
  }
  async function save() {
    await action(async () => {
      const p = {
        manifest: JSON.parse(manifest),
        handler,
        tests: JSON.parse(fixtures),
      };
      const row = await api<ToolRecord>("/v1/tools/import", {
        method: "POST",
        body: JSON.stringify(p),
      });
      await refresh();
      setSelected(row);
      setEditing(false);
    });
  }
  async function imported(file?: File) {
    if (!file) return;
    await action(async () => {
      if (file.size > 100000)
        throw new Error("Tool packages are limited to 100 KB.");
      const p: Package = JSON.parse(await file.text());
      load(p, true);
      setSelected(null);
    });
  }
  async function exportPackage() {
    await action(async () => {
      if (!current) return;
      const p = await api<Package>(
        `/v1/tools/${current.tool_id}/${current.version}/export`,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(p, null, 2)], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `${current.tool_id}.tool.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">REUSABLE CAPABILITIES</p>
          <h1>Tool library</h1>
          <p>
            Versioned packages. Test in a sandbox, then publish for your agents.
          </p>
        </div>
        <div className="tool-actions">
          <label className="secondary import-button">
            <Upload size={16} /> Import package
            <input
              type="file"
              accept=".json,application/json"
              onChange={(e) => {
                void imported(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
          </label>
          <button
            className="primary"
            onClick={() => {
              setSelected(null);
              load(example, true);
            }}
          >
            <Plus size={16} /> New tool
          </button>
        </div>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="library-layout">
        <section className="panel tool-library-list">
          {tools.map((t) => (
            <button
              key={`${t.tool_id}@${t.version}`}
              className={
                current?.tool_id === t.tool_id && current?.version === t.version
                  ? "active"
                  : ""
              }
              onClick={() => void open(t)}
            >
              <Code2 size={19} />
              <span>
                <strong>{t.tool_id}</strong>
                <small>
                  v{t.version} · {t.origin}
                </small>
              </span>
              <span
                className={`badge ${t.status === "published" ? "completed" : "queued"}`}
              >
                {t.status}
              </span>
            </button>
          ))}
        </section>
        <section className="panel tool-editor">
          <div className="panel-heading">
            <h2>
              {editing
                ? "Package editor"
                : current
                  ? `${current.tool_id} · ${current.version}`
                  : "Explore your tools"}
            </h2>
            {current && !editing && (
              <button
                className="text-button"
                onClick={() => {
                  const m = JSON.parse(manifest);
                  const parts = m.version.split(".");
                  parts[2] = String(Number(parts[2]) + 1);
                  m.version = parts.join(".");
                  setManifest(JSON.stringify(m, null, 2));
                  setConfirmDelete(false);
                  setEditing(true);
                }}
              >
                New version <Plus size={14} />
              </button>
            )}
          </div>
          {shown ? (
            <>
              <div className="panel-body">
                <p className="hint">
                  {editing
                    ? "Save an immutable draft, run its fixtures, then publish. Future edits require a new version."
                    : "Exact package contents. Published versions can be selected for agents and individual runs."}
                </p>
                <label htmlFor="tool-manifest">tool.json</label>
                <textarea
                  id="tool-manifest"
                  className="source-input"
                  rows={12}
                  readOnly={!editing}
                  value={manifest}
                  onChange={(e) => setManifest(e.target.value)}
                />
                <label htmlFor="tool-handler">handler.py</label>
                <textarea
                  id="tool-handler"
                  className="source-input"
                  rows={8}
                  readOnly={!editing}
                  value={handler}
                  onChange={(e) => setHandler(e.target.value)}
                />
                <label htmlFor="tool-fixtures">tests.json</label>
                <textarea
                  id="tool-fixtures"
                  className="source-input"
                  rows={8}
                  readOnly={!editing}
                  value={fixtures}
                  onChange={(e) => setFixtures(e.target.value)}
                />
                {current && !editing && (
                  <>
                    <p className="hint">
                      SHA-256: <code>{current.sha256}</code>
                    </p>
                    <p className="hint">
                      Last sandbox test: {current.test_status || "Not run"}{" "}
                      {current.test_run_id && (
                        <button
                          className="text-button"
                          onClick={() => void onRun(current.test_run_id!)}
                        >
                          View run
                        </button>
                      )}
                    </p>
                  </>
                )}
              </div>
              {confirmDelete && current && !editing && (
                <div className="panel-body" role="alert">
                  <p>
                    Delete {current.tool_id}@{current.version}? This removes it
                    from the library and future selections. Existing runs keep
                    their snapshots. This version number cannot be reused.
                  </p>
                  <div className="tool-actions">
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() => setConfirmDelete(false)}
                    >
                      Keep version
                    </button>
                    <button
                      className="secondary danger"
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          await api(
                            `/v1/tools/${current.tool_id}/${current.version}`,
                            { method: "DELETE" },
                          );
                          setSelected(null);
                          setShown(false);
                          setConfirmDelete(false);
                          await refresh();
                        })
                      }
                    >
                      Delete permanently from library
                    </button>
                  </div>
                </div>
              )}
              <div className="modal-footer">
                {editing ? (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => void save()}
                  >
                    Save draft
                  </button>
                ) : (
                  current && (
                    <>
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => void exportPackage()}
                      >
                        <Download size={15} /> Export
                      </button>
                      <button
                        className="secondary"
                        disabled={
                          busy ||
                          current.test_status === "queued" ||
                          current.test_status === "running"
                        }
                        onClick={() =>
                          void action(async () => {
                            const run = await api<{ id: string }>(
                              `/v1/tools/${current.tool_id}/${current.version}/test`,
                              { method: "POST" },
                            );
                            await refresh();
                            await onRun(run.id);
                          })
                        }
                      >
                        <Play size={15} /> Test in sandbox
                      </button>
                      {current.origin !== "bundled" && (
                        <button
                          className="secondary danger"
                          disabled={busy}
                          onClick={() => setConfirmDelete(true)}
                        >
                          <Trash2 size={15} /> Delete version
                        </button>
                      )}
                      {current.status !== "published" && (
                        <button
                          className="primary"
                          disabled={busy || current.test_status !== "completed"}
                          onClick={() =>
                            void action(async () => {
                              await api(
                                `/v1/tools/${current.tool_id}/${current.version}/publish`,
                                { method: "POST" },
                              );
                              await refresh();
                            })
                          }
                        >
                          Publish version
                        </button>
                      )}
                    </>
                  )
                )}
              </div>
            </>
          ) : (
            <div className="empty">
              <Code2 size={30} />
              <h3>Select a tool or create one.</h3>
              <p>
                Bundled tools come from repository folders.
                <br />
                Imported packages persist in the registry.
              </p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
