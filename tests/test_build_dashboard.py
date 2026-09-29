from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from scripts.build_dashboard import compute, passes, render

END = datetime(2026, 9, 29, 9, 0, 30, tzinfo=timezone.utc)


def _rec(event: str, minutes_ago: int, **fields) -> dict:
    return {"event": event, "_ts": END - timedelta(minutes=minutes_ago), **fields}


def _ok(minutes_ago: int, latency: int, cost: float = 0.002) -> list[dict]:
    return [
        _rec("request_received", minutes_ago),
        _rec(
            "response_sent", minutes_ago,
            latency_ms=latency, ttft_ms=50, cost_usd=cost, tokens_in=30, tokens_out=100,
            quality_score=0.9, tool_success=True,
        ),
    ]


def test_compute_aggregates_latency_errors_and_retrieval() -> None:
    records = _ok(1, 100) + _ok(1, 300) + _ok(2, 5000)
    records += [
        _rec("request_received", 2),
        _rec("request_failed", 2, error_type="RuntimeError", tool_success=False),
    ]

    data = compute(records, END, minutes=60)

    assert data["traffic"]["count"] == 4
    assert data["latency"]["overall"]["p50"] == 300
    assert data["latency"]["overall"]["p99"] == 5000
    assert data["errors"]["error_rate_pct"] == 25.0
    assert data["errors"]["breakdown"] == {"RuntimeError": 1}
    assert data["errors"]["tool_success_rate_pct"] == 75.0
    assert round(data["cost"]["total"], 6) == 0.006
    assert data["tokens"]["out_total"] == 300


def test_compute_ignores_records_outside_the_window() -> None:
    data = compute(_ok(1, 100) + _ok(61, 9999), END, minutes=60)

    assert data["traffic"]["count"] == 1
    assert data["latency"]["overall"]["p95"] == 100


def test_passes_respects_operator() -> None:
    assert passes(2500, {"operator": "lte", "value": 3000}) is True
    assert passes(3500, {"operator": "lte", "value": 3000}) is False
    assert passes(0.7, {"operator": "gte", "value": 0.75}) is False
    assert passes(None, {"operator": "gte", "value": 0.75}) is None


def test_render_contains_all_contract_panels_and_thresholds() -> None:
    cfg = yaml.safe_load(Path("config/dashboard.yaml").read_text(encoding="utf-8"))
    page = render(cfg, compute(_ok(1, 100), END, minutes=60), END)

    for panel in cfg["dashboard"]["panels"]:
        assert f'id="{panel["id"]}"' in page
        assert panel["title"] in page
    assert "Time range: last 60 min" in page
    assert page.count('class="threshold"') == 4  # latency, traffic, errors, quality
    assert page.count('class="meter-limit"') == 3  # cost total + input/output token limits
