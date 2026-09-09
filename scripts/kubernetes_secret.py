"""Create initial cluster credentials without putting secrets in command arguments or Helm values."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", default="agentberth")
    parser.add_argument("--release", default="agentberth")
    parser.add_argument("--secret", default="agentberth-secrets")
    parser.add_argument("--admin-key-file", type=Path, required=True)
    parser.add_argument(
        "--env-file", type=Path, help="Optionally read only LLM_API_KEY from a local .env file."
    )
    args = parser.parse_args()
    if args.admin_key_file.exists():
        parser.error(
            "Admin key output file already exists. Choose a new path; this command does not rotate credentials."
        )
    kubectl = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context]

    def call(*arguments, body=None):
        return subprocess.run(
            kubectl + list(arguments),
            input=json.dumps(body).encode() if body else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    ns = call("get", "namespace", args.namespace, "-o", "name", "--ignore-not-found")
    if ns.returncode:
        raise SystemExit("Cannot access the selected cluster. Check kubeconfig/context.")
    if not ns.stdout:
        created = call(
            "create",
            "-f",
            "-",
            body={"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": args.namespace}},
        )
        if created.returncode:
            raise SystemExit("Could not create namespace.")
    existing = call("-n", args.namespace, "get", "secret", args.secret, "-o", "name", "--ignore-not-found")
    if existing.returncode or existing.stdout:
        raise SystemExit(
            "Secret already exists or cannot be checked. Refusing to replace existing credentials."
        )
    provider_key = os.getenv("LLM_API_KEY", "")
    if args.env_file:
        for line in args.env_file.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "LLM_API_KEY":
                provider_key = value.strip().strip("\"'")
    admin_key, password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    # Match chart helper (<release>-agentberth, at most 50 characters).
    name = (args.release + "-agentberth")[:50].rstrip("-")
    args.admin_key_file.parent.mkdir(parents=True, exist_ok=True)
    with open(args.admin_key_file, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as f:
        f.write(admin_key)
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": args.secret, "namespace": args.namespace},
        "type": "Opaque",
        "stringData": {
            "ADMIN_KEY": admin_key,
            "LLM_API_KEY": provider_key,
            "POSTGRES_PASSWORD": password,
            "DATABASE_URL": f"postgresql://agentberth:{password}@{name}-postgres:5432/agentberth",
        },
    }
    result = call("create", "-f", "-", body=secret)
    if result.returncode:
        raise SystemExit("Secret creation failed. Key file retained; inspect cluster access before retrying.")
    print("Created initial Secret. Administration key saved privately to", args.admin_key_file)


if __name__ == "__main__":
    main()
