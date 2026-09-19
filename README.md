# 天津教师比赛速览 📢

面向天津中小学教师的比赛信息聚合应用：自动抓取国家级、天津市级、区级官方通知，
筛选与"教师参赛/评选"相关的内容，提取截止日期，生成手机可用的网页应用。

- **手机访问**：`https://<你的GitHub用户名>.github.io/teacher-competitions/`
- **更新频率**：GitHub Actions 每天北京时间 06:30 自动抓取，提交数据、同步网页

## 数据来源

| 层级 | 来源 | 栏目 |
|---|---|---|
| 国家级 | 教育部 | 教育要闻 |
| 国家级 | 中国教育学会 | 通知公告 |
| 天津市级 | 天津市教育委员会 | 通知公告 |
| 天津市级 | 天津市教科院 | 教研动态 |
| 区级 | 北辰区政府 | 通知公告 |
| 区级 | 北辰区教育局 | 教育栏目 |

筛选规则在 `scraper/scrape.py` 顶部的 `INCLUDE_RE` / `EXCLUDE_RE` 中维护，
可自行增删关键词、添加新的数据来源（`SOURCES` 列表）。

## 项目结构

```
index.html                 手机端网页应用（PWA，可添加到主屏幕）
manifest.json / sw.js      PWA 清单与离线缓存
data/competitions.json     抓取结果（每天由 Actions 自动更新）
scraper/scrape.py          抓取程序（来源配置、关键词、截止日期提取）
scraper/requirements.txt   Python 依赖
.github/workflows/update.yml  每日自动更新工作流
gen_icons.py               图标生成（本机运行一次即可）
run_local.bat              Windows 本机手动更新
```

## 本地手动更新（可选）

双击 `run_local.bat`，或在命令行执行：

```
python -m pip install -r scraper/requirements.txt
python scraper/scrape.py
```

## 添加新的数据来源

在 `scraper/scrape.py` 中：
1. 写一个解析函数（参考 `parse_moe` 等），返回 `[(标题, 链接, 日期), ...]`
2. 在 `SOURCES` 里加一条配置（name、level、parse、base、pages）
3. 提交后每天自动生效

## 免责声明

所有信息均转载自官方公开渠道，仅作个人参考；报名要求与截止时间
请以官方通知原文为准。
