"""Deterministic usage profiles shared by backfill, live generator and fast-forward.

Spend per hour depends only on (key, time) — never on how many events carry it — so a
live stream at 5k events/s has the same $/hour as the 2 events/s historical backfill,
and the anomaly baseline stays meaningful.
"""

from __future__ import annotations

import zlib
from datetime import UTC, date, datetime, timedelta

import numpy as np

from .catalog import HISTORICAL_PRICE_CHANGES, KEYS, MODELS, KeySpec

_HOURS = np.arange(24)
# Business-hours bump centred on 18:00 UTC (~1pm US Eastern).
_BUMP = np.exp(-(((_HOURS - 18 + 12) % 24 - 12) / 4.5) ** 2)
_BUMP = _BUMP / _BUMP.mean()


def month_start(d: datetime | date, offset: int = 0) -> datetime:
    y, m = d.year, d.month + offset
    while m <= 0:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return datetime(y, m, 1, tzinfo=UTC)


def backfill_start(now: datetime) -> datetime:
    """History starts on the 1st of the month three months before the current one."""
    return month_start(now, -3)


def units_per_hour(spec: KeySpec, epoch_s: np.ndarray, origin_epoch: float) -> np.ndarray:
    """Expected units (tokens / requests / GPU-hours) per hour at each timestamp."""
    hours = ((epoch_s // 3600) % 24).astype(int)
    diurnal = 1 - spec.diurnal + spec.diurnal * _BUMP[hours]
    dow = ((epoch_s // 86400 + 3) % 7).astype(int)  # 0 = Monday (epoch day 0 was a Thursday)
    week = np.where(dow >= 5, spec.weekend, 1.0)
    week = week / ((5 + 2 * spec.weekend) / 7)  # normalise so the weekly mean is 1
    months = (epoch_s - origin_epoch) / (30.4 * 86400)
    growth = (1 + spec.growth_per_month) ** months
    # Day-level wobble, deterministic per (key, day).
    day_idx = (epoch_s // 86400).astype(np.int64)
    seed = zlib.crc32(spec.label.encode()) % 10_000
    wobble = 1 + 0.08 * np.sin(day_idx * 1.7 + seed) + 0.05 * np.sin(day_idx * 0.37 + seed * 3)
    return spec.daily_units / 24 * diurnal * week * growth * wobble


def rate_tables(start: datetime) -> dict[tuple[str, str], list[tuple[float, tuple]]]:
    """Price history known at seed time: list of (effective_epoch, rates) per model."""
    tables: dict[tuple[str, str], list[tuple[float, tuple]]] = {}
    t0 = (start - timedelta(days=1)).timestamp()
    for key, (_, rates) in MODELS.items():
        tables[key] = [(t0, rates)]
    for provider, model, m_off, day, old in HISTORICAL_PRICE_CHANGES:
        change = month_start(start, m_off).replace(day=day).timestamp()
        new = tables[(provider, model)][0][1]
        tables[(provider, model)] = [(t0, old), (change, new)]
    return tables


def list_cost_cents(rates: tuple, inp, out, cached, requests, gpu_s):
    ri, ro, rc, rr, rg = rates
    return inp * ri / 1e6 + out * ro / 1e6 + cached * rc / 1e6 + requests * rr / 1e3 + gpu_s * rg / 3600


def rates_at(table: list[tuple[float, tuple]], epoch_s: np.ndarray) -> np.ndarray:
    """Vectorised as-of lookup -> (n, 5) array of rates."""
    eff = np.array([t for t, _ in table])
    vals = np.array([r for _, r in table], dtype=float)
    idx = np.clip(np.searchsorted(eff, epoch_s, side="right") - 1, 0, len(table) - 1)
    return vals[idx]


def _sround(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    fl = np.floor(x)
    return fl + (rng.random(x.shape) < (x - fl))


def build_events(
    key_idx: int,
    key_id: int,
    epoch_s: np.ndarray,
    units: np.ndarray,
    tables: dict,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Turn per-event unit amounts into usage_events columns (vectorised)."""
    spec = KEYS[key_idx]
    n = len(epoch_s)
    models = [m for m, _ in spec.models]
    shares = np.array([s for _, s in spec.models])
    model_idx = rng.choice(len(models), size=n, p=shares / shares.sum()) if len(models) > 1 else np.zeros(n, int)
    kind = MODELS[(spec.provider, models[0])][0]
    zeros = np.zeros(n)
    if kind == "tokens":
        mi, mo, mc = spec.mix
        jitter = rng.uniform(0.85, 1.15, size=(3, n))
        # Stochastic rounding: at 5k+ events/s an event is a metering record carrying a
        # fraction of a request's tokens; rint() would zero them and lose spend.
        inp = _sround(units * mi * jitter[0], rng)
        out = _sround(units * mo * jitter[1], rng)
        cached = _sround(units * mc * jitter[2], rng)
        reqs = np.ones(n)
        gpu = zeros
    elif kind == "gpu":
        inp = out = cached = zeros
        reqs = np.ones(n)
        gpu = units * 3600.0
    else:
        inp = out = cached = zeros
        # stochastic rounding keeps expected requests == units even when units/event < 1
        reqs = _sround(units, rng)
        gpu = zeros
    cost = np.zeros(n)
    for j, m in enumerate(models):
        mask = model_idx == j
        if mask.any():
            r = rates_at(tables[(spec.provider, m)], epoch_s[mask])
            cost[mask] = list_cost_cents(r.T, inp[mask], out[mask], cached[mask], reqs[mask], gpu[mask])
    return {
        "epoch": epoch_s,
        "api_key_id": np.full(n, key_id),
        "provider": spec.provider,
        "model_idx": model_idx,
        "models": models,
        "input_tokens": inp.astype(np.int64),
        "output_tokens": out.astype(np.int64),
        "cached_tokens": cached.astype(np.int64),
        "requests": reqs.astype(np.int64),
        "gpu_seconds": gpu,
        "cost": cost,
    }


def lognormal_split(total: np.ndarray, rng: np.random.Generator, sigma: float = 0.35) -> np.ndarray:
    """Multiplicative noise with mean 1 so totals are preserved in expectation."""
    noise = rng.lognormal(-sigma**2 / 2, sigma, size=total.shape)
    return total * noise
