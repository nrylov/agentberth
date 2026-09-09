# Contributing to Agentberth

Start with the [quick start](README.md) and [development guide](docs/development.md). Keep changes small and explain the user-facing behavior, design tradeoffs, and validation in your pull request.

Run Python lint/format/tests, the frontend build, and the demo smoke test before submitting execution changes. For worker lifecycle changes, also run the resilience script on a disposable local stack. Live provider tests are optional, incur charges, and should never require repository secrets in CI.

Never commit `.env`, credentials, conversation data, or local build artifacts. Update docs alongside configuration/API changes. Keep the support matrix honest: a backend is implemented only after its full deployment and lifecycle path is tested.

Contributions are under the repository's Apache-2.0 license. Do not add dependencies or copied code whose licensing is incompatible with the intended distribution.
