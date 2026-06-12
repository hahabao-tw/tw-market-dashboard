# 台股籌碼日報 —— 上線教學(零基礎版)

這個專案會每天自動抓證交所、期交所資料,更新成一個手機也好讀的網頁。
全程在 GitHub 網頁上操作,不用安裝任何軟體。

---

## 步驟 1:建立 Repository(倉庫)

1. 登入 GitHub,點右上角「+」→「**New repository**」
2. Repository name 填:`tw-market-dashboard`(也可自取,純英文)
3. 選 **Public**(GitHub Pages 免費版必須是 Public)
4. 其他都不要勾,按綠色「**Create repository**」

## 步驟 2:上傳檔案

1. 在新倉庫頁面點「**uploading an existing file**」連結
2. 把解壓縮後資料夾「裡面」的所有東西(index.html、data、scripts、.github)
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
4. 等它跑完(約 3~8 分鐘,圖示變綠色勾勾)
5. 回到你的網址重新整理,圖表應該都長出來了(含回補的近 20 日歷史)

## 之後它會自己做的事

- 週一到週五台北時間 14:55 / 15:15 / 15:40 / 17:00 抓期交所資料
- 21:00 抓證交所融資資料
- 當天抓過就不重抓;假日沒新資料就什麼都不動
- 排程實際執行可能比表定晚 5~15 分鐘,是 GitHub 免費版的特性,不影響正確性

## 偶爾需要你看一眼的事

- GitHub 若寄信說排程被暫停(倉庫太久沒活動),點信裡按鈕恢復即可
- 若官方網站改版導致抓不到資料,Actions 會顯示紅色叉叉,
  把錯誤訊息截圖貼給 Claude 就能修

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `index.html` | 網頁本體(圖表、版面) |
| `scripts/fetch_data.py` | 抓資料腳本 |
| `.github/workflows/update.yml` | 排程設定 |
| `data/*.json` | 每天自動更新的資料檔 |
