# Lighto 光印樣 EDM 點擊追蹤服務

## 部署步驟（5 分鐘完成）

### 1. 建立 GitHub Repo

1. 到 https://github.com/new 建立新 repo，名稱例如 `lighto-tracker`
2. 把這個資料夾的所有檔案上傳（或用 git push）

### 2. 在 Render 部署

1. 到 https://dashboard.render.com → **New** → **Blueprint**
2. 連接你的 GitHub repo
3. Render 會自動讀取 `render.yaml`，建立：
   - Web Service（FastAPI 追蹤伺服器）
   - PostgreSQL 資料庫（免費 90 天）
4. 點 **Apply**，等待約 2 分鐘部署完成

### 3. 修改儀表板密碼（重要！）

部署成功後，到 Render → Web Service → **Environment**：
- 修改 `DASHBOARD_PASSWORD` 為你自己的密碼

### 4. 取得你的服務 URL

格式為：`https://lighto-tracker.onrender.com`（名稱可能不同）

---

## 生成追蹤連結

部署完成後，在你的電腦執行：

```bash
cd "qdm data"
python lighto-tracker/generate_tracking_links.py \
  --tracker https://lighto-tracker.onrender.com
```

輸出：`cedar_buyers_tracked.csv`（含個人化追蹤連結）

---

## 儀表板

`https://lighto-tracker.onrender.com/dashboard?pwd=你的密碼`

可看到：
- 總點擊數 / 不重複客戶
- 各產品點擊排名
- 每位客戶的點擊紀錄（知道「誰」點了「哪個產品」）

---

## 追蹤 URL 格式

```
/t?c=BASE64(email)&p=PRODUCT_ID&campaign=CAMPAIGN&content=CONTENT&to=BASE64(dest_url)
```
