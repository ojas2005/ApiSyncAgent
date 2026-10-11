# API Contract Synchronization Agent

A small, dependency-free CLI and agent playbook for keeping a FastAPI/Pydantic backend and a TypeScript frontend in sync. It compares response models and route declarations with a Git base commit or saved snapshot, generates TypeScript interfaces, locates likely frontend consumers, and produces an integration checklist.

## What it detects

- Added, removed, or changed `BaseModel` fields, including inherited fields and simple `Field(alias=...)` / `Field(serialization_alias=...)` names.
- Added, removed, or changed FastAPI route response declarations such as `@app.get("/users/{id}", response_model=UserResponse)`.
- Type and requiredness changes that can break consumers. A removed field, changed type, or newly optional response field is marked potentially breaking. Added response fields are reported for review.
- Candidate TypeScript/JavaScript files and lines that mention the model or route and use an affected field.
