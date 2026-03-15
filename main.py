"""
Lighto 光印樣 - EDM 點擊追蹤服務
部署於 Render.com

追蹤 URL 格式:
  GET /t?c=CUSTOMER_ID&p=PRODUCT_ID&campaign=CAMPAIGN&to=DEST_URL

儀表板:
  GET /dashboard  (需要 DASHBOARD_PASSWORD 環境變數)
"""

import os
import base64
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote

from fastapi import FastAPI, Request, Response, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import databases
import sqlalchemy

# ── 資料庫設定 ────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./clicks.db")
# Render 的 PostgreSQL URL 開頭是 postgres://, SQLAlchemy 需要 postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()

clicks_table = sqlalchemy.Table(
    "clicks", metadata,
    sqlalchemy.Column("id",         sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("ts",         sqlalchemy.DateTime, default=datetime.utcnow),
    sqlalchemy.Column("campaign",   sqlalchemy.String(100)),
    sqlalchemy.Column("customer_id",sqlalchemy.String(200)),
    sqlalchemy.Column("product_id", sqlalchemy.String(50)),
    sqlalchemy.Column("content",    sqlalchemy.String(100)),   # utm_content
    sqlalchemy.Column("dest_url",   sqlalchemy.Text),
    sqlalchemy.Column("ip",         sqlalchemy.String(50)),
    sqlalchemy.Column("ua",         sqlalchemy.Text),
)

engine = sqlalchemy.create_engine(
    DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://")
    if "postgresql" in DATABASE_URL
    else DATABASE_URL
)
metadata.create_all(engine)

# ── App ───────────────────────────────────────────────────────
app = FastAPI(title="Lighto EDM Tracker", docs_url=None, redoc_url=None)
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "lighto2026")


@app.on_event("startup")
async def startup():
    await database.connect()


@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()


# ── 追蹤 + 轉跳 ───────────────────────────────────────────────
@app.get("/t")
async def track_click(
    request: Request,
    c:        str = Query(...,  description="customer email (base64)"),
    p:        str = Query("",   description="product_id"),
    campaign: str = Query("",   description="campaign name"),
    content:  str = Query("",   description="utm_content"),
    to:       str = Query(...,  description="destination URL (base64)"),
):
    # decode
    try:
        customer_id = base64.urlsafe_b64decode(c + "==").decode()
    except Exception:
        customer_id = c

    try:
        dest_url = base64.urlsafe_b64decode(to + "==").decode()
    except Exception:
        dest_url = unquote(to)

    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")

    # 記錄到 DB
    try:
        await database.execute(
            clicks_table.insert().values(
                ts=datetime.now(timezone.utc),
                campaign=campaign[:100],
                customer_id=customer_id[:200],
                product_id=p[:50],
                content=content[:100],
                dest_url=dest_url[:2000],
                ip=ip[:50],
                ua=ua[:500],
            )
        )
    except Exception as e:
        print(f"DB error: {e}")

    return RedirectResponse(url=dest_url, status_code=302)


# ── 儀表板 ────────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, pwd: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        return HTMLResponse("""
        <html><body style="font-family:sans-serif;max-width:400px;margin:80px auto;text-align:center;">
        <h2>🔒 Lighto EDM 追蹤儀表板</h2>
        <form method="get">
          <input name="pwd" type="password" placeholder="密碼" style="padding:8px;width:200px;">
          <button type="submit" style="padding:8px 16px;margin-left:8px;">登入</button>
        </form></body></html>""", status_code=401)

    # 統計
    total     = await database.fetch_val("SELECT COUNT(*) FROM clicks")
    campaigns = await database.fetch_all(
        "SELECT campaign, COUNT(*) as cnt FROM clicks GROUP BY campaign ORDER BY cnt DESC"
    )
    products  = await database.fetch_all(
        "SELECT product_id, content, COUNT(*) as cnt FROM clicks GROUP BY product_id, content ORDER BY cnt DESC LIMIT 20"
    )
    recent    = await database.fetch_all(
        "SELECT ts, customer_id, product_id, content, campaign FROM clicks ORDER BY ts DESC LIMIT 50"
    )
    unique_customers = await database.fetch_val("SELECT COUNT(DISTINCT customer_id) FROM clicks")

    camp_rows = "".join(f"<tr><td>{r['campaign']}</td><td><b>{r['cnt']}</b></td></tr>" for r in campaigns)
    prod_rows = "".join(
        f"<tr><td>{r['product_id']}</td><td>{r['content']}</td><td><b>{r['cnt']}</b></td></tr>"
        for r in products
    )
    rec_rows  = "".join(
        f"<tr><td style='color:#888;font-size:12px'>{str(r['ts'])[:16]}</td>"
        f"<td>{r['customer_id']}</td><td>{r['product_id']}</td>"
        f"<td>{r['content']}</td><td>{r['campaign']}</td></tr>"
        for r in recent
    )

    return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Lighto EDM 追蹤儀表板</title>
<style>
  body{{font-family:'PingFang TC',sans-serif;background:#f5f5f0;margin:0;padding:24px;}}
  .card{{background:#fff;border-radius:12px;padding:24px;margin-bottom:20px;}}
  h1{{font-size:22px;margin:0 0 4px;}} h2{{font-size:16px;color:#444;margin:0 0 16px;}}
  .stat{{display:inline-block;background:#1a1a1a;color:#fff;border-radius:8px;
         padding:16px 28px;margin-right:12px;text-align:center;}}
  .stat .n{{font-size:32px;font-weight:700;}}
  .stat .l{{font-size:12px;color:#aaa;margin-top:4px;}}
  table{{width:100%;border-collapse:collapse;font-size:14px;}}
  th{{background:#f0f0f0;padding:8px;text-align:left;}}
  td{{padding:7px 8px;border-bottom:1px solid #f0f0f0;}}
  a{{color:#1a1a1a;}}
</style></head>
<body>
<div class="card">
  <h1>Lighto 光印樣 EDM 追蹤儀表板</h1>
  <p style="color:#888;margin:0 0 20px;">資料即時更新 · <a href="/api/clicks?pwd={pwd}">JSON API</a> · <a href="/dashboard?pwd={pwd}">重新整理</a></p>
  <div>
    <div class="stat"><div class="n">{total}</div><div class="l">總點擊數</div></div>
    <div class="stat"><div class="n">{unique_customers}</div><div class="l">不重複客戶</div></div>
  </div>
</div>

<div class="card">
  <h2>各廣告活動</h2>
  <table><tr><th>Campaign</th><th>點擊數</th></tr>{camp_rows}</table>
</div>

<div class="card">
  <h2>各產品點擊</h2>
  <table><tr><th>Product ID</th><th>Content</th><th>點擊數</th></tr>{prod_rows}</table>
</div>

<div class="card">
  <h2>最近 50 筆點擊</h2>
  <table><tr><th>時間</th><th>客戶 Email</th><th>產品</th><th>內容</th><th>活動</th></tr>
  {rec_rows}</table>
</div>
</body></html>""")


# ── JSON API ──────────────────────────────────────────────────
@app.get("/api/clicks")
async def api_clicks(pwd: str = Query(""), campaign: str = Query("")):
    if pwd != DASHBOARD_PASSWORD:
        raise HTTPException(403, "Unauthorized")
    q = "SELECT * FROM clicks"
    if campaign:
        q += f" WHERE campaign = '{campaign}'"
    q += " ORDER BY ts DESC LIMIT 5000"
    rows = await database.fetch_all(q)
    return [dict(r) for r in rows]


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}
