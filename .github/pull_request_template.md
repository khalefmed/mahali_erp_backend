Closes #

## What

<!-- One or two sentences: what changed and why. -->

## API changes

<!-- New / changed endpoints and error codes the web app must handle. "None" if none. -->

## Checklist

- [ ] New store-scoped tables subclass `StoreScopedModel` and have an `EnableRowLevelSecurity` migration
- [ ] Business logic in `services.py` / `selectors.py`, views stay thin
- [ ] Permissions declared (`required_permissions` / `console_permissions`)
- [ ] Errors raise `ApiError` with a stable `code`
- [ ] `openapi/schema.yaml` regenerated and committed
- [ ] Tests added; `uv run pytest` and `uv run ruff check .` pass
