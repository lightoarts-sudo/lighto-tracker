"""Popostock PostgreSQL-backed market history explorer."""

from __future__ import annotations

import asyncio
import base64
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
from typing import Any, NamedTuple
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
    stock_name TEXT,
    reason TEXT,
    observed_date DATE,
    entry_date DATE,
    entry_price NUMERIC,
    status TEXT NOT NULL DEFAULT 'active',
    exit_date DATE,
    exit_price NUMERIC,
    entry_image BYTEA,
    entry_image_type TEXT,
    stop_loss_price NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_popostock_picks_status
    ON popostock_picks (status, entry_date DESC);

ALTER TABLE popostock_picks ADD COLUMN IF NOT EXISTS stock_name TEXT;
ALTER TABLE popostock_picks ADD COLUMN IF NOT EXISTS observed_date DATE;
ALTER TABLE popostock_picks ADD COLUMN IF NOT EXISTS entry_image BYTEA;
ALTER TABLE popostock_picks ADD COLUMN IF NOT EXISTS entry_image_type TEXT;
ALTER TABLE popostock_picks ADD COLUMN IF NOT EXISTS stop_loss_price NUMERIC;
ALTER TABLE popostock_picks ALTER COLUMN entry_date DROP NOT NULL;
ALTER TABLE popostock_picks ALTER COLUMN entry_price DROP NOT NULL;
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
  input[type=file] { padding: 6px 8px; }
  textarea { resize: vertical; min-height: 44px; }
  button {
    cursor: pointer; border: none; border-radius: 8px; padding: 10px 18px;
    font-size: 14px; font-weight: 700; font-family: inherit;
  }
  .btn-primary { background: #12295c; color: #ffd43b; }
  .btn-primary:hover { background: #1c3a7a; }
  .btn-danger { background: #c0392b; color: #fff; padding: 5px 12px; font-size: 12px; }
  .btn-danger:hover { background: #a5301f; }
  .btn-ghost { background: #eef1fa; color: #12295c; padding: 5px 12px; font-size: 12px; }
  .btn-ghost:hover { background: #dfe5f7; }
  .locked-hint { font-size: 13px; color: #7a8bb0; }
  #unlock-msg, #add-msg { font-size: 13px; margin-top: 6px; min-height: 16px; }
  .ok { color: #1a7a3c; }
  .err { color: #c0392b; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 9px 8px; text-align: right; border-bottom: 1px solid #eef1fa; white-space: nowrap; }
  th:nth-child(1), td:nth-child(1),
  th:nth-child(2), td:nth-child(2),
  th:nth-child(3), td:nth-child(3),
  th:nth-child(4), td:nth-child(4) { text-align: left; }
  td.reason { white-space: normal; text-align: left; color: #445; max-width: 200px; }
  th { color: #56698f; font-size: 12px; }
  tr.pick-row { cursor: pointer; }
  tr.pick-row:hover { background: #f7f9ff; }
  .up { color: #d0342c; font-weight: 700; }
  .down { color: #1a7a3c; font-weight: 700; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; }
  .tag-active { background: #fff4cc; color: #8a6d00; }
  .tag-exited { background: #eef1fa; color: #56698f; }
  .table-wrap { overflow-x: auto; }
  .empty { text-align: center; color: #9fb3d9; padding: 24px 0; }
  .foot { text-align: center; color: #6e83ad; font-size: 12px; margin-top: 24px; }
  .foot a { color: #9fb3d9; }
  .detail-cell { background: #f7f9ff; text-align: left; white-space: normal; }
  .detail-wrap { padding: 14px 6px; }
  .detail-toggle { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #56698f; margin-bottom: 8px; }
  .detail-toggle input { width: auto; }
  canvas.candles { width: 100%; height: 240px; display: block; background: #fff; border-radius: 8px; }
  .detail-loading { font-size: 12px; color: #9fb3d9; padding: 20px 0; text-align: center; }
  .image-btn { margin-top: 10px; }
  .observed-image { margin-top: 10px; max-width: 100%; border-radius: 8px; border: 1px solid #eef1fa; display: none; }
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
        <label>日期（觀察到的日期，通常是盤後）</label>
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
    <div class="row">
      <div>
        <label>停損價格（選填）</label>
        <input id="f-stoploss" type="number" step="0.01" placeholder="例：95">
      </div>
      <div>
        <label>觀察到的圖檔（選填）</label>
        <input id="f-image" type="file" accept="image/*">
      </div>
    </div>
    <button class="btn-primary" onclick="addPick()">新增追蹤</button>
    <div id="add-msg"></div>
  </div>

  <div class="card" style="max-width:1100px;">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>進場日</th><th>股號</th><th>名稱</th><th>理由</th>
            <th>進場價</th><th>停損價</th><th>現價/出場價</th><th>報酬率</th><th>狀態</th><th></th>
          </tr>
        </thead>
        <tbody id="rows"><tr><td colspan="10" class="empty">載入中...</td></tr></tbody>
      </table>
    </div>
  </div>

  <div class="foot">
    資料來源：TWSE／TPEx 官方收盤 &middot; <a href="/popostock/">回主站</a>
  </div>

<script>
let ADMIN_PWD = "";
let PICKS = [];
let EXPANDED_ID = null;
const CANDLE_CACHE = {};

function fmtPct(p) {
  if (p === null || p === undefined) return "-";
  const sign = p > 0 ? "+" : "";
  const cls = p > 0 ? "up" : (p < 0 ? "down" : "");
  return `<span class="${cls}">${sign}${p.toFixed(2)}%</span>`;
}

function esc(s) {
  return s ? String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])) : "";
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

function readImageAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    if (!file) { resolve(null); return; }
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function addPick() {
  const msg = document.getElementById("add-msg");
  msg.className = "";
  msg.textContent = "送出中...";
  const imageFile = document.getElementById("f-image").files[0] || null;
  let imageDataUrl = null;
  try {
    imageDataUrl = await readImageAsDataUrl(imageFile);
  } catch (e) {
    msg.className = "err";
    msg.textContent = "圖檔讀取失敗。";
    return;
  }
  const stopLossRaw = document.getElementById("f-stoploss").value.trim();
  const body = {
    password: ADMIN_PWD,
    date: document.getElementById("f-date").value,
    stockCode: document.getElementById("f-code").value.trim(),
    reason: document.getElementById("f-reason").value.trim(),
    stopLossPrice: stopLossRaw ? Number(stopLossRaw) : null,
    image: imageDataUrl,
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
    msg.textContent = data.entryPrice !== null
      ? `已新增，觀察日 ${data.observedDate} → 進場日 ${data.entryDate}（開盤價 ${data.entryPrice}）`
      : `已新增，觀察日 ${data.observedDate}。進場價還查不到，會在你重新打開這頁時自動補上。`;
    document.getElementById("f-code").value = "";
    document.getElementById("f-reason").value = "";
    document.getElementById("f-stoploss").value = "";
    document.getElementById("f-image").value = "";
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
    delete CANDLE_CACHE[id];
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

function toggleDetail(id, evt) {
  if (evt && evt.target && evt.target.tagName === "BUTTON") return;
  EXPANDED_ID = EXPANDED_ID === id ? null : id;
  render();
}

function drawCandles(canvas, candles, entryDate, dimAfterEntry, stopLossPrice) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!candles.length) {
    ctx.fillStyle = "#9fb3d9";
    ctx.font = "12px sans-serif";
    ctx.fillText("沒有可顯示的K線資料", 10, h / 2);
    return;
  }
  const pad = { top: 10, bottom: 18, left: 54, right: 10 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;
  let lo = Math.min(...candles.map(c => c.low));
  let hi = Math.max(...candles.map(c => c.high));
  if (stopLossPrice !== null && stopLossPrice !== undefined) {
    lo = Math.min(lo, stopLossPrice);
    hi = Math.max(hi, stopLossPrice);
  }
  const span = (hi - lo) || 1;
  const n = candles.length;
  const slot = plotW / n;
  const bodyW = Math.max(2, slot * 0.6);
  const y = v => pad.top + plotH - ((v - lo) / span) * plotH;

  // Price axis: a handful of evenly spaced gridlines with labels.
  const steps = 4;
  ctx.strokeStyle = "#eef1fa";
  ctx.fillStyle = "#9aa8c7";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= steps; i++) {
    const price = lo + (span * i) / steps;
    const yy = y(price);
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(w - pad.right, yy);
    ctx.stroke();
    ctx.fillText(price.toFixed(price < 100 ? 2 : 1), pad.left - 6, yy);
  }
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";

  candles.forEach((c, i) => {
    const x = pad.left + i * slot + slot / 2;
    const dimmed = dimAfterEntry && c.date >= entryDate;
    ctx.globalAlpha = dimmed ? 0.28 : 1;
    const up = c.close >= c.open;
    ctx.strokeStyle = ctx.fillStyle = up ? "#d0342c" : "#1a7a3c";
    ctx.beginPath();
    ctx.moveTo(x, y(c.high));
    ctx.lineTo(x, y(c.low));
    ctx.stroke();
    const yOpen = y(c.open), yClose = y(c.close);
    const top = Math.min(yOpen, yClose);
    const bh = Math.max(1, Math.abs(yClose - yOpen));
    ctx.fillRect(x - bodyW / 2, top, bodyW, bh);
  });
  ctx.globalAlpha = 1;

  if (entryDate) {
    const idx = candles.findIndex(c => c.date >= entryDate);
    if (idx >= 0) {
      const x = pad.left + idx * slot;
      ctx.strokeStyle = "#ffb020";
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x, pad.top);
      ctx.lineTo(x, pad.top + plotH);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  if (stopLossPrice !== null && stopLossPrice !== undefined) {
    const yy = y(stopLossPrice);
    ctx.strokeStyle = "#3b6bd6";
    ctx.setLineDash([6, 3]);
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(w - pad.right, yy);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#3b6bd6";
    ctx.font = "10px sans-serif";
    ctx.fillText(`停損 ${stopLossPrice}`, pad.left + 4, yy - 4);
  }
}

async function loadDetail(pick) {
  const container = document.getElementById(`detail-${pick.id}`);
  if (!container) return;
  if (!CANDLE_CACHE[pick.id]) {
    container.innerHTML = '<div class="detail-loading">載入K線中...</div>';
    try {
      const res = await fetch(`/popostock/api/picks/${pick.id}/candles`);
      CANDLE_CACHE[pick.id] = await res.json();
    } catch (e) {
      container.innerHTML = '<div class="detail-loading">K線載入失敗</div>';
      return;
    }
  }
  const data = CANDLE_CACHE[pick.id];
  container.innerHTML = `
    <div class="detail-wrap">
      <label class="detail-toggle">
        <input type="checkbox" id="dim-${pick.id}" checked>
        進場後半透明
      </label>
      <canvas class="candles" id="canvas-${pick.id}"></canvas>
      ${pick.hasImage ? `
        <button class="btn-ghost image-btn" onclick="toggleImage(${pick.id})">查看進場時觀測圖</button>
        <img class="observed-image" id="img-${pick.id}" src="/popostock/api/picks/${pick.id}/image">
      ` : ""}
    </div>`;
  const canvas = document.getElementById(`canvas-${pick.id}`);
  const checkbox = document.getElementById(`dim-${pick.id}`);
  const redraw = () => drawCandles(canvas, data.candles, data.entryDate, checkbox.checked, data.stopLossPrice);
  checkbox.addEventListener("change", redraw);
  window.addEventListener("resize", redraw);
  redraw();
}

function toggleImage(id) {
  const img = document.getElementById(`img-${id}`);
  if (img) img.style.display = img.style.display === "block" ? "none" : "block";
}

async function patchPick(id, patch) {
  const res = await fetch(`/popostock/api/picks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: ADMIN_PWD, ...patch }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "更新失敗");
  return data;
}

async function editReason(id, current, evt) {
  evt.stopPropagation();
  if (!ADMIN_PWD) return;
  const next = prompt("修改理由：", current || "");
  if (next === null) return;
  try {
    await patchPick(id, { reason: next.trim() });
    load();
  } catch (e) {
    alert(e.message);
  }
}

async function editStopLoss(id, current, evt) {
  evt.stopPropagation();
  if (!ADMIN_PWD) return;
  const next = prompt("修改停損價格（留空可清除）：", current ?? "");
  if (next === null) return;
  try {
    await patchPick(id, { stopLossPrice: next.trim() === "" ? null : Number(next) });
    load();
  } catch (e) {
    alert(e.message);
  }
}

function render() {
  const tbody = document.getElementById("rows");
  if (!PICKS.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty">尚無追蹤中的股票</td></tr>';
    return;
  }
  tbody.innerHTML = PICKS.map(p => {
    const priceCol = p.status === "exited"
      ? `${p.exitPrice}<br><span style="font-size:11px;color:#9aa8c7;">${p.exitDate}</span>`
      : (p.currentPrice ?? "-");
    const pending = p.entryPrice === null;
    const tag = p.status === "exited"
      ? '<span class="tag tag-exited">已出場</span>'
      : (pending
          ? '<span class="tag tag-active">待補價</span>'
          : '<span class="tag tag-active">追蹤中</span>');
    const actions = ADMIN_PWD
      ? (p.status === "active"
          ? `<button class="btn-danger" onclick="exitPick(${p.id})">出場</button>`
          : `<button class="btn-danger" onclick="deletePick(${p.id})">刪除</button>`)
      : "";
    const dateCol = p.entryDate || `${p.observedDate}（觀察，進場待定）`;
    const reasonCell = ADMIN_PWD
      ? `${esc(p.reason)} <button class="btn-ghost" style="padding:2px 6px;font-size:11px;" onclick="editReason(${p.id}, ${JSON.stringify(p.reason || "")}, event)">✎</button>`
      : esc(p.reason);
    const stopLossCell = ADMIN_PWD
      ? `${p.stopLossPrice ?? "-"} <button class="btn-ghost" style="padding:2px 6px;font-size:11px;" onclick="editStopLoss(${p.id}, ${p.stopLossPrice ?? "null"}, event)">✎</button>`
      : (p.stopLossPrice ?? "-");
    const mainRow = `<tr class="pick-row" onclick="toggleDetail(${p.id}, event)">
      <td>${dateCol}</td>
      <td>${esc(p.stockCode)}</td>
      <td>${esc(p.stockName) || "-"}</td>
      <td class="reason">${reasonCell}</td>
      <td>${pending ? "-" : p.entryPrice}</td>
      <td>${stopLossCell}</td>
      <td>${pending ? "-" : priceCol}</td>
      <td>${fmtPct(p.returnPct)}</td>
      <td>${tag}</td>
      <td>${actions}</td>
    </tr>`;
    if (EXPANDED_ID !== p.id) return mainRow;
    return mainRow + `<tr><td colspan="10" class="detail-cell"><div id="detail-${p.id}"></div></td></tr>`;
  }).join("");
  if (EXPANDED_ID !== null) {
    const pick = PICKS.find(p => p.id === EXPANDED_ID);
    if (pick) loadDetail(pick);
  }
}

async function load() {
  try {
    const res = await fetch("/popostock/api/picks");
    PICKS = await res.json();
    render();
  } catch (e) {
    document.getElementById("rows").innerHTML =
      '<tr><td colspan="10" class="empty">載入失敗，請重新整理</td></tr>';
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
# needs: one stock's whole month of OHLC at a time, cached in memory so
# repeat page loads don't re-hit the exchanges. A whole-market snapshot
# would be cheaper for many codes at once, but TPEx's snapshot endpoint
# silently ignores its own date parameter and always returns the latest
# trading day, which made any historical lookup fail — the per-stock
# month endpoint (TWSE STOCK_DAY / TPEx afterTrading/tradingStock) is the
# only one of the two that actually answers "what happened on date X".

_PICKS_TLS_CONTEXT = ssl.create_default_context()
_PICKS_TLS_CONTEXT.verify_flags &= ~ssl.VERIFY_X509_STRICT
_PICKS_USER_AGENT = "Mozilla/5.0 (compatible; PopoPicks/1.0)"
_PICKS_MONTH_CACHE: dict[tuple[str, int, int], list[tuple[date, float, float]]] = {}


def _picks_parse_decimal(value: Any) -> float | None:
    cleaned = re.sub(r"[^0-9.\-]", "", str(value or ""))
    if not re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", cleaned):
        return None
    return float(cleaned)


def _picks_parse_roc_date(value: str) -> date | None:
    try:
        year, month, day = str(value).split("/")
        return date(int(year) + 1911, int(month), int(day))
    except Exception:
        return None


class PicksCandle(NamedTuple):
    trade_date: date
    open: float
    high: float
    low: float
    close: float


def _picks_fetch_twse_month(code: str, year: int, month: int) -> tuple[str | None, list[PicksCandle]]:
    """(company_name, candles) for one TWSE-listed stock/month."""
    url = (
        "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?"
        + urllib.parse.urlencode({"date": f"{year:04d}{month:02d}01", "stockNo": code, "response": "json"})
    )
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": _PICKS_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=_PICKS_TLS_CONTEXT) as response:
            payload = json.load(response)
    except Exception:
        LOGGER.warning("popo picks: TWSE month fetch failed for %s %04d-%02d", code, year, month, exc_info=True)
        return None, []
    if payload.get("stat") != "OK":
        return None, []
    fields = payload.get("fields") or []
    required = {"日期", "開盤價", "最高價", "最低價", "收盤價"}
    if not required.issubset(fields):
        return None, []
    date_i = fields.index("日期")
    open_i = fields.index("開盤價")
    high_i = fields.index("最高價")
    low_i = fields.index("最低價")
    close_i = fields.index("收盤價")
    name_match = re.search(rf"\d+年\d+月\s+{re.escape(code)}\s+(\S+)", str(payload.get("title", "")))
    name = name_match.group(1) if name_match else None
    candles: list[PicksCandle] = []
    for row in payload.get("data", []):
        if len(row) <= max(date_i, open_i, high_i, low_i, close_i):
            continue
        trade_date = _picks_parse_roc_date(row[date_i])
        o = _picks_parse_decimal(row[open_i])
        h = _picks_parse_decimal(row[high_i])
        l = _picks_parse_decimal(row[low_i])
        c = _picks_parse_decimal(row[close_i])
        if trade_date and None not in (o, h, l, c):
            candles.append(PicksCandle(trade_date, o, h, l, c))
    return name, candles


def _picks_fetch_tpex_month(code: str, year: int, month: int) -> tuple[str | None, list[PicksCandle]]:
    """(company_name, candles) for one TPEx-listed stock/month."""
    url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    body = urllib.parse.urlencode({"code": code, "date": f"{year:04d}/{month:02d}/01"}).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": _PICKS_USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=_PICKS_TLS_CONTEXT) as response:
            payload = json.load(response)
    except Exception:
        LOGGER.warning("popo picks: TPEx month fetch failed for %s %04d-%02d", code, year, month, exc_info=True)
        return None, []
    if payload.get("stat") != "ok" or not payload.get("tables"):
        return None, []
    table = payload["tables"][0]
    fields = table.get("fields") or []
    required = {"日 期", "開盤", "最高", "最低", "收盤"}
    if not required.issubset(fields):
        return None, []
    date_i = fields.index("日 期")
    open_i = fields.index("開盤")
    high_i = fields.index("最高")
    low_i = fields.index("最低")
    close_i = fields.index("收盤")
    name_match = re.search(rf"^{re.escape(code)}\s+(\S+)\s+\d+年\d+月", str(table.get("subtitle", "")))
    name = name_match.group(1) if name_match else None
    candles: list[PicksCandle] = []
    for row in table.get("data", []):
        if len(row) <= max(date_i, open_i, high_i, low_i, close_i):
            continue
        trade_date = _picks_parse_roc_date(row[date_i])
        o = _picks_parse_decimal(row[open_i])
        h = _picks_parse_decimal(row[high_i])
        l = _picks_parse_decimal(row[low_i])
        c = _picks_parse_decimal(row[close_i])
        if trade_date and None not in (o, h, l, c):
            candles.append(PicksCandle(trade_date, o, h, l, c))
    return name, candles


_PICKS_NAME_CACHE: dict[str, str] = {}


async def _picks_month_data(code: str, year: int, month: int) -> list[PicksCandle]:
    key = (code, year, month)
    if key not in _PICKS_MONTH_CACHE:
        def _fetch() -> list[PicksCandle]:
            name, candles = _picks_fetch_twse_month(code, year, month)
            if not candles:
                name, candles = _picks_fetch_tpex_month(code, year, month)
            if name and code not in _PICKS_NAME_CACHE:
                _PICKS_NAME_CACHE[code] = name
            return candles
        _PICKS_MONTH_CACHE[key] = await asyncio.to_thread(_fetch)
    return _PICKS_MONTH_CACHE[key]


async def _picks_stock_name(code: str) -> str | None:
    if code not in _PICKS_NAME_CACHE:
        today = date.today()
        await _picks_month_data(code, today.year, today.month)
    return _PICKS_NAME_CACHE.get(code)


def _picks_shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


async def _picks_close_on_or_before(
    code: str, start: date, *, max_lookback_months: int = 4
) -> tuple[date, float] | None:
    """Most recent (date, close) at or before `start` — for current/exit prices."""
    year, month = start.year, start.month
    for step in range(max_lookback_months):
        y, m = _picks_shift_month(year, month, -step)
        candles = await _picks_month_data(code, y, m)
        candidates = [c for c in candles if c.trade_date <= start]
        if candidates:
            latest = max(candidates, key=lambda c: c.trade_date)
            return latest.trade_date, latest.close
    return None


async def _picks_open_on_or_after(
    code: str, start: date, *, max_lookahead_months: int = 4
) -> tuple[date, float] | None:
    """Earliest (date, open) at or after `start` — for entry price the day after
    the pick was actually observed (post-market), since that's the first price
    it could realistically have been bought at."""
    year, month = start.year, start.month
    today = date.today()
    for step in range(max_lookahead_months):
        y, m = _picks_shift_month(year, month, step)
        if date(y, m, 1) > today:
            break
        candles = await _picks_month_data(code, y, m)
        candidates = [c for c in candles if c.trade_date >= start]
        if candidates:
            earliest = min(candidates, key=lambda c: c.trade_date)
            return earliest.trade_date, earliest.open
    return None


async def _picks_candles_since(code: str, start: date, end: date) -> list[dict[str, Any]]:
    """Every candle for `code` from `start` through `end`, inclusive, ascending."""
    out: list[PicksCandle] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.extend(await _picks_month_data(code, year, month))
        year, month = _picks_shift_month(year, month, 1)
    seen: dict[date, PicksCandle] = {c.trade_date: c for c in out if start <= c.trade_date <= end}
    return [
        {"date": c.trade_date.isoformat(), "open": c.open, "high": c.high, "low": c.low, "close": c.close}
        for c in sorted(seen.values(), key=lambda c: c.trade_date)
    ]


def _picks_row(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": row["id"],
        "stockCode": row["stock_code"],
        "stockName": row["stock_name"],
        "reason": row["reason"],
        "observedDate": row["observed_date"].isoformat() if row["observed_date"] else None,
        "entryDate": row["entry_date"].isoformat() if row["entry_date"] else None,
        "entryPrice": _number(row["entry_price"]),
        "status": row["status"],
        "exitDate": row["exit_date"].isoformat() if row["exit_date"] else None,
        "exitPrice": _number(row["exit_price"]),
        "hasImage": row["entry_image"] is not None,
        "stopLossPrice": _number(row["stop_loss_price"]),
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
                "SELECT * FROM popostock_picks "
                "ORDER BY COALESCE(entry_date, observed_date) DESC, id DESC"
            )

        today = date.today()
        picks = [_picks_row(row) for row in rows]

        # A pick can be saved before its entry price is known (see add()) —
        # retry resolving it on every read, and persist as soon as it lands.
        pending = [p for p in picks if p["status"] == "active" and p["entryPrice"] is None]
        if pending:
            resolved = await asyncio.gather(
                *(
                    _picks_open_on_or_after(
                        p["stockCode"], date.fromisoformat(p["observedDate"]) + timedelta(days=1)
                    )
                    for p in pending
                ),
                return_exceptions=True,
            )
            newly_priced = [
                (p, hit) for p, hit in zip(pending, resolved)
                if isinstance(hit, tuple)
            ]
            if newly_priced:
                async with pool.acquire() as conn:
                    for p, (entry_date, entry_price) in newly_priced:
                        await conn.execute(
                            """
                            UPDATE popostock_picks
                            SET entry_date = $2, entry_price = $3, updated_at = NOW()
                            WHERE id = $1
                            """,
                            p["id"], entry_date, entry_price,
                        )
                        p["entryDate"] = entry_date.isoformat()
                        p["entryPrice"] = entry_price

        active_codes = {p["stockCode"] for p in picks if p["status"] == "active" and p["entryPrice"] is not None}
        current_prices: dict[str, float] = {}
        if active_codes:
            active_codes_list = list(active_codes)
            resolved = await asyncio.gather(
                *(_picks_close_on_or_before(code, today) for code in active_codes_list)
            )
            for code, hit in zip(active_codes_list, resolved):
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
            observed_date = date.fromisoformat(str(body.get("date", "")))
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式不正確")
        if observed_date > date.today():
            raise HTTPException(status_code=400, detail="日期不可以是未來")
        reason = str(body.get("reason", "")).strip() or None

        stop_loss_price: float | None = None
        raw_stop_loss = body.get("stopLossPrice")
        if raw_stop_loss not in (None, ""):
            try:
                stop_loss_price = float(raw_stop_loss)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="停損價格格式不正確")

        # `date` is the day the pick was observed after market close, so the
        # earliest it could realistically have been bought is the *next*
        # trading day's open — not that day's own close. Never block the save
        # on this: if the exchange doesn't have next-day data yet (or any
        # other lookup hiccup), record the pick anyway with the price left
        # pending — GET /api/picks retries it on every read until it resolves.
        try:
            resolved = await _picks_open_on_or_after(code, observed_date + timedelta(days=1))
        except Exception:
            LOGGER.warning("popo picks: entry price lookup failed for %s", code, exc_info=True)
            resolved = None
        entry_date, entry_price = resolved if resolved else (None, None)
        try:
            stock_name = await _picks_stock_name(code)
        except Exception:
            stock_name = None

        image_bytes: bytes | None = None
        image_type: str | None = None
        raw_image = body.get("image")
        if raw_image:
            match = re.fullmatch(r"data:(image/[\w.+-]+);base64,(.+)", str(raw_image), re.DOTALL)
            payload_b64 = match.group(2) if match else str(raw_image)
            image_type = match.group(1) if match else "image/png"
            try:
                image_bytes = base64.b64decode(payload_b64, validate=True)
            except Exception:
                raise HTTPException(status_code=400, detail="圖檔格式不正確")
            if len(image_bytes) > 6 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="圖檔太大，請控制在 6MB 以內")

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO popostock_picks (
                    stock_code, stock_name, reason, observed_date,
                    entry_date, entry_price, entry_image, entry_image_type,
                    stop_loss_price
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                code, stock_name, reason, observed_date,
                entry_date, entry_price, image_bytes, image_type,
                stop_loss_price,
            )
        return JSONResponse(_picks_row(row))

    @app.patch("/popostock/api/picks/{pick_id}")
    async def popostock_picks_update(pick_id: int, request: Request) -> JSONResponse:
        pool = pool_for(request)
        body = await request.json()
        if str(body.get("password", "")) != PICKS_ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="密碼錯誤")

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT * FROM popostock_picks WHERE id = $1", pick_id
            )
            if not existing:
                raise HTTPException(status_code=404, detail="找不到這筆紀錄")

            reason = existing["reason"]
            if "reason" in body:
                reason = str(body["reason"]).strip() or None

            stop_loss_price = existing["stop_loss_price"]
            if "stopLossPrice" in body:
                raw = body["stopLossPrice"]
                if raw in (None, ""):
                    stop_loss_price = None
                else:
                    try:
                        stop_loss_price = float(raw)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail="停損價格格式不正確")

            row = await conn.fetchrow(
                """
                UPDATE popostock_picks
                SET reason = $2, stop_loss_price = $3, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                pick_id, reason, stop_loss_price,
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

            resolved = await _picks_close_on_or_before(existing["stock_code"], exit_date)
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

    @app.get("/popostock/api/picks/{pick_id}/image")
    async def popostock_picks_image(pick_id: int, request: Request) -> Response:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT entry_image, entry_image_type FROM popostock_picks WHERE id = $1",
                pick_id,
            )
        if not row or row["entry_image"] is None:
            raise HTTPException(status_code=404, detail="這筆沒有圖檔")
        return Response(
            content=bytes(row["entry_image"]),
            media_type=row["entry_image_type"] or "image/png",
        )

    @app.get("/popostock/api/picks/{pick_id}/candles")
    async def popostock_picks_candles(pick_id: int, request: Request) -> JSONResponse:
        pool = pool_for(request)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM popostock_picks WHERE id = $1", pick_id
            )
        if not row:
            raise HTTPException(status_code=404, detail="找不到這筆紀錄")
        # Show the whole picture, not a narrow slice: well before entry so the
        # setup that was observed is visible, and all the way to today even
        # for an exited pick, so the exit decision can be judged in hindsight.
        anchor = row["entry_date"] or row["observed_date"] or date.today()
        start = anchor - timedelta(days=120)
        end = date.today()
        candles = await _picks_candles_since(row["stock_code"], start, end)
        return JSONResponse(
            {
                "stockCode": row["stock_code"],
                "stockName": row["stock_name"],
                "entryDate": row["entry_date"].isoformat() if row["entry_date"] else None,
                "exitDate": row["exit_date"].isoformat() if row["exit_date"] else None,
                "stopLossPrice": _number(row["stop_loss_price"]),
                "candles": candles,
            }
        )

    app.mount(
        "/popostock",
        StaticFiles(directory=SITE_DIR, html=True),
        name="popostock-static",
    )
