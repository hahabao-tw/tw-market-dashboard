#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
台股市場儀表板 - 每日資料抓取腳本
資料來源:證交所(TWSE)、期交所(TAIFEX)
只用 Python 標準庫,不需安裝任何套件。
邏輯:冪等更新 —— 抓到的資料若已存在就跳過,假日抓不到新資料就什麼都不做。
"""

import csv
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------- 基本設定 ----------
TPE = timezone(timedelta(hours=8))
NOW = datetime.now(TPE)
TODAY = NOW.strftime("%Y-%m-%d")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
KEEP_DAYS = 60  # 歷史最多保留筆數(交易日);前端顯示取最近 30 筆
FORCE = os.environ.get("FORCE", "0") == "1"  # 手動觸發時可在假日強制執行

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PRODUCTS = {  # 期交所商品代碼 ↔ 三大法人報表中的商品名稱
    "TX":  {"name": "臺股期貨",     "label": "大台"},
    "MTX": {"name": "小型臺指期貨", "label": "小台"},
    "TMF": {"name": "微型臺指期貨", "label": "微台"},
}


# ---------- 小工具 ----------
def log(msg):
    print(f"[{datetime.now(TPE).strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(name, default):
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(name, obj):
    path = os.path.join(DATA_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    log(f"已寫入 {name}")


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def http_post(url, params, timeout=60, referer=None):
    data = urllib.parse.urlencode(params).encode("utf-8")
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/csv,application/csv,text/html,*/*",
    }
    if referer:
        # 期交所部分下載端點會檢查來源頁,沒帶 Referer 會回 HTML 錯誤頁
        headers["Referer"] = referer
        headers["Origin"] = "https://www.taifex.com.tw"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def decode_csv(raw):
    """期交所 CSV 可能是 Big5 或 UTF-8,逐一嘗試。"""
    for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
        try:
            text = raw.decode(enc)
            return list(csv.reader(io.StringIO(text)))
        except (UnicodeDecodeError, LookupError):
            continue
    raise ValueError("CSV 編碼無法辨識")


def num(s):
    """把 '1,234' '-' '' 之類的字串轉成數字,失敗回 None。"""
    if s is None:
        return None
    s = str(s).replace(",", "").replace(" ", "").strip()
    if s in ("", "-", "--"):
        return None
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return None


def col_index(header, *keywords):
    """在表頭裡找出包含全部關鍵字的欄位位置。"""
    for i, h in enumerate(header):
        h = (h or "").replace(" ", "")
        if all(k in h for k in keywords):
            return i
    return None


def date_chunks(start, end, span=25):
    """把日期區間切成每段不超過 span 天(期交所下載有區間上限)。"""
    chunks = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=span), end)
        chunks.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return chunks


def trim_history(rows):
    """依日期排序並只留最近 KEEP_DAYS 筆。"""
    rows.sort(key=lambda r: r["date"])
    return rows[-KEEP_DAYS:]


# ---------- 1. 期交所:三大法人 + 全市場未平倉 → 散戶多空比 ----------
def fetch_taifex_institutional(start, end):
    """回傳 {date: {商品名稱: {身份別: {'l':多方OI, 's':空方OI}}}}"""
    out = {}
    for s, e in date_chunks(start, end):
        raw = http_post("https://www.taifex.com.tw/cht/3/futContractsDateDown", {
            "queryStartDate": s.strftime("%Y/%m/%d"),
            "queryEndDate": e.strftime("%Y/%m/%d"),
            "commodityId": "",
        }, referer="https://www.taifex.com.tw/cht/3/futContractsDate")
        rows = decode_csv(raw)
        if not rows:
            continue
        header = rows[0]
        # 若回傳的是 HTML 錯誤頁,第一格會是 <!DOCTYPE...>,印出協助診斷
        if header and "<" in header[0]:
            log(f"三大法人回傳非 CSV(前80字): {raw[:80]}")
            continue
        i_date = col_index(header, "日期")
        i_prod = col_index(header, "商品名稱")
        i_role = col_index(header, "身份別") or col_index(header, "身分別")
        i_lo = col_index(header, "多方", "未平倉", "口數")
        i_so = col_index(header, "空方", "未平倉", "口數")
        if None in (i_date, i_prod, i_role, i_lo, i_so):
            log(f"三大法人 CSV 表頭不符預期: {header}")
            continue
        for r in rows[1:]:
            if len(r) <= max(i_lo, i_so):
                continue
            d = r[i_date].strip().replace("/", "-")
            prod = r[i_prod].strip()
            role = r[i_role].strip()
            lo, so = num(r[i_lo]), num(r[i_so])
            if lo is None or so is None:
                continue
            out.setdefault(d, {}).setdefault(prod, {})[role] = {"l": lo, "s": so}
        time.sleep(2)
    return out


def fetch_taifex_market_oi(code, start, end):
    """每日行情 → 全市場未沖銷契約數合計。回傳 {date: total_oi}"""
    out = {}
    for s, e in date_chunks(start, end):
        raw = http_post("https://www.taifex.com.tw/cht/3/futDataDown", {
            "down_type": "1",
            "commodity_id": code,
            "queryStartDate": s.strftime("%Y/%m/%d"),
            "queryEndDate": e.strftime("%Y/%m/%d"),
        }, referer="https://www.taifex.com.tw/cht/3/futDailyMarketReport")
        rows = decode_csv(raw)
        if not rows:
            continue
        header = rows[0]
        i_date = col_index(header, "交易日期")
        i_month = col_index(header, "到期月份")
        i_oi = col_index(header, "未沖銷契約")
        i_sess = col_index(header, "交易時段")
        if None in (i_date, i_month, i_oi):
            log(f"{code} 行情 CSV 表頭不符預期: {header}")
            continue
        for r in rows[1:]:
            if len(r) <= i_oi:
                continue
            month = r[i_month].strip()
            if "/" in month:           # 跳過價差組合
                continue
            if i_sess is not None and len(r) > i_sess:
                if "一般" not in r[i_sess]:   # 只計一般時段(盤後時段 OI 重複)
                    continue
            oi = num(r[i_oi])
            if oi is None:
                continue
            d = r[i_date].strip().replace("/", "-")
            out[d] = out.get(d, 0) + oi
        time.sleep(2)
    return out


def update_futures():
    data = load_json("futures.json", {"updated": "", "history": {}})
    hist = data.setdefault("history", {})
    for code in PRODUCTS:
        hist.setdefault(code, [])

    # 已有今天的資料就跳過
    done = all(h and h[-1]["date"] == TODAY for h in hist.values())
    if done:
        log("期貨資料今日已更新,跳過")
        return False

    # 需要回補的起點:取三商品中最舊的「最後日期」,沒有資料就抓 45 天
    last_dates = [h[-1]["date"] for h in hist.values() if h]
    if last_dates and len(last_dates) == len(PRODUCTS):
        start = datetime.strptime(min(last_dates), "%Y-%m-%d").date() + timedelta(days=1)
    else:
        start = (NOW - timedelta(days=45)).date()
    end = NOW.date()
    if start > end:
        return False

    log(f"抓取期貨資料 {start} ~ {end}")
    inst = fetch_taifex_institutional(start, end)
    if not inst:
        log("三大法人無新資料(可能是假日或尚未公布)")
        return False

    changed = False
    for code, meta in PRODUCTS.items():
        total_oi = fetch_taifex_market_oi(code, start, end)
        existing = {r["date"] for r in hist[code]}
        for d in sorted(inst.keys()):
            if d in existing:
                continue
            roles = inst[d].get(meta["name"])
            total = total_oi.get(d)
            if not roles or not total:
                continue
            inst_l = sum(v["l"] for v in roles.values())
            inst_s = sum(v["s"] for v in roles.values())
            retail_l = max(total - inst_l, 0)
            retail_s = max(total - inst_s, 0)
            ratio = round((retail_l - retail_s) / total * 100, 2) if total else 0
            simplify = {}
            for role, v in roles.items():
                key = "外資" if "外資" in role else ("投信" if "投信" in role else "自營商")
                simplify[key] = {"l": v["l"], "s": v["s"], "net": v["l"] - v["s"]}
            hist[code].append({
                "date": d, "total": total, "inst": simplify,
                "retail": {"l": retail_l, "s": retail_s,
                           "net": retail_l - retail_s, "ratio": ratio},
            })
            changed = True
        hist[code] = trim_history(hist[code])

    if changed:
        data["updated"] = NOW.strftime("%Y-%m-%d %H:%M")
        save_json("futures.json", data)
    return changed


# ---------- 2. 期交所:選擇權近月月選 + 下一個結算週選 ----------
def classify_contract(month_code):
    """判斷合約類型:'monthly'(純6碼數字月選) 或 'weekly'(含W週三選/F週五選)。"""
    code = month_code.strip()
    if code.isdigit() and len(code) == 6:
        return "monthly"
    if len(code) > 6 and (code[6] in ("W", "F")):  # 202606W2 / 202606F3
        return "weekly"
    return "other"


def update_options():
    data = load_json("options.json", {"updated": "", "date": "", "months": []})
    if data.get("date") == TODAY:
        log("選擇權資料今日已更新,跳過")
        return False

    end = NOW.date()
    start = end - timedelta(days=6)   # 抓近一週,取最新交易日
    raw = http_post("https://www.taifex.com.tw/cht/3/optDataDown", {
        "down_type": "1",
        "commodity_id": "TXO",
        "queryStartDate": start.strftime("%Y/%m/%d"),
        "queryEndDate": end.strftime("%Y/%m/%d"),
    }, referer="https://www.taifex.com.tw/cht/3/optDailyMarketReport")
    rows = decode_csv(raw)
    if not rows:
        log("選擇權無資料")
        return False
    header = rows[0]
    log(f"選擇權 CSV 表頭: {header}")   # 第一次執行時可確認欄位名稱
    i_date = col_index(header, "交易日期")
    i_month = col_index(header, "到期月份") or col_index(header, "契約月份")
    i_expiry = col_index(header, "契約到期日")   # 2025/12/8 起新增的欄位
    i_strike = col_index(header, "履約價")
    i_cp = col_index(header, "買賣權")
    i_oi = col_index(header, "未沖銷契約")
    i_sess = col_index(header, "交易時段")
    if None in (i_date, i_month, i_strike, i_cp, i_oi):
        log(f"選擇權 CSV 表頭不符預期: {header}")
        return False

    # {date: {month_code: {'expiry':到期日, 'strikes':{strike:{'c':oi,'p':oi}}}}}
    book = {}
    for r in rows[1:]:
        if len(r) <= i_oi:
            continue
        # 只取一般交易時段
        if i_sess is not None and len(r) > i_sess and "一般" not in r[i_sess]:
            continue
        month = r[i_month].strip()
        kind = classify_contract(month)
        if kind == "other":      # 排除無法辨識的合約
            continue
        strike = num(r[i_strike])
        oi = num(r[i_oi])
        if strike is None or oi is None:
            continue
        cp_raw = r[i_cp].strip().upper()
        cp = "c" if ("買" in cp_raw or "CALL" in cp_raw) else "p"
        d = r[i_date].strip().replace("/", "-")
        expiry = r[i_expiry].strip().replace("/", "-") if (i_expiry is not None and len(r) > i_expiry) else ""
        m = book.setdefault(d, {}).setdefault(month, {"expiry": expiry, "kind": kind, "strikes": {}})
        if expiry and not m["expiry"]:
            m["expiry"] = expiry
        m["strikes"].setdefault(strike, {"c": 0, "p": 0})[cp] = oi

    if not book:
        log("選擇權解析後無資料(可能是假日)")
        return False
    latest = max(book.keys())
    if latest == data.get("date") and not FORCE:
        log("選擇權最新資料與現有相同,跳過")
        return False

    day = book[latest]   # {month_code: {expiry, kind, strikes}}

    def expiry_key(mc):
        e = day[mc]["expiry"]
        return e if e else mc   # 沒有到期日欄位時退而用合約代碼排序

    # 近月月選:月選中到期日 >= 資料日的最近一個
    monthlies = [mc for mc in day if day[mc]["kind"] == "monthly"
                 and (not day[mc]["expiry"] or day[mc]["expiry"] >= latest)]
    monthlies.sort(key=expiry_key)
    near_monthly = monthlies[0] if monthlies else None

    # 下一個結算週選:週選中到期日「嚴格大於」資料日的最近一個
    #   (到期日 == 資料日 的當天結算合約要排除,例如範例中的 202606F2)
    weeklies = [mc for mc in day if day[mc]["kind"] == "weekly"
                and day[mc]["expiry"] and day[mc]["expiry"] > latest]
    weeklies.sort(key=expiry_key)
    next_weekly = weeklies[0] if weeklies else None

    selected = [mc for mc in (near_monthly, next_weekly) if mc]
    if not selected:
        log("選擇權找不到符合條件的合約")
        return False

    months = []
    for mc in selected:
        chain = day[mc]["strikes"]
        strikes = sorted(chain.keys())
        if not strikes:
            continue
        call_max = max(strikes, key=lambda k: chain[k]["c"])
        put_max = max(strikes, key=lambda k: chain[k]["p"])
        months.append({
            "month": mc,
            "kind": day[mc]["kind"],          # monthly / weekly
            "expiry": day[mc]["expiry"],
            "call_max": {"strike": call_max, "oi": chain[call_max]["c"]},
            "put_max": {"strike": put_max, "oi": chain[put_max]["p"]},
            "chain": [{"k": k, "c": chain[k]["c"], "p": chain[k]["p"]} for k in strikes],
        })

    log(f"選擇權選定合約: {selected}")
    save_json("options.json", {
        "updated": NOW.strftime("%Y-%m-%d %H:%M"),
        "date": latest,
        "months": months,
    })
    return True


# ---------- 3. 證交所:融資餘額 / 成交量 / 融資比例 ----------
def twse_json(url):
    raw = http_get(url)
    return json.loads(raw.decode("utf-8"))


def fetch_turnover_map(months):
    """FMTQIK 每月成交資訊 → {date: 成交金額(元)}。months 是 ['202606', ...]"""
    out = {}
    for ym in months:
        url = (f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
               f"?date={ym}01&response=json")
        try:
            j = twse_json(url)
        except Exception as e:
            log(f"FMTQIK {ym} 失敗: {e}")
            continue
        for row in j.get("data", []) or []:
            # 日期格式 民國 115/06/12
            try:
                y, m, d = row[0].split("/")
                d_iso = f"{int(y) + 1911}-{m}-{d}"
            except Exception:
                continue
            amt = num(row[2])
            if amt is not None:
                out[d_iso] = amt
        time.sleep(3)
    return out


def fetch_margin_day(date_iso):
    """MI_MARGN 單日信用交易統計 → (融資餘額仟元, 融資買進仟元) 或 None(假日)。"""
    ymd = date_iso.replace("-", "")
    url = (f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
           f"?date={ymd}&selectType=MS&response=json")
    try:
        j = twse_json(url)
    except Exception as e:
        log(f"MI_MARGN {date_iso} 失敗: {e}")
        return None
    tables = j.get("tables") or ([j] if j.get("data") else [])
    for t in tables:
        fields = t.get("fields") or []
        data = t.get("data") or []
        i_today = None
        for i, f in enumerate(fields):
            if "今日餘額" in str(f):
                i_today = i
        for row in data:
            name = str(row[0]) if row else ""
            if "融資金額" in name:
                buy = num(row[1])
                bal = num(row[i_today]) if i_today is not None else num(row[-1])
                if bal is not None:
                    return (bal, buy or 0)
    return None


def fetch_market_cap_recent():
    """上市公司總市值。來源:證交所首頁 API,回傳近 5 個交易日。
    格式: [["06/10",1410325.63],...,["06/16",1494422.39]]  單位:億元。
    回傳 {ISO日期: 市值(億)}。只給近數日,故僅最新幾天的槓桿比算得出。"""
    url = "https://www.twse.com.tw/rwd/homeApi/mkt_cap"
    try:
        raw = http_get(url)
        arr = json.loads(raw.decode("utf-8"))
    except Exception as e:
        log(f"市值 mkt_cap 抓取/解析失敗: {e}")
        return {}
    log(f"市值 mkt_cap 回傳: {str(arr)[:200]}")
    out = {}
    year = NOW.year
    for item in (arr or []):
        try:
            md, val = item[0], num(item[1])
        except (TypeError, IndexError):
            continue
        if val is None:
            continue
        # "06/16" → 補上年份;若月份大於當前月份(跨年初情境)則用去年
        try:
            mm, dd = md.replace("-", "/").split("/")
            y = year if int(mm) <= NOW.month else year - 1
            iso = f"{y}-{int(mm):02d}-{int(dd):02d}"
        except (ValueError, AttributeError):
            continue
        out[iso] = round(val, 1)
    return out


def update_margin():
    data = load_json("margin.json", {"updated": "", "rows": []})
    rows = data.setdefault("rows", [])
    if rows and rows[-1]["date"] == TODAY:
        log("融資資料今日已更新,跳過")
        return False

    end = NOW.date()
    start = end - timedelta(days=50)
    months = sorted({(start + timedelta(days=i)).strftime("%Y%m")
                     for i in range((end - start).days + 1)})
    turnover = fetch_turnover_map(months)
    if not turnover:
        log("FMTQIK 無資料")
        return False

    mktcap_map = fetch_market_cap_recent()   # {ISO: 市值億},僅近數日

    existing = {r["date"] for r in rows}
    targets = [d for d in sorted(turnover.keys()) if d not in existing]
    targets = targets[-30:]   # 單次最多補 30 個交易日
    changed = False
    for d in targets:
        res = fetch_margin_day(d)
        time.sleep(3)          # 證交所對頻繁請求敏感,務必放慢
        if res is None:
            continue
        bal_k, buy_k = res                  # 仟元
        amt = turnover[d]                    # 元
        bal_e = round(bal_k / 1e5, 1)        # 融資餘額(億元)
        mktcap = mktcap_map.get(d)           # 億元 或 None(僅近數日有)
        # 槓桿比 = 融資餘額 ÷ 上市總市值 ×100%
        leverage = round(bal_e / mktcap * 100, 3) if mktcap else None
        rows.append({
            "date": d,
            "balance": bal_e,                          # 融資餘額(億)
            "turnover": round(amt / 1e8, 1),           # 成交金額(億)
            "mktcap": mktcap,                          # 上市總市值(億)
            "leverage": leverage,                      # 融資餘額/總市值 %
        })
        changed = True

    # 對已存在但缺市值的最近幾筆,用本次抓到的 mktcap 補上
    for r in rows:
        if r.get("mktcap") is None and r["date"] in mktcap_map:
            r["mktcap"] = mktcap_map[r["date"]]
            r["leverage"] = round(r["balance"] / r["mktcap"] * 100, 3) if r["mktcap"] else None
            changed = True

    if changed:
        rows.sort(key=lambda r: r["date"])
        for i, r in enumerate(rows):
            r["change"] = round(r["balance"] - rows[i - 1]["balance"], 1) if i else 0
        data["rows"] = rows[-KEEP_DAYS:]
        data["updated"] = NOW.strftime("%Y-%m-%d %H:%M")
        save_json("margin.json", data)
    return changed


# ---------- 主流程 ----------
def main():
    if NOW.weekday() >= 5 and not FORCE:
        log("週末,不執行")
        return
    os.makedirs(DATA_DIR, exist_ok=True)
    results = {}
    for name, fn in (("期貨/散戶多空比", update_futures),
                     ("選擇權最大OI", update_options),
                     ("融資/成交量", update_margin)):
        try:
            results[name] = fn()
        except Exception as e:
            log(f"{name} 發生錯誤: {e}")
            results[name] = f"錯誤: {e}"
    log(f"執行結果: {results}")


if __name__ == "__main__":
    main()
