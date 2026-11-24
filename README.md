# allweather-data · 全天候投资指南 · 每日收盘数据

由 GitHub Actions 每个交易日（北京时间 20:00）自动运行 `snapshot.py` 抓取收盘快照并提交，
全天候投资指南页面启动时从 `raw.githubusercontent.com` 拉取这份 `market_snapshot.json` 热更新
A 股 / 黄金两张 20 年走势图、黄金估值卡与温度卡 —— 页面本身不需要重新发布。

## 内容

| 文件 | 说明 |
|---|---|
| `market_snapshot.json` | 收盘快照（中证 H30269、沪金主连 AU0、COMEX GC 年均价、布鲁斯黄金、温度计、AISC 元数据） |
| `snapshot.py` | 抓取脚本（纯标准库），Actions 与本地共用同一份 |
| `_aisc.json` | WGC 金矿全维持成本（AISC）年度序列与估值阈值 |
| `.github/workflows/daily.yml` | 定时任务：UTC 12:00（北京 20:00）+ 手动触发 |

## 手动触发

GitHub 仓库 → Actions → 每日收盘数据更新 → Run workflow。
