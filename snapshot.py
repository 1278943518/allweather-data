# -*- coding: utf-8 -*-
"""抓取页面首屏快照 → market_snapshot.json

页面打开时会自己去腾讯拉行情与前复权 K 线；这个脚本只负责生成「打开前就画得出来」
的兜底数据，断网 / 首次加载也不会白屏。

用法：
    python snapshot.py            # 全量刷新
    python snapshot.py gold       # 只刷一只

产出结构：
    {"ohlc": {"us": [[date,open,close,high,low], ...], ...},
     "bruce": {...黄金 COT / PCR / 金价 原样快照...}}
"""
import json
import os
import sys
import time
import urllib.request
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "market_snapshot.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "Chrome/120 Safari/537.36"}
HOSTS = ["https://web.ifzq.gtimg.cn", "https://ifzq.gtimg.cn"]
BRUCE = ["https://1278943518.github.io/gold-bruce/",
         "https://raw.githubusercontent.com/1278943518/gold-bruce/main/"]
# 美股 / A股温度计（八特征 520 周滚动分位）
TEMP = ["https://cdn.jsdelivr.net/gh/1278943518/ndx-bubble-daily@main/bubble_app/data.json"]
TEMP_LOCAL = [r"E://WorkBuddy//美股温度计//ndx_site//data.json"]
BEGIN = "2015-01-01"
CHUNK = 640  # 腾讯单次上限
# 中证指数官网（红利低波动 H30269）。curl 直连可用，浏览器侧被 CORS 锁死（ACAO 只给 csindex.com.cn），
# 所以页面里不发起请求，全靠这份构建时快照。
CSI = ("https://www.csindex.com.cn/csindex-home/perf/index-perf"
       "?indexCode=%s&startDate=%s&endDate=%s")


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def klines(symbol):
    """分段向前翻，凑满 2015 年以来的前复权日线。"""
    rows, end = [], None
    for _ in range(8):
        param = "%s,day,,%s,%d,qfq" % (symbol, end or "", CHUNK)
        data = None
        for host in HOSTS:
            try:
                raw = get("%s/appstock/app/fqkline/get?param=%s&_=%d"
                          % (host, param, int(time.time() * 1000)))
                data = json.loads(raw)["data"][symbol]
                break
            except Exception:
                continue
        if not data:
            break
        chunk = data.get("qfqday") or data.get("day") or []
        if not chunk:
            break
        keep = []
        for row in chunk:
            d = row[0]
            if rows and d >= rows[0][0]:
                continue
            keep.append([d, float(row[1]), float(row[2]), float(row[3]), float(row[4])])
        rows = keep + rows
        if not keep or rows[0][0] <= BEGIN or len(chunk) < CHUNK:
            break
        end = rows[0][0]
        time.sleep(0.2)
    return rows


def us_klines(symbol):
    """新浪美股日线一次给完整历史，只有收盘价 —— 用收盘价填满 ohlc 四列，
    页面按「收盘线」渲染（见 market_charts.js 的 smooth）。"""
    url = ("https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%%20_%s=/"
           "US_MinKService.getDailyK?symbol=%s&___qn=3" % (symbol, symbol))
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read().decode("gbk", "replace")
    lo, hi = raw.find("(["), raw.rfind("])")
    if lo < 0 or hi < 0:
        return []
    rows = []
    for item in json.loads(raw[lo + 1:hi + 1]):
        d, c = str(item.get("d") or ""), item.get("c")
        try:
            c = float(c)
        except Exception:
            continue
        if len(d) != 10 or c <= 0:
            continue
        rows.append([d, c, c, c, c])
    rows.sort(key=lambda x: x[0])
    return [r for r in rows if r[0] >= BEGIN]


def sina_fut(symbol):
    """新浪内盘期货日线（沪金主连 AU0）：有开高低收，2008-01 起。
    上期所黄金 2008 年才有连续合约，比 518880（2013-07）多 5 年半，且同为人民币/克。"""
    url = ("https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20_" + symbol +
           "=/InnerFuturesNewService.getDailyKLine?symbol=" + symbol)
    raw = get(url, 30)
    lo, hi = raw.find("(["), raw.rfind("])")
    if lo < 0 or hi < 0:
        return []
    rows = []
    for item in json.loads(raw[lo + 1:hi + 1]):
        try:
            d = str(item["d"])[:10]
            o, c, h, l = (float(item[k]) for k in ("o", "c", "h", "l"))
        except Exception:
            continue
        if len(d) != 10 or min(o, c, h, l) <= 0:
            continue
        rows.append([d, o, c, h, l])
    rows.sort(key=lambda x: x[0])
    return rows


# LBMA 金价年均（美元/盎司，公开常数）：补新浪 GC 只有 2016-11 之前的历史
LBMA_HIST = {2005: 445, 2006: 604, 2007: 695, 2008: 872, 2009: 972, 2010: 1225,
             2011: 1572, 2012: 1669, 2013: 1411, 2014: 1266, 2015: 1160, 2016: 1251}


def gc_usd():
    """新浪全球期货 COMEX 金（GC）日线：美元/盎司，2016-11 起。
    只为黄金估值卡服务：算「年内均价 vs WGC AISC」的年度对比。"""
    url = ("https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20_GC="
           "=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol=GC")
    raw = get(url, 30)
    lo, hi = raw.find("(["), raw.rfind("])")
    if lo < 0 or hi < 0:
        return None
    rows = []
    for item in json.loads(raw[lo + 1:hi + 1]):
        try:
            d = str(item["date"])[:10]
            o, c = float(item["open"]), float(item["close"])
            h, l = float(item["high"]), float(item["low"])
        except Exception:
            continue
        if len(d) == 10 and min(o, c, h, l) > 0:
            rows.append([d, o, c, h, l])
    if len(rows) < 300:
        return None
    rows.sort()
    acc = {}
    for r in rows:
        acc.setdefault(r[0][:4], []).append(r[2])
    # 不完整年份剔除（<200 个交易日），避免 2016 年那种只有两个月均价的假点
    years = sorted(y for y in acc if len(acc[y]) >= 200)
    avg = {int(y): round(sum(acc[y]) / len(acc[y])) for y in years}
    # LBMA 补前段（2016 及以前新浪没有完整年），重叠年以新浪实测为准
    for y, v in LBMA_HIST.items():
        avg.setdefault(y, v)
    years = sorted(avg)
    return {"years": years, "gold": [avg[y] for y in years],
            "last": [rows[-1][0], rows[-1][2]], "rows": rows}


def csi_klines(code, start="20050101"):
    """中证指数官网日线，只有收盘价 —— 四列填同一个值，页面按收盘线画（同 QQQ）。

    坑：返回的第一行日期 = 请求的 startDate，值是第一条真实记录的收盘价（伪造点）。
    这里按「与下一条间隔 > 21 天」把它丢掉；H30269 真实基日是 2005-12-30。
    """
    req = urllib.request.Request(
        CSI % (code, start, date.today().strftime("%Y%m%d")),
        headers=dict(UA, Referer="https://www.csindex.com.cn/"))
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.loads(r.read().decode("utf-8", "replace")).get("data") or []
    rows = []
    for item in data:
        d, c = str(item.get("tradeDate") or ""), item.get("close")
        try:
            c = float(c)
        except Exception:
            continue
        if len(d) != 8 or c <= 0:
            continue
        rows.append([d[:4] + "-" + d[4:6] + "-" + d[6:], c, c, c, c])
    rows.sort(key=lambda x: x[0])
    while len(rows) > 1:
        gap = (date.fromisoformat(rows[1][0]) - date.fromisoformat(rows[0][0])).days
        if gap <= 21:
            break
        rows.pop(0)
    return rows


def bruce():
    for base in BRUCE:
        try:
            d = json.loads(get(base + "data.json?_=%d" % int(time.time() * 1000), 25))
            if d.get("view", {}).get("dates"):
                return d
        except Exception:
            continue
    return None


def temp():
    for src in TEMP:
        try:
            d = json.loads(get(src + "?_=%d" % int(time.time() * 1000), 25))
            if d.get("week"):
                return d
        except Exception:
            continue
    for path in TEMP_LOCAL:
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
    return None


def pct_of(values, v, window=None):
    """v 在样本里的百分位（0-100），window 只取最近 N 个。"""
    sample = [x for x in (values[-window:] if window else values) if isinstance(x, (int, float))]
    if not sample:
        return None
    return round(100.0 * sum(1 for x in sample if x < v) / len(sample), 1)


def summarize(t):
    """只留页面要用的摘要，别把 1200 周原始序列塞进 HTML。"""
    w = t["week"]
    last = w[-1]
    s = {k: last.get(k) for k in ["d", "total", "ndx", "f5", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"]}
    s["total"] = round(float(s["total"] or 0), 1)
    s["d13"] = round(float(s["total"]) - float(w[-14]["total"]), 1) if len(w) > 13 else None
    s["pct"] = pct_of([x.get("total") for x in w], s["total"], 520)
    peak = max(w[-520:], key=lambda x: x.get("total") or 0)
    s["peak"] = round(float(peak["total"]), 1)
    s["peak_d"] = peak["d"]
    s["weeks"] = len(w)
    cn = (t.get("cn") or {}).get("records") or []
    c = dict(cn[-1]) if cn else {}
    c["val_pct"] = pct_of([x.get("val") for x in cn], c.get("val"))
    c["mkt_pct"] = pct_of([x.get("mkt") for x in cn], c.get("mkt"))
    c["n"] = len(cn)
    return {"us": s, "cn": c, "meta": t.get("meta", {})}


def main():
    want = sys.argv[1:] or ["us", "cn", "gold", "bond", "cnetf"]
    # us 用 QQQ（新浪美股日线）；cn 用中证红利低波动指数本身（2006 起 20.9 年）；
    # gold 用沪金主连 AU0（2008 起，人民币/克，有开高低收）；bond 仍是腾讯前复权
    symbols = {"us": "QQQ", "cn": "H30269", "gold": "AU0", "bond": "sh511260", "cnetf": "sh512890"}
    snap = {"ohlc": {}, "bruce": None}
    if os.path.exists(OUT):
        try:
            snap = json.load(open(OUT, encoding="utf-8"))
            snap.setdefault("ohlc", {})
        except Exception:
            pass
    for key in want:
        if key == "cn":
            rows = csi_klines(symbols[key])
        elif key == "gold":
            rows = sina_fut(symbols[key])
        elif key == "us":
            rows = us_klines(symbols[key])
        else:
            rows = klines(symbols[key])
        if len(rows) < 200:
            print("SKIP %-5s 数据不足 %d 根" % (key, len(rows)))
            continue
        snap["ohlc"][key] = (rows if key in ("us", "cn", "gold")
                             else ([r for r in rows if r[0] >= BEGIN] or rows))
        print("OK   %-5s %-9s %d 根  %s → %s"
              % (key, symbols[key], len(rows), rows[0][0], rows[-1][0]))
    b = bruce()
    if b:
        snap["bruce"] = b
        print("OK   bruce  gold %s / cot %s / pcr %s"
              % (b.get("gold_last"), b.get("cot_last"), b.get("pcr_last")))
    else:
        print("WARN bruce 抓取失败，保留旧快照")
    g = gc_usd()
    if g:
        snap["gest"] = g
        # COMEX GC 日线（美元/盎司）：黄金走势图的主基线，替代人民币口径的 AU0
        snap.setdefault("ohlc", {})["gcu"] = g["rows"]
        print("OK   gest   %d 年均价  最新 %s $%.1f  GC 日线 %d 根"
              % (len(g["years"]), g["last"][0], g["last"][1], len(g["rows"])))
    else:
        print("WARN gest 抓取失败，保留旧快照")
    t = temp()
    if t:
        summed = summarize(t)
        # 防回退：本次 temp 比已有快照还旧（jsdelivr 挂了落到本地旧文件）→ 保留旧值不覆盖
        old = snap.get("temp") or {}
        try:
            older = (summed["us"]["d"] < old.get("us", {}).get("d", "") and
                     summed["cn"]["d"] < old.get("cn", {}).get("d", ""))
        except Exception:
            older = False
        if older:
            print("WARN temp 本次数据更旧（美股 %s / A股 %s < 已有 %s/%s），保留旧值"
                  % (summed["us"]["d"], summed["cn"]["d"],
                     old.get("us", {}).get("d"), old.get("cn", {}).get("d")))
        else:
            snap["temp"] = summed
            u, c = snap["temp"]["us"], snap["temp"]["cn"]
            print("OK   temp   美股 %s %.1f（%+.1f 分） / A股 %s 市场 %.1f 价值 %.1f"
                  % (u["d"], u["total"], u["d13"], c["d"], c["mkt"], c["val"]))
    else:
        print("WARN temp 抓取失败，保留旧快照")
    # AISC 元数据随快照一起走（GitHub Actions 仓库里也有 _aisc.json），页面运行时热更新估值卡要用
    try:
        ais = json.load(open(os.path.join(BASE, "_aisc.json"), encoding="utf-8"))
        snap["aisc"] = {"current": ais.get("current"), "year": ais.get("current_year"),
                        "q": ais.get("as_of"), "series": ais.get("series", {}),
                        "dcut": ais["thresholds"]["downgrade"], "rcut": ais["thresholds"]["restore"]}
    except Exception:
        pass
    snap["meta"] = {"built": date.today().isoformat()}
    json.dump(snap, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("WROTE", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
