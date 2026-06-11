#!/usr/bin/env python3
"""Review LIGHTOARTS OKX strategy research results with robustness gates.

This is a lightweight companion to scan/backtest scripts. It reads an existing
strategy scan JSON (default: data/top10_training_strategy_scan_latest.json),
classifies candidates with anti-overfitting checks, and writes a concise
Traditional-Chinese report for deciding whether a strategy is research-only,
Render shadow, or tiny OKX-pilot candidate.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_INPUT = Path("data/top10_training_strategy_scan_latest.json")
DEFAULT_OUT_MD = Path("data/okx_strategy_research_review_latest.md")
DEFAULT_OUT_JSON = Path("data/okx_strategy_research_review_latest.json")


@dataclass(frozen=True)
class GateResult:
    label: str
    reasons: list[str]
    warnings: list[str]
    one_day_dependency: float | None
    net_without_best_day: float | None


def pct(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def num(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def calc_one_day_dependency(row: dict[str, Any]) -> tuple[float | None, float | None]:
    net_sum = float(row.get("net_sum_pct") or 0.0)
    best_day = float(row.get("best_day_pct") or 0.0)
    if net_sum <= 0:
        return None, None
    return best_day / net_sum, net_sum - best_day


def classify_candidate(row: dict[str, Any], min_trades: int = 80) -> GateResult:
    """Classify a scan row without pretending it is live-ready.

    Labels intentionally stop at tiny-pilot candidate. OKX live readiness still
    requires the separate native-hard-stop/live preflight workflow.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    trades = int(row.get("trades") or 0)
    pf = float(row.get("profit_factor") or 0.0)
    net_avg = float(row.get("net_avg_pct") or 0.0)
    net_sum = float(row.get("net_sum_pct") or 0.0)
    day_win_rate = float(row.get("day_win_rate") or 0.0)
    days = int(row.get("days") or 0)
    max_loss = float(row.get("max_loss_pct") or 0.0)
    one_day_dep, net_without_best = calc_one_day_dependency(row)

    if trades < min_trades:
        reasons.append(f"交易數不足：{trades} < {min_trades}")
    if days < 5:
        reasons.append(f"天數不足：{days} 天")
    if net_avg <= 0 or net_sum <= 0:
        reasons.append("淨期望值/累積淨利不為正")
    if pf < 1.05:
        reasons.append(f"PF 過低：{pf:.2f}")
    if max_loss < -2.0:
        reasons.append(f"單筆最大損失過大：{max_loss:.2f}%")
    if day_win_rate < 50:
        reasons.append(f"日勝率不足：{day_win_rate:.1f}%")

    if one_day_dep is not None:
        if one_day_dep >= 0.45:
            warnings.append(f"單日依賴偏高：最佳日佔總淨利 {one_day_dep * 100:.1f}%")
        if net_without_best is not None and net_without_best <= 0:
            reasons.append("扣除最佳日後累積淨利不為正")

    # Conservative tiering: research scan can only nominate a tiny pilot candidate,
    # never declare a strategy live-ready.
    if reasons:
        label = "research-only"
    elif trades >= max(min_trades, 100) and pf >= 1.5 and net_avg > 0.15 and day_win_rate >= 60 and max_loss >= -1.25 and not warnings:
        label = "tiny-pilot candidate"
    elif pf >= 1.15 and net_avg > 0.05 and day_win_rate >= 55 and max_loss >= -1.5:
        label = "Render shadow candidate"
    else:
        label = "research candidate"

    return GateResult(label, reasons, warnings, one_day_dep, net_without_best)


def sorted_candidates(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            float(r.get("net_avg_pct") or 0.0),
            float(r.get("profit_factor") or 0.0),
            int(r.get("trades") or 0),
            float(r.get("day_win_rate") or 0.0),
        ),
        reverse=True,
    )


def build_review(payload: dict[str, Any], top_n: int = 10, min_trades: int = 80) -> dict[str, Any]:
    top_rows = sorted_candidates(payload.get("top") or [])[:top_n]
    reviewed = []
    for row in top_rows:
        gate = classify_candidate(row, min_trades=min_trades)
        reviewed.append(
            {
                "name": row.get("name"),
                "label": gate.label,
                "reasons": gate.reasons,
                "warnings": gate.warnings,
                "one_day_dependency_pct": None if gate.one_day_dependency is None else gate.one_day_dependency * 100,
                "net_without_best_day_pct": gate.net_without_best_day,
                "metrics": {
                    "trades": row.get("trades"),
                    "days": row.get("days"),
                    "win_rate_pct": row.get("win_rate"),
                    "day_win_rate_pct": row.get("day_win_rate"),
                    "net_avg_pct": row.get("net_avg_pct"),
                    "net_sum_pct": row.get("net_sum_pct"),
                    "profit_factor": row.get("profit_factor"),
                    "max_loss_pct": row.get("max_loss_pct"),
                    "best_day_pct": row.get("best_day_pct"),
                    "worst_day_pct": row.get("worst_day_pct"),
                    "exit_reasons": row.get("exit_reasons"),
                    "params": {
                        k: row.get(k)
                        for k in [
                            "delay_bars",
                            "max_entry_rank",
                            "min_entry_change",
                            "max_entry_change",
                            "min_current_change",
                            "min_vol_ratio",
                            "stop_pct",
                            "trail_start_pct",
                            "trail_giveback",
                            "time_stop_bars",
                            "exit_on_leave_top10",
                        ]
                    },
                },
            }
        )
    labels = {}
    for item in reviewed:
        labels[item["label"]] = labels.get(item["label"], 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_generated_at": payload.get("generated_at"),
        "coverage": payload.get("coverage"),
        "fee_slip_pct": payload.get("fee_slip_pct"),
        "params_scanned": payload.get("params_scanned"),
        "qualified": payload.get("qualified"),
        "top_n_reviewed": len(reviewed),
        "label_counts": labels,
        "reviewed": reviewed,
        "note": "Research review only. OKX real-money promotion still requires native hard-stop preflight and tiny-pilot workflow.",
    }


def render_markdown(review: dict[str, Any]) -> str:
    coverage = review.get("coverage") or {}
    lines = [
        "# OKX 策略研發 Robustness Review",
        "",
        f"- 產生時間 UTC：{review.get('generated_at')}",
        f"- 來源掃描時間：{review.get('source_generated_at')}",
        f"- 資料範圍：{coverage.get('min_ts')} ～ {coverage.get('max_ts')}",
        f"- 覆蓋：sessions={coverage.get('sessions')} / bars={coverage.get('bars')} / instruments={coverage.get('insts')}",
        f"- 掃描參數：{review.get('params_scanned')}，通過原始門檻：{review.get('qualified')}，本次複核 TopN：{review.get('top_n_reviewed')}",
        f"- 成本模型：round-trip fee/slippage = {review.get('fee_slip_pct')}%",
        "",
        "## 總結",
    ]
    for label, count in sorted((review.get("label_counts") or {}).items()):
        lines.append(f"- {label}: {count}")
    lines += [
        "",
        "> 注意：這份只判斷研發/Shadow/Tiny-pilot 候選；不是 OKX live-ready。實盤仍必須走 exchange-native 1% hard stop preflight。",
        "",
        "## Top 候選複核",
    ]
    for idx, item in enumerate(review.get("reviewed") or [], 1):
        m = item["metrics"]
        params = m.get("params") or {}
        lines += [
            "",
            f"### {idx}. {item['name']}",
            f"- 結論：**{item['label']}**",
            f"- 交易數/天數：{m.get('trades')} / {m.get('days')}",
            f"- 累積淨利 / 平均淨利：{pct(m.get('net_sum_pct'))} / {pct(m.get('net_avg_pct'), 3)}",
            f"- PF / 勝率 / 日勝率：{num(m.get('profit_factor'))} / {pct(m.get('win_rate_pct'))} / {pct(m.get('day_win_rate_pct'))}",
            f"- 最大損失 / 最差日 / 最佳日：{pct(m.get('max_loss_pct'))} / {pct(m.get('worst_day_pct'))} / {pct(m.get('best_day_pct'))}",
            f"- 單日依賴：{pct(item.get('one_day_dependency_pct'))}；扣除最佳日後：{pct(item.get('net_without_best_day_pct'))}",
            f"- 參數：delay={params.get('delay_bars')}, rank<={params.get('max_entry_rank')}, chg={params.get('min_entry_change')}~{params.get('max_entry_change')}, cur>={params.get('min_current_change')}, vol>={params.get('min_vol_ratio')}, SL={params.get('stop_pct')}%, trail={params.get('trail_start_pct')}x{params.get('trail_giveback')}, t={params.get('time_stop_bars')}",
            f"- 出場原因：{m.get('exit_reasons')}",
        ]
        if item.get("warnings"):
            lines.append(f"- 警告：{'；'.join(item['warnings'])}")
        if item.get("reasons"):
            lines.append(f"- 未升級原因：{'；'.join(item['reasons'])}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review OKX strategy research scan robustness")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Input scan JSON")
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD), help="Output markdown report")
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON), help="Output structured JSON review")
    parser.add_argument("--top-n", type=int, default=10, help="Number of top candidates to review")
    parser.add_argument("--min-trades", type=int, default=80, help="Minimum trades for candidate gate")
    args = parser.parse_args()

    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    review = build_review(payload, top_n=args.top_n, min_trades=args.min_trades)

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(review), encoding="utf-8")

    best = review["reviewed"][0] if review["reviewed"] else None
    print(json.dumps({
        "ok": True,
        "input": str(input_path),
        "out_md": str(out_md),
        "out_json": str(out_json),
        "top_n_reviewed": review["top_n_reviewed"],
        "label_counts": review["label_counts"],
        "best": None if best is None else {"name": best["name"], "label": best["label"]},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
