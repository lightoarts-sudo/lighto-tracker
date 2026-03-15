"""
Lighto 光印樣 - EDM 點擊追蹤服務
使用 asyncpg (PostgreSQL) / aiosqlite (SQLite fallback)
"""

import os, base64, asyncio
from datetime import datetime, timezone
from urllib.parse import unquote
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
import asyncpg
import aiosqlite

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "lighto2026")
USE_PG = DATABASE_URL.startswith("postgresql://")

app = FastAPI(docs_url=None, redoc_url=None)
_pg_pool = None
SQLITE_PATH = "/tmp/clicks.db"

# ── 初始化 ────────────────────────────────────────────────────
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS clicks (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT NOW(),
    campaign    TEXT,
    customer_id TEXT,
    product_id  TEXT,
    content     TEXT,
    dest_url    TEXT,
    ip          TEXT,
    ua          TEXT
);
"""
CREATE_SQL_LITE = CREATE_SQL.replace("SERIAL", "INTEGER").replace("TIMESTAMPTZ", "TEXT")

@app.on_event("startup")
async def startup():
    global _pg_pool
    if USE_PG:
        _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with _pg_pool.acquire() as conn:
            await conn.execute(CREATE_SQL)
    else:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            await db.execute(CREATE_SQL_LITE)
            await db.commit()

@app.on_event("shutdown")
async def shutdown():
    if _pg_pool:
        await _pg_pool.close()

# ── DB 操作 ───────────────────────────────────────────────────
async def db_insert(row: dict):
    sql = """INSERT INTO clicks (ts,campaign,customer_id,product_id,content,dest_url,ip,ua)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8)"""
    vals = (row["ts"], row["campaign"], row["customer_id"], row["product_id"],
            row["content"], row["dest_url"], row["ip"], row["ua"])
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            await conn.execute(sql, *vals)
    else:
        sql_lite = sql.replace("$1","?").replace("$2","?").replace("$3","?").replace("$4","?").replace("$5","?").replace("$6","?").replace("$7","?").replace("$8","?")
        async with aiosqlite.connect(SQLITE_PATH) as db:
            await db.execute(sql_lite, vals)
            await db.commit()

async def db_fetch(sql: str, *args):
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            return [dict(r) for r in await conn.fetch(sql, *args)]
    else:
        sql_lite = sql
        for i in range(len(args), 0, -1):
            sql_lite = sql_lite.replace(f"${i}", "?")
        async with aiosqlite.connect(SQLITE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql_lite, args) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

async def db_val(sql: str):
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            return await conn.fetchval(sql)
    else:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            async with db.execute(sql) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

# ── 追蹤轉跳 ──────────────────────────────────────────────────
@app.get("/t")
async def track(
    request: Request,
    c: str = Query(...),
    p: str = Query(""),
    campaign: str = Query(""),
    content: str = Query(""),
    to: str = Query(...),
):
    try:
        customer_id = base64.urlsafe_b64decode(c + "==").decode()
    except Exception:
        customer_id = c
    try:
        dest_url = base64.urlsafe_b64decode(to + "==").decode()
    except Exception:
        dest_url = unquote(to)

    ip = request.headers.get("x-forwarded-for", "")
    if not ip and request.client:
        ip = request.client.host

    try:
        await db_insert({
            "ts": datetime.now(timezone.utc).isoformat(),
            "campaign": campaign[:100],
            "customer_id": customer_id[:200],
            "product_id": p[:50],
            "content": content[:100],
            "dest_url": dest_url[:2000],
            "ip": ip[:50],
            "ua": request.headers.get("user-agent", "")[:500],
        })
    except Exception as e:
        print(f"[tracker] DB error: {e}")

    return RedirectResponse(url=dest_url, status_code=302)

# ── 儀表板 ────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(pwd: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        return HTMLResponse("""<html><body style="font-family:sans-serif;max-width:400px;
        margin:80px auto;text-align:center;">
        <h2>🔒 Lighto EDM 追蹤儀表板</h2>
        <form method="get"><input name="pwd" type="password" placeholder="密碼"
        style="padding:8px;width:200px;">
        <button type="submit" style="padding:8px 16px;margin-left:8px;">登入</button>
        </form></body></html>""", status_code=401)

    total    = await db_val("SELECT COUNT(*) FROM clicks")
    uniq     = await db_val("SELECT COUNT(DISTINCT customer_id) FROM clicks")
    camps    = await db_fetch("SELECT campaign, COUNT(*) as cnt FROM clicks GROUP BY campaign ORDER BY cnt DESC")
    prods    = await db_fetch("SELECT product_id, content, COUNT(*) as cnt FROM clicks GROUP BY product_id, content ORDER BY cnt DESC LIMIT 20")
    recent   = await db_fetch("SELECT ts, customer_id, product_id, content, campaign FROM clicks ORDER BY ts DESC LIMIT 100")

    camp_rows = "".join(f"<tr><td>{r['campaign']}</td><td><b>{r['cnt']}</b></td></tr>" for r in camps)
    prod_rows = "".join(f"<tr><td>{r['product_id']}</td><td>{r['content']}</td><td><b>{r['cnt']}</b></td></tr>" for r in prods)
    rec_rows  = "".join(
        f"<tr><td style='color:#888;font-size:12px'>{str(r['ts'])[:16]}</td>"
        f"<td>{r['customer_id']}</td><td>{r['product_id']}</td>"
        f"<td>{r['content']}</td><td>{r['campaign']}</td></tr>"
        for r in recent
    )

    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Lighto EDM 儀表板</title>
<style>
body{{font-family:'PingFang TC',sans-serif;background:#f5f5f0;margin:0;padding:24px;}}
.card{{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;}}
h1{{font-size:22px;margin:0 0 4px;}} h2{{font-size:16px;color:#444;margin:0 0 16px;}}
.stat{{display:inline-block;background:#1a1a1a;color:#fff;border-radius:8px;padding:16px 28px;margin-right:12px;text-align:center;}}
.stat .n{{font-size:32px;font-weight:700;}} .stat .l{{font-size:12px;color:#aaa;margin-top:4px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th{{background:#f0f0f0;padding:8px;text-align:left;}} td{{padding:7px 8px;border-bottom:1px solid #f0f0f0;}}
</style></head><body>
<div class="card">
  <h1>Lighto 光印樣 EDM 追蹤儀表板</h1>
  <p style="color:#888;margin:0 0 20px;"><a href="/api/clicks?pwd={pwd}">JSON API</a> ·
  <a href="/dashboard?pwd={pwd}">重新整理</a></p>
  <div>
    <div class="stat"><div class="n">{total}</div><div class="l">總點擊數</div></div>
    <div class="stat"><div class="n">{uniq}</div><div class="l">不重複客戶</div></div>
  </div>
</div>
<div class="card"><h2>各廣告活動</h2>
<table><tr><th>Campaign</th><th>點擊數</th></tr>{camp_rows}</table></div>
<div class="card"><h2>各產品點擊</h2>
<table><tr><th>Product ID</th><th>Content</th><th>點擊數</th></tr>{prod_rows}</table></div>
<div class="card"><h2>最近 100 筆點擊</h2>
<table><tr><th>時間</th><th>客戶 Email</th><th>產品</th><th>內容</th><th>活動</th></tr>
{rec_rows}</table></div>
</body></html>""")

@app.get("/api/clicks")
async def api_clicks(pwd: str = Query(""), campaign: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    if campaign:
        rows = await db_fetch("SELECT * FROM clicks WHERE campaign=$1 ORDER BY ts DESC LIMIT 5000", campaign)
    else:
        rows = await db_fetch("SELECT * FROM clicks ORDER BY ts DESC LIMIT 5000")
    return rows

@app.get("/health")
async def health():
    return {"status": "ok", "db": "postgresql" if USE_PG else "sqlite",
            "time": datetime.now(timezone.utc).isoformat()}
