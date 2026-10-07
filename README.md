# API Contract Synchronization Agent

A small, dependency-free CLI and agent playbook for keeping a FastAPI/Pydantic backend and a TypeScript frontend in sync. It compares response models and route declarations with a Git base commit or saved snapshot, generates TypeScript interfaces, locates likely frontend consumers, and produces an integration checklist.
