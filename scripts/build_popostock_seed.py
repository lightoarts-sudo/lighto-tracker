#!/usr/bin/env python3
"""Build the compressed Popostock seed from the fund tracker JSON exports."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def compact_candle(row: dict) -> list:
    return [
        row.get("time"),
        row.get("open"),
        row.get("high"),
        row.get("low"),
        row.get("close"),
        row.get("volume"),
        row.get("turnover"),
    ]


def load_market(source: Path) -> list[dict]:
    instruments = []
    for path in sorted((source / "market").glob("*.json")):
        if path.name in {"index.json", "passive-index.json", "us-index.json"}:
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        symbol = str(item["code"]).upper()
        if symbol in {"TAIEX", "VIXTWN"}:
            category = "index"
        elif symbol in {"SPY", "QQQ", "SMH"}:
            category = "us_etf"
        elif symbol.endswith("A"):
            category = "active_etf"
        else:
            category = "passive_etf"
        instruments.append(
            {
                "symbol": symbol,
                "name": item.get("name") or symbol,
                "category": category,
                "sourceTitle": item.get("sourceTitle"),
                "sourceUrl": item.get("sourceUrl"),
                "sourceDate": item.get("sourceDate"),
                "candles": [compact_candle(row) for row in item.get("values", [])],
            }
        )
    return instruments


def load_nav(source: Path) -> list[dict]:
    instruments = []
    for path in sorted((source / "nav").glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        symbol = str(item["code"]).upper()
        candles = []
        for row in item.get("values", []):
            if not isinstance(row, list) or len(row) < 2:
                continue
            candles.append([row[0], None, None, None, row[1], None, None])
        instruments.append(
            {
                "symbol": symbol,
                "name": item.get("name") or symbol,
                "category": "fund",
                "sourceTitle": "基金官方歷史淨值",
                "sourceUrl": item.get("sourceUrl"),
                "sourceDate": item.get("sourceDate"),
                "candles": candles,
            }
        )
    return instruments


def load_fund_profiles(path: Path) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items", [])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Path to public/data")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("popostock/data/market_seed.json.gz"),
    )
    parser.add_argument(
        "--fund-data",
        type=Path,
        help="Path to normalized fund-bootstrap.json",
    )
    args = parser.parse_args()

    instruments = load_market(args.source) + load_nav(args.source)
    fund_data = args.fund_data or args.source.parents[1] / "data" / "fund-bootstrap.json"
    fund_profiles = load_fund_profiles(fund_data)
    canonical = json.dumps(
        {"instruments": instruments, "fundProfiles": fund_profiles},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    version = hashlib.sha256(canonical).hexdigest()[:16]
    payload = {
        "version": version,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "instrumentCount": len(instruments),
        "candleCount": sum(len(item["candles"]) for item in instruments),
        "fundProfileCount": len(fund_profiles),
        "fundHoldingCount": sum(len(item.get("holdings", [])) for item in fund_profiles),
        "fundAssetClassCount": sum(len(item.get("assetClasses", [])) for item in fund_profiles),
        "instruments": instruments,
        "fundProfiles": fund_profiles,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    print(
        f"wrote {args.output}: {payload['instrumentCount']} instruments, "
        f"{payload['candleCount']} rows, {payload['fundProfileCount']} fund profiles, "
        f"{payload['fundHoldingCount']} fund holdings, version {version}"
    )


if __name__ == "__main__":
    main()
