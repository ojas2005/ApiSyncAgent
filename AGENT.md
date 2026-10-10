# API Contract Synchronization Agent

Use this playbook in a full-stack repository containing a FastAPI/Pydantic backend and a TypeScript frontend.

1. Identify the backend and frontend source directories and the committed generated TypeScript contract file.
2. Run `api-contract-sync check --backend BACKEND --frontend FRONTEND --base-ref BASE_REF --types-out TYPES_FILE --write-types --report api-contract-report.md --json-report api-contract-report.json`. Use a committed snapshot with `--baseline` when there is no Git base ref.
