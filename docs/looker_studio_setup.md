# Looker Studio（Data Studio）資料來源設定指南

把 BigQuery 的寬表接進 Looker Studio 之後，欄位的「維度 / 指標」分類、貨幣格式、
比率欄位（CTR/CPC/CPA/ROAS）都是 **Looker Studio 這一端的設定**，不是 BigQuery
能決定的。好消息：這些只要在「資料來源」設定 **一次**，存成可重複使用的資料來源
（Reusable data source），之後每張報表共用，就不必再重設。

> Windsor.ai 之所以「一接上就分好維度/指標、貨幣自動套」，是因為它是 Google 審核過的
> **社群連接器（Community Connector）**，schema 裡直接寫死了每個欄位的型態。我們用原生
> BigQuery 連接器，型態靠 Looker 自動猜，所以要手動定一次。要做到跟 Windsor 一模一樣的
> 「零設定」，需要另外開一個 Community Connector 專案（之後可做，見最後一節）。

接的兩張寬表：
- Meta：`oudseed.ads_pipeline.vw_looker_meta_ads_wide`
- Google：`oudseed.ads_pipeline.vw_looker_google_ads_wide`

---

## 1. 維度 vs 指標（為什麼 spend、clicks 看起來像維度）

Looker Studio 接 BigQuery 時，會用欄位型態自動猜「維度（綠色）」或「指標（藍色）」。
數字欄位通常會被猜成指標，但有時會落在維度。要改：

1. 打開資料來源（Resource → Manage added data sources → Edit）。
2. 找到該欄位（例如 `spend`、`clicks`、`impressions`、`purchases`…）。
3. 點欄位左側的圖示或右鍵 → **Change to metric**（改成指標）。
4. 反過來，純文字/ID 欄位（`campaign_name`、`ad_name`、`date`…）保持維度。

設定一次後存起來，整個報表都生效。

---

## 2. 貨幣格式（不用每個欄位手動改）

BigQuery 沒有「貨幣」型態，所以貨幣顯示一定是在 Looker 這端設定。要省事：

- 在資料來源裡，把跟錢有關的欄位（`spend`、`cpc`、`cpm`、`cpa`、
  `purchases_value`、`conversion_value`、`adds_to_cart_value`…）的 **Type** 一次改成
  `Currency → TWD`（或你帳戶幣別）。
- 存成可重複使用的資料來源後，之後新報表直接套，不必再改。

> 真的想「完全不手動」→ 只能走 Community Connector（最後一節）。原生 BigQuery 連接器
> 沒辦法從資料庫端帶貨幣格式。

---

## 3. CTR / CPC / CPM / CPA / ROAS 為什麼直接拉會錯，怎麼修

寬表裡的 `ctr`、`cpc`、`cpm`、`cpa`、`purchase_roas` 是 **每一列（每支廣告每天）的比率**。
你把它拉進表格、Looker 幫你 SUM 或 AVG，就會變成「把比率相加/平均」——數字一定錯。

正確做法：**只用可加總的原始欄位**（spend、impressions、clicks、purchases、值），
在資料來源裡用 **Add a field** 建「計算欄位」，公式用 SUM 包起來，這樣不管你怎麼切
（按活動、按日期…）總數都正確。

把這幾個建一次就好（Meta 版）：

| 新欄位名稱 | 公式 | Type |
|---|---|---|
| CTR | `SUM(link_clicks) / SUM(impressions)` | Percent |
| CPC | `SUM(spend) / SUM(link_clicks)` | Currency TWD |
| CPM | `SUM(spend) / SUM(impressions) * 1000` | Currency TWD |
| CPA（每購買成本） | `SUM(spend) / SUM(purchases)` | Currency TWD |
| ROAS | `SUM(purchases_value) / SUM(spend)` | Number |
| CVR（購買轉換率） | `SUM(purchases) / SUM(link_clicks)` | Percent |

Google 版（欄位名不同）：

| 新欄位名稱 | 公式 | Type |
|---|---|---|
| CTR | `SUM(clicks) / SUM(impressions)` | Percent |
| CPC | `SUM(spend) / SUM(clicks)` | Currency TWD |
| CPM | `SUM(spend) / SUM(impressions) * 1000` | Currency TWD |
| CPA | `SUM(spend) / SUM(conversions)` | Currency TWD |
| ROAS | `SUM(conversion_value) / SUM(spend)` | Number |

建好之後，圖表用這些「計算欄位」版本，不要用寬表內建的 `ctr`/`cpc`/… 原始欄位。

---

## 4. 同步要跑多久？（為什麼 3 個帳號要 2 分鐘）

正常。第一次同步（first sync）抓的是最近約 30 天，而且為了避免大帳號逾時，程式會把
30 天切成多個 7 天小窗、逐一抓、逐一寫進 BigQuery（raw + 精簡表兩張）。所以一個帳號
大約要：5 個小窗的 API 呼叫 + 幾次 BigQuery 寫入 ≈ 30–40 秒，3 個帳號 ≈ 1.5–2 分鐘。

這是「一次性 / 偶爾」的成本；之後每日自動同步只補當天，會快很多。帳號很多、覺得太慢時，
再跟我說，可以改成「多帳號平行處理」加速。

---

## 5.（之後）要做到跟 Windsor 一樣零設定

上面 1–3 的手動設定，本質是 Windsor 用「社群連接器」幫你寫死了。若要我們的工具上架到
Data Studio 的資料來源選單、且接上就自動分好維度/指標/貨幣，需要另開一個
**Looker Studio Community Connector**（Apps Script / JavaScript 專案，讀我們的 BigQuery
或 API）。這條路 **不需要 Cloud SQL**；只有要「公開分享給其他人用」時才需要送 Google 審核，
自己私用可以直接用未審核版本。屬於之後的進階項目。

---

## 6. 一個帳號一張資料來源（per-account views）

想要「一個 Data Studio 資料來源 = 一個廣告帳號」時，**不用**幫每個帳號各建一張實體表
（那會浪費儲存、又要重跑）。改用一支產生器，幫每個帳號各建一張**只篩該帳號**的 view，
都是疊在寬表上的薄薄一層過濾，**不需要重新同步**：

```bash
# 先看會建哪些（dry-run，不會真的動到 BigQuery）
make per-account-views

# 確認後實際建立
.venv/bin/python scripts/generate_per_account_views.py --apply
```

會幫**每個帳號、每一種報表類型**各建一張 view（名字裡就是你自己的帳號 ID，方便在
Data Studio 裡認）：

- `vw_acct_meta_<帳號ID>`：Meta — 花費/點擊/廣告
- `vw_acct_google_<帳號ID>`：Google — 花費/點擊/廣告（ad 層）
- `vw_acct_google_keyword_<帳號ID>`：Google 關鍵字
- `vw_acct_google_searchterm_<帳號ID>`：Google 搜尋字詞
- `vw_acct_google_conversion_<帳號ID>`：Google **廣告活動 × 轉換動作**

之後新加帳號，再跑一次 `--apply` 即可（`CREATE OR REPLACE`，可重複執行、不會壞）。
在 Data Studio 新增資料來源時，選對應那張 `vw_acct_...` view 就只會看到那一個帳號、
那一種報表。`google_conversion` 那張就是「活動 × 轉換動作」報表的資料來源（維度用
`campaign_name` + `conversion_action_name`，指標用 `all_conversions` + `conversion_value`）。

---

## 7. Google 轉換動作 / 自訂轉換（conversion action 維度）

Google 的「各個轉換動作」（含你在後台設定的**自訂轉換**）會放在一張獨立的寬表
`vw_looker_google_ads_conversion_action_wide`，用**長表 / 維度**形式呈現：每一列是
（日期 × 活動 × 轉換動作），用 `conversion_action_name` 當維度去 group，就能看到每個
轉換動作各自的 `conversions` / `conversion_value` / `all_conversions` / `all_conversions_value`。

注意這張表**故意不含花費/曝光/點擊**（那些會在每個轉換動作上重複，加總會錯）；要看花費請用
ad-level 的 `vw_looker_google_ads_wide`。

> 這份資料是**新的**（要連接器多撈一段 GAQL），所以跟前面幾張「只加 view 就有」不一樣：
> 需要**重跑一次同步**才會有 `report_level = 'conversion_action'` 的資料。每日自動同步上線後
> 會自動往後累積；要補近期歷史可以跑一段有界回補，例如近 180 天（避免一次回補 36 個月逾時）：
>
> ```bash
> BACKFILL_GOOGLE_DAYS=180 make backfill
> ```

---

## 8. 一張表同時看「花費 + 每個轉換動作」（活動樞紐表）

花費/點擊/曝光跟「各個轉換動作的轉換數」是**不同層級**，硬塞同一張平表會讓花費在每個轉換
動作上重複、加總出錯。要在**同一張表**同時看到，就要把轉換動作**展開成欄位（pivot）**。

產生器會對每個 Google 帳號建一張 `vw_acct_google_campaign_pivot_<帳號ID>`：每個 campaign
一列，欄位是 `spend` / `clicks` / `impressions` / `total_conversions` /
`total_conversion_value`，**外加每個轉換動作各一欄**（`conv_<動作名>`，例如
`conv_Request_quote_LINE`、`conv_加入詢價車`）。轉換動作的欄位是**執行時**從帳號資料讀出來
動態長的（所以客戶的轉換動作名稱不會寫進 git，新增轉換動作也會自動補欄位）。

```bash
make campaign-pivot-views                                          # 先看會建哪些（dry-run）
.venv/bin/python scripts/generate_campaign_pivot_views.py --apply  # 真的建立
```

在 Data Studio 接這張 `vw_acct_google_campaign_pivot_<id>`，一張表就同時有花費和每個轉換
動作的轉換數了。注意：這是 **campaign 層級**；關鍵字/搜尋字詞層級的「各轉換動作」拆分需要
連接器另外多撈 + 重跑（見上）。
