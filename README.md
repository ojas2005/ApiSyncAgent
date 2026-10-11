# API Contract Synchronization Agent

A small, dependency-free CLI and agent playbook for keeping a FastAPI/Pydantic backend and a TypeScript frontend in sync. It compares response models and route declarations with a Git base commit or saved snapshot, generates TypeScript interfaces, locates likely frontend consumers, and produces an integration checklist.

## What it detects

- Added, removed, or changed `BaseModel` fields, including inherited fields and simple `Field(alias=...)` / `Field(serialization_alias=...)` names.
- Added, removed, or changed FastAPI route response declarations such as `@app.get("/users/{id}", response_model=UserResponse)`.
- Type and requiredness changes that can break consumers. A removed field, changed type, or newly optional response field is marked potentially breaking. Added response fields are reported for review.
- Candidate TypeScript/JavaScript files and lines that mention the model or route and use an affected field.

The report also suggests a *possible* rename when one removed and one added field share a model and type. Confirm semantics before changing frontend code.

## Install

Python 3.9 or newer is required. No runtime dependencies are needed.

```bash
python3 -m pip install -e .
```

Run `api-contract-sync --help` for all options. `python3 -m api_contract_sync` also works after installation.

## Local workflow

From the full-stack repository root:

```bash
api-contract-sync check \
  --backend backend \
  --frontend frontend/src \
  --base-ref origin/main \
  --types-out frontend/src/generated/api-contracts.ts \
  --write-types \
  --report api-contract-report.md \
  --json-report api-contract-report.json \
  --fail-on-breaking
```

Review the generated type diff and the checklist. The tool returns exit code `2` when `--fail-on-breaking` finds a potentially breaking change. It returns `3` when `--verify-types` finds stale generated types, and `1` for input or parsing errors. Without `--fail-on-breaking`, reported contract changes do not fail the command.

For repositories without a suitable Git base ref, save a baseline before editing the backend:

```bash
api-contract-sync snapshot --backend backend --output api-contract-baseline.json
api-contract-sync check --backend backend --frontend frontend/src \
  --baseline api-contract-baseline.json --types-out frontend/src/generated/api-contracts.ts \
  --write-types --report api-contract-report.md
```

For the example in the request, replacing `username: str` with `full_name: str` reports `UserResponse.username` as removed, `UserResponse.full_name` as added, suggests the possible rename, and lists matching frontend access sites.

## Pull request automation

Copy this project into `tools/api-contract-agent` in the full-stack repository. Copy [the workflow template](examples/api-contract-pr.yml) to `.github/workflows/api-contract.yml`, then set `BACKEND_DIR`, `FRONTEND_DIR`, and `TYPES_OUT` to the repository's paths. Commit the generated TypeScript file after running `--write-types` locally. On each pull request, the workflow compares against the PR base commit, checks whether generated types are current, and uploads the checklist as an artifact. Teams that want a strict compatibility gate can add `--fail-on-breaking` to the workflow command.

For automated code edits, give [AGENT.md](AGENT.md) to a coding agent in that repository. It describes how to inspect candidate consumers, make confirmed frontend changes, verify them, and prepare a PR when requested. This CLI does not rewrite frontend behavior based on a static guess.
