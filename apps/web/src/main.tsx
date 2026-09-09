import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import {
  Anchor,
  ArrowUpRight,
  Box,
  Check,
  ChevronRight,
  CircleHelp,
  Code2,
  Copy,
  Download,
  FileText,
  KeyRound,
  Layers,
  LoaderCircle,
  Play,
  Plus,
  Radio,
  Settings2,
  Square,
  Terminal,
  X,
} from "lucide-react";
import "./style.css";

type Config = {
  name: string;
  instructions: string;
  provider: "demo" | "openrouter";
  model: string;
  tools: string[];
  max_steps: number;
  timeout_seconds: number;
};
type Agent = { slug: string; name: string; version: number; config: Config };
type Run = {
  id: string;
  agent_slug: string;
  version: number;
  input: string;
  status: string;
  output: string | null;
  error: string | null;
  created_at: string;
  model_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost: string | number;
  cancel_requested: boolean;
  artifacts?: { id: string; name: string; size: number }[];
};
type RunEvent = {
  id: number;
  kind: string;
  data: Record<string, unknown>;
  created_at: string;
};
type Settings = {
  provider: { configured: boolean; base_url: string; model: string };
  worker_online: boolean;
  demo_key: boolean;
};
type View = "playground" | "runs" | "settings";
const terminal = new Set(["completed", "failed", "cancelled", "timed_out"]);
const initial: Config = {
  name: "",
  instructions:
    "Help the user. Use tools when useful. Save requested deliverables to files in the workspace.",
  provider: "demo",
  model: "",
  tools: ["python", "write_file", "read_file"],
  max_steps: 6,
  timeout_seconds: 120,
};
const money = (value: number | string) => `$${Number(value).toFixed(5)}`;

function App() {
  const [key, setKey] = useState(
    () => sessionStorage.getItem("agentberth-key") || "agentberth-local",
  );
  const keyRef = useRef(key);
  keyRef.current = key;
  const [locked, setLocked] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selected, setSelected] = useState("harbor-guide");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [view, setView] = useState<View>("playground");
  const [input, setInput] = useState(
    "Calculate the total and average of 12, 18, and 24. Save a short report to report.md.",
  );
  const [active, setActive] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<{
    slug: string;
    config: Config;
    isNew: boolean;
  } | null>(null);
  const [copied, setCopied] = useState(false);
  const [pane, setPane] = useState<"result" | "events">("events");
  const agent = agents.find((a) => a.slug === selected);
  const running = !!active && !terminal.has(active.status);

  async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${keyRef.current}`,
        ...options.headers,
      },
    });
    if (response.status === 401) setLocked(true);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(
        typeof body.detail === "string"
          ? body.detail
          : `Request failed (${response.status}). Check the form values.`,
      );
    }
    return response.json();
  }

  async function refresh() {
    try {
      const [a, s, r] = await Promise.all([
        api<Agent[]>("/v1/agents"),
        api<Settings>("/v1/settings"),
        api<Run[]>("/v1/runs"),
      ]);
      setAgents(a);
      setSettings(s);
      setRuns(r);
      setLocked(false);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, 5000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!editor && !locked) return;
    const previous = document.activeElement as HTMLElement | null;
    function trap(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const dialogs = document.querySelectorAll<HTMLElement>(".modal");
      const dialog = dialogs[dialogs.length - 1];
      const controls = dialog?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), textarea, select:not(:disabled), [tabindex="0"]',
      );
      if (!controls?.length) return;
      const first = controls[0],
        last = controls[controls.length - 1];
      if (
        event.shiftKey &&
        (document.activeElement === first ||
          !dialog.contains(document.activeElement))
      ) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      previous?.focus();
    };
  }, [!!editor, locked]);

  useEffect(() => {
    type ModelContext = {
      registerTool: (
        tool: {
          name: string;
          description: string;
          inputSchema: object;
          annotations: object;
          execute: (input: unknown) => Promise<unknown>;
        },
        options: { signal: AbortSignal },
      ) => void | Promise<void>;
    };
    const context = (document as Document & { modelContext?: ModelContext })
      .modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tools = [
      {
        name: "agentberth_list_agents",
        description:
          "List the local workspace agents and their provider settings. Requires the console administration key.",
        inputSchema: {
          type: "object",
          properties: {},
          additionalProperties: false,
        },
        annotations: { readOnlyHint: true, untrustedContentHint: true },
        execute: async () =>
          (await api<Agent[]>("/v1/agents")).map((a) => ({
            slug: a.slug,
            name: a.name,
            provider: a.config.provider,
            version: a.version,
          })),
      },
      {
        name: "agentberth_prepare_run",
        description:
          "Select an existing agent and stage a task in the visible playground. Does not execute the run or spend model credits.",
        inputSchema: {
          type: "object",
          properties: {
            slug: { type: "string" },
            input: { type: "string", minLength: 1, maxLength: 8000 },
          },
          required: ["slug", "input"],
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false, untrustedContentHint: false },
        execute: async (value: unknown) => {
          const data = value as { slug?: unknown; input?: unknown };
          if (
            !data ||
            typeof data.slug !== "string" ||
            typeof data.input !== "string" ||
            !data.input.trim() ||
            data.input.length > 8000
          )
            throw new Error(
              "An agent slug and task of 1–8000 characters are required.",
            );
          const available = await api<Agent[]>("/v1/agents");
          if (!available.some((a) => a.slug === data.slug))
            throw new Error("Agent not found.");
          const slug = data.slug,
            task = data.input;
          flushSync(() => {
            setAgents(available);
            setSelected(slug);
            setInput(task);
            setView("playground");
          });
          return { status: "prepared", slug: data.slug, executed: false };
        },
      },
    ];
    for (const tool of tools) {
      try {
        void Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch(() => {});
      } catch {
        /* Optional browser capability. */
      }
    }
    return () => lifecycle.abort();
  }, []);

  useEffect(() => {
    if (!active?.id) return;
    const id = active.id;
    const controller = new AbortController();
    setEvents([]);
    let cursor = 0;
    async function watch() {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(
            `/v1/runs/${id}/events?after=${cursor}`,
            {
              headers: { Authorization: `Bearer ${keyRef.current}` },
              signal: controller.signal,
            },
          );
          if (!response.ok || !response.body)
            throw new Error("Could not connect to the event stream.");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let pending = "";
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            pending += decoder.decode(value, { stream: true });
            let boundary: number;
            while ((boundary = pending.indexOf("\n\n")) >= 0) {
              const frame = pending.slice(0, boundary);
              pending = pending.slice(boundary + 2);
              const data = frame
                .split("\n")
                .find((line) => line.startsWith("data: "));
              if (data) {
                const event: RunEvent = JSON.parse(data.slice(6));
                if (event.id > cursor) {
                  cursor = event.id;
                  if (!controller.signal.aborted)
                    setEvents((prev) => [...prev, event]);
                }
              }
            }
          }
          const detail = await api<Run>(`/v1/runs/${id}`);
          if (controller.signal.aborted) return;
          setActive(detail);
          if (terminal.has(detail.status)) {
            if (detail.output) setPane("result");
            void refresh();
            return;
          }
        } catch (e) {
          if (controller.signal.aborted) return;
          setError((e as Error).message + " Reconnecting…");
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
    void watch();
    const timer = setInterval(async () => {
      try {
        const detail = await api<Run>(`/v1/runs/${id}`);
        if (!controller.signal.aborted) setActive(detail);
      } catch {
        /* stream reports errors */
      }
    }, 1500);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [active?.id]);

  async function launch() {
    setBusy(true);
    setError("");
    setPane("events");
    try {
      const accepted = await api<{ id: string }>(
        `/v1/deployments/${selected}/runs`,
        {
          method: "POST",
          body: JSON.stringify({ input }),
          headers: { "Idempotency-Key": crypto.randomUUID() },
        },
      );
      setActive(await api<Run>(`/v1/runs/${accepted.id}`));
      void refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (!active) return;
    try {
      setActive(
        await api<Run>(`/v1/runs/${active.id}/cancel`, { method: "POST" }),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function openRun(run: Run) {
    try {
      setActive(await api<Run>(`/v1/runs/${run.id}`));
      setView("playground");
      setSelected(run.agent_slug);
      setPane(run.output ? "result" : "events");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!editor) return;
    setBusy(true);
    setError("");
    try {
      const saved = await api<Agent>(
        editor.isNew ? "/v1/agents" : `/v1/agents/${editor.slug}`,
        {
          method: editor.isNew ? "POST" : "PUT",
          body: JSON.stringify(
            editor.isNew
              ? { ...editor.config, slug: editor.slug }
              : editor.config,
          ),
        },
      );
      setSelected(saved.slug);
      setEditor(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function download(artifact: { id: string; name: string }) {
    if (!active) return;
    try {
      const res = await fetch(
        `/v1/runs/${active.id}/artifacts/${artifact.id}`,
        { headers: { Authorization: `Bearer ${key}` } },
      );
      if (!res.ok) throw new Error("Artifact download failed.");
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = artifact.name.split("/").pop()!;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function copyEndpoint() {
    try {
      await navigator.clipboard.writeText(
        `${location.origin}/v1/deployments/${selected}/runs`,
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Clipboard unavailable. Select and copy the endpoint below.");
    }
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Agentberth home">
          <span className="brand-mark">
            <Anchor size={23} />
          </span>
          <span>
            agentberth<span className="version">LOCAL CONSOLE / 0.1</span>
          </span>
        </a>
        <div className="workspace-label">
          <span className="workspace-avatar">A</span>
          <div>
            Local workspace<small>Personal development</small>
          </div>
        </div>
        <p className="nav-label">WORKSPACE</p>
        <nav aria-label="Main navigation">
          <button
            className={view === "playground" ? "selected" : ""}
            onClick={() => setView("playground")}
          >
            <Box size={18} /> Agents{" "}
            <span className="count">{agents.length}</span>
          </button>
          <button
            className={view === "runs" ? "selected" : ""}
            onClick={() => setView("runs")}
          >
            <Radio size={18} /> Run history{" "}
            <span className="count">{runs.length}</span>
          </button>
          <button
            className={view === "settings" ? "selected" : ""}
            onClick={() => setView("settings")}
          >
            <Settings2 size={18} /> Settings
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="engine">
            <Box size={17} />
            <span>
              Docker engine
              <small>
                {settings?.worker_online
                  ? "Worker connected"
                  : "Waiting for worker"}
              </small>
            </span>
            <span
              className={`status-dot ${settings?.worker_online ? "online" : ""}`}
            />
          </div>
          <p>
            <CircleHelp size={15} /> Local development preview
          </p>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Workspace <ChevronRight size={14} />{" "}
            <strong>
              {view === "playground"
                ? "Agents"
                : view === "runs"
                  ? "Run history"
                  : "Settings"}
            </strong>
          </span>
          <span className="local-badge">LOCAL</span>
        </header>
        <div className="content">
          {error && (
            <div className="error" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {view === "playground" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">YOUR AGENT WORKSPACE</p>
                  <h1>Ready when you are.</h1>
                  <p>Equip an agent, give it a task, follow every tool call.</p>
                </div>
                <button
                  className="primary"
                  onClick={() =>
                    setEditor({ slug: "", config: { ...initial }, isNew: true })
                  }
                >
                  <Plus size={17} /> New agent
                </button>
              </div>
              <div className="agent-strip">
                {agents.map((a) => (
                  <button
                    key={a.slug}
                    className={`agent-card ${selected === a.slug ? "active" : ""}`}
                    onClick={() => setSelected(a.slug)}
                  >
                    <span className="agent-icon">
                      <Box size={21} />
                    </span>
                    <span>
                      <strong>{a.name}</strong>
                      <small>
                        {a.config.provider === "demo"
                          ? "Demo provider"
                          : "OpenRouter"}{" "}
                        <span>·</span> v{a.version}
                      </small>
                    </span>
                    <ChevronRight size={17} />
                  </button>
                ))}
              </div>
              {agent ? (
                <>
                  <div className="deployment">
                    <div>
                      <span className="endpoint-label">ENDPOINT</span>
                      <code>POST /v1/deployments/{selected}/runs</code>
                    </div>
                    <button
                      className="icon-button"
                      onClick={() => void copyEndpoint()}
                      aria-label="Copy endpoint"
                    >
                      {copied ? <Check size={17} /> : <Copy size={17} />}
                    </button>
                  </div>
                  <div className="workbench">
                    <section className="compose-panel panel">
                      <div className="panel-heading">
                        <h2>
                          <Terminal size={18} /> Playground
                        </h2>
                        <button
                          className="text-button"
                          onClick={() =>
                            setEditor({
                              slug: selected,
                              config: { ...agent.config },
                              isNew: false,
                            })
                          }
                        >
                          Configure <Settings2 size={15} />
                        </button>
                      </div>
                      <div className="panel-body">
                        <div className="model-line">
                          <span className="provider-mark">
                            {agent.config.provider === "demo" ? "D" : "O"}
                          </span>
                          <div>
                            <strong>
                              {agent.config.provider === "demo"
                                ? "Deterministic demo"
                                : agent.config.model ||
                                  settings?.provider.model ||
                                  "OpenRouter"}
                            </strong>
                            <small>
                              {agent.config.provider === "demo"
                                ? "No API key or credits needed"
                                : "Model requests through OpenRouter"}
                            </small>
                          </div>
                        </div>
                        {agent.config.provider === "demo" && (
                          <p className="demo-note">
                            This example runs a fixed calculation and writes a
                            report. Switch the provider in Configure for a real
                            AI response.
                          </p>
                        )}
                        <label htmlFor="task">Task</label>
                        <textarea
                          id="task"
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (
                              (e.metaKey || e.ctrlKey) &&
                              e.key === "Enter" &&
                              !busy &&
                              !running &&
                              input.trim() &&
                              settings?.worker_online
                            ) {
                              e.preventDefault();
                              void launch();
                            }
                          }}
                          maxLength={8000}
                          rows={8}
                          placeholder="What should this agent do?"
                        />
                        <div className="tool-label">
                          ENABLED TOOLS <span>{agent.config.tools.length}</span>
                        </div>
                        <div className="tool-chips">
                          {agent.config.tools.map((t) => (
                            <span key={t}>
                              <Code2 size={13} />
                              {t}
                            </span>
                          ))}
                          {!agent.config.tools.length && (
                            <small>No tools enabled</small>
                          )}
                        </div>
                        <div className="limits">
                          <span>
                            Up to {agent.config.max_steps} model calls
                          </span>
                          <span>{agent.config.timeout_seconds}s timeout</span>
                        </div>
                        <button
                          className="primary launch"
                          disabled={
                            busy ||
                            running ||
                            !input.trim() ||
                            !settings?.worker_online
                          }
                          onClick={() => void launch()}
                        >
                          {busy ? (
                            <LoaderCircle className="spin" size={17} />
                          ) : (
                            <Play size={16} fill="currentColor" />
                          )}{" "}
                          {running ? "Run in progress" : "Run agent"}
                          <span title="Command or Control + Enter">
                            ⌘/Ctrl ↵
                          </span>
                        </button>
                      </div>
                      <div className="panel-foot">
                        <Layers size={14} /> A fresh container and workspace for
                        every run
                      </div>
                    </section>
                    <section className="output-panel panel">
                      <div className="panel-heading">
                        <div
                          className="tabs"
                          role="tablist"
                          aria-label="Run details"
                        >
                          <button
                            role="tab"
                            aria-selected={pane === "events"}
                            className={pane === "events" ? "chosen" : ""}
                            onClick={() => setPane("events")}
                          >
                            Activity{" "}
                            {events.length > 0 && <span>{events.length}</span>}
                          </button>
                          <button
                            role="tab"
                            aria-selected={pane === "result"}
                            className={pane === "result" ? "chosen" : ""}
                            onClick={() => setPane("result")}
                          >
                            Result
                          </button>
                        </div>
                        {active ? (
                          <Status status={active.status} />
                        ) : (
                          <span className="muted">No active run</span>
                        )}
                      </div>
                      {!active ? (
                        <div className="empty">
                          <span className="empty-icon">
                            <Radio size={29} />
                          </span>
                          <h3>A clear view of every step.</h3>
                          <p>
                            Run a task to see model calls, tool activity,
                            <br />
                            and the files your agent creates.
                          </p>
                          <div className="empty-flow">
                            <span>Input</span>
                            <ChevronRight size={13} />
                            <span>Tools</span>
                            <ChevronRight size={13} />
                            <span>Result</span>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="run-meta">
                            <code>{active.id.slice(0, 8)}</code>
                            <span>v{active.version}</span>
                            <span>
                              {new Date(active.created_at).toLocaleTimeString()}
                            </span>
                            {running && (
                              <button
                                className="text-button danger"
                                disabled={active.cancel_requested}
                                onClick={() => void cancel()}
                              >
                                <Square size={12} />
                                {active.cancel_requested
                                  ? "Cancelling…"
                                  : "Cancel"}
                              </button>
                            )}
                          </div>
                          <div className="activity-content" role="tabpanel">
                            {pane === "events" ? (
                              <div className="event-list">
                                {events.map((event) => (
                                  <EventRow key={event.id} event={event} />
                                ))}
                                {running && (
                                  <div className="waiting">
                                    <LoaderCircle size={16} className="spin" />{" "}
                                    Waiting for the next event…
                                  </div>
                                )}
                              </div>
                            ) : (
                              <>
                                <pre className="answer">
                                  {active.output ||
                                    active.error ||
                                    "The result will appear when the agent finishes."}
                                </pre>
                                {active.artifacts?.length ? (
                                  <div className="artifacts">
                                    <h3>Artifacts</h3>
                                    {active.artifacts.map((a) => (
                                      <button
                                        key={a.id}
                                        onClick={() => void download(a)}
                                      >
                                        <FileText size={18} />
                                        <span>
                                          {a.name}
                                          <small>
                                            {a.size.toLocaleString()} bytes
                                          </small>
                                        </span>
                                        <Download size={16} />
                                      </button>
                                    ))}
                                  </div>
                                ) : null}
                              </>
                            )}
                          </div>
                          <div className="usage">
                            <span>{active.model_calls} model calls</span>
                            <span>
                              {(
                                active.prompt_tokens + active.completion_tokens
                              ).toLocaleString()}{" "}
                              tokens
                            </span>
                            <strong>{money(active.cost)}</strong>
                          </div>
                        </>
                      )}
                    </section>
                  </div>
                </>
              ) : (
                <div className="empty">Loading agents…</div>
              )}
              <div className="bottom-note">
                <span>
                  <KeyRound size={14} /> Provider credentials stay in the API
                  service.
                </span>
                <span>
                  Docker backend <ArrowUpRight size={14} />
                </span>
              </div>
            </>
          )}
          {view === "runs" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">EXECUTION LOG</p>
                  <h1>Run history</h1>
                  <p>
                    The latest 100 runs, with persisted events and artifacts.
                  </p>
                </div>
              </div>
              <div className="panel history">
                {runs.length ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Run / agent</th>
                        <th>Status</th>
                        <th>Created</th>
                        <th>Model calls</th>
                        <th>Cost</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <button
                              className="run-link"
                              onClick={() => void openRun(r)}
                            >
                              {r.agent_slug}
                              <small>
                                {r.id.slice(0, 8)} · v{r.version}
                              </small>
                            </button>
                          </td>
                          <td>
                            <Status status={r.status} />
                          </td>
                          <td>{new Date(r.created_at).toLocaleString()}</td>
                          <td>{r.model_calls}</td>
                          <td>{money(r.cost)}</td>
                          <td>
                            <button
                              className="icon-button"
                              aria-label={`Open run ${r.id}`}
                              onClick={() => void openRun(r)}
                            >
                              <ArrowUpRight size={18} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="empty">
                    <Radio size={28} />
                    <h3>No runs yet</h3>
                    <p>Your first agent run will appear here.</p>
                    <button
                      className="primary"
                      onClick={() => setView("playground")}
                    >
                      Open playground
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
          {view === "settings" && (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">WORKSPACE CONFIGURATION</p>
                  <h1>Connections & execution</h1>
                  <p>
                    Local settings are managed in your repository’s .env file.
                  </p>
                </div>
              </div>
              <div className="settings-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>
                      <KeyRound size={18} /> Model provider
                    </h2>
                    <span
                      className={`badge ${settings?.provider.configured ? "completed" : "queued"}`}
                    >
                      {settings?.provider.configured
                        ? "Configured"
                        : "Demo only"}
                    </span>
                  </div>
                  <div className="panel-body settings-body">
                    <label>API base URL</label>
                    <code>{settings?.provider.base_url}</code>
                    <label>Default model</label>
                    <code>{settings?.provider.model}</code>
                    <label>API key</label>
                    <p>
                      {settings?.provider.configured
                        ? "Saved in the API environment. Never returned to the browser."
                        : "Add LLM_API_KEY to .env to enable real model calls."}
                    </p>
                    <p className="hint">
                      After changing .env, run <code>docker compose up -d</code>{" "}
                      to recreate services with the new values. Choose
                      OpenRouter when configuring an agent.
                    </p>
                  </div>
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>
                      <Box size={18} /> Execution
                    </h2>
                  </div>
                  <div className="panel-body settings-body">
                    <label>Backend</label>
                    <p>Docker · one container per run</p>
                    <label>Sandbox resources</label>
                    <p>1 CPU · 256 MB RAM · 64 MB workspace</p>
                    <label>Network</label>
                    <p>Internal API access. No direct internet route.</p>
                    <label>Worker</label>
                    <p>
                      {settings?.worker_online
                        ? "Connected and accepting work"
                        : "Offline — check docker compose logs worker"}
                    </p>
                    <label>Administration</label>
                    <p>
                      {settings?.demo_key
                        ? "Using the local demo key. Set AGENTBERTH_ADMIN_KEY before sharing access."
                        : "Custom administration key configured."}
                    </p>
                    <button
                      className="secondary"
                      onClick={() => setLocked(true)}
                    >
                      Change console API key
                    </button>
                  </div>
                </section>
              </div>
            </>
          )}
        </div>
      </main>
      {editor && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="editor-title"
            onKeyDown={(e) => {
              if (e.key === "Escape") setEditor(null);
            }}
          >
            <form onSubmit={save}>
              <div className="panel-heading">
                <h2 id="editor-title">
                  {editor.isNew ? "Create an agent" : "Configure agent"}
                </h2>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Close editor"
                  onClick={() => setEditor(null)}
                >
                  <X size={19} />
                </button>
              </div>
              <div className="modal-body">
                <label htmlFor="agent-name">Name</label>
                <input
                  autoFocus
                  id="agent-name"
                  required
                  maxLength={80}
                  value={editor.config.name}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      config: { ...editor.config, name: e.target.value },
                    })
                  }
                />
                {editor.isNew && (
                  <>
                    <label htmlFor="slug">Endpoint slug</label>
                    <input
                      id="slug"
                      required
                      pattern="[a-z][a-z0-9-]{1,47}"
                      placeholder="research-assistant"
                      value={editor.slug}
                      onChange={(e) =>
                        setEditor({ ...editor, slug: e.target.value })
                      }
                    />
                  </>
                )}
                <label htmlFor="instructions">Instructions</label>
                <textarea
                  id="instructions"
                  required
                  rows={4}
                  maxLength={12000}
                  value={editor.config.instructions}
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      config: {
                        ...editor.config,
                        instructions: e.target.value,
                      },
                    })
                  }
                />
                <div className="form-row">
                  <div>
                    <label htmlFor="provider">Provider</label>
                    <select
                      id="provider"
                      value={editor.config.provider}
                      onChange={(e) =>
                        setEditor({
                          ...editor,
                          config: {
                            ...editor.config,
                            provider: e.target.value as Config["provider"],
                          },
                        })
                      }
                    >
                      <option value="demo">Demo (no API calls)</option>
                      <option
                        value="openrouter"
                        disabled={!settings?.provider.configured}
                      >
                        OpenRouter
                        {!settings?.provider.configured
                          ? " — key required"
                          : ""}
                      </option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="model">Model override (optional)</label>
                    <input
                      id="model"
                      maxLength={150}
                      disabled={editor.config.provider === "demo"}
                      placeholder={settings?.provider.model}
                      value={editor.config.model}
                      onChange={(e) =>
                        setEditor({
                          ...editor,
                          config: { ...editor.config, model: e.target.value },
                        })
                      }
                    />
                  </div>
                </div>
                <fieldset>
                  <legend>Tools</legend>
                  {["python", "write_file", "read_file"].map((t) => (
                    <label className="checkbox" key={t}>
                      <input
                        type="checkbox"
                        checked={editor.config.tools.includes(t)}
                        onChange={(e) =>
                          setEditor({
                            ...editor,
                            config: {
                              ...editor.config,
                              tools: e.target.checked
                                ? [...editor.config.tools, t]
                                : editor.config.tools.filter((v) => v !== t),
                            },
                          })
                        }
                      />
                      {t}
                    </label>
                  ))}
                </fieldset>
                <div className="form-row">
                  <div>
                    <label htmlFor="steps">Maximum model calls</label>
                    <input
                      id="steps"
                      type="number"
                      min={1}
                      max={12}
                      required
                      value={editor.config.max_steps}
                      onChange={(e) =>
                        setEditor({
                          ...editor,
                          config: {
                            ...editor.config,
                            max_steps: +e.target.value,
                          },
                        })
                      }
                    />
                  </div>
                  <div>
                    <label htmlFor="timeout">Timeout (seconds)</label>
                    <input
                      id="timeout"
                      type="number"
                      min={10}
                      max={300}
                      required
                      value={editor.config.timeout_seconds}
                      onChange={(e) =>
                        setEditor({
                          ...editor,
                          config: {
                            ...editor.config,
                            timeout_seconds: +e.target.value,
                          },
                        })
                      }
                    />
                  </div>
                </div>
                <p className="hint">
                  Saving publishes a new configuration version at this endpoint.
                  Existing runs keep their original configuration.
                </p>
                {error && (
                  <p className="form-error" role="alert">
                    {error}
                  </p>
                )}
              </div>
              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setEditor(null)}
                >
                  Cancel
                </button>
                <button className="primary" disabled={busy}>
                  {busy
                    ? "Saving…"
                    : editor.isNew
                      ? "Create & publish"
                      : "Save & publish"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
      {locked && (
        <div className="modal-backdrop">
          <form
            className="modal login"
            onSubmit={(e) => {
              e.preventDefault();
              sessionStorage.setItem("agentberth-key", key);
              setError("");
              void refresh();
            }}
          >
            <Anchor size={30} />
            <h2>Connect to Agentberth</h2>
            <p>
              Enter the AGENTBERTH_ADMIN_KEY from your .env file. The local demo
              default is agentberth-local.
            </p>
            <label htmlFor="admin-key">Administration API key</label>
            <input
              id="admin-key"
              autoFocus
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
            />
            <button className="primary">Connect</button>
          </form>
        </div>
      )}
    </div>
  );
}

function Status({ status }: { status: string }) {
  return (
    <span className={`badge ${status}`}>
      {status === "running" ? (
        <LoaderCircle className="spin" size={12} />
      ) : null}
      {status.replace("_", " ")}
    </span>
  );
}
function EventRow({ event }: { event: RunEvent }) {
  const names: Record<string, string> = {
    "run.queued": "Run queued",
    "run.started": "Sandbox ready",
    "model.started": "Calling model",
    "model.completed": "Model responded",
    "tool.started": "Running tool",
    "tool.completed": "Tool finished",
    "agent.result": "Result saved",
    "run.completed": "Run completed",
    "run.failed": "Run failed",
    "run.cancelled": "Run cancelled",
    "run.timed_out": "Run timed out",
    "agent.message": "Agent message",
  };
  return (
    <div
      className={`event-row ${event.kind === "run.completed" ? "success" : ""}`}
    >
      <span className="event-icon">
        {event.kind.startsWith("tool") ? (
          <Code2 size={15} />
        ) : event.kind === "run.completed" ? (
          <Check size={15} />
        ) : (
          <Radio size={15} />
        )}
      </span>
      <div>
        <div className="event-title">
          <strong>{names[event.kind] || event.kind}</strong>
          {!!event.data.name && <code>{String(event.data.name)}</code>}
          <time>{new Date(event.created_at).toLocaleTimeString()}</time>
        </div>
        {!!event.data.text ? (
          <p>{String(event.data.text)}</p>
        ) : (
          <details>
            <summary>Details</summary>
            <pre>{JSON.stringify(event.data, null, 2)}</pre>
          </details>
        )}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
