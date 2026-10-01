# 淡江咖啡館

<img src="static/images/tankang-cafe-logo.png" alt="淡江咖啡館標誌" width="160">

咖啡館網站專案，使用繁體中文，包含黑金版型、玻璃按鈕、首頁輪播、菜單搜尋與快速預覽。支援手機、平板與桌面版面。

## 線上展示

展示網址列在此 repository 首頁的 **About → Website**。

GitHub Pages 提供首頁、菜單、商品介紹及示範消息。不提供會員登入、寄信、訂位提交或後台。價格、消息、店內照片為展示用內容，圖片包含 AI 生成素材，不代表實際店址或供應狀況。

完整 Flask 原始碼也保留在此專案；需要執行後端時，請自行配置支援 Python 的主機。GitHub Pages 不會執行 Python，也沒有資料庫。

## 本機展示

需要 Python 3.11 以上。執行：

```sh
python -m pip install -r requirements.txt
python build_pages.py
python -m http.server --directory _site 8080
```

在瀏覽器開啟 `http://localhost:8080`。`build_pages.py` 不會讀取 `.env`、資料庫、後台編輯內容或上傳檔案，只使用 `app.py` 中的預設公開內容。

建置時預設輸出到 `_site/`。為避免誤刪檔案，已存在的輸出資料夾不會覆寫。重新建置可指定不同路徑：

```sh
python build_pages.py --output _site/preview-v2
```

若放在 GitHub 專案路徑下，可設定前綴：

```sh
python build_pages.py --base-path /tankang-cafe --output _site/github-preview
```

## 自動部署

`.github/workflows/pages.yml` 會在推送至 `main` 時執行測試、建置壓縮與混淆資源，再將靜態展示頁部署到 GitHub Pages。只發布 `_site/`，不發布原始碼、設定檔或資料庫。

複製到自己的 repository 後，在 **Settings → Pages → Build and deployment** 選擇 **GitHub Actions**。部署時會自動使用 GitHub Pages 提供的網站路徑，支援專案路徑或網站根目錄。

## 完整 Flask 後端

1. 將 `.env.example` 複製為 `.env`，只在自己的電腦或部署主機保存。
2. 設定 `SECRET_KEY`、`ADMIN_USERNAME`、`ADMIN_PASSWORD`；正式環境使用至少 12 碼、含大小寫及數字的管理員密碼，並設定 `APP_ENV=production`。
3. 寄信、Turnstile 及 Cloudflare API 設定僅在需要使用時填入。正式環境應透過 HTTPS 並配置正確的代理與允許網域。
4. 安裝 Python 依賴後執行 `python scripts/serve_backend.py`。

可在本機產生隨機 session key：

```sh
python -c "import secrets; print(secrets.token_hex(32))"
```

預設不建立可登入的示範帳號；設定管理員環境變數後才建立管理員。測試會員須明確啟用 `ENABLE_DEMO_ACCOUNT=true`，且只在開發環境有效，不要在公開服務啟用。請先配置寄信服務，再測試會員註冊及 Email 認證。

完整後端保留會員、Email 認證、密碼重設、訂位、留言、菜單與會員管理，以及安全事件監控。`data/` 會在執行後端時建立，本專案不附任何既有會員或營運資料。

## 資料位置

| 路徑 | 內容 |
| --- | --- |
| `app.py` | Flask 路由、權限、資料庫遷移、預設菜單與品牌文案 |
| `templates/` | 公開頁面及後台模板；Pages 只匯出白名單公開頁 |
| `static/css/style.css` | 響應式版面及按鈕樣式 |
| `static/js/app.js` | 輪播、動畫、搜尋、分類及快速預覽 |
| `static/js/editor.js` | 後台文案編輯；不發布到 Pages |
| `static/images/` | 已核對的公開品牌與示範圖片 |
| `.env.example` | 空白設定範本，沒有真實金鑰或帳密 |
| `build_pages.py` | 隔離的靜態展示匯出工具 |
| `build_assets.py` | CSS 壓縮、JS 壓縮及混淆 |

## 測試與建置

```sh
python -m unittest discover -s tests -v
python -m py_compile app.py build_pages.py build_assets.py render_templates.py
npm ci
python build_assets.py
```

混淆只增加閱讀成本，不是加密，也不能讓瀏覽器裡的公開內容無法取得。詳見 [SECURITY.md](SECURITY.md)。

## 素材與授權

公開程式碼不等於授予任意再利用授權。本專案未指定開源授權；品牌標誌、照片與生成素材也不另行授權。使用前請取得權利人的許可。
