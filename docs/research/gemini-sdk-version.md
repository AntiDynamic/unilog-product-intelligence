# Gemini SDK version audit

- Declared in `pyproject.toml`: `google-genai>=2.0,<3.0`
- Historical `uv.lock`: `1.75.0`
- Historical runtime report: `1.75.0`
- Canonical status: **INCONSISTENT; reconcile before live execution**

No live API request was made in Phase 6.11. Run `uv lock`/`uv sync` in the canonical environment, then verify the installed package version matches the lockfile and declared range. The lockfile must not be hand-edited.
