# Ads AI Pipeline × Codex 開發規格書 v0.2

## 0. 文件目的

本文件用來引導 Codex / AI coding assistant 在 `Mark0615/OudSeed` repository 中開發廣告數據自動化管線。

本專案初期不是要完整複製 Supermetrics / Windsor.ai，而是先建立一套可自用、可本機測試、可逐步擴充成 SaaS 的 MVP。

核心目標：

```text
Ads APIs → BigQuery → Looker Studio / Google Sheet → AI Summary
```

目前 MVP 優先順序：

```text
Meta Ads → Google Ads → LINE Ads
```

第一個真正可運作版本只做：

```text
Meta Ads → BigQuery → unified_ads_daily → Looker Studio
```

---

## 1. 專案資訊

| 項目 | 值 |
|---|---|
| GitHub repository | `Mark0615/OudSeed` |
| 本機路徑 | `/Users/mark/Desktop/OudSeed` |
| 專案內部代號 | `ads-ai-pipeline` |
| GCP project name | `oudseed` |
| GCP project id | `oudseed` |
| GCP project number | `252487346065` |
| BigQuery dataset | `ads_pipeline` |
| Runtime timezone | `Asia/Taipei` |

---

## 2. 產品背景

目前使用者投放多個廣告平台，包括：

- Meta Ads / Facebook Ads
- Google Ads
- LINE Ads

目前市場上已有 Windsor.ai、Supermetrics 等工具可以同步資料，但多數定位偏向「資料搬運」。本專案希望先建立自用管線，後續逐步提供給廣告投手、行銷顧問或小型代理商使用。

長期差異化方向：

> 不只同步資料，而是成為廣告投手的 AI Performance Analyst。

### 2.1 產品願景：自動回報廣告成效的廣告助理

最終產品應協助廣告投手與行銷顧問自動完成：

- 每天同步 Meta Ads、Google Ads、LINE Ads 等平台數據
- 將資料集中到 BigQuery
- 讓使用者選擇資料落地位置，MVP 先以 Looker Studio 為主，後續支援 Google Sheets
- 每週、每月，未來可每日，自動產出廣告成效洞察與行動建議
- 以客戶或廣告帳戶為單位寄送報告；同一客戶若有 Meta + Google，應整合在同一份報告中，不同客戶分開寄送
- MVP 可先以 `account_name` 判斷報告分組；若不同平台帳戶名稱相同或被設定為同一客戶，合併成同一封報告；若帳戶名稱不同，例如 Meta `Miniware TW` 與 Google `JK貓舍`，預設視為不同客戶並分開寄送。後續 SaaS 版本需支援手動 customer mapping 覆蓋自動判斷。
- 支援 Email 與 LINE 發送；未來 SaaS 版本可讓使用者自行選擇發送頻率與通路，多通路可作為付費升級
- 支援使用者自行選擇報告週期與寄送時間，例如每週一收到週報、每月 10 號收到月報；系統需依使用者設定推算當期區間與比較區間

AI 報告的核心價值不是重述數字，而是協助客戶提升業績，並依照廣告原始目標給出合理建議。

### 2.2 AI 報告內容格式

AI 報告應以繁體中文輸出。若同一客戶有多個平台，需依平台分段呈現，但維持一致格式。

每週或每月報告至少包含：

```text
**[當週/當月 Summary]**
- 本週/本月整體花費、CPM、CPC（連結點擊成本）、CPA（預設 purchase）、ROAS（如有）
- 加入購物車數、購買數（如有）

**表現較好的廣告**
- 不限一個 campaign / ad set / ad
- 說明 CPA 特別低、ROAS 特別高、CPC 特別低、CTR 特別好或轉換量明顯成長的原因
- 建議如何維持或放大表現

**表現較差的廣告**
- 不限一個 campaign / ad set / ad
- 說明相比上週或上月下降的指標
- 建議如何改善、是否降低預算、是否暫停

**素材觀察**
- 判斷哪些素材值得學習
- 除 CPC / CTR 外，盡量納入留言、按讚、分享、儲存、影片觀看、outbound click 等互動指標
- 建議下週或下月應提供哪些素材，哪些素材可減少

**整體建議**
- 下週或下月具體調整項目
- 需要客戶提供的素材、優惠、Landing Page 或其他資源
```

建議原則：

- 第一優先是協助客戶業績提升
- 若廣告目標是導流，優先提供降低 CPC、提高 CTR、提高點擊品質的建議
- 若廣告目標是轉換，優先提供增加購買數、轉換價值、降低 CPA、提高 ROAS 的建議
- 若資料不足，不可捏造原因，應明確說明缺少哪些資料
- 報告不應只停留在 campaign 層級；當資料可用時，需能讀取 ad set 與 ad/creative 層級資料，說明哪些廣告組合有放大潛力、哪些應降低預算或關閉，哪些素材值得延伸、汰換或減少提供

### 2.3 AI 報告排程與比較區間

使用者最終應能自行設定報告 cadence 與寄送時間：

- Weekly：可選擇每週幾寄送，例如每週一
- Monthly：可選擇每月幾號寄送，例如每月 10 號
- Daily：未來版本可支援每日固定時間寄送

比較區間需依使用者的報告設定推算，不可只寫死自然週或自然月：

- 週報需根據使用者設定的週期結束日推算本期與上一期，例如每週一寄送時，預設比較剛結束的一週與再前一週
- 月報需根據使用者設定的寄送日與產品定義推算本期與上一期，例如每月 10 號寄送時，可比較前一個完整月與再前一個完整月，或依後續產品設定支援自訂 billing/reporting cycle
- 報告文案需清楚標示本期日期區間與比較期日期區間
- 若使用者設定變更，後續 WoW/MoM 應以新的設定重新推算，不可沿用舊的固定日期邏輯

### 2.4 AI 報告數字格式

AI 報告需維持一致、容易閱讀的數字格式：

- 所有金額相關欄位前綴加上 `$`，包含 spend、CPM、CPC、CPA、cost per add-to-cart、purchase value、conversion value 等
- 所有數字需使用千分位符號，例如 `$12,324`、`1,234 clicks`
- CPC 顯示到小數點後 2 位，例如 `$10.13`
- 除 CPC 外，其他金額預設取整數，例如 `$3,577`、`$190`、`$1,789`
- CTR、CVR 與其他比例欄位以百分比顯示，並到小數點後 2 位，例如 `1.87%`
- ROAS 顯示到小數點後 2 位，例如 `1.40`
- 若資料幣別可用，後續 UI 可顯示幣別或支援帳戶幣別設定；文字報告中的 `$` 作為目前 MVP 的金額前綴格式
- WoW/MoM 指標若有前期資料，需一致呈現「本期值 + 前期值 + 上升/下降差額」，例如 `Spend：$13,006（較上月 $13,601 下降 $594）`，不可不同平台使用不同格式
- 前期總計需以完整前期資料計算，不可只加總本期仍存在 campaign 的 previous 欄位；若前期有花費但本期無花費的 campaign，也必須納入前期總計比較
- Summary 內的 MoM/WoW 與核心 KPI 不可重複列同一批指標；若已用比較表呈現 spend、clicks、CPC、CPA、ROAS 等，後方只需補 1-2 句重點判讀
- 報告不可顯示內部資料狀態文字，例如「有提供 previous 與 delta」；這類內容只供 prompt/context 使用，不應讓客戶看到

### 2.5 Email 報告呈現格式

Email 不應直接寄送 Markdown 原文。系統需寄送 HTML email，至少包含：

- Report header：客戶/帳戶名稱、report id、period
- Period 後方先放 campaign 維度表格
- Campaign 表格欄位：campaign name、spent、clicks、CPC、CPM、add to cart、CPA(add_to_cart)、purchase、CPA(purchase)、purchase value、ROAS
- 表格最下方需有總計列，總計該平台當期數據，ratio/cost 類欄位需由總計分子分母重算，不可加總 row-level ratio
- 若同一客戶有兩個以上平台，需依平台分段：先放該平台表格，再放該平台 insight；完成一個平台後再呈現下一平台
- 粗體、標題、重點不可用未渲染的 Markdown `**`，需以 HTML `<strong>`、標題字級或其他 email client 可支援的樣式呈現
- 指標密集段落需優先表格化，例如 Summary comparison、Campaign/ad group/keyword 診斷、下期行動清單
- 風險或警訊可用 `⚠️`、淺色底 callout 或左側色條凸顯，例如高花費低轉換、CPC/CPA 快速上升、ROAS 明顯下滑
- HTML renderer 需盡量補強模型輸出格式，例如將 Markdown table 轉為 HTML table、移除未渲染 Markdown、補上大數字千分位符號
- 文字層級需符合 Markdown heading 語意：`#` 作為主段落（例如本月 Summary、表現較好的廣告）、`##` 作為命名對象（例如最佳主力活動：某 campaign）、`###` 作為分析層級（活動層級、ad group 層級、keyword/search term 層級、建議做法）
- 一般建議句或 numbered action 不應被渲染成大標題；建議段落後需有明顯留白，再進入下一個 campaign/ad set/ad/keyword 或段落
- Email 視覺可參考顧問式洞察信件：固定內容寬度、清楚 heading hierarchy、表格與 callout 區塊、足夠段落留白；但需保持廣告月報的資料密度與可掃描性

### 2.6 洞察深度與資料覆蓋

AI 建議需保留模型判斷彈性，但資料 context 必須足夠讓模型做出具體判斷：

- Meta Ads 應逐步提供 campaign、ad set、ad/creative、互動指標、版位、年齡、性別等 context；若某些 breakdown 尚未接入，報告需明確列為資料限制
- Google Ads 應提供 campaign、ad group、ad、keyword、search term 等 context；當 keyword/search term 有高花費、高 CPC、低轉換或低 ROAS 時，模型應提出具體的暫停、降價、縮減、或加入否定關鍵字方向
- 建議不可只停留在「提高預算」、「避免 CPC 上升」等泛用語；若資料足夠，需點名具體 campaign / ad group / ad / keyword / search term 與指標依據
- Google Ads campaign 層級診斷需向下追到造成變化的 ad group、keyword 或 search term，例如說明某 campaign CPC 上升是由哪些 keyword/search term 拉高，同時指出哪些低 CPC 或高轉換 search term 應加強曝光
- 若模型需要受眾、版位、搜尋字詞、年齡、性別、素材 metadata 等資料才可做出更準確建議，需在資料限制或客戶需補資料中說明
- Google Ads UI 自訂欄位（Custom columns）不能假設能以單一報表欄位完整同步。產品需優先同步底層 conversion actions、conversion values、click/call/form 等事件與可用 metrics，並在 BigQuery / reporting config 重建客戶自訂公式，例如 `PV_立即預約`、`CPA_Click to call`、`LINE 點擊` 等。每個客戶的 custom column 對應需可設定、可版本控管，並在報告中標示該欄位的計算來源。

---

## 3. 產品階段

## 3.1 v0.1 MVP

只做 Meta Ads。

v0.1 必須做到：

- 從 Meta Ads Insights API 擷取 ad level daily data
- 將 Meta Ads raw response 寫入 BigQuery raw table
- 將 Meta Ads 資料轉成 `unified_ads_daily`
- 支援每天同步與近 7 天回補
- 寫入 `sync_logs`
- Looker Studio 可連接 BigQuery 查看資料
- 不做 SaaS 登入
- 不做付款
- 不做 Google Ads
- 不做 LINE Ads
- 不做 AI weekly report

## 3.2 v0.2

加入 Google Ads：

- Google Ads connector
- Google Ads normalize
- Google Ads → BigQuery daily sync
- Google Sheet export optional

## 3.3 v0.2.5

加入 LINE Ads：

- LINE Ads connector
- LINE Ads normalize
- LINE Ads → BigQuery daily sync

## 3.4 v0.3

加入 AI 週報：

- Weekly summary SQL
- AI weekly report generator
- 儲存 AI report logs

## 3.5 v0.4

加入雲端排程與 AI 報告部署：

- Cloud Run Job 執行 Meta Ads daily sync
- Cloud Scheduler 每日觸發 sync
- Cloud Run Job 執行 AI weekly/monthly report generation
- Cloud Scheduler 觸發 monthly report，weekly report 可依需求新增
- AI report logs 可被 Looker Studio 查詢
- 下一階段需將排程設定抽象成 client/account-level config，讓每個客戶可設定 weekly/monthly cadence、寄送日與寄送通路

## 3.6 v0.5

擴充 Meta Ads 欄位覆蓋率：

- 加入 Meta action/action_values/cost_per_action_type 常用 action 展開欄位
- 加入 creative metadata，例如 image URL、thumbnail URL、headline、body、link URL
- 加入 campaign/ad set/ad settings，例如 objective、optimization goal、bid strategy、budget、status、created/end time
- 擴充 ad set 與 ad/creative 層級 summary marts 或 views，讓 AI 能比較 campaign、ad set、ad 三個層級，而不是只依 campaign 給建議
- 加入 engagement metrics，例如 comments、reactions、saves、shares、page engagement、post engagement
- 規劃 Meta field catalog，記錄欄位名稱、來源 endpoint、報表層級、資料型別與 Looker 顯示名稱

## 3.7 v1.0

內測版：

- 1–3 位夥伴使用
- 手動 onboarding
- 多 client / 多 account
- 蒐集產品回饋

---

## 4. MVP 技術架構

```text
Meta Ads Insights API
        ↓
Python Meta Connector
        ↓
Raw response storage
        ↓
BigQuery raw_meta_ads_daily
        ↓
Normalize / Transform
        ↓
BigQuery unified_ads_daily
        ↓
Looker Studio
```

後續擴充：

```text
Google Ads API
LINE Ads API
        ↓
Platform Connectors
        ↓
Raw Tables
        ↓
Unified Ads Table
        ↓
Dashboard / Google Sheet / AI Summary
```

---

## 5. 技術選型

| 模組 | 技術 |
|---|---|
| Language | Python 3.11+ |
| Local IDE | VS Code / Cursor + Codex in IDE |
| API calls | `requests` first, official SDK optional |
| Data warehouse | BigQuery |
| Runtime later | Cloud Run Jobs |
| Scheduler later | Cloud Scheduler |
| Secrets later | Google Secret Manager |
| Local secrets | `.env`, never committed |
| Dashboard | Looker Studio |
| Sheet export later | Google Sheets API |
| AI report later | OpenAI API or Gemini API |

---

## 6. Repo 結構

```text
OudSeed/
  AGENTS.md
  README.md
  requirements.txt
  .env.example
  .gitignore
  Makefile
  config/
    clients.example.yaml
  docs/
    ads_ai_pipeline_codex_development_spec.md
  src/
    main.py
    connectors/
      __init__.py
      base.py
      meta_ads.py
      google_ads.py
      line_ads.py
    destinations/
      __init__.py
      bigquery.py
      google_sheets.py
    transforms/
      __init__.py
      normalize_meta.py
      normalize_google.py
      normalize_line.py
    utils/
      __init__.py
      config_loader.py
      date_utils.py
      logger.py
      secret_manager.py
    ai/
      __init__.py
      weekly_report.py
      prompt_templates.py
  sql/
    create_tables.sql
    weekly_summary.sql
  tests/
    fixtures/
      meta_ads_raw_sample.json
    test_config_loader.py
    test_date_utils.py
    test_normalize_meta.py
  .github/
    pull_request_template.md
```

---

## 7. BigQuery 資料設計

Dataset:

```text
ads_pipeline
```

Tables:

| Table | 說明 |
|---|---|
| `raw_meta_ads_daily` | Meta Ads 原始資料 |
| `raw_google_ads_daily` | Google Ads 原始資料，v0.2 再實作 |
| `raw_line_ads_daily` | LINE Ads 原始資料，v0.2.5 再實作 |
| `unified_ads_daily` | 跨平台標準化資料 |
| `sync_logs` | 每次同步紀錄 |
| `weekly_performance_summary` | AI 週報用彙總資料，v0.3 再實作 |
| `ai_report_logs` | AI 報告產出紀錄，v0.3 再實作 |

---

## 8. 欄位擷取策略

MVP 採用雙層設計：

```text
Raw Tables：盡可能保留平台原始回傳資料，方便未來重算與補欄位
Unified Table：只放跨平台常用且可標準化的核心欄位，方便 dashboard / AI summary 使用
```

### 8.1 Raw table 原則

Raw table 應盡量保留 Meta Ads API response。

原則：

- 優先抓取 Meta Ads Insights API 常用報表欄位
- 若 API 不支援一次抓全部欄位，維護一組 `default_fields`
- 每筆資料保留 `raw_payload`
- 不應只保存 unified schema 欄位
- 不應靜默丟棄未知欄位

建議欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| date | DATE | 報表日期 |
| workspace_id | STRING | 工作區 ID |
| client_id | STRING | 客戶 ID |
| platform | STRING | `meta_ads` |
| account_id | STRING | Meta ad account ID |
| report_level | STRING | `ad` |
| attribution_setting | STRING | `platform_default` |
| timezone_setting | STRING | `platform_account_default` |
| raw_payload | JSON / STRING | 原始 API response |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 更新時間 |

### 8.2 Unified table 原則

Unified table 不追求保存所有平台欄位，而是保存三個平台都容易對齊、且適合 dashboard / AI summary 使用的核心欄位。

Table name:

```text
unified_ads_daily
```

| 欄位 | 型別 | 說明 |
|---|---|---|
| date | DATE | 報表日期 |
| workspace_id | STRING | 工作區 ID |
| client_id | STRING | 客戶 ID |
| platform | STRING | `meta_ads` / `google_ads` / `line_ads` |
| account_id | STRING | 廣告帳號 ID |
| account_name | STRING | 廣告帳號名稱 |
| campaign_id | STRING | Campaign ID |
| campaign_name | STRING | Campaign 名稱 |
| ad_group_id | STRING | Meta adset / Google ad group / LINE ad group ID |
| ad_group_name | STRING | Ad group / adset 名稱 |
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
| source_updated_at | TIMESTAMP | 來源更新時間 |
| created_at | TIMESTAMP | 建立時間 |
| updated_at | TIMESTAMP | 更新時間 |

去重 key：

```text
date + platform + account_id + campaign_id + ad_group_id + ad_id
```

### 8.3 Windsor-like Meta 欄位覆蓋策略

本專案可以逐步做到接近 Windsor.ai 的 Meta 欄位覆蓋，但不應理解成「Meta 廣告管理員所有欄位都能用一次 API call 抓進同一張表」。

原因：

- Ads Manager UI 欄位來自多個來源：Insights、Campaign、Ad Set、Ad、Creative、Custom Conversion、Breakdowns 等
- 有些 UI 欄位是衍生指標，例如 cost per action、ROAS、CTR、CPC
- 有些欄位是 nested action type，例如 `actions:purchase`、`actions:add_to_cart`
- 有些欄位需要特定歸因設定、conversion event 或 Pixel/CAPI 設定才會有值
- 有些 breakdown 不能任意互相組合，且會讓資料列數大幅增加

建議資料層：

| Layer | 說明 |
|---|---|
| Raw API payload | 保存完整 API 回傳，支援重算與補欄位 |
| Platform wide table/view | 展開 Meta-only 欄位，給 Looker Studio 與 AI 使用 |
| Unified table/view | 保存跨平台核心欄位，避免被平台特有欄位污染 |
| Field catalog | 記錄欄位來源、型別、endpoint、report level、是否可用於 Looker/AI |

Meta 欄位擴充順序：

1. Insights performance preset：spend、impressions、reach、frequency、clicks、inline link clicks、CTR、CPC、CPM
2. Conversion preset：`actions`、`action_values`、`cost_per_action_type` 中的 purchase、add_to_cart、view_content、initiate_checkout、lead 等
3. Engagement preset：comments、reactions、shares、saves、page engagement、post engagement、video metrics
4. Creative preset：ad creative ID、headline、body、description、image URL、thumbnail URL、destination URL、object type
5. Settings preset：campaign objective、status、budget、bid strategy、optimization goal、created/end time
6. Breakdown preset：publisher platform、platform position、device、country、region、age、gender

實作規則：

- 使用 configurable field presets，不要在 connector 中硬寫一份不可調整的巨大欄位清單
- Meta API 不支援或當前帳戶無資料的欄位，應保留為 `NULL` 或從 raw_payload 可追溯，不可捏造
- 若新增欄位只適用 Meta，優先放在 Meta-specific view/table，不要直接塞進 `unified_ads_daily`
- Looker Studio 可連接 platform wide view 取得更多欄位；AI summary 可優先使用 summary marts，再補 creative/engagement context
- AI 報告資料集需逐步支援 campaign、ad set、ad/creative 三個分析層級；若某層級資料暫缺，報告需明確說明目前僅能使用哪些層級，而不是假裝已完成完整素材判讀

---

## 9. 歸因與時區原則

### 9.1 歸因

MVP 階段不主動覆寫平台歸因設定。

Meta Ads：

- 使用 Meta Ads Insights API 預設歸因設定
- 不主動指定 attribution window
- raw table / sync log 記錄：

```text
attribution_setting = platform_default
```

未來若要支援 1-day click、7-day click、1-day view，應新增 config 設定，不要直接改既有邏輯。

### 9.2 時區

MVP 階段不主動轉換平台報表時區。

原則：

- 報表日期依照 Meta 廣告帳號預設時區
- 系統排程時間使用 `Asia/Taipei`
- BigQuery `date` 欄位代表平台報表日期，不代表 Cloud Run 執行日期
- raw table / sync log 記錄：

```text
timezone_setting = platform_account_default
scheduler_timezone = Asia/Taipei
```

---

## 10. Meta Ads Connector 規格

檔案：

```text
src/connectors/meta_ads.py
```

功能：

- 使用 Meta Marketing API Ads Insights
- 支援 `ad_account_id`，格式如 `act_xxxxxxxxx`
- 預設抓 ad level daily data
- 支援 date range
- 回傳 `list[dict]`
- 保留 raw response
- API 錯誤需提供清楚錯誤訊息

MVP 建議 fields：

```text
date_start
date_stop
account_id
account_name
campaign_id
campaign_name
adset_id
adset_name
ad_id
ad_name
impressions
clicks
spend
actions
action_values
```

注意：

- conversions 與 conversion_value 從 `actions` / `action_values` 解析
- conversion action type 應可設定，MVP 可預設 `purchase`
- 不確定欄位時不要硬猜，應把 API 回傳保存到 raw_payload

---

## 11. Normalize 規格

檔案：

```text
src/transforms/normalize_meta.py
```

Function:

```python
def normalize_meta_ads_rows(raw_rows: list[dict], context: dict) -> list[dict]:
    ...
```

Context required:

| 欄位 | 說明 |
|---|---|
| workspace_id | 工作區 |
| client_id | 客戶 |
| account_id | Meta ad account |
| account_name | optional |
| conversion_action_type | default `purchase` |
| attribution_setting | default `platform_default` |
| timezone_setting | default `platform_account_default` |

計算邏輯：

| 指標 | 計算 |
|---|---|
| ctr | clicks / impressions |
| cpc | spend / clicks |
| cpm | spend / impressions * 1000 |
| cpa | spend / conversions |
| roas | conversion_value / spend |

分母為 0 時回傳 `None`。

---

## 12. 同步流程

MVP daily sync flow：

```text
1. Load config/clients.yaml
2. Determine sync range: yesterday and previous 7 days
3. For each enabled client and enabled Meta Ads account:
   3.1 Fetch Meta Ads raw rows
   3.2 Write raw rows to raw_meta_ads_daily
   3.3 Normalize rows
   3.4 Delete + insert unified_ads_daily for the date range/account
   3.5 Write sync_logs
4. Continue other accounts if one account fails
```

回補邏輯：

```text
Delete date range from target table → Insert latest data
```

---

## 13. Coding rules

Codex 必須遵守：

- Python 3.11+
- Use type hints
- Do not hardcode secrets, tokens, account IDs, customer IDs, or API keys
- Keep connectors, transforms, destinations separated
- Do not implement future roadmap items unless explicitly requested
- Preserve raw payloads
- Add tests for transform logic
- Keep code simple and readable
- Before editing, inspect existing files to avoid duplicate logic and conflicts
- Before finishing, summarize changed files, how to test, assumptions, and limitations

---

## 14. API field accuracy rule

When implementing real API connectors, do not guess undocumented field names.

If exact API fields are uncertain:

1. Keep endpoint, fields, and payload configurable.
2. Add comments marking fields that need verification.
3. Return raw API responses before aggressive transformation.
4. Prefer storing `raw_payload` first.
5. Do not silently drop unknown fields.
6. Add clear errors when expected fields are missing.

---

## 15. Codex task strategy

Do not ask Codex to build the whole system at once.

Recommended order:

| Order | Task |
|---:|---|
| 1 | Engineering governance files and project skeleton |
| 2 | BigQuery schema |
| 3 | Config loader |
| 4 | Date utils |
| 5 | BigQuery destination |
| 6 | Base connector |
| 7 | Meta Ads connector |
| 8 | Meta Ads normalize |
| 9 | Main Meta sync flow |
| 10 | Local verification |
| 11 | Cloud Run deployment later |
| 12 | Google Ads connector later |
| 13 | LINE Ads connector later |

---

## 16. 第一個 Codex 任務建議

```text
You are working on the GitHub repository Mark0615/OudSeed.

Please read:
- AGENTS.md
- docs/ads_ai_pipeline_codex_development_spec.md

Goal:
Create the initial engineering governance files and project skeleton only.

Do not implement real API calls yet.

The current MVP priority is:
Meta Ads → BigQuery → unified_ads_daily → Looker Studio

Do not implement Google Ads, LINE Ads, OAuth, SaaS login, payment, Google Sheet export, or AI reports.

Acceptance criteria:
- Project folder structure is created.
- No real secrets are committed.
- `make check` runs successfully.
- README explains project purpose and local setup if README is created.
- The repo is ready for the next task: BigQuery schema.
```

---

## 17. MVP 成功定義

v0.1 成功定義：

1. Meta Ads 每天可同步資料到 BigQuery
2. `raw_meta_ads_daily` 有保存 raw payload
3. `unified_ads_daily` 可以查到 Meta Ads daily ad-level data
4. `sync_logs` 可追蹤成功與失敗
5. Looker Studio 可連 BigQuery 做 dashboard
6. 架構可無痛加入 Google Ads 與 LINE Ads
