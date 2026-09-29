"""Build the 6-panel Day 13 dashboard from data/logs.jsonl as one self-contained HTML page.

Panel ids, units and thresholds come from config/dashboard.yaml so the page can
never drift from the grading contract.

    python scripts/build_dashboard.py            # write data/dashboard.html once
    python scripts/build_dashboard.py --watch    # rebuild every refresh_seconds
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

DEFAULT_LOGS = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_CONFIG = REPO_ROOT / "config" / "dashboard.yaml"
DEFAULT_OUT = REPO_ROOT / "data" / "dashboard.html"


# --------------------------------------------------------------------------- data


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            rec["_ts"] = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        records.append(rec)
    return records


def compute(records: list[dict[str, Any]], end: datetime, minutes: int) -> dict[str, Any]:
    """Aggregate log records into per-minute buckets for the last `minutes` minutes."""
    last_bucket = end.replace(second=0, microsecond=0)
    start = last_bucket - timedelta(minutes=minutes - 1)
    buckets = [start + timedelta(minutes=i) for i in range(minutes)]

    def new_bucket() -> dict[str, list]:
        return {k: [] for k in ("latency", "ttft", "cost", "tokens_in", "tokens_out", "quality")}

    per_min = [new_bucket() for _ in buckets]
    received = [0] * minutes
    failed = [0] * minutes
    errors: Counter[str] = Counter()
    tool_results: list[bool] = []

    for rec in records:
        idx = int((rec["_ts"] - start).total_seconds() // 60)
        if not 0 <= idx < minutes:
            continue
        event = rec.get("event")
        if event == "request_received":
            received[idx] += 1
        elif event == "request_failed":
            failed[idx] += 1
            errors[rec.get("error_type") or "unknown"] += 1
        elif event == "response_sent":
            b = per_min[idx]
            b["latency"].append(rec.get("latency_ms", 0))
            b["ttft"].append(rec.get("ttft_ms", 0))
            b["cost"].append(rec.get("cost_usd", 0.0))
            b["tokens_in"].append(rec.get("tokens_in", 0))
            b["tokens_out"].append(rec.get("tokens_out", 0))
            b["quality"].append(rec.get("quality_score", 0.0))
        if event in ("response_sent", "request_failed") and rec.get("tool_success") is not None:
            tool_results.append(bool(rec["tool_success"]))

    def flat(key: str) -> list:
        return [v for b in per_min for v in b[key]]

    def per_bucket(key: str, fn) -> list[float | None]:
        return [fn(b[key]) if b[key] else None for b in per_min]

    total_received = sum(received)
    latency, ttft = flat("latency"), flat("ttft")
    return {
        "buckets": buckets,
        "start": start,
        "end": last_bucket + timedelta(minutes=1),
        "latency": {
            "p50": per_bucket("latency", lambda v: percentile(v, 50)),
            "p95": per_bucket("latency", lambda v: percentile(v, 95)),
            "p99": per_bucket("latency", lambda v: percentile(v, 99)),
            "ttft_p95": per_bucket("ttft", lambda v: percentile(v, 95)),
            "overall": {
                "p50": percentile(latency, 50),
                "p95": percentile(latency, 95),
                "p99": percentile(latency, 99),
                "ttft_p95": percentile(ttft, 95),
            },
        },
        "traffic": {
            "per_min": received,
            "count": total_received,
            "rate_per_minute": total_received / minutes,
            "peak": max(received) if received else 0,
        },
        "errors": {
            "rate_per_min": [
                (f / r * 100) if r else None for f, r in zip(failed, received)
            ],
            "error_rate_pct": (sum(failed) / total_received * 100) if total_received else 0.0,
            "failed": sum(failed),
            "breakdown": dict(errors.most_common()),
            "tool_success_rate_pct": (
                sum(tool_results) / len(tool_results) * 100 if tool_results else None
            ),
            "tool_calls": len(tool_results),
        },
        "cost": {
            "per_min": per_bucket("cost", sum),
            "total": sum(flat("cost")),
        },
        "tokens": {
            "in_per_min": per_bucket("tokens_in", sum),
            "out_per_min": per_bucket("tokens_out", sum),
            "in_total": sum(flat("tokens_in")),
            "out_total": sum(flat("tokens_out")),
        },
        "quality": {
            "per_min": per_bucket("quality", mean),
            "mean": mean(flat("quality")) if flat("quality") else None,
        },
    }


def passes(value: float | None, threshold: dict[str, Any]) -> bool | None:
    if value is None:
        return None
    if threshold["operator"] == "lte":
        return value <= threshold["value"]
    return value >= threshold["value"]


# --------------------------------------------------------------------------- svg

W, H = 620, 210
PAD_L, PAD_R, PAD_T, PAD_B = 52, 16, 14, 28
PLOT_W, PLOT_H = W - PAD_L - PAD_R, H - PAD_T - PAD_B


def nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        if step * 10**exp >= value:
            return step * 10**exp
    return 10 ** (exp + 1)


def fmt_num(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    if abs(value) >= 1:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value:.4f}".rstrip("0").rstrip(".")


def local_hm(dt: datetime) -> str:
    return dt.astimezone().strftime("%H:%M")


def svg_chart(
    buckets: list[datetime],
    series: list[tuple[str, str, list[float | None]]],
    *,
    unit: str,
    kind: str = "line",
    threshold: dict[str, Any] | None = None,
    threshold_label: str = "",
) -> str:
    n = len(buckets)
    values = [v for _, _, vals in series for v in vals if v is not None]
    top = max(values + [0.0])
    if threshold is not None:
        top = max(top, threshold["value"])
    top = nice_ceiling(top * 1.1)

    def x(i: float) -> float:
        return PAD_L + (i + 0.5) * PLOT_W / n

    def y(v: float) -> float:
        return PAD_T + PLOT_H - (v / top) * PLOT_H

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']
    for frac in (0, 0.5, 1):
        gy = y(top * frac)
        cls = "axis" if frac == 0 else "grid"
        parts.append(f'<line class="{cls}" x1="{PAD_L}" x2="{W - PAD_R}" y1="{gy:.1f}" y2="{gy:.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 6}" y="{gy + 4:.1f}" text-anchor="end">{fmt_num(top * frac)}</text>')
    for i in range(0, n, 10):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{local_hm(buckets[i])}</text>')
    parts.append(f'<text class="tick" x="{x(n - 1):.1f}" y="{H - 8}" text-anchor="end">{local_hm(buckets[-1])}</text>')

    if kind == "bar":
        name, color, vals = series[0]
        bar_w = max(2.0, PLOT_W / n - 2)
        for i, v in enumerate(vals):
            if not v:
                continue
            top_y = y(v)
            parts.append(
                f'<rect class="mark" x="{x(i) - bar_w / 2:.1f}" y="{top_y:.1f}" width="{bar_w:.1f}" '
                f'height="{PAD_T + PLOT_H - top_y:.1f}" rx="2" fill="var({color})">'
                f'<title>{local_hm(buckets[i])} · {html.escape(name)}: {fmt_num(v)} {unit}</title></rect>'
            )
    else:
        for name, color, vals in series:
            segment: list[str] = []
            for i, v in enumerate(vals + [None]):
                if v is None:
                    if len(segment) > 1:
                        parts.append(f'<polyline class="line" stroke="var({color})" points="{" ".join(segment)}"/>')
                    segment = []
                    continue
                segment.append(f"{x(i):.1f},{y(v):.1f}")
            for i, v in enumerate(vals):
                if v is None:
                    continue
                parts.append(
                    f'<circle class="mark" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" fill="var({color})">'
                    f'<title>{local_hm(buckets[i])} · {html.escape(name)}: {fmt_num(v)} {unit}</title></circle>'
                )

    if threshold is not None:
        ty = y(threshold["value"])
        # Draw after the marks so the SLO line and its (haloed) label stay on top.
        parts.append(f'<line class="threshold" x1="{PAD_L}" x2="{W - PAD_R}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        parts.append(
            f'<text class="threshold-label" x="{PAD_L + 6}" y="{ty - 5:.1f}">'
            f"{html.escape(threshold_label)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------- html

OPS = {"lte": "≤", "gte": "≥"}


def badge(ok: bool | None) -> str:
    if ok is None:
        return '<span class="badge none">– No data</span>'
    if ok:
        return '<span class="badge ok">✓ Within threshold</span>'
    return '<span class="badge bad">✗ Threshold breached</span>'


def tile(label: str, value: str, note: str = "") -> str:
    note_html = f'<div class="tile-note">{note}</div>' if note else ""
    return f'<div class="tile"><div class="tile-label">{label}</div><div class="tile-value">{value}</div>{note_html}</div>'


def legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:var({c})"></i>{html.escape(n)}</span>' for n, c in items
    ) + "</div>"


def meter(label: str, value: float, limit: float, unit_fmt) -> str:
    pct = min(100.0, value / limit * 100) if limit else 0
    return (
        f'<div class="meter"><div class="meter-head"><span>{label}</span>'
        f"<span>{unit_fmt(value)} / {unit_fmt(limit)} ({value / limit * 100:.2f}%)</span></div>"
        f'<div class="meter-track"><div class="meter-fill" style="width:{pct:.2f}%"></div>'
        f'<div class="meter-limit"></div></div></div>'
    )


def panel(p: dict[str, Any], ok: bool | None, body: str) -> str:
    th = p["threshold"]
    return (
        f'<section class="panel" id="{p["id"]}"><header><div>'
        f'<h2>{html.escape(p["title"])}</h2>'
        f'<div class="meta">Unit: {html.escape(p["unit"])} · Threshold: {th["aggregation"]} '
        f'{OPS[th["operator"]]} {fmt_num(th["value"])}</div></div>{badge(ok)}</header>{body}</section>'
    )


def render(cfg: dict[str, Any], data: dict[str, Any], generated_at: datetime) -> str:
    dash = cfg["dashboard"]
    panels = {p["id"]: p for p in dash["panels"]}
    b = data["buckets"]
    out: list[str] = []

    # 1. Latency
    p = panels["latency"]
    lat = data["latency"]
    ov = lat["overall"]
    has_lat = any(v is not None for v in lat["p95"])
    body = '<div class="tiles">' + "".join([
        tile("P50", f"{fmt_num(ov['p50'])} ms"),
        tile("P95", f"{fmt_num(ov['p95'])} ms"),
        tile("P99", f"{fmt_num(ov['p99'])} ms"),
        tile("TTFT P95", f"{fmt_num(ov['ttft_p95'])} ms"),
    ]) + "</div>"
    series = [
        ("Latency P50", "--series-1", lat["p50"]),
        ("Latency P95", "--series-2", lat["p95"]),
        ("Latency P99", "--series-3", lat["p99"]),
        ("TTFT P95", "--series-4", lat["ttft_p95"]),
    ]
    body += svg_chart(b, series, unit="ms", threshold=p["threshold"],
                      threshold_label=f"SLO: P95 ≤ {fmt_num(p['threshold']['value'])} ms")
    body += legend([(n, c) for n, c, _ in series])
    out.append(panel(p, passes(ov["p95"], p["threshold"]) if has_lat else None, body))

    # 2. Traffic
    p = panels["traffic"]
    tr = data["traffic"]
    body = '<div class="tiles">' + "".join([
        tile("Requests (60 min)", fmt_num(tr["count"])),
        tile("Avg rate", f"{tr['rate_per_minute']:.2f} req/min"),
        tile("Peak minute", f"{tr['peak']} req/min"),
    ]) + "</div>"
    body += svg_chart(b, [("Requests", "--series-1", tr["per_min"])], unit="req/min", kind="bar",
                      threshold=p["threshold"],
                      threshold_label=f"Min healthy rate ≥ {fmt_num(p['threshold']['value'])} req/min")
    out.append(panel(p, passes(tr["rate_per_minute"], p["threshold"]), body))

    # 3. Errors + retrieval success
    p = panels["errors"]
    er = data["errors"]
    tsr = er["tool_success_rate_pct"]
    body = '<div class="tiles">' + "".join([
        tile("Error rate", f"{er['error_rate_pct']:.2f} %", f"{er['failed']} failed / {tr['count']} requests"),
        tile("Retrieval success", f"{tsr:.1f} %" if tsr is not None else "–", f"{er['tool_calls']} retrieval calls"),
    ]) + "</div>"
    body += svg_chart(b, [("Error rate", "--series-2", er["rate_per_min"])], unit="%",
                      threshold=p["threshold"],
                      threshold_label=f"SLO: error rate ≤ {fmt_num(p['threshold']['value'])} %")
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>" for k, v in er["breakdown"].items()
    ) or '<tr><td colspan="2" class="muted">No errors in window</td></tr>'
    body += f'<table class="breakdown"><thead><tr><th>error_type</th><th>count</th></tr></thead><tbody>{rows}</tbody></table>'
    out.append(panel(p, passes(er["error_rate_pct"], p["threshold"]) if tr["count"] else None, body))

    # 4. Cost
    p = panels["cost"]
    co = data["cost"]
    body = '<div class="tiles">' + tile("Total cost (60 min)", f"${co['total']:.4f}") + "</div>"
    body += meter("Cost vs budget", co["total"], p["threshold"]["value"], lambda v: f"${v:.4f}" if v < 1 else f"${v:.2f}")
    body += svg_chart(b, [("Cost", "--series-1", co["per_min"])], unit="USD/min", kind="bar")
    out.append(panel(p, passes(co["total"], p["threshold"]), body))

    # 5. Tokens
    p = panels["tokens"]
    tk = data["tokens"]
    limit = p["threshold"]["value"]
    body = '<div class="tiles">' + "".join([
        tile("Input tokens", fmt_num(tk["in_total"])),
        tile("Output tokens", fmt_num(tk["out_total"])),
    ]) + "</div>"
    body += meter("Input vs limit", tk["in_total"], limit, fmt_num)
    body += meter("Output vs limit", tk["out_total"], limit, fmt_num)
    series = [("Input tokens", "--series-1", tk["in_per_min"]), ("Output tokens", "--series-2", tk["out_per_min"])]
    body += svg_chart(b, series, unit="tokens/min")
    body += legend([(n, c) for n, c, _ in series])
    out.append(panel(p, passes(max(tk["in_total"], tk["out_total"]), p["threshold"]), body))

    # 6. Quality
    p = panels["quality"]
    q = data["quality"]
    body = '<div class="tiles">' + tile("Mean quality", f"{q['mean']:.3f}" if q["mean"] is not None else "–") + "</div>"
    body += svg_chart(b, [("Quality", "--series-3", q["per_min"])], unit="score",
                      threshold=p["threshold"],
                      threshold_label=f"Min quality ≥ {fmt_num(p['threshold']['value'])}")
    out.append(panel(p, passes(q["mean"], p["threshold"]), body))

    window = f"{local_hm(data['start'])} – {local_hm(data['end'])}"
    return PAGE.format(
        title=html.escape(dash["title"]),
        refresh=dash["refresh_seconds"],
        minutes=dash["time_range_minutes"],
        window=window,
        generated=generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        panels="".join(out),
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>Day 13 Dashboard</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
  --good: #0ca30c; --good-text: #006300; --critical: #d03b3b;
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #ffffff; --text-secondary: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
    --good-text: #0ca30c;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface-1: #1a1a19; --text-primary: #ffffff; --text-secondary: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
  --good-text: #0ca30c;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--text-primary);
  font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }}
.top {{ padding: 16px 20px 8px; display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: baseline; }}
.top h1 {{ font-size: 20px; margin: 0; }}
.top .meta {{ color: var(--text-secondary); }}
.grid-panels {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(560px, 1fr)); gap: 16px; padding: 8px 20px 24px; }}
.panel {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }}
.panel header {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
.panel h2 {{ font-size: 15px; margin: 0; }}
.meta {{ color: var(--text-secondary); font-size: 12px; margin-top: 2px; }}
.badge {{ font-size: 12px; font-weight: 600; white-space: nowrap; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; }}
.badge.ok {{ color: var(--good-text); }} .badge.bad {{ color: var(--critical); }} .badge.none {{ color: var(--muted); }}
.tiles {{ display: flex; flex-wrap: wrap; gap: 8px 28px; margin: 10px 0 6px; }}
.tile-label {{ color: var(--text-secondary); font-size: 12px; }}
.tile-value {{ font-size: 20px; font-weight: 600; }}
.tile-note {{ color: var(--muted); font-size: 12px; }}
.chart {{ width: 100%; height: auto; display: block; }}
.chart .grid {{ stroke: var(--grid); stroke-width: 1; }}
.chart .axis {{ stroke: var(--axis); stroke-width: 1; }}
.chart .tick {{ fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }}
.chart .line {{ fill: none; stroke-width: 2; stroke-linejoin: round; }}
.chart .mark {{ stroke: var(--surface-1); stroke-width: 2; }}
.chart .threshold {{ stroke: var(--critical); stroke-width: 1.5; stroke-dasharray: 6 4; }}
.chart .threshold-label {{ fill: var(--text-secondary); font-size: 11px;
  paint-order: stroke; stroke: var(--surface-1); stroke-width: 4px; stroke-linejoin: round; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 4px 16px; color: var(--text-secondary); font-size: 12px; margin-top: 4px; }}
.legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }}
.meter {{ margin: 6px 0 8px; font-size: 12px; color: var(--text-secondary); }}
.meter-head {{ display: flex; justify-content: space-between; margin-bottom: 4px; }}
.meter-track {{ position: relative; height: 8px; background: var(--grid); border-radius: 4px; }}
.meter-fill {{ height: 100%; background: var(--series-1); border-radius: 4px; min-width: 2px; }}
.meter-limit {{ position: absolute; right: 0; top: -3px; bottom: -3px; border-right: 2px dashed var(--critical); }}
.breakdown {{ border-collapse: collapse; font-size: 12px; margin-top: 8px; }}
.breakdown th, .breakdown td {{ text-align: left; padding: 3px 16px 3px 0; border-bottom: 1px solid var(--grid); }}
.breakdown th {{ color: var(--text-secondary); font-weight: 600; }}
.muted {{ color: var(--muted); }}
@media (max-width: 640px) {{ .grid-panels {{ grid-template-columns: 1fr; padding: 8px 16px 24px; }} }}
</style></head>
<body>
<div class="top"><h1>{title}</h1>
<span class="meta">Time range: last {minutes} min ({window}) · Auto-refresh: {refresh}s · Source: data/logs.jsonl · Built {generated}</span></div>
<main class="grid-panels">{panels}</main>
</body></html>
"""


# --------------------------------------------------------------------------- main


def build(logs: Path, config: Path, out: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    data = compute(load_records(logs), now, cfg["dashboard"]["time_range_minutes"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(cfg, data, now), encoding="utf-8")
    return data


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Build the Day 13 six-panel dashboard")
    parser.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--watch", action="store_true", help="Rebuild every refresh_seconds")
    args = parser.parse_args()

    refresh = yaml.safe_load(args.config.read_text(encoding="utf-8"))["dashboard"]["refresh_seconds"]
    while True:
        data = build(args.logs, args.config, args.out)
        print(
            f"Dashboard written: {args.out} | requests={data['traffic']['count']} "
            f"p95={data['latency']['overall']['p95']:.0f}ms "
            f"error_rate={data['errors']['error_rate_pct']:.2f}%"
        )
        if not args.watch:
            return 0
        time.sleep(refresh)


if __name__ == "__main__":
    raise SystemExit(main())
