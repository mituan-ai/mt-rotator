# Repository Guidelines

## Product boundaries

- MT Rotator is an invite-only, multi-user A-share ETF research and paper-trading application.
- It never sends live broker orders and never presents end-of-day data as real-time.
- Strategy code is administrator-maintained and versioned. Users cannot upload code or edit strategy parameters.
- Do not add social feeds, avatars, leaderboards, manual trading, or public portfolio data.

## Structure

- `backend/`: Django, DRF, Celery, market-data ingestion, strategy engine, backtests, and immutable paper ledger.
- `frontend/`: Vite, React, TypeScript, authenticated application and integrated admin pages.
- `infra/`: Caddy and operational scripts.

## Development

- Backend: `cd backend && uv sync --all-groups && MT_TESTING=1 uv run pytest`.
- Frontend: `cd frontend && npm ci && npm test && npm run build`.
- Full stack: copy `.env.example` to `.env`, then run `docker compose up --build`.
- Never commit `.env`, credentials, database files, market caches, or generated build output.

## Correctness invariants

- Signals may only read completed data at or before their signal date.
- A close-derived signal may not fill before the next trading session.
- Research uses back-adjusted data; fills use raw OHLC only.
- Missing pre-listing data stays missing. Never backward-fill price history.
- Orders, fills, ledger entries, strategy versions, and dataset snapshots are append-only.

## Style and verification

- Python uses Ruff formatting and explicit Decimal arithmetic for money.
- TypeScript uses single quotes and no semicolons.
- Add tests for every accounting, temporal, authentication, or data-readiness change.
- Preserve user data and unrelated worktree changes. Never overwrite the archived project.
