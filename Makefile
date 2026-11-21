# TokenTrueUp: two-command setup.
#   make up    start TimescaleDB, build the venv, migrate, seed, backfill ROWS events (~2 min first time)
#   make demo  run the API with the in-process live event generator on :8000
#   make web   run the frontend on :3000 (second terminal)
# Others: make flow (scripted end-to-end demo against a running API), bench, test, lint, reset, psql, down.
#
# The venv lives outside the repo (~/.cache/tokentrueup/venv; backend/.venv is a symlink) and we never
# use `uv run`: on macOS it rebuilds the editable install and the new .pth file gets the hidden flag,
# which Python 3.12 then skips.

ROWS  ?= 20000000
VENV  := $(HOME)/.cache/tokentrueup/venv
PY    := cd backend && PYTHONPATH=src .venv/bin
DBSQL := docker compose exec -T tsdb psql -U postgres -d tokentrueup -v ON_ERROR_STOP=1 -Atc
API   ?= http://localhost:8000

.PHONY: web up demo flow bench test lint reset psql down down-volumes venv db compress

up: venv db
	$(PY)/db-migrate
	@if [ "$$($(DBSQL) 'SELECT count(*) FROM api_keys')" = "0" ]; then \
	  echo "seeding + backfilling $(ROWS) events"; \
	  $(PY)/ttu-seed && $(PY)/ttu-backfill --rows $(ROWS) && $(MAKE) compress; \
	else echo "database already seeded; skipping seed + backfill (make down-volumes to start over)"; fi
	@echo "ready: make demo"

# run every columnstore policy now (they're scheduled every 12 h; fresh cagg ranges otherwise wait)
compress:
	$(DBSQL) "DO \$$\$$ DECLARE j int; BEGIN FOR j IN SELECT job_id FROM timescaledb_information.jobs \
	  WHERE proc_name = 'policy_compression' ORDER BY job_id LOOP CALL run_job(j); END LOOP; END \$$\$$"

demo:
	$(PY)/uvicorn tokentrueup.api.main:app --port 8000

web:
	cd frontend && ([ -d node_modules ] || npm install --no-audit --no-fund) && npx next dev -p 3000

flow:
	$(PY)/python scripts/demo_flow.py --base $(API)

bench:
	$(PY)/python -m tokentrueup.bench.run_benchmarks --live-api $(API)

test:
	cd backend && PYTHONPATH=src:. .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check src scripts tests

reset:
	curl -s -X POST $(API)/api/sim/reset > /dev/null && echo "sim reset (paused at real time)"

psql:
	docker compose exec tsdb psql -U postgres -d tokentrueup

down:
	docker compose down

down-volumes:
	docker compose down -v

venv:
	@if [ ! -x $(VENV)/bin/python ]; then \
	  cd backend && UV_PROJECT_ENVIRONMENT=$(VENV) uv sync && chflags -R nohidden $(VENV) 2>/dev/null || true; fi
	@[ -e backend/.venv ] || ln -s $(VENV) backend/.venv

db:
	docker compose up -d
	@until docker compose exec -T tsdb pg_isready -U postgres -q; do sleep 1; done
	@until $(DBSQL) 'SELECT 1' > /dev/null 2>&1; do sleep 1; done
