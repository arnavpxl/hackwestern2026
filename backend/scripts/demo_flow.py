"""End-to-end demo flow against a running API: live month → close → runaway → month end →
approvals → invoices → reconciliation → rule replay. Prints a compact log of each step.

    PYTHONPATH=src .venv/bin/python scripts/demo_flow.py [--base http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

BASE = "http://localhost:8000"


def call(method: str, path: str, body: dict | None = None, timeout: float = 600) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"!! {method} {path} -> {e.code}: {e.read().decode()[:2000]}")
        sys.exit(1)
    print(f"-- {method} {path}  ({time.perf_counter() - t:.2f}s)")
    return out.get("data", out)


def money(c) -> str:
    return f"${(c or 0) / 100:,.2f}"


def summary(tag: str) -> dict:
    s = call("GET", "/api/close/summary")
    print(f"   [{tag}] accrued {money(s['accrued_cents'])}, approved {money(s['approved_cents'])}, "
          f"status {s['by_status']}")
    return s


def wait_for_case(case_type: str, key: str, timeout: float = 30) -> dict | None:
    t = time.time()
    while time.time() - t < timeout:
        for c in call("GET", "/api/close/summary")["cases"]:
            if c["type"] == case_type and c["key_label"] == key:
                return c
        time.sleep(1)
    return None


def main() -> None:
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    BASE = ap.parse_args().base

    st = call("POST", "/api/sim/reset")
    print("   sim_now", st["sim_now"])
    call("POST", "/api/sim/play")
    print("   stealth", call("POST", "/api/scenario/stealth_price"))
    print("   dup", call("POST", "/api/scenario/duplicate_invoice"))
    time.sleep(3)

    r = call("POST", "/api/close/run")
    print("   close:", {k: v for k, v in r.items() if not isinstance(v, list | dict)})
    summary("close #1")

    t0 = time.time()
    call("POST", "/api/scenario/runaway")
    case = wait_for_case("anomaly", "support-triage-agent")
    if not case:
        print("!! runaway not detected within 30s")
        sys.exit(1)
    print(f"   anomaly case {case['id']} after {time.time() - t0:.1f}s wall, "
          f"detection_latency_ms={case['detection_latency_ms']}, est {money(case['estimate_cents'])}")
    detail = call("GET", f"/api/cases/{case['id']}")
    for m in detail["outreach"]:
        print(f"   outreach -> {m.get('owner_name')}: {str(m.get('body'))[:120]!r}")
    rep = call("POST", f"/api/cases/{case['id']}/reply",
               {"body": "Yikes - that was a retry loop bug in the triage agent. Fixed and deployed just now."})
    print("   reply ->", json.dumps(rep, default=str)[:300])

    # ownerless key: its usage case asks who owns growth-scraper-legacy; answer so it gets an owner
    for c in call("GET", "/api/close/summary")["cases"]:
        if c["status"] != "needs_info" or c["type"] == "anomaly":
            continue
        d = call("GET", f"/api/cases/{c['id']}")
        if any("growth-scraper-legacy" in str(m.get("body")) for m in d["outreach"]):
            rep = call("POST", f"/api/cases/{c['id']}/reply",
                       {"body": "That key is ours - Growth team. Owner is tomas.i@example.test, keep it accrued."})
            print("   orphan reply ->", json.dumps(rep, default=str)[:300])

    ff = call("POST", "/api/sim-fast-forward", {"target": "month_end"})
    print("   ff month_end:", ff)
    call("POST", "/api/close/run")
    s = summary("close #2")
    for c in call("GET", "/api/approvals"):
        call("POST", f"/api/cases/{c['id']}/approve")
    s = summary("approved")

    ff = call("POST", "/api/sim-fast-forward", {"target": "invoices"})
    print("   ff invoices:", ff)
    rr = call("POST", "/api/recon/run")
    print("   recon run:", json.dumps(rr, default=str)[:3000])
    rv = call("GET", "/api/recon")
    for inv in rv["invoices"]:
        if str(inv["period_start"]) >= str(s["period"]):
            recon = inv.get("recon") or {}
            print(f"   invoice {inv['invoice_no']:<28} {inv['provider_id']:<14} {money(inv['amount_cents']):>14} "
                  f"{inv['status']:<12} dup_of={inv['is_duplicate_of']} "
                  f"variance={money(recon.get('variance_cents'))} diag={[d.get("cause") for d in recon.get("causes", [])]}")
    for rule in rv["rules"]:
        print(f"   rule {rule['id']} [{rule['status']}] {rule["kind"]} {rule["provider_id"]} {rule["params"]}: {str(rule.get("rationale"))[:160]}")
        rep = call("POST", f"/api/rules/{rule['id']}/replay")
        print("      replay:", json.dumps(rep, default=str)[:800])


if __name__ == "__main__":
    main()
