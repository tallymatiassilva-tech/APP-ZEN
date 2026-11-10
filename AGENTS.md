# AGENTS.md

## Project overview

This repository contains a Python desktop application for JadLog/Zendesk document processing and reporting. The current work is a gradual refactor: keep the GUI coordination in `src/app_legacy.py` while moving business rules and processing logic into smaller, testable services under `src/services/`, `src/repositories/`, `src/utils/`, `src/states/`, and `src/models/`.

For the current refactor status and constraints, see [ANDAMENTO_REFACTORIZACAO.md](ANDAMENTO_REFACTORIZACAO.md).

## Working conventions

- Prefer incremental extraction over large rewrites.
- Keep UI callbacks, dialogs, and display logic in `src/app_legacy.py` unless the task is explicitly about the refactor itself.
- Move logic into services when it is testable and independent of the GUI.
- Preserve existing behavior, UF-specific rules, and legacy compatibility unless the task explicitly requires a change.
- Follow the current naming and pattern used by the existing service layer; do not introduce a new framework or architecture during routine fixes.
- Treat `checkpoints/`, generated artifacts, and `Tesseract-OCR/` as non-source assets and keep changes out of them unless the task requires it.

## Key entry points

- `src/app.py`: app bootstrap entry point.
- `src/app_legacy.py`: legacy orchestration point for GUI behavior and callbacks.
- `tests/`: regression coverage for the extraction, validation, Zendesk, and report flows.
- `pyproject.toml`: project lint configuration; Python target is 3.11 and Ruff is enabled.

## Validation commands

Run these from the repository root when verifying changes:

- `python -m pytest -q`
- `ruff check .`
- `python -m compileall src`

The project history in [ANDAMENTO_REFACTORIZACAO.md](ANDAMENTO_REFACTORIZACAO.md) notes that the latest validated state included 171 passing tests and a clean Ruff import-order pass. Avoid relying on real Zendesk/Fraction traffic or real PDFs during routine validation; the suite is designed around simulated data and mocked responses.

## Agent guidance

- Prefer the smallest fix that matches the existing architecture.
- Update or add tests for behavior changes in `tests/`.
- Do not broaden the refactor beyond the relevant task.
- If a change touches extracted services, keep the public contract stable and minimize GUI coupling.
- Before making a large refactor, check the current refactor notes in [ANDAMENTO_REFACTORIZACAO.md](ANDAMENTO_REFACTORIZACAO.md) to avoid conflicting with the in-progress design.
