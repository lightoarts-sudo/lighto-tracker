"""
Lighto 光印樣 - EDM 點擊追蹤服務
使用 asyncpg (PostgreSQL) / aiosqlite (SQLite fallback)
"""

import os, base64, asyncio
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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

# 台灣時區 UTC+8
TW_TZ = timezone(timedelta(hours=8))

def tw_str(ts) -> str:
    """把 datetime 或字串轉成台灣時間顯示"""
    if ts is None:
        return ""
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return ts
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(TW_TZ).strftime("%Y-%m-%d %H:%M")
    return str(ts)

def html_head(title: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:'PingFang TC',Helvetica,sans-serif;background:#f5f5f0;margin:0;padding:20px;}}
.card{{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;}}
h1{{font-size:22px;margin:0 0 4px;}} h2{{font-size:16px;color:#444;margin:0 0 16px;}}
.stat{{display:inline-block;background:#1a1a1a;color:#fff;border-radius:8px;
       padding:16px 28px;margin:0 12px 8px 0;text-align:center;}}
.stat .n{{font-size:32px;font-weight:700;}} .stat .l{{font-size:12px;color:#aaa;margin-top:4px;}}
.unsub{{background:#c0392b;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th{{background:#f0f0f0;padding:8px;text-align:left;font-weight:600;}}
td{{padding:7px 8px;border-bottom:1px solid #f0f0f0;}}
tr:hover td{{background:#fafaf8;}}
a{{color:#1a6aff;text-decoration:none;}} a:hover{{text-decoration:underline;}}
.badge{{display:inline-block;background:#e8f4fd;color:#1a6aff;border-radius:4px;
        padding:2px 8px;font-size:12px;}}
.search-bar{{display:flex;gap:8px;margin-bottom:16px;}}
.search-bar input{{flex:1;padding:8px 12px;border:1px solid #ddd;border-radius:6px;font-size:14px;}}
.search-bar button{{padding:8px 18px;background:#1a1a1a;color:#fff;border:none;
                    border-radius:6px;cursor:pointer;font-size:14px;}}
.back-link{{margin-bottom:16px;display:inline-block;color:#888;font-size:13px;}}
</style></head><body>"""

# ── 初始化 ────────────────────────────────────────────────────
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS clicks (
    id           SERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ DEFAULT NOW(),
    campaign     TEXT,
    customer_id  TEXT,
    product_id   TEXT,
    product_name TEXT,
    content      TEXT,
    dest_url     TEXT,
    ip           TEXT,
    ua           TEXT
);
CREATE TABLE IF NOT EXISTS unsubscribes (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT NOW(),
    email       TEXT UNIQUE,
    campaign    TEXT
);
CREATE TABLE IF NOT EXISTS email_previews (
    id          SERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT NOW(),
    campaign    TEXT UNIQUE,
    subject     TEXT,
    html        TEXT
);
"""
CREATE_SQL_LITE = (
    CREATE_SQL
    .replace("SERIAL", "INTEGER")
    .replace("TIMESTAMPTZ", "TEXT")
)

MIGRATE_PG = [
    "ALTER TABLE clicks ADD COLUMN IF NOT EXISTS product_name TEXT;",
    """CREATE TABLE IF NOT EXISTS email_previews (
        id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(),
        campaign TEXT UNIQUE, subject TEXT, html TEXT);""",
]

@app.on_event("startup")
async def startup():
    global _pg_pool
    if USE_PG:
        _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
        async with _pg_pool.acquire() as conn:
            await conn.execute(CREATE_SQL)
            for m in MIGRATE_PG:
                try:
                    await conn.execute(m)
                except Exception:
                    pass
    else:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            await db.execute(CREATE_SQL_LITE)
            await db.commit()
            async with db.execute(
                "SELECT COUNT(*) FROM pragma_table_info('clicks') WHERE name='product_name'"
            ) as cur:
                row = await cur.fetchone()
                if row and row[0] == 0:
                    await db.execute("ALTER TABLE clicks ADD COLUMN product_name TEXT;")
                    await db.commit()

@app.on_event("shutdown")
async def shutdown():
    if _pg_pool:
        await _pg_pool.close()

# ── DB 操作 ───────────────────────────────────────────────────
async def db_insert(row: dict):
    sql = """INSERT INTO clicks
             (ts,campaign,customer_id,product_id,product_name,content,dest_url,ip,ua)
             VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)"""
    vals = (row["ts"], row["campaign"], row["customer_id"], row["product_id"],
            row["product_name"], row["content"], row["dest_url"], row["ip"], row["ua"])
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            await conn.execute(sql, *vals)
    else:
        sql_lite = sql
        for i in range(9, 0, -1):
            sql_lite = sql_lite.replace(f"${i}", "?")
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

async def db_val(sql: str, *args):
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            return await conn.fetchval(sql, *args)
    else:
        sql_lite = sql
        for i in range(len(args), 0, -1):
            sql_lite = sql_lite.replace(f"${i}", "?")
        async with aiosqlite.connect(SQLITE_PATH) as db:
            async with db.execute(sql_lite, args) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

# ── 追蹤轉跳 ──────────────────────────────────────────────────
@app.get("/t")
async def track(
    request: Request,
    c: str = Query(...),
    p: str = Query(""),
    pn: str = Query(""),        # product_name (base64)
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
    try:
        product_name = base64.urlsafe_b64decode(pn + "==").decode() if pn else ""
    except Exception:
        product_name = pn

    ip = request.headers.get("x-forwarded-for", "")
    if not ip and request.client:
        ip = request.client.host

    try:
        await db_insert({
            "ts":           datetime.now(timezone.utc),
            "campaign":     campaign[:100],
            "customer_id":  customer_id[:200],
            "product_id":   p[:50],
            "product_name": product_name[:100],
            "content":      content[:100],
            "dest_url":     dest_url[:2000],
            "ip":           ip[:50],
            "ua":           request.headers.get("user-agent", "")[:500],
        })
    except Exception as e:
        print(f"[tracker] DB error: {e}")

    return RedirectResponse(url=dest_url, status_code=302)

# ── 取消訂閱 ──────────────────────────────────────────────────
@app.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(c: str = Query(...), campaign: str = Query("")):
    try:
        email = base64.urlsafe_b64decode(c + "==").decode()
    except Exception:
        email = c

    try:
        if USE_PG:
            async with _pg_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO unsubscribes (ts, email, campaign) VALUES ($1,$2,$3) ON CONFLICT (email) DO NOTHING",
                    datetime.now(timezone.utc), email[:200], campaign[:100]
                )
        else:
            async with aiosqlite.connect(SQLITE_PATH) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO unsubscribes (ts, email, campaign) VALUES (?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), email[:200], campaign[:100])
                )
                await db.commit()
    except Exception as e:
        print(f"[unsubscribe] DB error: {e}")

    tw_now = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>已取消訂閱 - Lighto 光印樣</title></head>
<body style="margin:0;padding:0;background:#f5f5f0;font-family:'PingFang TC',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0"><tr>
<td align="center" style="padding:80px 16px;">
<div style="background:#fff;border-radius:12px;padding:48px 40px;max-width:480px;text-align:center;">
  <p style="font-size:32px;margin:0 0 16px;">🌲</p>
  <h1 style="font-size:22px;font-weight:700;color:#1a1a1a;margin:0 0 12px;">已取消訂閱</h1>
  <p style="font-size:15px;color:#666;line-height:1.7;margin:0 0 24px;">
    <b>{email}</b><br>已從 Lighto 光印樣 電子報名單中移除。<br>
    我們不會再寄送活動通知給您。<br>
    <span style="font-size:13px;color:#aaa;">{tw_now} (台灣時間)</span>
  </p>
  <a href="https://www.lightochan.com"
     style="display:inline-block;padding:12px 28px;background:#1a1a1a;color:#fff;
            text-decoration:none;border-radius:6px;font-size:14px;">
    回到 Lighto 光印樣
  </a>
</div>
</td></tr></table>
</body></html>""")

# ── 退訂 API ──────────────────────────────────────────────────
@app.get("/api/unsubscribes")
async def api_unsubscribes(pwd: str = Query(""), fmt: str = Query("json")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    rows = await db_fetch("SELECT ts, email, campaign FROM unsubscribes ORDER BY ts DESC")
    for r in rows:
        r["ts"] = tw_str(r["ts"])
    if fmt == "emails":
        return JSONResponse([r["email"] for r in rows])
    return rows

@app.delete("/api/unsubscribes")
async def delete_unsubscribe(pwd: str = Query(""), email: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    if not email:
        raise HTTPException(400, "email required")
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            await conn.execute("DELETE FROM unsubscribes WHERE email=$1", email)
    else:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            await db.execute("DELETE FROM unsubscribes WHERE email=?", (email,))
            await db.commit()
    return {"ok": True, "deleted": email}

# ── 儲存信件預覽 ──────────────────────────────────────────────
@app.post("/api/save_preview")
async def save_preview(request: Request, pwd: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    data = await request.json()
    campaign = data.get("campaign", "")
    subject  = data.get("subject", "")
    html     = data.get("html", "")
    if USE_PG:
        async with _pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO email_previews (ts, campaign, subject, html)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT (campaign) DO UPDATE
                   SET subject=EXCLUDED.subject, html=EXCLUDED.html, ts=EXCLUDED.ts""",
                datetime.now(timezone.utc), campaign, subject, html
            )
    else:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            await db.execute(
                """INSERT OR REPLACE INTO email_previews (ts, campaign, subject, html)
                   VALUES (?,?,?,?)""",
                (datetime.now(timezone.utc).isoformat(), campaign, subject, html)
            )
            await db.commit()
    return {"ok": True}

# ── 儀表板 ────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(pwd: str = Query(""), search: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        return HTMLResponse("""<html><body style="font-family:sans-serif;max-width:400px;
        margin:80px auto;text-align:center;">
        <h2>🔒 Lighto EDM 追蹤儀表板</h2>
        <form method="get"><input name="pwd" type="password" placeholder="密碼"
        style="padding:8px;width:200px;">
        <button type="submit" style="padding:8px 16px;margin-left:8px;">登入</button>
        </form></body></html>""", status_code=401)

    total  = await db_val("SELECT COUNT(*) FROM clicks")
    uniq   = await db_val("SELECT COUNT(DISTINCT customer_id) FROM clicks")
    unsubs = await db_val("SELECT COUNT(*) FROM unsubscribes")
    camps  = await db_fetch("SELECT campaign, COUNT(*) as cnt FROM clicks GROUP BY campaign ORDER BY cnt DESC")
    prods  = await db_fetch("""SELECT product_id, product_name, COUNT(*) as cnt
                               FROM clicks GROUP BY product_id, product_name
                               ORDER BY cnt DESC LIMIT 20""")
    unsub_list = await db_fetch("SELECT ts, email, campaign FROM unsubscribes ORDER BY ts DESC")

    search_rows = ""
    search_count = 0
    if search:
        search_results = await db_fetch(
            "SELECT ts, customer_id, product_id, product_name, content, campaign FROM clicks WHERE customer_id=$1 ORDER BY ts DESC",
            search.strip()
        )
        search_count = len(search_results)
        search_rows = "".join(
            f"<tr><td style='color:#888;font-size:12px'>{tw_str(r['ts'])}</td>"
            f"<td>{r['product_id']}</td><td style='color:#555'>{r['product_name'] or '-'}</td>"
            f"<td>{r['content']}</td><td>{r['campaign']}</td></tr>"
            for r in search_results
        )

    recent = await db_fetch("""SELECT ts, customer_id, product_id, product_name, content, campaign
                               FROM clicks ORDER BY ts DESC LIMIT 100""")

    camp_rows = "".join(
        f"<tr><td><a href='/campaign?pwd={pwd}&name={r['campaign']}'>{r['campaign']}</a></td>"
        f"<td><b>{r['cnt']}</b></td></tr>"
        for r in camps
    )
    prod_rows = "".join(
        f"<tr><td>{r['product_id']}</td><td>{r['product_name'] or '-'}</td><td><b>{r['cnt']}</b></td></tr>"
        for r in prods
    )
    rec_rows = "".join(
        f"<tr><td style='color:#888;font-size:12px'>{tw_str(r['ts'])}</td>"
        f"<td><a href='/customer?pwd={pwd}&email={r['customer_id']}'>{r['customer_id']}</a></td>"
        f"<td>{r['product_id']}</td><td style='color:#555'>{r['product_name'] or '-'}</td>"
        f"<td>{r['content']}</td><td>{r['campaign']}</td></tr>"
        for r in recent
    )
    unsub_rows = "".join(
        f"<tr><td style='color:#888;font-size:12px'>{tw_str(r['ts'])}</td>"
        f"<td><b>{r['email']}</b></td>"
        f"<td>{r['campaign']}</td>"
        f"<td><button onclick=\"delUnsub('{r['email']}', this)\" "
        f"style='background:#c0392b;color:#fff;border:none;border-radius:4px;"
        f"padding:3px 10px;cursor:pointer;font-size:12px;'>刪除</button></td></tr>"
        for r in unsub_list
    )

    search_section = ""
    if search:
        search_section = f"""
<div class="card">
  <h2>🔍 搜尋結果：{search}（共 {search_count} 筆點擊）</h2>
  {'<p style="color:#aaa;font-size:14px;">無點擊紀錄</p>' if not search_count else f'''
  <table><tr><th>時間 (台灣)</th><th>Product ID</th><th>產品名稱</th><th>內容</th><th>活動</th></tr>
  {search_rows}</table>'''}
</div>"""

    return HTMLResponse(html_head("Lighto EDM 儀表板") + f"""
<div class="card">
  <h1>Lighto 光印樣 EDM 追蹤儀表板</h1>
  <p style="color:#888;margin:0 0 20px;font-size:13px;">
    <a href="/api/clicks?pwd={pwd}">JSON API</a> ·
    <a href="/dashboard?pwd={pwd}">重新整理</a> ·
    所有時間均為台灣時間 (UTC+8)
  </p>
  <div>
    <div class="stat"><div class="n">{total}</div><div class="l">總點擊數</div></div>
    <div class="stat"><div class="n">{uniq}</div><div class="l">不重複客戶</div></div>
    <div class="stat unsub"><div class="n">{unsubs}</div><div class="l">退訂人數</div></div>
  </div>
</div>
<div class="card">
  <h2>🔍 搜尋客戶點擊記錄</h2>
  <form method="get" action="/dashboard">
    <input type="hidden" name="pwd" value="{pwd}">
    <div class="search-bar">
      <input type="text" name="search" placeholder="輸入客戶 Email..." value="{search}">
      <button type="submit">搜尋</button>
    </div>
  </form>
</div>
{search_section}
<div class="card"><h2>各廣告活動 <span style="font-size:13px;color:#888;font-weight:normal;">（點擊活動名稱查看詳情）</span></h2>
<table><tr><th>Campaign</th><th>點擊數</th></tr>{camp_rows}</table></div>
<div class="card"><h2>各產品點擊</h2>
<table><tr><th>Product ID</th><th>產品名稱</th><th>點擊數</th></tr>{prod_rows}</table></div>
<div class="card">
  <h2 style="color:#c0392b;">🚫 退訂名單（共 {unsubs} 人）</h2>
  {'<p style="color:#aaa;font-size:14px;">目前無退訂記錄</p>' if not unsub_list else f'''
  <table><tr><th>退訂時間 (台灣)</th><th>Email</th><th>來源活動</th><th style="width:60px">操作</th></tr>
  {unsub_rows}</table>'''}
</div>
<script>
async function delUnsub(email, btn) {{
  if (!confirm('確定要從退訂名單中移除 ' + email + ' 嗎？\n移除後此客戶下次收到 EDM 時不會被過濾。')) return;
  btn.disabled = true; btn.textContent = '...';
  try {{
    const r = await fetch('/api/unsubscribes?pwd={pwd}&email=' + encodeURIComponent(email), {{method:'DELETE'}});
    if (r.ok) {{ btn.closest('tr').remove(); }}
    else {{ alert('刪除失敗'); btn.disabled = false; btn.textContent = '刪除'; }}
  }} catch(e) {{ alert('網路錯誤'); btn.disabled = false; btn.textContent = '刪除'; }}
}}
</script>
<div class="card"><h2>最近 100 筆點擊 <span style="font-size:13px;color:#888;font-weight:normal;">（點擊 Email 查看記錄）</span></h2>
<table>
  <tr><th>時間 (台灣)</th><th>客戶 Email</th><th>Product ID</th><th>產品名稱</th><th>內容</th><th>活動</th></tr>
  {rec_rows}
</table></div>
</body></html>""")

# ── 客戶詳情頁 ────────────────────────────────────────────────
@app.get("/customer", response_class=HTMLResponse)
async def customer_detail(pwd: str = Query(""), email: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    if not email:
        raise HTTPException(400, "email required")

    rows = await db_fetch(
        "SELECT ts, product_id, product_name, content, campaign, dest_url FROM clicks WHERE customer_id=$1 ORDER BY ts DESC",
        email
    )
    is_unsub = await db_val("SELECT COUNT(*) FROM unsubscribes WHERE email=$1", email)
    unsub_badge = '<span style="background:#c0392b;color:#fff;padding:2px 10px;border-radius:4px;font-size:13px;margin-left:8px;">已退訂</span>' if is_unsub else ""
    click_rows = "".join(
        f"<tr><td style='color:#888;font-size:12px'>{tw_str(r['ts'])}</td>"
        f"<td>{r['product_id']}</td><td>{r['product_name'] or '-'}</td>"
        f"<td>{r['content']}</td><td>{r['campaign']}</td>"
        f"<td style='font-size:12px;color:#888'>{r['dest_url'][:60]}...</td></tr>"
        for r in rows
    )
    return HTMLResponse(html_head(f"客戶記錄 - {email}") + f"""
<a class="back-link" href="/dashboard?pwd={pwd}">← 返回儀表板</a>
<div class="card">
  <h1>{email} {unsub_badge}</h1>
  <p style="color:#888;font-size:13px;margin:8px 0 0;">共 {len(rows)} 筆點擊記錄</p>
</div>
{'<div class="card" style="border:2px solid #c0392b;"><p style="color:#c0392b;margin:0;font-weight:600;">⚠️ 此客戶已退訂，請勿再寄送 EDM</p></div>' if is_unsub else ''}
<div class="card">
  <h2>點擊記錄（台灣時間）</h2>
  {'<p style="color:#aaa;">無點擊記錄</p>' if not rows else f'''
  <table><tr><th>時間</th><th>Product ID</th><th>產品名稱</th><th>內容</th><th>活動</th><th>連結</th></tr>
  {click_rows}</table>'''}
</div>
</body></html>""")

# ── Campaign 詳情頁 ────────────────────────────────────────────
@app.get("/campaign", response_class=HTMLResponse)
async def campaign_detail(pwd: str = Query(""), name: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    if not name:
        raise HTTPException(400, "name required")

    total_clicks   = await db_val("SELECT COUNT(*) FROM clicks WHERE campaign=$1", name)
    uniq_customers = await db_val("SELECT COUNT(DISTINCT customer_id) FROM clicks WHERE campaign=$1", name)
    prods = await db_fetch(
        "SELECT product_id, product_name, COUNT(*) as cnt FROM clicks WHERE campaign=$1 GROUP BY product_id, product_name ORDER BY cnt DESC",
        name
    )
    customers = await db_fetch(
        """SELECT customer_id, COUNT(*) as clicks, MIN(ts) as first_click, MAX(ts) as last_click
           FROM clicks WHERE campaign=$1
           GROUP BY customer_id ORDER BY clicks DESC LIMIT 200""",
        name
    )
    preview_rows = await db_fetch("SELECT subject, html FROM email_previews WHERE campaign=$1", name)
    preview = preview_rows[0] if preview_rows else None

    prod_rows = "".join(
        f"<tr><td>{r['product_id']}</td><td>{r['product_name'] or '-'}</td><td><b>{r['cnt']}</b></td></tr>"
        for r in prods
    )
    cust_rows = "".join(
        f"<tr><td><a href='/customer?pwd={pwd}&email={r['customer_id']}'>{r['customer_id']}</a></td>"
        f"<td>{r['clicks']}</td>"
        f"<td style='color:#888;font-size:12px'>{tw_str(r['first_click'])}</td>"
        f"<td style='color:#888;font-size:12px'>{tw_str(r['last_click'])}</td></tr>"
        for r in customers
    )
    preview_section = f"""
<div class="card"><h2>📧 信件內容預覽</h2>
  <p style="color:#888;font-size:13px;margin:0 0 12px;">主旨：<b>{preview['subject']}</b></p>
  <div style="border:1px solid #eee;border-radius:8px;overflow:hidden;">
    <iframe srcdoc="{preview['html'].replace(chr(34), '&quot;')}"
            style="width:100%;height:600px;border:none;" sandbox="allow-same-origin"></iframe>
  </div></div>""" if preview else """
<div class="card"><h2>📧 信件內容預覽</h2>
  <p style="color:#aaa;font-size:14px;">尚未儲存此活動的信件預覽。</p></div>"""

    return HTMLResponse(html_head(f"活動詳情 - {name}") + f"""
<a class="back-link" href="/dashboard?pwd={pwd}">← 返回儀表板</a>
<div class="card">
  <h1>📢 {name}</h1>
  <div style="margin-top:16px;">
    <div class="stat"><div class="n">{total_clicks}</div><div class="l">總點擊數</div></div>
    <div class="stat"><div class="n">{uniq_customers}</div><div class="l">有點擊客戶數</div></div>
  </div>
</div>
{preview_section}
<div class="card"><h2>各產品點擊</h2>
<table><tr><th>Product ID</th><th>產品名稱</th><th>點擊數</th></tr>{prod_rows}</table></div>
<div class="card"><h2>點擊客戶列表（前 200 名）<span style="font-size:13px;color:#888;font-weight:normal;">（點擊 Email 查看詳情）</span></h2>
<table><tr><th>客戶 Email</th><th>點擊次數</th><th>首次點擊</th><th>最後點擊</th></tr>
{cust_rows}</table></div>
</body></html>""")

# ── Clicks API ────────────────────────────────────────────────
@app.get("/api/clicks")
async def api_clicks(pwd: str = Query(""), campaign: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403)
    if campaign:
        rows = await db_fetch("SELECT * FROM clicks WHERE campaign=$1 ORDER BY ts DESC LIMIT 5000", campaign)
    else:
        rows = await db_fetch("SELECT * FROM clicks ORDER BY ts DESC LIMIT 5000")
    for r in rows:
        r["ts"] = tw_str(r.get("ts"))
    return rows

@app.get("/health")
async def health():
    return {"status": "ok", "db": "postgresql" if USE_PG else "sqlite",
            "time": datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S +08:00")}
