"""Bundled agents, inserted once so administrator edits survive restarts."""

from runtime.packages import reference

EXAMPLES = [
    {
        "slug": "sales-data-auditor",
        "name": "Sales data auditor",
        "instructions": "Audit the supplied data using Python's standard library. Validate before calculating. "
        "Explain exclusions and never invent missing values. Verify generated files by reading them back. "
        "Save all deliverables at the workspace root and summarize findings.",
        "example_task": "Audit this CSV. Remove exact duplicate rows, exclude rows with missing region or "
        "non-numeric amounts, and retain negative amounts as refunds. Produce cleaned.csv, "
        "summary.json (net revenue by region, overall net revenue, valid row count), and audit.md "
        "explaining each excluded row and the refund. Use Python to verify totals.\n\n"
        "order_id,region,amount\nA001,North,120.50\nA002,South,80\nA002,South,80\n"
        "A003,North,-20\nA004,West,not_available\nA005,,60\nA006,South,45.25\nA007,West,200\n",
    },
    {
        "slug": "project-dependency-planner",
        "name": "Project dependency planner",
        "instructions": "Use Python to validate task dependencies, detect cycles, and calculate a critical path. "
        "Treat durations as working days and assume unlimited parallel capacity unless told otherwise. "
        "Explain assumptions. Save machine-readable results and a readable plan, then verify the files.",
        "example_task": "Plan this release starting at working day 0. Tasks: requirements (2 days, no dependencies); "
        "api (4 days, depends on requirements); ui (3 days, depends on requirements); "
        "integration (2 days, depends on api and ui); security-review (3 days, depends on api); "
        "launch (1 day, depends on integration and security-review). Check for cycles, calculate earliest "
        "start/finish and the critical path using Python. Write schedule.csv and plan.md with a Mermaid "
        "dependency diagram. Also quantify how adding two days to api changes the launch finish date. "
        "Verify calculations and save checks.json containing baseline_finish_day and delayed_finish_day.",
    },
    {
        "slug": "release-notes-editor",
        "name": "Release notes editor",
        "instructions": "Turn rough engineering notes into clear customer-facing release notes. Preserve facts, "
        "separate shipped work from future plans, and flag ambiguity rather than guessing. "
        "Write requested files with the file tools and read them back to verify their contents.",
        "example_task": "Turn these notes into release-notes.md and qa-checklist.md. Notes: ZIP uploads now "
        "extract automatically; input files expire after each task; users can download multi-file output as ZIP; "
        "the console defaults to dark mode; fixed-interval schedules can be paused and resumed; cron expressions "
        "are planned but not shipped. Make release notes understandable to a new user. The QA checklist should "
        "include normal cases, invalid ZIPs, cancellation, and restarting the worker. Do not invent performance claims.",
        "tool_names": ["write_file", "read_file"],
    },
]


def configs():
    for example in EXAMPLES:
        config = {k: v for k, v in example.items() if k not in {"slug", "tool_names"}}
        config.update(
            provider="openrouter",
            model="",
            max_steps=10,
            max_output_tokens=8192,
            timeout_seconds=240,
            tools=[reference(n) for n in example.get("tool_names", ["python", "write_file", "read_file"])],
        )
        yield example["slug"], config


LEGACY_TASKS = {
    "harbor-guide": (
        "Harbor guide",
        "Run the fixed demonstration: calculate the total and average of 12, 18, and 24, and save report.md.",
    ),
    "scheduled-example-": (
        "Scheduled report example",
        "Generate the scheduled demonstration report for 12, 18, and 24. Save the total and average to report.md.",
    ),
    "tool-check-": (
        "Tool integration check",
        "Use Python to create sample.csv with columns name,score and rows Ada,10 and Lin,20. Read it back, calculate the average score, and write the row count, column names, and average to report.md.",
    ),
    "kube-check-": (
        "Kubernetes integration check",
        "Run the fixed demonstration in a Kubernetes sandbox and save report.md with the total and average of 12, 18, and 24.",
    ),
    "smoke-": (
        "Smoke test",
        "Run the fixed demonstration and generate report.md to verify task execution and artifact downloads.",
    ),
}


def legacy_task(slug, name, provider="openrouter"):
    for prefix, (expected_name, task) in LEGACY_TASKS.items():
        if name == expected_name and (
            slug == prefix if prefix == "harbor-guide" else slug.startswith(prefix)
        ):
            if prefix == "tool-check-" and provider == "demo":
                return "Run the fixed demonstration to verify built-in tool execution and save report.md. Select OpenRouter to process arbitrary data."
            return task
    return None
