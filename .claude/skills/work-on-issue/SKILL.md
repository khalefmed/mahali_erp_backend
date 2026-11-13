---
name: work-on-issue
description: Implement a GitHub issue of the backend end to end — branch, build, test, regenerate the OpenAPI schema, open the PR. Use when asked to "work on issue #N", "pick up #N", "implement #N", or given an issue URL from this repo.
---

# Work on an issue

Input: an issue number (or URL). One issue = one branch = one PR.

1. **Read the issue**: `gh issue view <n> --comments`. Note the module, endpoints, error
   codes and acceptance criteria. If the Figma link matters, look at the node with the
   Figma MCP to know which fields the screen needs. Ask if something essential is missing.
2. **Branch** from an up-to-date `main`:
   ```bash
   git switch main && git pull --ff-only && git switch -c feat/<n>-<short-name>
   ```
   `fix/` for bugs.
3. **Model** in the right app. Data of one store → subclass `StoreScopedModel`, then
   `uv run python manage.py makemigrations` and add `EnableRowLevelSecurity("<model>")`
   (see `apps/inventory/migrations/0003_row_level_security.py`).
4. **Service first**: business rules and transactions in `services.py`, raising
   `ApiError` with stable codes. Then a thin view with `StoreScopedViewMixin` and
   `required_permissions` (or `ConsoleMixin` + `console_permissions`), `extend_schema`
   with an `operation_id` and the error codes in `description`.
5. **Test** the rules, permissions and isolation (`conftest.py` has `make_store`,
   `client_for`, `add_member`, `api()`).
6. **Verify**:
   ```bash
   uv run ruff check . && uv run ruff format . && uv run pytest
   uv run python manage.py spectacular --file openapi/schema.yaml --validate --fail-on-warn
   ```
7. **Commit and PR** (ask the user before pushing):
   ```bash
   gh pr create --fill --body-file - <<< "Closes #<n> …"
   ```
   Follow `.github/pull_request_template.md`, list API changes for the web app, and tick
   only what you actually checked.

Keep the PR to the issue's scope. Unrelated problem → `gh issue create`, not this PR.
