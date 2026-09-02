"""Popostock PostgreSQL-backed market history explorer."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
import ssl
import urllib.parse
import urllib.request
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
SEED_PATH = BASE_DIR / "popostock" / "data" / "market_seed.json.gz"
SITE_DIR = BASE_DIR / "popostock" / "site"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS popostock_instruments (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    source_title TEXT,
    source_url TEXT,
    source_date DATE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_candles (
    instrument_id BIGINT NOT NULL REFERENCES popostock_instruments(id) ON DELETE CASCADE,
    trade_date DATE NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1d',
    open NUMERIC,
    high NUMERIC,
    low NUMERIC,
    close NUMERIC NOT NULL,
    volume BIGINT,
    turnover NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_id, trade_date, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_popostock_candles_symbol_date
    ON popostock_candles (instrument_id, trade_date DESC);

CREATE TABLE IF NOT EXISTS popostock_fund_profiles (
    symbol TEXT PRIMARY KEY REFERENCES popostock_instruments(symbol) ON DELETE CASCADE,
    name TEXT NOT NULL,
    category TEXT,
    aum_twd BIGINT,
    aum_date TEXT,
    nav_date DATE,
    nav_value NUMERIC,
    manager TEXT,
    official_url TEXT,
    bootstrap_source_url TEXT,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_fund_holdings (
    fund_symbol TEXT NOT NULL REFERENCES popostock_fund_profiles(symbol) ON DELETE CASCADE,
    source_date DATE NOT NULL,
    stock_code TEXT,
    stock_name TEXT NOT NULL,
    weight NUMERIC,
    source_title TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fund_symbol, source_date, stock_name)
);

CREATE INDEX IF NOT EXISTS idx_popostock_fund_holdings_symbol_date
    ON popostock_fund_holdings (fund_symbol, source_date DESC);

CREATE TABLE IF NOT EXISTS popostock_fund_asset_classes (
    fund_symbol TEXT NOT NULL REFERENCES popostock_fund_profiles(symbol) ON DELETE CASCADE,
    source_date DATE NOT NULL,
    label TEXT NOT NULL,
    weight NUMERIC NOT NULL,
    source_title TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (fund_symbol, source_date, label)
);

CREATE TABLE IF NOT EXISTS popostock_tracker_items (
    item_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES popostock_instruments(symbol) ON DELETE CASCADE,
    group_name TEXT NOT NULL,
    group_rank INTEGER NOT NULL,
    name TEXT NOT NULL,
    aum_twd BIGINT,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_popostock_tracker_items_group_rank
    ON popostock_tracker_items (group_name, group_rank);

CREATE TABLE IF NOT EXISTS popostock_tracker_holdings (
    item_id TEXT NOT NULL REFERENCES popostock_tracker_items(item_id) ON DELETE CASCADE,
    holding_index INTEGER NOT NULL,
    stock_code TEXT,
    stock_name TEXT NOT NULL,
    shares TEXT,
    weight NUMERIC,
    source_date TEXT,
    source_title TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (item_id, holding_index)
);

CREATE INDEX IF NOT EXISTS idx_popostock_tracker_holdings_stock
    ON popostock_tracker_holdings (stock_code, stock_name);

CREATE TABLE IF NOT EXISTS popostock_tracker_metadata (
    metadata_key TEXT PRIMARY KEY,
    payload_json JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_sync_runs (
    id BIGSERIAL PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    instrument_count INTEGER NOT NULL,
    candle_count INTEGER NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_page_views (
    view_date DATE PRIMARY KEY,
    view_count BIGINT NOT NULL DEFAULT 0 CHECK (view_count >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS popostock_picks (
    id BIGSERIAL PRIMARY KEY,
    stock_code TEXT NOT NULL,
    reason TEXT,
    entry_date DATE NOT NULL,
    entry_price NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    exit_date DATE,
    exit_price NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_popostock_picks_status
    ON popostock_picks (status, entry_date DESC);
"""

PICKS_ADMIN_PASSWORD = "poadmin"

PICKS_PAGE_HTML = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Popo選股 | 波波流 PoPoStock</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px 16px 64px;
    background: #12295c; color: #fff;
    font-family: "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
  }
  h1 { text-align: center; font-size: 28px; margin: 0 0 4px; }
  h1 b { color: #ffd43b; }
  .sub { text-align: center; color: #9fb3d9; font-size: 14px; margin-bottom: 24px; }
  .card {
    max-width: 720px; margin: 0 auto 20px; background: #fff; color: #12295c;
    border-radius: 14px; padding: 18px 20px; box-shadow: 0 4px 14px rgba(0,0,0,.25);
  }
  .row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
  .row > * { flex: 1 1 140px; }
  label { display: block; font-size: 12px; color: #56698f; margin-bottom: 4px; font-weight: 700; }
  input, textarea {
    width: 100%; padding: 9px 10px; border: 1px solid #d7deee; border-radius: 8px;
    font-size: 14px; font-family: inherit; background: #f7f9ff; color: #12295c;
  }
  textarea { resize: vertical; min-height: 44px; }
  button {
    cursor: pointer; border: none; border-radius: 8px; padding: 10px 18px;
    font-size: 14px; font-weight: 700; font-family: inherit;
  }
  .btn-primary { background: #12295c; color: #ffd43b; }
  .btn-primary:hover { background: #1c3a7a; }
  .btn-danger { background: #c0392b; color: #fff; padding: 5px 12px; font-size: 12px; }
  .btn-danger:hover { background: #a5301f; }
  .locked-hint { font-size: 13px; color: #7a8bb0; }
  #unlock-msg, #add-msg { font-size: 13px; margin-top: 6px; min-height: 16px; }
  .ok { color: #1a7a3c; }
  .err { color: #c0392b; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 9px 8px; text-align: right; border-bottom: 1px solid #eef1fa; white-space: nowrap; }
  th:nth-child(1), td:nth-child(1),
  th:nth-child(2), td:nth-child(2),
  th:nth-child(3), td:nth-child(3) { text-align: left; }
  td.reason { white-space: normal; text-align: left; color: #445; max-width: 220px; }
  th { color: #56698f; font-size: 12px; }
  .up { color: #d0342c; font-weight: 700; }
  .down { color: #1a7a3c; font-weight: 700; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }
  .tag-active { background: #fff4cc; color: #8a6d00; }
  .tag-exited { background: #eef1fa; color: #56698f; }
  .table-wrap { overflow-x: auto; }
  .empty { text-align: center; color: #9fb3d9; padding: 24px 0; }
  .foot { text-align: center; color: #6e83ad; font-size: 12px; margin-top: 24px; }
  .foot a { color: #9fb3d9; }
</style>
</head>
<body>
  <h1>Popo<b>選股</b></h1>
  <div class="sub">波波流自選股績效追蹤 &middot; 僅供個人紀錄，不構成投資建議</div>

  <div class="card">
    <div class="row">
      <div>
        <label>管理員密碼</label>
        <input id="pwd" type="password" placeholder="輸入密碼以新增/出場" autocomplete="off">
      </div>
      <div style="flex:0 0 auto; align-self:flex-end;">
        <button class="btn-primary" onclick="unlock()">解鎖</button>
      </div>
    </div>
    <div id="unlock-msg" class="locked-hint">尚未解鎖，僅能檢視績效。</div>
  </div>

  <div class="card" id="add-card" style="display:none;">
    <div class="row">
      <div>
        <label>日期</label>
        <input id="f-date" type="date">
      </div>
      <div>
        <label>股號</label>
        <input id="f-code" type="text" placeholder="例：2330" maxlength="10">
      </div>
    </div>
    <div class="row">
      <div>
        <label>理由</label>
        <textarea id="f-reason" placeholder="為什麼選這檔？"></textarea>
      </div>
    </div>
    <button class="btn-primary" onclick="addPick()">新增追蹤</button>
    <div id="add-msg"></div>
  </div>

  <div class="card" style="max-width:960px;">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>進場日</th><th>股號</th><th>理由</th>
            <th>進場價</th><th>現價/出場價</th><th>報酬率</th><th>狀態</th><th></th>
          </tr>
        </thead>
        <tbody id="rows"><tr><td colspan="8" class="empty">載入中...</td></tr></tbody>
      </table>
    </div>
  </div>

  <div class="foot">
    資料來源：TWSE／TPEx 官方收盤 &middot; <a href="/popostock/">回主站</a>
  </div>

<script>
let ADMIN_PWD = "";

function fmtPct(p) {
  if (p === null || p === undefined) return "-";
  const sign = p > 0 ? "+" : "";
  const cls = p > 0 ? "up" : (p < 0 ? "down" : "");
  return `<span class="${cls}">${sign}${p.toFixed(2)}%</span>`;
}

function unlock() {
  const v = document.getElementById("pwd").value;
  const msg = document.getElementById("unlock-msg");
  if (v === "poadmin") {
    ADMIN_PWD = v;
    document.getElementById("add-card").style.display = "block";
    msg.textContent = "已解鎖，可以新增股票、標記出場。";
    msg.className = "ok";
  } else {
    ADMIN_PWD = "";
    document.getElementById("add-card").style.display = "none";
    msg.textContent = "密碼錯誤。";
    msg.className = "err";
  }
  render();
}

async function addPick() {
  const msg = document.getElementById("add-msg");
  msg.className = "";
  msg.textContent = "送出中...";
  const body = {
    password: ADMIN_PWD,
    date: document.getElementById("f-date").value,
    stockCode: document.getElementById("f-code").value.trim(),
    reason: document.getElementById("f-reason").value.trim(),
  };
  if (!body.date || !body.stockCode) {
    msg.className = "err";
    msg.textContent = "請填日期與股號。";
    return;
  }
  try {
    const res = await fetch("/popostock/api/picks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "新增失敗");
    msg.className = "ok";
    msg.textContent = `已新增，進場價 ${data.entryPrice}（${data.entryDate}）`;
    document.getElementById("f-code").value = "";
    document.getElementById("f-reason").value = "";
    load();
  } catch (e) {
    msg.className = "err";
    msg.textContent = e.message;
  }
}

async function exitPick(id) {
  if (!ADMIN_PWD) return;
  if (!confirm("確定要標記這檔出場嗎？")) return;
  try {
    const res = await fetch(`/popostock/api/picks/${id}/exit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: ADMIN_PWD }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "出場失敗");
    load();
  } catch (e) {
    alert(e.message);
  }
}

async function deletePick(id) {
  if (!ADMIN_PWD) return;
  if (!confirm("確定要刪除這筆紀錄嗎？此動作無法復原。")) return;
  try {
    const res = await fetch(`/popostock/api/picks/${id}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: ADMIN_PWD }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || "刪除失敗");
    }
    load();
  } catch (e) {
    alert(e.message);
  }
}

let PICKS = [];

function render() {
  const tbody = document.getElementById("rows");
  if (!PICKS.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">尚無追蹤中的股票</td></tr>';
    return;
  }
  tbody.innerHTML = PICKS.map(p => {
    const priceCol = p.status === "exited"
      ? `${p.exitPrice}<br><span style="font-size:11px;color:#9aa8c7;">${p.exitDate}</span>`
      : (p.currentPrice ?? "-");
    const tag = p.status === "exited"
      ? '<span class="tag tag-exited">已出場</span>'
      : '<span class="tag tag-active">追蹤中</span>';
    const actions = ADMIN_PWD
      ? (p.status === "active"
          ? `<button class="btn-danger" onclick="exitPick(${p.id})">出場</button>`
          : `<button class="btn-danger" onclick="deletePick(${p.id})">刪除</button>`)
      : "";
    return `<tr>
      <td>${p.entryDate}</td>
      <td>${p.stockCode}</td>
      <td class="reason">${p.reason ? p.reason.replace(/</g,"&lt;") : ""}</td>
      <td>${p.entryPrice}</td>
      <td>${priceCol}</td>
      <td>${fmtPct(p.returnPct)}</td>
      <td>${tag}</td>
      <td>${actions}</td>
    </tr>`;
  }).join("");
}

async function load() {
  try {
    const res = await fetch("/popostock/api/picks");
    PICKS = await res.json();
    render();
  } catch (e) {
    document.getElementById("rows").innerHTML =
      '<tr><td colspan="8" class="empty">載入失敗，請重新整理</td></tr>';
  }
}

document.getElementById("f-date").valueAsDate = new Date();
load();
</script>
</body>
</html>
"""

UPSERT_CANDLE_SQL = """
INSERT INTO popostock_candles
    (instrument_id, trade_date, timeframe, open, high, low, close, volume, turnover)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8)
ON CONFLICT (instrument_id, trade_date, timeframe) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    turnover = EXCLUDED.turnover,
    updated_at = NOW()
"""


def _read_seed() -> dict[str, Any] | None:
    if not SEED_PATH.exists():
        return None
    with gzip.open(SEED_PATH, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(str(value).replace("/", "-")) if value else None


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _popostock_redirect_target(query_items: list[tuple[str, str]]) -> str:
    query = urlencode(query_items)
    return f"/popostock?{query}" if query else "/popostock"


def _basic_value(item: dict[str, Any], label: str) -> str | None:
    for entry in item.get("basicInfo", []):
        if entry.get("label") == label:
            return entry.get("value")
    return None


def _nav_value(item: dict[str, Any]) -> float | None:
    value = str((item.get("performance") or {}).get("priceOrNav") or "").split(" ", 1)[0]
    try:
        return float(value)
    except ValueError:
        return None


# --- Popo picks: minimal TWSE/TPEx close-price lookup -----------------------
# Mirrors the working fetch logic in this project's data pipeline
# (scripts/official_close_prices.py), trimmed to what a live web request
# needs: one whole-market snapshot per calendar day, cached in memory so
# repeat page loads don't re-hit the exchanges.

_PICKS_TLS_CONTEXT = ssl.create_default_context()
_PICKS_TLS_CONTEXT.verify_flags &= ~ssl.VERIFY_X509_STRICT
_PICKS_USER_AGENT = "Mozilla/5.0 (compatible; PopoPicks/1.0)"
_PICKS_QUOTE_CACHE: dict[str, dict[str, float]] = {}


def _picks_parse_decimal(value: Any) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", str(value or ""))
    if not re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
        return None
    return float(cleaned)


def _picks_roc_date(value: date) -> str:
    return f"{value.year - 1911:03d}/{value.month:02d}/{value.day:02d}"


def _picks_fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": _PICKS_USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=15, context=_PICKS_TLS_CONTEXT) as response:
        return json.load(response)


def _picks_fetch_quotes_sync(target: date) -> dict[str, float]:
    """One day's close price for every TWSE + TPEx stock, keyed by code."""
    quotes: dict[str, float] = {}
    compact = target.strftime("%Y%m%d")
    try:
        payload = _picks_fetch_json(
            "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?"
            + urllib.parse.urlencode({"date": compact, "type": "ALLBUT0999", "response": "json"})
        )
        if payload.get("stat") == "OK" and str(payload.get("date", "")) == compact:
            for table in payload.get("tables", []):
                fields = table.get("fields") or []
                if not {"證券代號", "收盤價"}.issubset(fields):
                    continue
                code_index = fields.index("證券代號")
                close_index = fields.index("收盤價")
                for row in table.get("data", []):
                    if len(row) <= max(code_index, close_index):
                        continue
                    close = _picks_parse_decimal(row[close_index])
                    code = str(row[code_index]).strip()
                    if code and close is not None:
                        quotes[code] = close
                break
    except Exception:
        LOGGER.warning("popo picks: TWSE quote fetch failed for %s", compact, exc_info=True)
    try:
        rows = _picks_fetch_json(
            "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes?"
            + urllib.parse.urlencode({"l": "zh-tw", "d": _picks_roc_date(target), "s": "0,asc,0"})
        )
        expected = _picks_roc_date(target).replace("/", "")
        for row in rows:
            if str(row.get("Date", "")) != expected:
                continue
            close = _picks_parse_decimal(row.get("Close"))
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if code and close is not None:
                quotes[code] = close
    except Exception:
        LOGGER.warning("popo picks: TPEx quote fetch failed for %s", compact, exc_info=True)
    return quotes


async def _picks_quotes_for_date(target: date) -> dict[str, float]:
    key = target.isoformat()
    if key not in _PICKS_QUOTE_CACHE:
        _PICKS_QUOTE_CACHE[key] = await asyncio.to_thread(_picks_fetch_quotes_sync, target)
    return _PICKS_QUOTE_CACHE[key]


async def _picks_resolve_price(
    code: str, start: date, *, max_lookback: int = 10
) -> tuple[date, float] | None:
    """Most recent close on or before `start` (skips weekends/holidays with no data)."""
    cursor = start
    for _ in range(max_lookback):
        if cursor.weekday() < 5:  # Mon-Fri only; exchanges are closed weekends
            quotes = await _picks_quotes_for_date(cursor)
            price = quotes.get(code)
            if price is not None:
                return cursor, price
        cursor -= timedelta(days=1)
    return None


def _picks_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"],
        "stockCode": row["stock_code"],
        "reason": row["reason"],
        "entryDate": row["entry_date"].isoformat(),
        "entryPrice": _number(row["entry_price"]),
        "status": row["status"],
        "exitDate": row["exit_date"].isoformat() if row["exit_date"] else None,
        "exitPrice": _number(row["exit_price"]),
    }


async def import_seed(pool: asyncpg.Pool, seed: dict[str, Any]) -> bool:
    version = str(seed["version"])
    tracker_items = seed.get("trackerItems")
    tracker_references = seed.get("trackerReferences")
    if (
        not isinstance(tracker_items, list)
        or len(tracker_items) != int(seed.get("trackerItemCount", 0))
        or not tracker_items
    ):
        raise ValueError("Complete trackerItems are required before database import")
    if (
        not isinstance(tracker_references, list)
        or len(tracker_references) != int(seed.get("trackerReferenceCount", -1))
    ):
        raise ValueError("Complete trackerReferences are required before database import")
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM popostock_sync_runs WHERE version = $1", version
        )
        if exists:
            return False

        async with conn.transaction():
            for item in seed.get("instruments", []):
                instrument_id = await conn.fetchval(
                    """
                    INSERT INTO popostock_instruments
                        (symbol, name, category, source_title, source_url, source_date)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        source_title = EXCLUDED.source_title,
                        source_url = EXCLUDED.source_url,
                        source_date = EXCLUDED.source_date,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    item["symbol"],
                    item["name"],
                    item["category"],
                    item.get("sourceTitle"),
                    item.get("sourceUrl"),
                    _as_date(item.get("sourceDate")),
                )
                rows = []
                for candle in item.get("candles", []):
                    if len(candle) < 7 or candle[4] is None:
                        continue
                    rows.append(
                        (
                            instrument_id,
                            _as_date(candle[0]),
                            candle[1],
                            candle[2],
                            candle[3],
                            candle[4],
                            candle[5],
                            candle[6],
                        )
                    )
                if rows:
                    await conn.executemany(UPSERT_CANDLE_SQL, rows)

            for item in seed.get("fundProfiles", []):
                symbol = str(item["code"]).upper()
                performance = item.get("performance") or {}
                metadata = item.get("sourceMetadata") or {}
                await conn.execute(
                    """
                    INSERT INTO popostock_fund_profiles (
                        symbol, name, category, aum_twd, aum_date, nav_date,
                        nav_value, manager, official_url, bootstrap_source_url,
                        payload_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                    ON CONFLICT (symbol) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        aum_twd = EXCLUDED.aum_twd,
                        aum_date = EXCLUDED.aum_date,
                        nav_date = EXCLUDED.nav_date,
                        nav_value = EXCLUDED.nav_value,
                        manager = EXCLUDED.manager,
                        official_url = EXCLUDED.official_url,
                        bootstrap_source_url = EXCLUDED.bootstrap_source_url,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = NOW()
                    """,
                    symbol,
                    item["name"],
                    item.get("category"),
                    item.get("aumTwd"),
                    item.get("aumDate"),
                    _as_date(performance.get("date")),
                    _nav_value(item),
                    _basic_value(item, "基金經理人"),
                    metadata.get("officialUrl"),
                    metadata.get("bootstrapSourceUrl"),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                )

                await conn.execute(
                    "DELETE FROM popostock_fund_holdings WHERE fund_symbol = $1",
                    symbol,
                )
                holding_rows = [
                    (
                        symbol,
                        _as_date(holding.get("sourceDate")),
                        holding.get("stockCode"),
                        holding["stockName"],
                        holding.get("weight"),
                        holding.get("sourceTitle"),
                    )
                    for holding in item.get("holdings", [])
                    if holding.get("sourceDate")
                ]
                if holding_rows:
                    await conn.executemany(
                        """
                        INSERT INTO popostock_fund_holdings (
                            fund_symbol, source_date, stock_code, stock_name,
                            weight, source_title
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        holding_rows,
                    )

                await conn.execute(
                    "DELETE FROM popostock_fund_asset_classes WHERE fund_symbol = $1",
                    symbol,
                )
                asset_rows = [
                    (
                        symbol,
                        _as_date(asset.get("sourceDate")),
                        asset["label"],
                        asset["weight"],
                        asset.get("sourceTitle"),
                    )
                    for asset in item.get("assetClasses", [])
                    if asset.get("sourceDate")
                ]
                if asset_rows:
                    await conn.executemany(
                        """
                        INSERT INTO popostock_fund_asset_classes (
                            fund_symbol, source_date, label, weight, source_title
                        ) VALUES ($1, $2, $3, $4, $5)
                        """,
                        asset_rows,
                    )

            await conn.execute("DELETE FROM popostock_tracker_holdings")
            await conn.execute("DELETE FROM popostock_tracker_items")
            for item in seed.get("trackerItems", []):
                item_id = str(item["id"])
                symbol = str(item["code"]).upper()
                await conn.execute(
                    """
                    INSERT INTO popostock_tracker_items (
                        item_id, symbol, group_name, group_rank, name,
                        aum_twd, payload_json
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    item_id,
                    symbol,
                    item["group"],
                    int(item["groupRank"]),
                    item["name"],
                    item.get("aumTwd"),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                )
                holding_rows = [
                    (
                        item_id,
                        index,
                        holding.get("stockCode"),
                        holding["stockName"],
                        holding.get("shares"),
                        holding.get("weight"),
                        holding.get("sourceDate"),
                        holding.get("sourceTitle"),
                    )
                    for index, holding in enumerate(item.get("holdings", []))
                ]
                if holding_rows:
                    await conn.executemany(
                        """
                        INSERT INTO popostock_tracker_holdings (
                            item_id, holding_index, stock_code, stock_name,
                            shares, weight, source_date, source_title
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        holding_rows,
                    )

            await conn.execute(
                """
                INSERT INTO popostock_tracker_metadata (
                    metadata_key, payload_json
                ) VALUES ('references', $1::jsonb)
                ON CONFLICT (metadata_key) DO UPDATE SET
                    payload_json = EXCLUDED.payload_json,
                    updated_at = NOW()
                """,
                json.dumps(
                    seed.get("trackerReferences", []),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )

            await conn.execute(
                """
                INSERT INTO popostock_sync_runs
                    (version, instrument_count, candle_count)
                VALUES ($1, $2, $3)
                """,
                version,
                int(seed.get("instrumentCount", 0)),
                int(seed.get("candleCount", 0)),
            )
    return True


def install_popostock(app: FastAPI, database_url: str) -> None:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    @app.on_event("startup")
    async def popostock_startup() -> None:
        if not database_url.startswith("postgresql://"):
            LOGGER.warning("Popostock disabled: PostgreSQL DATABASE_URL is unavailable")
            app.state.popostock_pool = None
            return
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=3)
        app.state.popostock_pool = pool
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_SQL)
        seed = _read_seed()
        if seed:
            imported = await import_seed(pool, seed)
            LOGGER.info(
                "Popostock seed %s: %s",
                seed["version"],
                "imported" if imported else "already current",
            )

    @app.on_event("shutdown")
    async def popostock_shutdown() -> None:
        pool = getattr(app.state, "popostock_pool", None)
        if pool:
            await pool.close()

    def pool_for(request: Request) -> asyncpg.Pool:
        pool = getattr(request.app.state, "popostock_pool", None)
        if not pool:
            raise HTTPException(status_code=503, detail="Popostock database unavailable")
        return pool

    @app.get("/popostock/")
    async def popostock_slash(request: Request) -> RedirectResponse:
        return RedirectResponse(
            _popostock_redirect_target(list(request.query_params.multi_items())),
            status_code=308,
        )

    @app.get("/popostock", response_class=FileResponse)
    async def popostock_page() -> FileResponse:
        return FileResponse(SITE_DIR / "index.html")

    @app.get("/popostock/api/summary")
    async def popostock_summary(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(DISTINCT i.id) AS instruments,
                       COUNT(c.trade_date) AS candles,
                       MIN(c.trade_date) AS first_date,
                       MAX(c.trade_date) AS latest_date
                FROM popostock_instruments i
                LEFT JOIN popostock_candles c ON c.instrument_id = i.id
                """
            )
            fund_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS profiles,
                       (SELECT COUNT(*) FROM popostock_fund_holdings) AS holdings,
                       (SELECT COUNT(*) FROM popostock_fund_asset_classes) AS asset_classes
                FROM popostock_fund_profiles
                """
            )
            tracker_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS items,
                       (SELECT COUNT(*) FROM popostock_tracker_holdings) AS holdings,
                       COUNT(*) FILTER (WHERE group_name = 'funds') AS funds,
                       COUNT(*) FILTER (WHERE group_name = 'activeEtfs') AS active_etfs,
                       COUNT(*) FILTER (WHERE group_name = 'passiveEtfs') AS passive_etfs
                FROM popostock_tracker_items
                """
            )
        return JSONResponse(
            {
                "instruments": row["instruments"],
                "candles": row["candles"],
                "firstDate": row["first_date"].isoformat() if row["first_date"] else None,
                "latestDate": row["latest_date"].isoformat() if row["latest_date"] else None,
                "fundProfiles": fund_row["profiles"],
                "fundHoldings": fund_row["holdings"],
                "fundAssetClasses": fund_row["asset_classes"],
                "trackerItems": tracker_row["items"],
                "trackerHoldings": tracker_row["holdings"],
                "trackerGroups": {
                    "funds": tracker_row["funds"],
                    "activeEtfs": tracker_row["active_etfs"],
                    "passiveEtfs": tracker_row["passive_etfs"],
                },
            }
        )

    @app.post("/popostock/api/page-view", status_code=204)
    async def record_popostock_page_view(request: Request) -> Response:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO popostock_page_views (view_date, view_count)
                VALUES ((CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei')::date, 1)
                ON CONFLICT (view_date) DO UPDATE SET
                    view_count = popostock_page_views.view_count + 1,
                    updated_at = NOW()
                """
            )
        return Response(status_code=204)

    @app.get("/popostock/api/page-views/summary")
    async def popostock_page_view_summary(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(view_count), 0) AS total,
                       COALESCE(SUM(view_count) FILTER (
                           WHERE view_date =
                               (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Taipei')::date
                       ), 0) AS today,
                       MIN(view_date) AS first_date,
                       MAX(view_date) AS latest_date
                FROM popostock_page_views
                """
            )
        return JSONResponse(
            {
                "total": int(row["total"] or 0),
                "today": int(row["today"] or 0),
                "firstDate": row["first_date"].isoformat() if row["first_date"] else None,
                "latestDate": row["latest_date"].isoformat() if row["latest_date"] else None,
            }
        )

    @app.get("/popostock/api/instruments")
    async def popostock_instruments(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH ranked AS (
                    SELECT instrument_id, trade_date, close,
                           ROW_NUMBER() OVER (
                               PARTITION BY instrument_id ORDER BY trade_date DESC
                           ) AS rn
                    FROM popostock_candles
                    WHERE timeframe = '1d'
                ), stats AS (
                    SELECT instrument_id, COUNT(*) AS points,
                           MIN(trade_date) AS first_date, MAX(trade_date) AS latest_date
                    FROM popostock_candles
                    WHERE timeframe = '1d'
                    GROUP BY instrument_id
                )
                SELECT i.symbol, i.name, i.category, i.source_title, i.source_url,
                       i.source_date, s.points, s.first_date, s.latest_date,
                       latest.close AS latest_close, previous.close AS previous_close
                FROM popostock_instruments i
                LEFT JOIN stats s ON s.instrument_id = i.id
                LEFT JOIN ranked latest
                       ON latest.instrument_id = i.id AND latest.rn = 1
                LEFT JOIN ranked previous
                       ON previous.instrument_id = i.id AND previous.rn = 2
                ORDER BY CASE i.category
                    WHEN 'index' THEN 1 WHEN 'active_etf' THEN 2
                    WHEN 'passive_etf' THEN 3 ELSE 4 END,
                    i.symbol
                """
            )
        payload = []
        for row in rows:
            latest = _number(row["latest_close"])
            previous = _number(row["previous_close"])
            change = None
            if latest is not None and previous not in (None, 0):
                change = round((latest / previous - 1) * 100, 3)
            payload.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "category": row["category"],
                    "sourceTitle": row["source_title"],
                    "sourceUrl": row["source_url"],
                    "sourceDate": row["source_date"].isoformat() if row["source_date"] else None,
                    "points": row["points"] or 0,
                    "firstDate": row["first_date"].isoformat() if row["first_date"] else None,
                    "latestDate": row["latest_date"].isoformat() if row["latest_date"] else None,
                    "latestClose": latest,
                    "changePct": change,
                }
            )
        return JSONResponse(payload)

    @app.get("/popostock/api/funds")
    async def popostock_funds(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload_json
                FROM popostock_fund_profiles
                ORDER BY aum_twd DESC NULLS LAST, symbol
                """
            )
        return JSONResponse(
            [
                json.loads(row["payload_json"])
                if isinstance(row["payload_json"], str)
                else row["payload_json"]
                for row in rows
            ]
        )

    @app.get("/popostock/api/tracker")
    async def popostock_tracker(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload_json
                FROM popostock_tracker_items
                ORDER BY CASE group_name
                    WHEN 'funds' THEN 1
                    WHEN 'activeEtfs' THEN 2
                    WHEN 'passiveEtfs' THEN 3
                    ELSE 4
                END, group_rank, item_id
                """
            )
            references = await conn.fetchval(
                """
                SELECT payload_json
                FROM popostock_tracker_metadata
                WHERE metadata_key = 'references'
                """
            )
            version = await conn.fetchval(
                """
                SELECT version
                FROM popostock_sync_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )

        def json_value(value: Any) -> Any:
            return json.loads(value) if isinstance(value, str) else value

        return JSONResponse(
            {
                "version": version,
                "items": [json_value(row["payload_json"]) for row in rows],
                "references": json_value(references) if references is not None else [],
            }
        )

    @app.get("/popostock/api/candles/{symbol}")
    async def popostock_candles(
        symbol: str,
        request: Request,
        limit: int = Query(12000, ge=20, le=20000),
    ) -> JSONResponse:
        pool = pool_for(request)
        symbol = symbol.upper().strip()
        if not symbol.replace("-", "").isalnum():
            raise HTTPException(status_code=400, detail="Invalid symbol")
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM (
                    SELECT c.trade_date, c.open, c.high, c.low, c.close,
                           c.volume, c.turnover
                    FROM popostock_candles c
                    JOIN popostock_instruments i ON i.id = c.instrument_id
                    WHERE i.symbol = $1 AND c.timeframe = '1d'
                    ORDER BY c.trade_date DESC
                    LIMIT $2
                ) history
                ORDER BY trade_date
                """,
                symbol,
                limit,
            )
        if not rows:
            raise HTTPException(status_code=404, detail="Symbol not found")
        return JSONResponse(
            [
                {
                    "time": row["trade_date"].isoformat(),
                    "open": _number(row["open"]),
                    "high": _number(row["high"]),
                    "low": _number(row["low"]),
                    "close": _number(row["close"]),
                    "volume": _number(row["volume"]),
                    "turnover": _number(row["turnover"]),
                }
                for row in rows
            ]
        )

    @app.get("/popostock/picks", response_class=HTMLResponse)
    async def popostock_picks_page() -> HTMLResponse:
        return HTMLResponse(PICKS_PAGE_HTML)

    @app.get("/popostock/api/picks")
    async def popostock_picks_list(request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM popostock_picks ORDER BY entry_date DESC, id DESC"
            )

        today = date.today()
        picks = [_picks_row(row) for row in rows]
        active_codes = {p["stockCode"] for p in picks if p["status"] == "active"}
        current_prices: dict[str, float] = {}
        if active_codes:
            resolved = await asyncio.gather(
                *(_picks_resolve_price(code, today) for code in active_codes)
            )
            for code, hit in zip(active_codes, resolved):
                if hit:
                    current_prices[code] = hit[1]

        for pick in picks:
            entry_price = pick["entryPrice"]
            if pick["status"] == "exited":
                exit_price = pick["exitPrice"]
                pick["returnPct"] = (
                    round((exit_price / entry_price - 1) * 100, 2)
                    if entry_price else None
                )
                pick["currentPrice"] = None
            else:
                current = current_prices.get(pick["stockCode"])
                pick["currentPrice"] = current
                pick["returnPct"] = (
                    round((current / entry_price - 1) * 100, 2)
                    if current is not None and entry_price else None
                )
        return JSONResponse(picks)

    @app.post("/popostock/api/picks")
    async def popostock_picks_add(request: Request) -> JSONResponse:
        pool = pool_for(request)
        body = await request.json()
        if str(body.get("password", "")) != PICKS_ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="密碼錯誤")
        code = str(body.get("stockCode", "")).strip().upper()
        if not code or not re.fullmatch(r"[0-9A-Z]{2,10}", code):
            raise HTTPException(status_code=400, detail="股號格式不正確")
        try:
            entry_date = date.fromisoformat(str(body.get("date", "")))
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正確")
        if entry_date > date.today():
            raise HTTPException(status_code=400, detail="日期不可以是未來")
        reason = str(body.get("reason", "")).strip() or None

        resolved = await _picks_resolve_price(code, entry_date)
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail=f"查無 {code} 在 {entry_date.isoformat()} 前後的收盤價，請確認股號",
            )
        priced_date, price = resolved

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO popostock_picks (stock_code, reason, entry_date, entry_price)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                code, reason, priced_date, price,
            )
        return JSONResponse(_picks_row(row))

    @app.post("/popostock/api/picks/{pick_id}/exit")
    async def popostock_picks_exit(pick_id: int, request: Request) -> JSONResponse:
        pool = pool_for(request)
        body = await request.json()
        if str(body.get("password", "")) != PICKS_ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="密碼錯誤")
        raw_date = body.get("date")
        try:
            exit_date = date.fromisoformat(str(raw_date)) if raw_date else date.today()
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正確")

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM popostock_picks WHERE id = $1", pick_id
            )
            if not existing:
                raise HTTPException(status_code=404, detail="找不到這筆紀錄")
            if existing["status"] != "active":
                raise HTTPException(status_code=400, detail="這筆已經出場過了")

            resolved = await _picks_resolve_price(existing["stock_code"], exit_date)
            if not resolved:
                raise HTTPException(status_code=400, detail="查無出場當日收盤價")
            priced_date, price = resolved

            row = await conn.fetchrow(
                """
                UPDATE popostock_picks
                SET status = 'exited', exit_date = $2, exit_price = $3, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                pick_id, priced_date, price,
            )
        return JSONResponse(_picks_row(row))

    @app.delete("/popostock/api/picks/{pick_id}")
    async def popostock_picks_delete(pick_id: int, request: Request) -> Response:
        pool = pool_for(request)
        body = await request.json()
        if str(body.get("password", "")) != PICKS_ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="密碼錯誤")
        async with pool.acquire() as conn:
            deleted = await conn.fetchval(
                "DELETE FROM popostock_picks WHERE id = $1 RETURNING id", pick_id
            )
        if not deleted:
            raise HTTPException(status_code=404, detail="找不到這筆紀錄")
        return Response(status_code=204)

    app.mount(
        "/popostock",
        StaticFiles(directory=SITE_DIR, html=True),
        name="popostock-static",
    )
