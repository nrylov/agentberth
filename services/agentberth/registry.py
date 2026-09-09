import json
import os
from pathlib import Path

from psycopg.types.json import Jsonb

from runtime.packages import digest, read_folder, reference, validate_package


class Conflict(ValueError):
    pass


def register(conn, package, origin="imported", published=False):
    validate_package(package)
    m = package["manifest"]
    sha = digest(package)
    # One transaction serializes bundle reload/import and package publication.
    conn.execute("SELECT pg_advisory_xact_lock(71003)")
    existing = conn.execute(
        "SELECT * FROM tool_versions WHERE tool_id=%s AND version=%s", (m["id"], m["version"])
    ).fetchone()
    if existing:
        if existing["status"] == "deleted":
            raise Conflict("This tool version was deleted. Use a new version number.")
        if existing["sha256"] != sha:
            raise Conflict(
                f"{m['id']}@{m['version']} already exists with different contents. Increment the version."
            )
        return existing
    return conn.execute(
        "INSERT INTO tool_versions(tool_id,version,name,package,sha256,status,origin) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            m["id"],
            m["version"],
            m["name"],
            Jsonb(package),
            sha,
            "published" if published else "draft",
            origin,
        ),
    ).fetchone()


def bundled(conn):
    root = Path(
        os.getenv("BUNDLED_TOOLS_DIR", str(Path(__file__).resolve().parents[2] / "tools" / "builtin"))
    )
    if not root.is_dir():
        raise ValueError("Bundled tools directory is missing.")
    packages = [read_folder(p.parent) for p in sorted(root.glob("*/tool.json"))]
    if not packages:
        raise ValueError("No bundled tools found.")
    return [register(conn, p, origin="bundled", published=True) for p in packages]


def resolve(conn, defaults, additions=(), disabled=()):
    refs = [reference(r) for r in defaults]
    disabled = set(disabled)
    if disabled - {r["id"] for r in refs}:
        raise ValueError("Only inherited tools can be disabled.")
    refs = [r for r in refs if r["id"] not in disabled]
    refs += [reference(r) for r in additions]
    if len(refs) > 12:
        raise ValueError("A run supports at most 12 tools.")
    result, ids, names = [], set(), set()
    for ref in refs:
        if ref["id"] in ids:
            raise ValueError("Duplicate tool ID. Disable the inherited version before adding a replacement.")
        row = conn.execute(
            "SELECT * FROM tool_versions WHERE tool_id=%s AND version=%s AND status='published'",
            (ref["id"], ref["version"]),
        ).fetchone()
        if not row:
            raise ValueError(f"Published tool {ref['id']}@{ref['version']} was not found.")
        if row["name"] in names:
            raise ValueError("Selected tools have conflicting model-facing names.")
        ids.add(ref["id"])
        names.add(row["name"])
        result.append({**row["package"], "sha256": row["sha256"]})
    if len(json.dumps(result).encode()) > 400_000:
        raise ValueError("Selected tool packages exceed the 400 KB run limit.")
    return result


def refs(packages):
    return [
        {
            "id": p["manifest"]["id"],
            "version": p["manifest"]["version"],
            "sha256": p["sha256"],
            "name": p["manifest"]["name"],
        }
        for p in packages
    ]


def snapshot(conn, defaults, additions=(), disabled=()):
    packages = resolve(conn, defaults, additions, disabled)
    return [p["manifest"]["name"] for p in packages], packages
