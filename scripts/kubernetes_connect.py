"""Forward a selected Agentberth cluster console to localhost without changing your default context."""

import argparse
import os
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", default=".kubeconfig")
    parser.add_argument(
        "--context", help="Defaults to the current context inside the explicitly supplied kubeconfig."
    )
    parser.add_argument("--namespace", default="agentberth")
    parser.add_argument("--release", default="demo")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    context = (
        args.context
        or subprocess.check_output(
            ["kubectl", "--kubeconfig", args.kubeconfig, "config", "current-context"], text=True
        ).strip()
    )
    service = (args.release + "-agentberth")[:50].rstrip("-") + "-api"
    print(
        f"Connecting context {context} to http://localhost:{args.port}. Leave this terminal open; Ctrl+C disconnects.",
        flush=True,
    )
    os.execvp(
        "kubectl",
        [
            "kubectl",
            "--kubeconfig",
            args.kubeconfig,
            "--context",
            context,
            "-n",
            args.namespace,
            "port-forward",
            "--address=127.0.0.1",
            "svc/" + service,
            f"{args.port}:8080",
        ],
    )


if __name__ == "__main__":
    main()
