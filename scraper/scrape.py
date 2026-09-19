# -*- coding: utf-8 -*-
"""
天津中小学教师比赛信息聚合抓取器
=================================
从以下官方来源抓取通知列表，按关键词筛选与"教师参赛/评选"相关的内容，
抓取详情页提取截止日期，与历史数据合并后写入 ../data/competitions.json

数据来源（均为官方发布渠道）：
  国家级 : 教育部教育要闻、中国教育学会通知公告
  天津市级: 天津市教委通知公告、天津市教科院教研动态
  区级  : 北辰区政府通知公告、北辰区教育局教育栏目

用法：
  python scrape.py            # 正常抓取
  python scrape.py --refresh  # 丢弃全部历史重新抓取
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DATA_FILE = os.path.join(DATA_DIR, "competitions.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 25
MAX_DETAIL_FETCH = 40          # 每轮最多抓取详情页数量（控制速度、礼貌抓取）
KEEP_DAYS = 150                # 发布超过该天数的条目将被清理
MAX_ITEMS = 1000

# ---------- 关键词过滤 ----------
# 标题中包含以下关键词才保留（教师参赛/评选相关）
INCLUDE_RE = re.compile(
    r"比赛|大赛|竞赛|征集|评选|遴选|精品课|课例|微课|说课|论文|展示|基本功|技能|"
    r"赛课|评优|申报|选拔|推荐|展评|观摩|教学设计|作业设计|优秀案例|评比|"
    r"成果奖|评审|优质课|教学成果"
)
# 对"新闻动态"类来源使用更严格的关键词（避免教研新闻混入）
STRICT_INCLUDE_RE = re.compile(
    r"比赛|大赛|竞赛|征集|评选|遴选|精品课|课例|微课|说课|论文|基本功|技能|"
    r"赛课|评优|申报|选拔|推荐|观摩|成果奖|评审|优质课"
)
# 与初中教师参赛无关的内容（可自行增删）
EXCLUDE_RE = re.compile(
    r"采购|招标|磋商|中标|成交|招聘|就业|简历|大学生|研究生|高校|职业院校|职校|"
    r"留学生|学前|幼儿园|近视|获奖名单|表彰|举报|夏令营|考试"
)
# 已结束活动的回顾性新闻 / 结果公布类新闻
RETRO_RE = re.compile(r"(成功|顺利|圆满)举办|圆满举行|圆满落幕|(于|在).{0,12}举办|公布")

# ---------- 截止日期提取 ----------
DEADLINE_RES = [
    re.compile(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?\s*(?:前|止|截止|之前)"),
    re.compile(r"截止(?:时间|日期)?\s*[:：]?\s*(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})"),
    re.compile(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*日?\s*(?:前完成|前提交|前报送|前上报|前上传|前申报|前报名)"),
    re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*前"),   # 无年份，用上下文推断
]
DEADLINE_DONE_RE = re.compile(r"截至|已于.{0,6}(截止|结束)|(报名|申报|提交).{0,10}(截止|结束)")

LEVEL_ORDER = {"national": 0, "city": 1, "district": 2, "society": 3}
STATUS_ORDER = {"报名中": 0, "进行中": 1, "公示": 2, "已截止": 3}


def http_get(url, tries=2):
    """带重试与编码自动识别的 GET，返回 BeautifulSoup。失败抛异常。"""
    last_err = None
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, verify=True)
            if r.status_code != 200:
                raise RuntimeError("HTTP %s" % r.status_code)
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser")
        except requests.exceptions.SSLError:
            # 个别政务站点证书链不全，降级重试一次
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, verify=False)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                return BeautifulSoup(r.text, "html.parser")
            last_err = RuntimeError("HTTP %s" % r.status_code)
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5)
    raise last_err


# ---------- 各来源列表页解析 ----------
# 均返回 [(title, url, date_str, inline_text|None), ...]
# inline_text 为列表页自带的摘要/全文（若有），可免抓详情页直接提取截止日期

def parse_moe(soup, base):
    items = []
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        span = li.find("span")
        if not (a and span):
            continue
        m = re.fullmatch(r"\s*(20\d{2})-(\d{2})-(\d{2})\s*", span.get_text())
        href = a["href"]
        if m and re.search(r"\.html$", href):
            items.append((a.get_text(strip=True), urljoin(base, href),
                          "%s-%s-%s" % m.groups(), None))
    return items


def parse_cse(soup, base):
    items = []
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        span = li.find("span")
        if not (a and span):
            continue
        m = re.fullmatch(r"\s*(20\d{2})-(\d{2})-(\d{2})\s*", span.get_text())
        if m and "detail.html" in a["href"]:
            items.append((a.get_text(strip=True), urljoin(base, a["href"]),
                          "%s-%s-%s" % m.groups(), None))
    return items


def parse_jy(soup, base):
    items = []
    for li in soup.find_all("li"):
        a = li.find("a", onclick=True)
        if not a:
            continue
        m = re.search(r"isDownLoad\(this,\s*'([^']+)'\)", a["onclick"])
        if not m:
            continue
        url = m.group(1)
        ymd = re.search(r"/(20\d{2})(\d{2})/", url)
        pd = li.find("p", class_="list-date")
        if not (ymd and pd):
            continue
        dm = re.search(r"(20\d{2})-(\d{2})-(\d{2})", pd.get_text())
        if not dm:
            continue
        # 列表页自带正文摘要（hidDom.text），直接用于截止日期提取
        inline = ""
        hid = li.find("div", class_="hidDom")
        if hid:
            t = hid.find("span", class_="text")
            inline = t.get_text(" ", strip=True) if t else ""
        items.append((a.get("title", "").strip(), url,
                      "%s-%s-%s" % (dm.group(1), dm.group(2), dm.group(3)),
                      inline or None))
    return items


def parse_tjjky(soup, base):
    items = []
    for a in soup.find_all("a", href=True):
        if "show.jsp" not in a["href"] or not a.get("title"):
            continue
        title = a["title"].strip()
        date_txt = ""
        row = a.find_parent("tr") or a.find_parent("td")
        if row:
            spans = row.find_all("span")
            for s in spans:
                if re.fullmatch(r"\s*20\d{2}\.\d{2}\.\d{2}\s*", s.get_text()):
                    date_txt = s.get_text(strip=True).replace(".", "-")
                    break
        if date_txt and "我院简介" not in title and "领导班子" not in title:
            items.append((title, urljoin(base, a["href"]), date_txt, None))
    return items


def parse_tjbc(soup, base):
    items = []
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        if not re.search(r"t20\d{6}_\d+\.html", href):
            continue
        title = a.get_text(strip=True).lstrip("· ")
        date_txt = ""
        span = li.find("span", class_="date")
        if span:
            m = re.fullmatch(r"\s*(20\d{2}-\d{2}-\d{2})\s*", span.get_text())
            date_txt = m.group(1) if m else ""
        if title and date_txt:
            items.append((title, urljoin(base, href), date_txt, None))
    return items


def parse_tjbc_jyj(soup, base):
    items = []
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        b = li.find("b")
        if not (a and b):
            continue
        href = a["href"]
        if not re.search(r"t20\d{6}_\d+\.html", href):
            continue
        title = a.get_text(strip=True).lstrip("· ")
        m = re.fullmatch(r"\s*(20\d{2}-\d{2}-\d{2})\s*", b.get_text())
        if title and m:
            items.append((title, urljoin(base, href), m.group(1), None))
    return items


def parse_eol(soup, base):
    items = []
    for div in soup.find_all("div", class_="list"):
        fa = div.find("div", class_="fline")
        a = fa.find("a", href=True) if fa else None
        t = div.find("span", class_="time")
        if not (a and t):
            continue
        m = re.fullmatch(r"\s*(20\d{2}-\d{2}-\d{2})\s*", t.get_text())
        if m:
            items.append((a.get_text(strip=True), urljoin(base, a["href"]),
                          m.group(1), None))
    return items


# ---------- 来源配置 ----------
# pages: 抓取的列表页（None 表示栏目首页）；strict: 使用更严格的标题关键词
SOURCES = [
    dict(name="教育部", level="national", parse=parse_moe, strict=False,
         base="https://www.moe.gov.cn/jyb_xwfb/gzdt_gzdt/s5987/",
         pages=[None, "index_2.html", "index_3.html"]),
    dict(name="中国教育在线", level="national", parse=parse_eol, strict=False,
         base="https://www.eol.cn/news/yaowen/",
         pages=[None]),
    dict(name="中国教育学会", level="society", parse=parse_cse, strict=False,
         base="http://www.cse.edu.cn/index/index.html?category=118",
         pages=["", "?category=118&page=2", "?category=118&page=3"]),
    dict(name="天津市教育委员会", level="city", parse=parse_jy, strict=False,
         base="https://jy.tj.gov.cn/ZWGK_52172/TZGG/",
         pages=[None]),
    dict(name="天津市教科院", level="city", parse=parse_tjjky, strict=True,
         base="https://tjjky.tj.edu.cn/list.jsp?classid=202204110908009887",
         pages=[None]),
    dict(name="北辰区政府", level="district", parse=parse_tjbc, strict=False,
         base="https://www.tjbc.gov.cn/zwgk/tzgg/",
         pages=[None, "index_1.html"]),
    dict(name="北辰区教育局", level="district", parse=parse_tjbc_jyj, strict=False,
         base="https://www.tjbc.gov.cn/zwgk/zfxxgk/xxgk_wbj/zjyq_xxgk_jyj/"
               "xxgk_fdzdgk_jyj/xxgk_zdmsxx_jyj/xxgk_jy_jyj/",
         pages=[None, "index_1.html"]),
]


def scrape_lists():
    """抓取所有来源的列表，返回 [(title, url, date_str, inline_text, source_name, level, strict), ...]"""
    out = []
    for src in SOURCES:
        name, level, strict = src["name"], src["level"], src.get("strict", False)
        got_any = False
        for page in src["pages"]:
            url = src["base"] if page is None else urljoin(src["base"], page)
            try:
                soup = http_get(url)
                items = src["parse"](soup, src["base"])
                for title, link, d, inline in items:
                    out.append((title, link, d, inline, name, level, strict))
                got_any = True
            except Exception as e:  # noqa: BLE001
                print("  [警告] %s %s 抓取失败: %s" % (name, url, e), file=sys.stderr)
        if got_any:
            print("  [OK] %-10s 抓取完成" % name)
    return out


def keep_item(title, strict=False):
    if RETRO_RE.search(title):
        return False
    if EXCLUDE_RE.search(title):
        return False
    rx = STRICT_INCLUDE_RE if strict else INCLUDE_RE
    return bool(rx.search(title))


def extract_deadline(text):
    """从详情页文本中提取截止日期，返回 (date|None, 来源片段)"""
    # 缩小范围：取正文前 8000 字符
    text = text[:8000]
    found = []  # (date, priority, context)
    for rx in DEADLINE_RES:
        for m in rx.finditer(text):
            y, mo, d = (m.groups() + (None,))[:3] if len(m.groups()) >= 3 else (None,) + m.groups()[:2]
            if y is None:
                y = date.today().year
                if int(mo) < date.today().month:
                    y += 1
            try:
                dt = date(int(y), int(mo), int(d))
            except ValueError:
                continue
            if dt.year < 2020 or dt.year > 2035:
                continue
            ctx = text[max(0, m.start() - 12): m.end() + 8]
            found.append((dt, ctx))
    if not found:
        return None
    today = date.today()
    future = [f for f in found if f[0] >= today]
    if future:
        return min(f[0] for f in future)
    return max(f[0] for f in found)


def detail_text(url):
    soup = http_get(url, tries=2)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def calc_status(title, deadline):
    if "公示" in title:
        return "公示"
    if deadline:
        try:
            dl = date.fromisoformat(str(deadline))
            return "报名中" if dl >= date.today() else "已截止"
        except ValueError:
            pass
    return "进行中"


def load_history():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {it["url"]: it for it in data.get("items", [])}
    except Exception:  # noqa: BLE001
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="丢弃历史数据重新抓取")
    args = parser.parse_args()

    t0 = time.time()
    print("开始抓取 %s ..." % datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"))

    raw = scrape_lists()

    # 去重（按URL）+ 关键词过滤
    seen, fresh = set(), {}
    for title, url, d, inline, src_name, level, strict in raw:
        if url in seen:
            continue
        seen.add(url)
        if not keep_item(title, strict):
            continue
        try:
            pd = date.fromisoformat(d)
        except ValueError:
            continue
        fresh[url] = dict(title=title, url=url, source=src_name, level=level,
                          publish_date=pd.isoformat(), deadline=None, status="",
                          _inline=inline)

    print("筛选后候选 %d 条，开始提取截止日期..." % len(fresh))
    history = {} if args.refresh else load_history()
    fetched = 0
    for url, it in fresh.items():
        old = history.get(url)
        # 新条目 或 尚无截止日期且未明确结束的旧条目 → 提取截止日期
        need = old is None or (not old.get("deadline") and old.get("status") not in ("已截止",))
        if not need:
            it.pop("_inline", None)
            continue
        # 优先用列表页自带的摘要/全文，其次抓详情页
        text = it.pop("_inline", None)
        try:
            if text:
                dl = extract_deadline(text)
            else:
                if fetched >= MAX_DETAIL_FETCH:
                    continue
                text = detail_text(url)
                fetched += 1
                time.sleep(0.4)
                dl = extract_deadline(text)
            it["deadline"] = dl.isoformat() if dl else None
        except Exception as e:  # noqa: BLE001
            print("  [警告] 详情页抓取失败 %s: %s" % (url, e), file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print("  [警告] 详情页抓取失败 %s: %s" % (url, e), file=sys.stderr)

    # 与历史合并：保留本轮未再出现的旧条目（来源临时故障也不丢数据）
    merged = dict(history)
    for url, it in fresh.items():
        old = merged.get(url)
        if old:
            it["deadline"] = it.get("deadline") or old.get("deadline")
        merged[url] = it

    # 清理过期条目、更新状态、排序
    cutoff = date.today() - timedelta(days=KEEP_DAYS)
    items = []
    for url, it in merged.items():
        try:
            pd = date.fromisoformat(it["publish_date"])
        except ValueError:
            pd = date.today()
        if pd < cutoff:
            continue
        it["status"] = calc_status(it["title"], it.get("deadline"))
        items.append(it)
    # 先按发布日期倒序，再按状态置顶（稳定排序：组内仍保持日期倒序）
    items.sort(key=lambda x: x["publish_date"], reverse=True)
    items.sort(key=lambda x: STATUS_ORDER.get(x["status"], 9))
    items = items[:MAX_ITEMS]

    payload = {
        "updated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="minutes"),
        "count": len(items),
        "open_count": sum(1 for i in items if i["status"] == "报名中"),
        "items": items,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print("完成：共 %d 条（其中报名中 %d 条），耗时 %.1f 秒" %
          (len(items), payload["open_count"], time.time() - t0))


if __name__ == "__main__":
    main()
