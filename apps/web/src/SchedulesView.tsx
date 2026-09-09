import { useState } from "react";
import { type ToolRecord, refKey } from "./ToolsView";

export type Schedule = {
  id: string;
  name: string;
  agent_slug: string;
  version: number;
  input: string;
  interval_seconds: number | null;
  next_run_at: string | null;
  enabled: boolean;
  last_run_id: string | null;
};
export type Queue = { queued: number; running: number; capacity: number };
type Api = <T>(path: string, options?: RequestInit) => Promise<T>;
type Props = {
  schedules: Schedule[];
  queue: Queue | null;
  agents: {
    slug: string;
    name: string;
    config: { tools: { id: string; version: string }[] };
  }[];
  tools: ToolRecord[];
  runs: { id: string; agent_slug: string; status: string }[];
  api: Api;
  refresh: () => Promise<void>;
  onRun: (id: string) => Promise<void>;
};

export function SchedulesView({
  schedules,
  queue,
  agents,
  tools,
  runs,
  api,
  refresh,
  onRun,
}: Props) {
  const [name, setName] = useState("Scheduled report");
  const [slug, setSlug] = useState("harbor-guide");
  const [input, setInput] = useState(
    "Calculate the total and average of 12, 18, and 24. Save a short report to report.md.",
  );
  const [start, setStart] = useState("");
  const [repeat, setRepeat] = useState(true);
  const [seconds, setSeconds] = useState(3600);
  const [additions, setAdditions] = useState<string[]>([]);
  const [disabled, setDisabled] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function action(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const toggle = (items: string[], value: string) =>
    items.includes(value)
      ? items.filter((x) => x !== value)
      : [...items, value];
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">AUTOMATION</p>
          <h1>Queue & schedules</h1>
          <p>
            {queue?.queued ?? 0} / {queue?.capacity ?? 50} queued ·{" "}
            {queue?.running ?? 0} running. Tasks execute one at a time in
            submission order.
          </p>
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <section className="panel schedule-panel">
        <div className="panel-heading">
          <h2>Create a schedule</h2>
        </div>
        <form
          className="panel-body schedule-form"
          onSubmit={(e) => {
            e.preventDefault();
            void action(async () => {
              await api("/v1/schedules", {
                method: "POST",
                body: JSON.stringify({
                  name,
                  agent_slug: slug,
                  input,
                  start_at: start
                    ? new Date(start).toISOString()
                    : new Date().toISOString(),
                  interval_seconds: repeat ? seconds : null,
                  additional_tools: additions.map((value) => {
                    const [id, version] = value.split("@");
                    return { id, version };
                  }),
                  disabled_tools: disabled,
                }),
              });
              setNotice(
                "Schedule created. Its runs will appear below and in Run history.",
              );
            });
          }}
        >
          <label>
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={80}
            />
          </label>
          <label>
            Agent
            <select
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setDisabled([]);
                setAdditions([]);
              }}
            >
              {agents.map((a) => (
                <option key={a.slug} value={a.slug}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Task
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              required
              maxLength={8000}
              rows={3}
            />
          </label>
          <label>
            First run (your local time; blank starts now)
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            Frequency
            <select
              value={repeat ? "repeat" : "once"}
              onChange={(e) => setRepeat(e.target.value === "repeat")}
            >
              <option value="once">Once</option>
              <option value="repeat">Repeat at a fixed interval</option>
            </select>
          </label>
          {repeat && (
            <label>
              Interval in seconds (60 minimum)
              <input
                type="number"
                min={60}
                max={31536000}
                required
                value={seconds}
                onChange={(e) => setSeconds(Number(e.target.value))}
              />
            </label>
          )}
          <fieldset>
            <legend>Agent tools</legend>
            {agents
              .find((a) => a.slug === slug)
              ?.config.tools.map((t) => (
                <label className="schedule-check" key={t.id}>
                  <input
                    type="checkbox"
                    checked={!disabled.includes(t.id)}
                    onChange={() => setDisabled(toggle(disabled, t.id))}
                  />
                  {refKey(t)}
                </label>
              ))}
          </fieldset>
          <fieldset>
            <legend>Additional published tools</legend>
            {tools
              .filter(
                (t) =>
                  t.status === "published" &&
                  !agents
                    .find((a) => a.slug === slug)
                    ?.config.tools.some(
                      (r) => r.id === t.tool_id && !disabled.includes(r.id),
                    ),
              )
              .map((t) => {
                const value = `${t.tool_id}@${t.version}`;
                return (
                  <label className="schedule-check" key={value}>
                    <input
                      type="checkbox"
                      checked={additions.includes(value)}
                      onChange={() => setAdditions(toggle(additions, value))}
                    />
                    {value}
                  </label>
                );
              })}
          </fieldset>
          <p>
            The current agent version and tools are saved with this schedule.
            Upload files on individual runs. Missed intervals are combined into
            one run; overlapping occurrences are skipped.
          </p>
          <button className="primary" disabled={busy || !agents.length}>
            Create schedule
          </button>
        </form>
      </section>
      <section className="panel history schedule-panel">
        <div className="panel-heading">
          <h2>Schedules</h2>
        </div>
        {schedules.length ? (
          <table>
            <thead>
              <tr>
                <th>Name / agent</th>
                <th>Frequency</th>
                <th>Next run</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.name}
                    <small className="schedule-detail">
                      {s.agent_slug} · v{s.version}
                    </small>
                    <small className="schedule-detail">{s.input}</small>
                  </td>
                  <td>
                    {s.interval_seconds
                      ? `Every ${s.interval_seconds}s`
                      : "Once"}
                  </td>
                  <td>
                    {!s.next_run_at
                      ? "Finished"
                      : !s.enabled
                        ? "Paused"
                        : new Date(s.next_run_at).toLocaleString()}
                  </td>
                  <td>
                    <div className="schedule-actions">
                      {s.last_run_id && (
                        <button
                          onClick={() =>
                            void action(() => onRun(s.last_run_id!))
                          }
                        >
                          Latest run
                        </button>
                      )}
                      {s.next_run_at && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            void action(() =>
                              api(`/v1/schedules/${s.id}`, {
                                method: "PATCH",
                                body: JSON.stringify({ enabled: !s.enabled }),
                              }),
                            )
                          }
                        >
                          {s.enabled ? "Pause" : "Resume"}
                        </button>
                      )}
                      <button
                        disabled={busy}
                        onClick={() => {
                          if (
                            confirm(
                              `Delete schedule “${s.name}”? Existing runs will be kept.`,
                            )
                          )
                            void action(() =>
                              api(`/v1/schedules/${s.id}`, {
                                method: "DELETE",
                              }),
                            );
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">
            <p>No schedules yet.</p>
          </div>
        )}
        <p className="panel-body">
          Pause or delete prevents future submissions. Cancel an existing run
          separately. To change a schedule's task or configuration, replace it
          with a new schedule.
        </p>
      </section>
      <section className="panel history">
        <div className="panel-heading">
          <h2>Pending runs</h2>
        </div>
        {runs
          .filter((r) => ["queued", "running"].includes(r.status))
          .map((r) => (
            <div className="panel-body schedule-actions" key={r.id}>
              <button onClick={() => void action(() => onRun(r.id))}>
                {r.agent_slug} · {r.id.slice(0, 8)}
              </button>
              <span>{r.status}</span>
              <button
                disabled={busy}
                onClick={() =>
                  void action(() =>
                    api(`/v1/runs/${r.id}/cancel`, { method: "POST" }),
                  )
                }
              >
                Cancel
              </button>
            </div>
          ))}
        {!queue?.queued && !queue?.running && (
          <div className="empty">
            <p>The queue is empty.</p>
          </div>
        )}
      </section>
    </>
  );
}
