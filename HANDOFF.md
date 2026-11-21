# TokenTrueUp: session handoff

Working notes for whoever (human or Claude Code session) continues the build.
The approved implementation plan is at `~/.claude/plans/steady-stirring-lynx.md`; read it first.
The original product spec was the first message of the previous session; the plan summarises it.

## State (as of the handoff)

- Repo moved from `~/Documents/hackwestern2026` (iCloud-synced, which made file reads hang) to
  `~/hackwestern2026`.
- **Uncommitted work.** The last commit is `c8f6777` (stage 2: simulator + estimators). Not yet
  committed: agents, verifier, orchestrator (close + recon), API, bench metrics, tests,
  migrations 0007–0012. **Commit first.**
- **DB:** TimescaleDB 2.32 / PG17 in Docker at `localhost:5433`
  (`postgresql://postgres:tokentrueup@localhost:5433/tokentrueup`). Migrations 0001–0012 are applied.
  About 20M rows of `usage_events` are loaded, at 90.6% columnstore compression.
  `docker-compose.yml` pins `name: hackwestern2026`, so the existing volume is reused.
- **The sim may be half-reset.** A `/api/sim/reset` and a manual `usage_1m` refresh were interrupted.
  Check `SELECT * FROM sim_state` and the cagg watermarks:
  ```sql
  SELECT view_name, _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark(h.id))
  FROM timescaledb_information.continuous_aggregates ca
  JOIN _timescaledb_catalog.hypertable h ON h.table_name = ca.materialization_hypertable_name;
  ```
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

- 27/27 tests pass: cagg == raw (including late data and real-time visibility), every estimator against
  hand-computed values, the SQL anomaly detector, the verifier, and the fallback agents.
- Backfill: 20M rows in 47s (424k rows/s), 3.5 GB → 327 MB.
- Anomaly detection runs in the DB (`detect_anomalies` job, every 5s). The demo key
  `support-triage-agent` is caught in about 5s wall clock (4.1s from spike to case).
  `scan_anomalies` takes about 165 ms.
- Close flow via the API, through approvals: 12 cases, $384,662.17 accrued. Owner reply → `bug_fixed`
  stops the runaway; orphan key reply → owner assigned.

## Remaining (backend), in order

1. **Verify the fast-forward fix** in `backend/src/tokentrueup/sim/world.py`. It's written but has
   never run: the gap clamp in `LiveGenerator._run`, plus `refresh_ahead()` and 5-minute density in
   `fast_forward`. The bug: after a fast-forward the generator tried to back-fill the whole gap, and the
   fast-forwarded data sat above the cagg watermark, so every estimate re-aggregated weeks of raw rows.
2. **Reset vs watermark.** After a fast-forward the watermarks are in the future. Check whether
   `reset_world` leaves them there. If so, make reset do a full reseed + backfill (about 2 min).
3. **Full flow incl. reconciliation** (script: `/api/sim/reset` → `/api/sim/play` → scenarios
   `stealth_price` and `duplicate_invoice` → `/api/close/run` → `/api/scenario/runaway` → reply →
   `/api/sim-fast-forward {"target":"month_end"}` → close → approve all →
   `/api/sim-fast-forward {"target":"invoices"}` → `/api/recon/run` → `/api/recon`).
   `orchestrator/recon.py` has **never run end to end**. Expected diagnoses: rate change (nimbus-pro
   output, unannounced), duplicate stratus invoice, ownerless quill key (resolved by reply this month,
   but present in history), Helio about 2.5% late metering, Cortexa 50% cached discount. Rule replay
   should show the error dropping across Aug, Sep and Oct.
4. `backend/src/tokentrueup/bench/run_benchmarks.py` → `BENCHMARKS.md`, using `bench/metrics.py`
   (stats, `race()`, `freshness_probe()`).
5. Makefile for 2-command setup (`make up`, `make demo`), then commit.

## Then

- Next.js + Tailwind + Recharts frontend, 7 pages. Use the `node_modules.nosync` + symlink trick only
  if the repo ever goes back under iCloud.
- README: problem, Mermaid diagram with Tiger Data at the centre, why each Tiger feature, 2-command
  setup, Assumptions, "How we used Tiger Data" with benchmark numbers, 3-minute demo script.
- Tiger Cloud cutover: the user runs `tiger auth login`, then `tiger service create`, migrate, backfill,
  and point `DATABASE_URL` in `.env` at it.
- Optional: live LLM mode test once `ANTHROPIC_API_KEY` is in `.env` (default model
  `claude-opus-5-5`; `agents/runner.py` uses `messages.parse`).

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
