# 台股籌碼日報 —— 上線教學(零基礎版)

這個專案會在平日由 GitHub Actions 自動檢查證交所、期交所資料;有新交易日資料時,更新成一個手機也好讀的網頁。
全程在 GitHub 網頁上操作,不用安裝任何軟體。

---

## 步驟 1:建立 Repository(倉庫)

1. 登入 GitHub,點右上角「+」→「**New repository**」
2. Repository name 填:`tw-market-dashboard`(也可自取,純英文)
3. 選 **Public**(GitHub Pages 免費版必須是 Public)
4. 其他都不要勾,按綠色「**Create repository**」

## 步驟 2:上傳檔案

1. 在新倉庫頁面點「**uploading an existing file**」連結
2. 把解壓縮後資料夾「裡面」的所有東西(index.html、data、scripts、tests、.github、README.md、DATA_NOTES.md)
   一起拖進上傳區
3. 下方按綠色「**Commit changes**」
4. 上傳完確認倉庫首頁看得到 `.github` 資料夾。
   **如果沒看到 `.github`**(有些電腦會隱藏它),改用手動建立:
   - 點「Add file」→「Create new file」
   - 檔名欄輸入:`.github/workflows/update.yml`(輸入 / 會自動變資料夾)
   - 把本資料夾內 `.github/workflows/update.yml` 的內容全部複製貼上
   - 按「Commit changes」

## 步驟 3:開啟 GitHub Pages(讓網頁上線)

1. 倉庫上方點「**Settings**」→ 左側選單「**Pages**」
2. Source 選「**Deploy from a branch**」
3. Branch 選「**main**」、資料夾選「**/ (root)**」→ 按「**Save**」
4. 等 1~2 分鐘,頁面上方會出現你的網址:
   `https://你的帳號.github.io/tw-market-dashboard/`

## 步驟 4:啟用並手動跑第一次抓資料

1. 倉庫上方點「**Actions**」,若出現綠色按鈕問你要不要啟用,按啟用
2. 左側點「**更新市場資料**」
3. 右邊點「**Run workflow**」→ 再按綠色「**Run workflow**」
4. 等它跑完(通常數分鐘;最長 15 分鐘會逾時,成功時圖示變綠色勾勾)
5. 回到你的網址重新整理,圖表應該都長出來了。新資料回補範圍依模組而異;融資與期貨歷史最多保留 60 個交易日,其餘模組保留最新快照

## 之後它會自己做的事

- 平日多個時段執行完整資料 pipeline;14:55 / 15:15 / 15:40 / 17:00 主要補抓期交所資料
- 20:30 / 22:30 主要補抓證交所融資資料,次日 07:00 主要補抓收盤資料
- 期貨每次重驗最近 3 個交易日,依日期新增或在官方數值修訂時覆寫;假日沒新資料就不寫檔
- GitHub 免費排程可能延遲;抓取器會先檢查資料是否完整,並由後續班次自動補抓
- 期貨會在最近重驗區間內,最多向前探測 15 個日曆日;找不到可驗證的法人資料時,排程會失敗示警

## 偶爾需要你看一眼的事

- GitHub 若寄信說排程被暫停(倉庫太久沒活動),點信裡按鈕恢復即可
- 期貨法人或全市場 OI 來源失效時,Actions 會顯示紅色叉叉;可把錯誤訊息截圖交給開發者診斷
- 選擇權、P/C 比、融資、市值、加權指數、台積電權重與前十大股期的部分錯誤可能只記錄在執行紀錄;資料檔可能保留舊資料,或以部分新資料與空值更新。因此要同時留意頁面資料日是否停止更新,以及欄位是否顯示 `--`

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `index.html` | 網頁本體(圖表、版面) |
| `scripts/fetch_data.py` | 抓資料腳本 |
| `.github/workflows/update.yml` | 排程設定 |
| `data/*.json` | 交易日有新官方資料時自動更新的資料檔 |
| `tests/test_fetch_data.py` | 零值、覆寫、資料完整性、來源失效與延遲排程邊界測試 |
| `DATA_NOTES.md` | 資料來源、欄位、計算方式與維護注意事項 |
