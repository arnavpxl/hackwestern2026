# TokenTrueUp: session handoff

Working notes for whoever (human or Claude Code session) continues the build.
The approved implementation plan is at `~/.claude/plans/steady-stirring-lynx.md`; read it first.
The original product spec was the first message of the previous session; the plan summarises it.

## State (as of the handoff)

- Repo is at `~/hackwestern2026` (moved off iCloud, which made file reads hang). Backend is **done and
  committed**; everything below "Then" is still to build.
- **DB:** TimescaleDB 2.32 / PG17 in Docker at `localhost:5433`. Migrations 0001–0013 applied. About 28.9M
  `usage_events` rows (20M backfill plus demo runs); raw 90.6% compressed, caggs 38–92%.
- **Setup:** `make up` (DB, venv, migrate, and seed + backfill + `make compress` only if empty), then
  `make demo` (API with the in-process generator on :8000), `make web` (frontend on :3000). Also `make flow` (scripted end-to-end demo,
  `backend/scripts/demo_flow.py`), `make bench` (writes `BENCHMARKS.md`), `make test`, `make lint`,
  `make reset`.
- **Live LLM mode is on locally:** `.env` has an `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL=claude-haiku-4-5`
  (the original `claude-haiku-4.5` 404'd, so every agent silently fell back). `.env` is gitignored.
- The test DB `tokentrueup_test` is created and dropped by `backend/tests/conftest.py`.

## Environment gotchas

- `psql` is at `/opt/homebrew/opt/libpq/bin/psql` (not on PATH).
- The venv lives **outside the repo** at `~/.cache/tokentrueup/venv`; `backend/.venv` is a symlink to it.
- **Do not use `uv run`.** It rebuilds the editable install, macOS marks the new `.pth` file hidden,
  and Python 3.12 then skips it; a uv lock can also hang. Instead, from `backend/`:
  - `PYTHONPATH=src .venv/bin/uvicorn tokentrueup.api.main:app --port 8000` (no `--reload`: the
    in-process generator makes reloads hang)
  - `PYTHONPATH=src:. .venv/bin/pytest -q`
  - `PYTHONPATH=src .venv/bin/db-migrate`, `.venv/bin/ttu-seed`, `.venv/bin/ttu-backfill --rows 20000000`
  - `.venv/bin/ruff check src`
- To re-sync deps: `UV_PROJECT_ENVIRONMENT=$HOME/.cache/tokentrueup/venv uv sync`, then
  `chflags -R nohidden ~/.cache/tokentrueup/venv`.
- Migrations run inside one transaction per file, so `CALL refresh_continuous_aggregate` can't go in a
  migration. In TimescaleDB 2.32, `add_columnstore_policy` and `remove_columnstore_policy` are
  procedures (`CALL`).

## Verified so far

- 27/27 tests pass; ruff clean.
- **Full flow (`make flow`) runs clean end to end with live LLM:** reset → play → stealth_price +
  duplicate_invoice → close ($370k) → runaway caught in ~5–8 s → owner reply stops it → orphan reply
  assigns an owner → fast-forward to month end → close → approve all ($384k) → fast-forward to invoices
  → recon. Diagnoses: nimbus-pro rate change (+$8.3k), duplicate Stratus invoice, Cortexa 50% cached
  discount, Helio +2.5% GPU-hours, Quill orphan key (this month $0 after the reply; history −25%).
  Rule replay: every rule takes Aug–Nov error to 0.0%.
- `BENCHMARKS.md` (via `make bench`): 30-day query raw 1.78 s vs cagg 1.8 ms (~1000×, totals match);
  real-time visibility ~5 ms; `scan_anomalies` ~23 ms; COPY ~250k rows/s; 18 provider-months
  re-accrued in ~360 ms; runaway to case ~8 s.
- Fixed this session (see commit `87fff1c` and the later one): reset rewinds future cagg watermarks
  (catalog write, needs superuser; on Tiger Cloud fall back to a full rebuild if refused), trims the
  last 10 min and waits out the generator tick; fast-forward tail at live density; rate-based
  `spike_start` (0013); invoice sim and diagnosis price stealth rates with discounts; invoice-delivery
  advisory lock; close LLM calls run concurrently (72 s → 9 s).

## Known rough edges

- Once (not reproducible since): right after a reset, three keys got false anomaly cases with no
  change point (`spike_started_at` NULL, window spend ~5-min fat events). Suspect stale usage_1m
  buckets surviving a reset; watch for it. Close no longer crashes on those (falls back to opened_at).

- `/api/recon/run` takes ~15 s in live mode: variance narrators still run one invoice at a time
  (`orchestrator/recon.py: reconcile`). Same fix as close (gather after the deterministic part).
- The anomaly case's own `estimate_cents` stays NULL (its excess is folded into the usage case via
  `exclude_window`); the UI should show the usage case's number.
- The detector opens at most one case per key per 6 h, so repeat a runaway on another key or reset.
- The rewind uses a catalog UPDATE (`_timescaledb_catalog.continuous_aggs_watermark`). Check on
  Tiger Cloud; if refused, reset logs a warning and live data stays invisible until a rebuild.

## Then (next steps, in order)

- Frontend basics are in `frontend/` (Next.js 15 + Tailwind 4 + Recharts + SWR, polling every 1–2 s, SSE toasts):
  Live spend, Close, Case detail (SQL + re-run, reply box), Reconciliation (invoices, rules, replay table),
  Under the hood (race, freshness probe, columnstore, caggs, jobs). Sim controls live in the header.
  Still to do: a scripted `/sim/demo` button and polish. Headless screenshots need real waiting
  (polling defeats `--virtual-time-budget`); a CDP helper that does this is easy to rebuild.
- README: frame it as **AI usage spend** (models, GPUs, vector/inference APIs), not AI subscriptions;
  problem, Mermaid diagram with Tiger Data at the centre, why each Tiger feature, 2-command
  setup, Assumptions, "How we used Tiger Data" with benchmark numbers, 3-minute demo script.
- Tiger Cloud cutover: the user runs `tiger auth login`, then `tiger service create`, migrate, backfill,
  and point `DATABASE_URL` in `.env` at it.

## Design decisions to log in the README "Assumptions"

- The sim clock is anchored to real time: `sim_now() = now() + sim_offset`. Live events must land
  above the cagg watermark, which is relative to real `now()`, for real-time aggregation to show them.
- Caggs store token/request sums. Cost comes from views (`usage_1h_cost`, `usage_1d_cost`) that join
  each bucket to the rate in effect (`price_changes`, as-of LATERAL), because caggs can't range-join
  two hypertables.
- The baseline is an hour-of-day-aware `stats_agg` cagg (`spend_baseline`). Trailing 14-day
  mean/stddev comes from `rollup()`.
- The usage estimator truncates `as_of` to the hour so the stored SQL + params reproduce exactly.
- At 3–10k events/s an event is a metering record (a streamed chunk), not a whole API request.
  Tokens use stochastic rounding.
- The orphan key is excluded from accrual until an owner is assigned. The provider bills all keys,
  so history invoices show about −25% on Quill.
