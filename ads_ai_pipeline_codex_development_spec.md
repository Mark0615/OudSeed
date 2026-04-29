# Ads AI Pipeline × Codex 開發規格書 v0.1

## 0. 文件目的

本文件是為了讓開發者可以和 Codex / AI coding assistant 一起開發一套廣告數據自動化管線。

此專案初期目標不是完整複製 Supermetrics / Windsor.ai，而是先建立一套可自用的 MVP：

- 自動從 Google Ads、Meta Ads、LINE Ads 擷取廣告數據
- 將資料寫入 BigQuery
- 讓 Looker Studio / Google Sheet 可以取用資料
- 後續加入 AI 自動週報 / 月報摘要
- 保留未來 SaaS 化、多使用者、多客戶、多廣告帳號擴充彈性

---

# 1. 專案名稱

GitHub repository：

```text
Mark0615/OudSeed
```

專案內部代號 / Python package 可暫用：

```text
ads-ai-pipeline
```

未來產品化可再改名，例如：

```text
AdPilot AI
Performance AI Analyst
Marketing Data Copilot
```

---

# 2. 專案背景

目前使用者投放多個廣告平台，包括：

- Google Ads
- Meta Ads / Facebook Ads
- LINE Ads

目前使用 Windsor.ai / Supermetrics 類型工具將廣告數據同步至 Google Sheet 或 Looker Studio，但第三方工具訂閱費用較高，且功能多半偏向「資料搬運」。

本專案希望自建一套輕量化廣告數據同步系統，初期自用，後續提供給身邊廣告投手、行銷顧問或小型代理商使用。

長期差異化方向：

> 不只同步資料，而是成為廣告投手的 AI Performance Analyst。

---

# 3. 產品目標

## 3.1 MVP 目標

MVP 階段只追求核心流程跑通：

```text
Ads APIs → BigQuery → Looker Studio / Google Sheet → AI Summary
```

MVP 必須做到：

- 每天自動同步廣告數據
- 支援 Google Ads、Meta Ads、LINE Ads 三大平台
- 資料寫入 BigQuery
- 支援資料回補，避免轉換延遲造成數據不完整
- 支援 Looker Studio 讀取 BigQuery 做 dashboard
- 支援基本同步 log
- 支援每週 AI 摘要草稿

## 3.2 中期目標

提供給 1–3 位廣告投放夥伴內測：

- 支援多 client
- 支援多 workspace
- 支援多 ad account
- 提供簡易設定檔或後台管理
- 提供每週 / 每月 AI 報告

## 3.3 長期 SaaS 目標

- 使用者註冊 / 登入
- OAuth 授權連接廣告帳號
- 使用者可選擇資料目的地
- 自動產出報表與 AI 建議
- 訂閱制收費
- 多租戶資料隔離

---

# 4. 產品定位

本產品不是單純 ETL 工具，而是：

> 廣告數據整合 + AI 成效分析助理。

| 價值 | 說明 |
|---|---|
| 自動化 | 減少每日手動下載報表 |
| 數據整合 | 統一 Google / Meta / LINE Ads 數據 |
| 分析效率 | 快速找出異常、亮點與優化方向 |
| 客戶溝通 | 自動產出可給客戶看的週報 / 月報文字 |
| SaaS 彈性 | 未來可讓夥伴或客戶使用 |

---

# 5. MVP 功能範圍

## 5.1 MVP 必做功能

| 模組 | 功能 | 說明 |
|---|---|---|
| Connector | LINE Ads API | 擷取 LINE Ads 報表資料 |
| Connector | Google Ads API | 擷取 Google Ads 報表資料 |
| Connector | Meta Ads API | 擷取 Meta Ads Insights 資料 |
| Warehouse | BigQuery Raw Tables | 儲存各平台原始資料 |
| Warehouse | BigQuery Unified Table | 儲存標準化後跨平台資料 |
| Scheduler | Daily Sync | 每日自動同步 |
| Backfill | Recent Days Backfill | 每次回補最近 7 天資料 |
| Logging | Sync Log | 紀錄成功 / 失敗 / 錯誤原因 |
| Dashboard | Looker Studio | 透過 BigQuery 建立 dashboard |
| Export | Google Sheet | 可選擇輸出 summary 給非技術使用者 |
| AI | Weekly Summary | 每週產出中文成效摘要與優化建議 |

## 5.2 MVP 暫不做功能

| 功能 | 暫不做原因 |
|---|---|
| SaaS 使用者註冊 | 初期自用，先不用完整帳號系統 |
| 前端 OAuth 授權流程 | 初期可以手動設定 token |
| 付款系統 | 尚未商業化 |
| 自製 Looker Studio Connector | 先用 BigQuery connector 即可 |
| 多 destination 管理 UI | 初期 destination 固定為 BigQuery / Google Sheet |
| 大量 data source | 初期只做 Google Ads、Meta Ads、LINE Ads |

---

# 6. 技術架構

## 6.1 MVP 系統架構

```text
Google Ads API
Meta Marketing API
LINE Ads API
        ↓
Python Connector Layer
        ↓
Normalize / Transform Layer
        ↓
BigQuery Raw Tables
        ↓
BigQuery Unified Tables
        ↓
Looker Studio / Google Sheet
        ↓
AI Summary Generator
        ↓
Weekly / Monthly Report
```

## 6.2 建議技術選型

| 模組 | 技術 |
|---|---|
| Programming Language | Python 3.11+ |
| API connectors | Python requests / official SDKs |
| Data warehouse | BigQuery |
| Cloud runtime | Cloud Run Jobs |
| Scheduler | Cloud Scheduler |
| Secrets | Google Secret Manager |
| Dashboard | Looker Studio |
| Sheet export | Google Sheets API |
| AI summary | OpenAI API 或 Gemini API |
| Repo | GitHub |
| AI coding assistant | Codex |

---

# 7. BigQuery 資料設計

## 7.1 Dataset

```text
ads_pipeline
```

## 7.2 Tables

| Table | 說明 |
|---|---|
| raw_google_ads_daily | Google Ads 原始資料 |
| raw_meta_ads_daily | Meta Ads 原始資料 |
| raw_line_ads_daily | LINE Ads 原始資料 |
| unified_ads_daily | 跨平台標準化資料 |
| sync_logs | 每次同步紀錄 |
| weekly_performance_summary | AI 週報用彙總資料 |
| ai_report_logs | AI 報告產出紀錄 |

---

# 8. 資料欄位擷取策略

## 8.1 MVP 欄位原則

MVP 階段採用「Raw 完整保留、Unified 精簡標準化」的雙層設計。

```text
Raw Tables：盡可能保留平台原始回傳資料，方便未來重算與補欄位
Unified Table：只放跨平台常用且可標準化的核心欄位，方便 Looker Studio / AI summary 使用
```

## 8.2 Raw Tables 欄位策略

每個平台的 raw table 應盡量保存該平台 API 報表回傳的原始欄位。

MVP 原則：

- 優先抓取該平台報表 API 的常用預設報表欄位
- 若 API 不支援「一次抓全部欄位」，則使用一組可維護的 default fields list
- 所有 API response 需保留在 `raw_payload` 欄位中，格式為 JSON / STRING
- 後續若需要新增欄位，應優先從 raw_payload 或重新回補 raw table 處理
- 不應只保存 unified schema 欄位，避免未來要補欄位時無法回推

建議 raw table 至少包含：

| 欄位 | 型別 | 說明 |
|---|---|---|
| date | DATE | 報表日期 |
| workspace_id | STRING | 工作區 ID |
| client_id | STRING | 客戶 ID |
| platform | STRING | 平台 |
| account_id | STRING | 廣告帳號 ID |
| report_level | STRING | campaign / ad_group / ad |
| attribution_setting | STRING | 使用的平台預設歸因設定，MVP 不自訂 |
| timezone_setting | STRING | 使用的平台帳號預設時區，MVP 不自訂 |
| raw_payload | JSON / STRING | 平台 API 原始回傳資料 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 更新時間 |

## 8.3 Unified Table 欄位策略

Unified table 不追求保存所有平台欄位，而是保存三個平台都容易對齊、且適合 dashboard / AI summary 使用的核心欄位。

若未來需要加入平台獨有欄位，例如：

- Google Ads keyword / search term / bidding strategy
- Meta Ads reach / frequency / purchase_roas / action breakdowns
- LINE Ads 特定 conversion 或 audience 欄位

應優先新增到 raw table 或新增 platform-specific mart table，不建議全部塞進 unified table。

## 8.4 歸因設定原則

MVP 階段不主動覆寫各平台歸因設定。

原則：

- Google Ads：使用 Google Ads 帳號 / conversion action 目前預設歸因與報表口徑
- Meta Ads：使用 Meta Ads Insights API 預設歸因設定，不主動指定 attribution window
- LINE Ads：使用 LINE Ads 報表 API 預設歸因與報表口徑

需在 raw table 或 sync log 中記錄：

```text
attribution_setting = platform_default
```

若未來要支援自訂歸因，例如 1-day click、7-day click、1-day view，應新增 config 設定，不要直接改寫既有預設邏輯。

## 8.5 時區設定原則

MVP 階段不主動轉換平台報表時區。

原則：

- 報表日期依照各廣告平台 / 廣告帳號的預設時區
- 系統排程時間使用 Asia/Taipei
- BigQuery 中的 `date` 欄位代表平台報表日期，不代表 Cloud Run 執行日期
- 需在 raw table 或 sync log 中記錄：

```text
timezone_setting = platform_account_default
scheduler_timezone = Asia/Taipei
```

注意：若同一個 workspace 中有不同時區的廣告帳號，dashboard 需清楚標示 date 是平台帳號時區下的日期。

---

# 9. Unified Table Schema

Table name:

```text
unified_ads_daily
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| date | DATE | 報表日期 |
| workspace_id | STRING | 工作區 ID，MVP 固定為 mark_internal |
| client_id | STRING | 客戶 ID，MVP 可固定為 demo_client_001 |
| platform | STRING | google_ads / meta_ads / line_ads |
| account_id | STRING | 廣告帳號 ID |
| account_name | STRING | 廣告帳號名稱 |
| campaign_id | STRING | Campaign ID |
| campaign_name | STRING | Campaign 名稱 |
| ad_group_id | STRING | Google ad group / Meta ad set / LINE ad group ID |
| ad_group_name | STRING | Ad group / ad set 名稱 |
| ad_id | STRING | Ad ID |
| ad_name | STRING | Ad 名稱 |
| impressions | INTEGER | 曝光數 |
| clicks | INTEGER | 點擊數 |
| spend | FLOAT | 花費 |
| conversions | FLOAT | 轉換數 |
| conversion_value | FLOAT | 轉換價值 |
| ctr | FLOAT | 點擊率 |
| cpc | FLOAT | 每次點擊成本 |
| cpm | FLOAT | 每千次曝光成本 |
| cpa | FLOAT | 每次轉換成本 |
| roas | FLOAT | 廣告投資報酬率 |
| currency | STRING | 幣別 |
| source_updated_at | TIMESTAMP | 來源資料更新時間 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 更新時間 |

## 8.1 去重 Key

```text
date + platform + account_id + campaign_id + ad_group_id + ad_id
```

如果某平台某層級沒有 ad_id，則允許為 null，但轉換時需保持 key 邏輯穩定。

---

# 9. 同步流程

## 9.1 每日同步流程

```text
1. Cloud Scheduler 觸發 Cloud Run Job
2. Python main.py 啟動
3. 讀取 config/clients.yaml
4. 依照 client / platform / account_id 執行 connector
5. 抓取昨天 + 最近 7 天資料
6. 寫入 raw table
7. 執行 normalize transform
8. delete + insert 到 unified table
9. 寫入 sync_logs
10. 若有 Google Sheet destination，輸出 summary
11. 若為週報日，執行 AI weekly summary
```

## 9.2 建議排程

| 任務 | 時間 |
|---|---|
| Daily ads sync | 每日台灣時間 04:00 |
| Weekly AI report | 每週一台灣時間 09:00 |
| Monthly AI report | 每月 1 日台灣時間 09:00，後續再做 |

## 9.3 回補邏輯

每次執行同步時，預設同步：

```text
今天往前推 7 天 ~ 昨天
```

寫入方式：

```text
Delete date range from target table → Insert latest data
```

---

# 10. Sync Log Schema

Table name:

```text
sync_logs
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| sync_id | STRING | 同步任務 ID |
| workspace_id | STRING | 工作區 ID |
| client_id | STRING | 客戶 ID |
| platform | STRING | 平台 |
| account_id | STRING | 廣告帳號 ID |
| sync_start_date | DATE | 同步資料起始日 |
| sync_end_date | DATE | 同步資料結束日 |
| status | STRING | success / failed / partial_success |
| rows_fetched | INTEGER | API 回傳筆數 |
| rows_inserted | INTEGER | 寫入筆數 |
| error_message | STRING | 錯誤訊息 |
| started_at | TIMESTAMP | 任務開始時間 |
| finished_at | TIMESTAMP | 任務結束時間 |

---

# 11. Connector 規格

## 11.1 Connector 共用介面

所有平台 connector 應盡量遵守同一個 interface。

```python
class BaseAdsConnector:
    def fetch_daily_report(self, account_id: str, start_date: str, end_date: str) -> list[dict]:
        pass
```

每個 connector 回傳 `list[dict]`，後續交給 normalize function 處理。

## 11.2 LINE Ads Connector

檔案：

```text
src/connectors/line_ads.py
```

功能：

- 使用 LINE Ads API 取得廣告報表
- 支援多 account_id
- 支援 date range
- 支援 campaign / ad group / ad 維度
- 回傳標準 list[dict]

需要注意：

- HMAC 簽章
- API request path 與 body 要與簽章一致
- 每個帳號失敗不能中斷全部流程

## 11.3 Google Ads Connector

檔案：

```text
src/connectors/google_ads.py
```

功能：

- 使用 Google Ads API 查詢報表
- 使用 GAQL 查詢 campaign / ad group / ad 層級資料
- 支援 customer_id / login_customer_id
- 回傳 list[dict]

## 11.4 Meta Ads Connector

檔案：

```text
src/connectors/meta_ads.py
```

功能：

- 使用 Meta Marketing API Ads Insights
- 支援 campaign / adset / ad level
- 支援 date range
- 回傳 list[dict]

注意：

- attribution window 可能導致數字與後台不同
- token 期限與權限要特別處理
- 初期可以先使用 long-lived token，自用即可

---

# 12. Normalize / Transform 規格

每個平台需有對應 normalize function：

```text
src/transforms/normalize_line.py
src/transforms/normalize_google.py
src/transforms/normalize_meta.py
```

目標：

- 將各平台欄位轉成 unified schema
- 統一數字型別
- 統一日期格式
- 統一 platform 命名
- 計算 ctr / cpc / cpm / cpa / roas

## 12.1 計算邏輯

| 指標 | 計算方式 |
|---|---|
| ctr | clicks / impressions |
| cpc | spend / clicks |
| cpm | spend / impressions * 1000 |
| cpa | spend / conversions |
| roas | conversion_value / spend |

遇到分母為 0 時，回傳 null，不要報錯。

---

# 13. AI Weekly Report 規格

## 13.1 原則

AI 不直接分析 raw data。

必須先由 BigQuery SQL 產生 summary table，再把 summary 給 AI 產生文字。

原因：

- 降低 AI 幻覺
- 確保數字由 SQL 計算
- 讓 AI 專注於解讀與表達

## 13.2 AI 週報輸出格式

AI 週報必須包含：

1. 本週整體成效摘要
2. 主要成長亮點
3. 主要風險與異常
4. 平台別觀察
5. Campaign 層級觀察
6. 建議優化行動
7. 下週觀察重點

---

# 14. Repo 結構

建議專案結構：

```text
ads-ai-pipeline/
  README.md
  requirements.txt
  .env.example
  .gitignore
  config/
    clients.example.yaml
  src/
    main.py
    connectors/
      __init__.py
      base.py
      line_ads.py
      google_ads.py
      meta_ads.py
    destinations/
      __init__.py
      bigquery.py
      google_sheets.py
    transforms/
      __init__.py
      normalize_line.py
      normalize_google.py
      normalize_meta.py
    ai/
      __init__.py
      weekly_report.py
      prompt_templates.py
    utils/
      __init__.py
      date_utils.py
      logger.py
      secret_manager.py
      config_loader.py
  sql/
    create_tables.sql
    weekly_summary.sql
  tests/
    test_normalize_line.py
    test_normalize_google.py
    test_normalize_meta.py
  deploy/
    Dockerfile
    cloudbuild.yaml
  docs/
    development_spec.md
```

---

# 15. Coding Style 要求

Codex 產出的程式碼需符合：

- Python 3.11+
- 使用 type hints
- 使用清楚 function / class 命名
- 不要把 token 寫死在程式碼中
- 所有 secrets 從環境變數或 Secret Manager 讀取
- connector、transform、destination 分層清楚
- BigQuery 寫入邏輯要能重複執行，不產生重複資料
- 錯誤要寫入 sync_logs
- 每個主要 function 要有簡短 docstring
- 優先寫可讀性高的程式，不要過度抽象

---

# 16. 環境變數設計

`.env.example`

```bash
# GCP
GCP_PROJECT_ID=your-gcp-project-id
BIGQUERY_DATASET=ads_pipeline
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json

# LINE Ads
LINE_ADS_ACCESS_KEY=your-line-access-key
LINE_ADS_SECRET_KEY=your-line-secret-key

# Google Ads
GOOGLE_ADS_DEVELOPER_TOKEN=your-developer-token
GOOGLE_ADS_CLIENT_ID=your-client-id
GOOGLE_ADS_CLIENT_SECRET=your-client-secret
GOOGLE_ADS_REFRESH_TOKEN=your-refresh-token
GOOGLE_ADS_LOGIN_CUSTOMER_ID=your-login-customer-id

# Meta Ads
META_APP_ID=your-meta-app-id
META_APP_SECRET=your-meta-app-secret
META_ACCESS_TOKEN=your-meta-access-token

# AI
OPENAI_API_KEY=your-openai-api-key
```

---

# 17. Codex 開發流程建議

每次給 Codex 的任務不要太大，建議一次只做一個模組。

## 建議流程

1. 先建立 repo skeleton
2. 建立 BigQuery table SQL
3. 建立 config loader
4. 建立 BigQuery destination
5. 建立 LINE Ads connector
6. 建立 LINE normalize
7. 建立 main sync flow
8. 本機測試 LINE → BigQuery
9. 再加入 Google Ads
10. 再加入 Meta Ads
11. 最後加入 AI weekly report

---

# 18. Codex Task Prompts

以下 prompt 可以直接貼給 Codex 使用。

## Task 1：建立專案骨架

```text
Create the initial Python project structure for an ads data pipeline.

Requirements:
- Use Python 3.11+
- Create folders: src/connectors, src/destinations, src/transforms, src/ai, src/utils, sql, tests, config, deploy, docs
- Add __init__.py where needed
- Create README.md
- Create requirements.txt
- Create .env.example
- Create .gitignore
- Do not implement real API logic yet
- Add placeholder files for:
  - src/main.py
  - src/connectors/base.py
  - src/connectors/line_ads.py
  - src/connectors/google_ads.py
  - src/connectors/meta_ads.py
  - src/destinations/bigquery.py
  - src/destinations/google_sheets.py
  - src/transforms/normalize_line.py
  - src/transforms/normalize_google.py
  - src/transforms/normalize_meta.py
  - src/ai/weekly_report.py
  - src/utils/config_loader.py
  - src/utils/date_utils.py
  - src/utils/logger.py

Acceptance criteria:
- Project imports should not fail
- README explains the purpose of the project
- requirements.txt includes basic packages for requests, google-cloud-bigquery, pyyaml, python-dotenv
```

## Task 2：建立 BigQuery SQL schema

```text
Create sql/create_tables.sql for BigQuery.

Requirements:
- Dataset name should be parameterized as ads_pipeline in comments
- Create tables:
  - raw_google_ads_daily
  - raw_meta_ads_daily
  - raw_line_ads_daily
  - unified_ads_daily
  - sync_logs
  - weekly_performance_summary
  - ai_report_logs
- unified_ads_daily should include fields:
  date, workspace_id, client_id, platform, account_id, account_name,
  campaign_id, campaign_name, ad_group_id, ad_group_name,
  ad_id, ad_name, impressions, clicks, spend, conversions,
  conversion_value, ctr, cpc, cpm, cpa, roas, currency,
  source_updated_at, created_at, updated_at
- sync_logs should include sync_id, workspace_id, client_id, platform, account_id,
  sync_start_date, sync_end_date, status, rows_fetched, rows_inserted,
  error_message, started_at, finished_at
- Use BigQuery Standard SQL
- Add partitioning by date for daily tables where appropriate
- Add clustering by workspace_id, client_id, platform, account_id where appropriate

Acceptance criteria:
- SQL is valid BigQuery Standard SQL
- Tables can be created manually from the script
```

## Task 3：建立 config loader

```text
Implement src/utils/config_loader.py.

Requirements:
- Load YAML config from config/clients.yaml
- Validate required fields:
  - workspace_id
  - clients
  - client_id
  - platforms
  - destinations
- Provide a function load_config(path: str) -> dict
- Raise clear ValueError messages when required fields are missing
- Add config/clients.example.yaml with one demo client and platforms:
  - line_ads
  - google_ads
  - meta_ads
- Do not include real tokens or real account IDs

Acceptance criteria:
- Unit tests pass for valid and invalid YAML
- Missing required fields raise clear errors
```

## Task 4：建立 BigQuery destination module

```text
Implement src/destinations/bigquery.py.

Requirements:
- Use google-cloud-bigquery
- Create a BigQueryDestination class
- Constructor accepts project_id and dataset_id
- Implement methods:
  - insert_rows(table_name: str, rows: list[dict]) -> int
  - delete_date_range(table_name: str, start_date: str, end_date: str, filters: dict) -> None
  - replace_date_range(table_name: str, rows: list[dict], start_date: str, end_date: str, filters: dict) -> int
- replace_date_range should delete matching date range and then insert rows
- Add safe handling when rows is empty
- Log useful messages

Acceptance criteria:
- Methods have type hints and docstrings
- Empty rows do not crash
- BigQuery errors are raised with readable messages
```

## Task 5：建立日期工具

```text
Implement src/utils/date_utils.py.

Requirements:
- Add function get_default_sync_range(days_back: int = 7, timezone: str = "Asia/Taipei") -> tuple[str, str]
- The function should return start_date and end_date as YYYY-MM-DD
- end_date should be yesterday in the given timezone
- start_date should be days_back days before end_date
- Add helper function today_in_timezone(timezone: str) -> date

Acceptance criteria:
- Works correctly for Asia/Taipei timezone
- Includes unit tests
```

## Task 6：建立 Base Connector

```text
Implement src/connectors/base.py.

Requirements:
- Create abstract BaseAdsConnector class
- Define abstract method:
  fetch_daily_report(self, account_id: str, start_date: str, end_date: str) -> list[dict]
- Add simple connector metadata fields:
  platform_name: str
- Use abc.ABC and abstractmethod

Acceptance criteria:
- Other connector classes can inherit from it
- Type hints are included
```

## Task 7：建立 LINE Ads Connector

```text
Implement src/connectors/line_ads.py.

Requirements:
- Create LineAdsConnector that inherits BaseAdsConnector
- Constructor accepts access_key and secret_key
- Implement HMAC signature helper method
- Implement fetch_daily_report(account_id, start_date, end_date)
- Keep API endpoint and payload easy to modify
- Return list[dict]
- Handle non-200 responses with readable exceptions
- Do not hardcode credentials
- Add clear comments where API endpoint details may need adjustment based on LINE Ads API docs

Acceptance criteria:
- Code is modular and testable
- HMAC signature logic is isolated
- API errors include status code and response text
```

## Task 8：建立 LINE normalize function

```text
Implement src/transforms/normalize_line.py.

Requirements:
- Create function normalize_line_ads_rows(raw_rows: list[dict], context: dict) -> list[dict]
- Convert LINE Ads raw rows into unified_ads_daily schema
- Required context fields:
  - workspace_id
  - client_id
  - account_id
  - account_name optional
- Calculate ctr, cpc, cpm, cpa, roas
- If denominator is 0, return None for calculated metric
- Ensure numeric fields are converted to int or float
- Add created_at and updated_at timestamps

Acceptance criteria:
- Unit tests cover normal rows and zero denominator cases
- Output keys match unified_ads_daily schema
```

## Task 9：建立 main sync flow for LINE Ads

```text
Implement src/main.py for the first working MVP sync flow using LINE Ads only.

Requirements:
- Load config from config/clients.yaml
- Determine sync date range using get_default_sync_range(days_back=7)
- For each enabled client and line_ads account_id:
  - Fetch raw rows from LineAdsConnector
  - Write rows to raw_line_ads_daily
  - Normalize rows
  - Replace matching date range in unified_ads_daily
  - Write sync_logs
- Continue processing other accounts even if one account fails
- Print useful logs to console
- Read credentials from environment variables

Acceptance criteria:
- Running python src/main.py triggers LINE Ads sync
- Failed account does not stop all accounts
- sync_logs records success or failure
```

## Task 10：加入 Google Ads Connector

```text
Implement src/connectors/google_ads.py and src/transforms/normalize_google.py.

Requirements:
- Use google-ads Python client library if appropriate
- Support customer_id and optional login_customer_id
- Query daily campaign / ad group / ad metrics using GAQL
- Fetch fields:
  date, customer id/name, campaign id/name, ad group id/name,
  ad id/name, impressions, clicks, cost, conversions, conversion value
- Convert cost micros to normal currency value
- Normalize output to unified_ads_daily schema
- Add error handling for Google Ads API errors

Acceptance criteria:
- Connector returns list[dict]
- Normalize function outputs unified schema
- Zero denominator cases handled
```

## Task 11：加入 Meta Ads Connector

```text
Implement src/connectors/meta_ads.py and src/transforms/normalize_meta.py.

Requirements:
- Use requests or Meta Business SDK
- Support ad_account_id like act_xxxxx
- Fetch Ads Insights at ad level
- Fetch fields:
  date_start, account_id, account_name, campaign_id, campaign_name,
  adset_id, adset_name, ad_id, ad_name, impressions, clicks, spend,
  actions, action_values
- Parse conversions and conversion_value from actions/action_values with configurable action_type
- Normalize output to unified_ads_daily schema
- Add error handling for API errors

Acceptance criteria:
- Connector returns list[dict]
- Normalize function outputs unified schema
- Conversion parsing is configurable
```

## Task 12：建立 weekly summary SQL

```text
Create sql/weekly_summary.sql.

Requirements:
- Read from unified_ads_daily
- Aggregate by week, workspace_id, client_id, platform, campaign_id, campaign_name
- Calculate spend, impressions, clicks, conversions, conversion_value, ctr, cpc, cpa, roas
- Calculate WoW metrics by comparing with previous week:
  spend_wow, conversions_wow, cpa_wow, roas_wow
- Use BigQuery Standard SQL
- Avoid division by zero using SAFE_DIVIDE

Acceptance criteria:
- SQL can run in BigQuery
- Output fields match weekly_performance_summary schema
```

## Task 13：建立 AI weekly report generator

```text
Implement src/ai/weekly_report.py.

Requirements:
- Read weekly_performance_summary data from BigQuery
- Build a structured prompt in Traditional Chinese
- AI output should include:
  1. 本週整體成效摘要
  2. 主要成長亮點
  3. 主要風險與異常
  4. 平台別觀察
  5. Campaign 層級觀察
  6. 建議優化行動
  7. 下週觀察重點
- The AI should not invent numbers not present in the input
- Save report output to ai_report_logs

Acceptance criteria:
- Report is generated in Traditional Chinese
- Numeric claims are based only on provided summary data
- Report is saved with timestamp, workspace_id, client_id, week_start_date, week_end_date
```

## Task 14：建立 Dockerfile for Cloud Run Job

```text
Create deploy/Dockerfile for Cloud Run Job deployment.

Requirements:
- Use Python 3.11 slim base image
- Install requirements.txt
- Copy project files
- Set working directory
- Default command should run python -m src.main or python src/main.py
- Do not include secrets in image

Acceptance criteria:
- Docker image builds locally
- Container can run main sync script
```

---

# 19. 開發順序建議

強烈建議按照以下順序，不要一次叫 Codex 做完整系統。

| 順序 | 任務 | 原因 |
|---:|---|---|
| 1 | Repo skeleton | 先有乾淨結構 |
| 2 | BigQuery schema | 先定資料模型 |
| 3 | Config loader | 之後多 client 會用到 |
| 4 | Date utils | 每日同步必備 |
| 5 | BigQuery destination | 先確定能寫資料 |
| 6 | Base connector | 統一架構 |
| 7 | LINE connector | 你最熟，最快跑通 |
| 8 | LINE normalize | 先完成一條管線 |
| 9 | main LINE sync | 第一個可運作 MVP |
| 10 | Google Ads connector | 第二個平台 |
| 11 | Meta Ads connector | 第三個平台 |
| 12 | Weekly summary SQL | 報告資料基礎 |
| 13 | AI weekly report | 加入差異化功能 |
| 14 | Cloud Run deployment | 自動化部署 |

---

# 20. MVP 驗收標準

| 項目 | 驗收標準 |
|---|---|
| LINE Ads 同步 | 可成功抓取指定帳號資料並寫入 BigQuery |
| Google Ads 同步 | 可成功抓取指定帳號資料並寫入 BigQuery |
| Meta Ads 同步 | 可成功抓取指定帳號資料並寫入 BigQuery |
| 每日排程 | Cloud Scheduler 可每日觸發 |
| 回補邏輯 | 每次同步最近 7 天且不產生重複資料 |
| Unified Table | 三平台資料可統一查詢 |
| Sync Log | 每次同步成功 / 失敗皆有紀錄 |
| Looker Studio | 可透過 BigQuery 建 dashboard |
| AI Weekly Report | 可產出繁體中文週報草稿 |
| Secrets | 程式碼中沒有硬編碼 token |

---

# 21. 未來 SaaS 化預留設計

即使 MVP 是自用，以下設計要先保留：

| 設計 | 原因 |
|---|---|
| workspace_id | 未來多公司 / 多使用者 |
| client_id | 一個 workspace 可管理多客戶 |
| platform | 多平台擴充 |
| account_id | 多廣告帳號 |
| sync_logs | 未來顯示同步狀態 |
| config file | 未來可改成 database settings |
| connector interface | 未來新增 TikTok / GA4 / Shopify |
| raw + unified 分層 | 未來可重算資料 |

---

# 22. 不建議 Codex 一開始做的事

| 不建議項目 | 原因 |
|---|---|
| 完整 SaaS 登入系統 | 太早，會分散焦點 |
| 付款系統 | 還沒驗證產品價值 |
| 自製 Looker Studio Connector | 複雜度高，BigQuery connector 足夠 |
| 一次做三平台完整串接 | debug 難度高 |
| 複雜前端 UI | 初期用 config file 即可 |
| 自動建立客戶報表模板 | 等資料穩定後再做 |

---

# 23. 給 Codex 的總指令原則

每次要求 Codex 修改前，應明確提供：

1. 目前要做哪個 task
2. 要修改哪些檔案
3. 不要碰哪些檔案
4. 輸入 / 輸出格式
5. 驗收標準
6. 是否需要測試

## 建議格式

```text
You are working on the Mark0615/OudSeed repo.

Goal:
[這次任務目標]

Files to modify:
[列出檔案]

Do not modify:
[列出不要改的檔案]

Requirements:
[列出具體需求]

Acceptance criteria:
[列出驗收標準]

Please keep the code simple, readable, modular, and suitable for Python 3.11+.
Do not hardcode any secrets or account IDs.
```

---

# 24. 第一個最推薦丟給 Codex 的 Prompt$1You are helping me build a Python project in the GitHub repository Mark0615/OudSeed.

The internal project name can be ads-ai-pipeline.

This project will sync advertising data from Google Ads, Meta Ads, and LINE Ads into BigQuery, then support Looker Studio dashboards and AI-generated weekly reports.

For now, only create the initial project skeleton. Do not implement real API calls yet.

Requirements:
- Use Python 3.11+
- Create this folder structure:
  OudSeed/
    README.md
    requirements.txt
    .env.example
    .gitignore
    config/
      clients.example.yaml
    src/
      main.py
      connectors/
        __init__.py
        base.py
        line_ads.py
        google_ads.py
        meta_ads.py
      destinations/
        __init__.py
        bigquery.py
        google_sheets.py
      transforms/
        __init__.py
        normalize_line.py
        normalize_google.py
        normalize_meta.py
      ai/
        __init__.py
        weekly_report.py
        prompt_templates.py
      utils/
        __init__.py
        config_loader.py
        date_utils.py
        logger.py
        secret_manager.py
    sql/
      create_tables.sql
      weekly_summary.sql
    tests/
      test_normalize_line.py
      test_normalize_google.py
      test_normalize_meta.py
    deploy/
      Dockerfile
      cloudbuild.yaml
    docs/
      development_spec.md

- Add simple placeholder code where appropriate.
- Add README.md explaining the project goal, architecture, and setup steps.
- Add requirements.txt with at least:
  requests
  google-cloud-bigquery
  google-cloud-secret-manager
  google-api-python-client
  google-auth
  pyyaml
  python-dotenv
  pandas

- Add .env.example with placeholder environment variables for GCP, LINE Ads, Google Ads, Meta Ads, and OpenAI.
- Do not include any real credentials.
- Keep everything simple and readable.

Acceptance criteria:
- The folder structure is created.
- Python imports should not fail.
- No real secrets are included.
- README gives a clear overview of the project.
```

---

# 25. 最小可行版本定義

真正的 MVP 不等於功能最多，而是能證明這件事：

> 系統可以每天自動把廣告資料同步到 BigQuery，並產出可用的報表與 AI 摘要。

只要做到以下 5 件事，就算 MVP 成功：

1. LINE Ads 每天自動進 BigQuery
2. unified_ads_daily 可以正常查詢
3. Looker Studio 可以做 dashboard
4. sync_logs 可以追蹤成功 / 失敗
5. AI weekly report 可以根據資料產出初版摘要

---

# 26. 版本規劃

## v0.1

- Repo skeleton
- BigQuery schema
- LINE Ads connector
- BigQuery write
- Unified table
- Sync log

## v0.2

- Google Ads connector
- Meta Ads connector
- Google Sheet export

## v0.3

- Weekly summary SQL
- AI weekly report
- Cloud Run deployment
- Cloud Scheduler

## v0.4

- Multi-client config
- Sync status dashboard
- Error notification

## v1.0

- 內測版
- 1–3 位夥伴使用
- 手動 onboarding
- 蒐集產品回饋

---

# 27. 結論

本專案建議以「先自用、後產品化」方式開發。

最重要策略：

```text
不要一開始做 SaaS。
先做一條穩定的資料管線。
再做 dashboard。
再做 AI summary。
最後才做登入、授權、付款與多租戶管理。
```

與 Codex 協作時，請務必小步提交、分階段開發，避免一次產出過大的功能導致難以 debug。

