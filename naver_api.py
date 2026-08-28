"""
naver_api.py - Naver Cafe / 博客挖掘引擎（KOL Finder 第二数据源）

两条数据通道：
1. Naver 官方搜索 API（需要免费的 Client ID / Secret，developers.naver.com 申请）
   - cafearticle：搜 cafe 帖子（标题/链接/카페명，不含发帖人）
   - blog：搜博客帖（含博主名 bloggername + 博客地址 bloggerlink + 发帖日期）
2. 公开页面抓取（不需要任何 key）
   - m.blog.naver.com/{blogId} 博客主页 → 邻居数（"N명의 이웃"）、博客名、简介
   - cafe.naver.com 公开帖子页 → 发帖人昵称、成员页链接、cafe 名、正文摘录
   （cafe 成员个人页是 JS 渲染，不登录抓不到，因此不做深挖）

候选统一整形成和 YouTube 频道兼容的 dict（channel_id 以 NV 开头），
复用现有的 AI 定垂类 / 入库 / 状态流 / BD 邮件链路。
"""

import hashlib
import html as html_lib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

NAVER_API_BASE = "https://openapi.naver.com/v1/search"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15")

# 每次挖掘最多抓正文的帖子数 / 补博客数据的博主数（控制耗时和请求量）
MAX_POSTER_FETCH = 24
MAX_BLOG_ENRICH = 30

# 公司网络直连 Naver 会被拦：未手动配代理时，直连失败自动回退到这个本地代理
FALLBACK_PROXY = "socks5h://127.0.0.1:13659"
_fallback_ok = None  # 记住回退是否有效，有效就直接走代理，不再每次先等直连超时


# ============================================================
# 基础请求
# ============================================================

def _proxies(proxy: str) -> dict | None:
    proxy = (proxy or "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _get(url: str, proxy: str = "", timeout: int = 12, headers: dict = None,
         referer: str = None) -> requests.Response | None:
    """带重试的 GET。未配代理且直连失败时（公司网络拦 Naver），自动回退本地代理。
    Naver 对代理 IP 偶尔弹密码确认页，重试一次常能过。"""
    global _fallback_ok
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    if headers:
        h.update(headers)
    use_proxy = (proxy or "").strip()
    if not use_proxy and _fallback_ok is True:
        use_proxy = FALLBACK_PROXY  # 已知直连不通，直接走代理，不浪费时间
    for attempt in range(2):
        try:
            r = requests.get(url, headers=h, timeout=timeout, proxies=_proxies(use_proxy))
            if r.status_code == 200:
                if not (proxy or "").strip() and use_proxy:
                    _fallback_ok = True
                return r
            if r.status_code in (429, 503) and attempt == 0:
                time.sleep(1.5)
                continue
            return r
        except requests.RequestException:
            if not use_proxy and not (proxy or "").strip():
                use_proxy = FALLBACK_PROXY  # 直连失败 → 自动试本地代理
                continue
            if attempt == 0:
                time.sleep(1.0)
    return None


# ============================================================
# 官方搜索 API（需要 Client ID / Secret）
# ============================================================

def naver_ready(client_id: str, client_secret: str) -> bool:
    return bool((client_id or "").strip() and (client_secret or "").strip())


def _api_search(api_type: str, query: str, client_id: str, client_secret: str,
                display: int = 100, start: int = 1, sort: str = "sim",
                proxy: str = "") -> tuple[list, str]:
    """调 Naver 搜索 API。返回 (items, 错误信息)。api_type: cafearticle / blog / webkr"""
    if not naver_ready(client_id, client_secret):
        return [], "未配置 Naver Client ID / Secret"
    url = f"{NAVER_API_BASE}/{api_type}.json"
    params = {"query": query, "display": min(display, 100),
              "start": min(max(start, 1), 1000), "sort": sort}
    try:
        r = requests.get(url, params=params, timeout=15, proxies=_proxies(proxy),
                         headers={"X-Naver-Client-Id": client_id.strip(),
                                  "X-Naver-Client-Secret": client_secret.strip()})
    except requests.RequestException as e:
        return [], f"网络错误：{e}"
    if r.status_code == 401:
        return [], "Client ID / Secret 不对，请检查（developers.naver.com → 我的应用）"
    if r.status_code == 429:
        return [], "调用太频繁，稍后再试（免费额度每天 25,000 次）"
    if r.status_code != 200:
        return [], f"API 返回 {r.status_code}"
    try:
        return r.json().get("items", []), ""
    except (ValueError, KeyError):
        return [], "API 返回格式异常"


def search_cafe_articles(query: str, client_id: str, client_secret: str,
                         pages: int = 3, sort: str = "sim", proxy: str = "") -> tuple[list, str]:
    """搜 cafe 帖子。返回去重后的 [{title, link, description, cafename, cafeurl}]"""
    out, seen, err = [], set(), ""
    for p in range(pages):
        items, err = _api_search("cafearticle", query, client_id, client_secret,
                                 display=100, start=p * 100 + 1, sort=sort, proxy=proxy)
        if err:
            break
        for it in items:
            link = (it.get("link") or "").split("?")[0]
            if not link or link in seen:
                continue
            seen.add(link)
            out.append({
                "title": html_lib.unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))).strip(),
                "link": link,
                "description": html_lib.unescape(
                    re.sub(r"<[^>]+>", "", it.get("description", ""))).strip()[:200],
                "cafename": (it.get("cafename") or "").strip(),
                "cafeurl": (it.get("cafeurl") or "").strip(),
            })
        if len(items) < 100:
            break
        time.sleep(0.2)
    return out, err


def search_blog_posts(query: str, client_id: str, client_secret: str,
                      pages: int = 3, sort: str = "sim", proxy: str = "") -> tuple[list, str]:
    """搜博客帖。返回 [{title, link, description, bloggername, bloggerlink, postdate}]"""
    out, err = [], ""
    for p in range(pages):
        items, err = _api_search("blog", query, client_id, client_secret,
                                 display=100, start=p * 100 + 1, sort=sort, proxy=proxy)
        if err:
            break
        for it in items:
            out.append({
                "title": html_lib.unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))).strip(),
                "link": (it.get("link") or "").strip(),
                "description": html_lib.unescape(
                    re.sub(r"<[^>]+>", "", it.get("description", ""))).strip()[:200],
                "bloggername": (it.get("bloggername") or "").strip(),
                "bloggerlink": (it.get("bloggerlink") or "").rstrip("/"),
                "postdate": (it.get("postdate") or "").strip(),  # YYYYMMDD
            })
        if len(items) < 100:
            break
        time.sleep(0.2)
    return out, err


# ============================================================
# 公开页面抓取（不需要 key）
# ============================================================

def parse_blog_id(url_or_id: str) -> str:
    """从各种博客 URL / 裸 ID 里提取 blogId。识别不了返回空串。"""
    s = (url_or_id or "").strip()
    if not s:
        return ""
    # 裸 blogId：仅 ASCII 字母数字下划线连字符（韩文/中文昵称不算，走昵称找博客）
    if re.fullmatch(r"[A-Za-z0-9_\-]+", s):
        return s
    m = re.search(r"blogId=([A-Za-z0-9_\-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"(?:m\.)?blog\.naver\.com/([A-Za-z0-9_\-]+)", s)
    if m and m.group(1) not in ("PostView", "PostList", "ProfileView"):
        return m.group(1)
    return ""


def get_blog_stats(blog_id: str, proxy: str = "", timeout: int = 20) -> dict | None:
    """抓博客主页（公开，不需登录）。返回 {blog_id, name, neighbors, description}。
    邻居数 = 博客的「粉丝数」，只用于门槛筛选。失败返回 None。"""
    blog_id = parse_blog_id(blog_id)
    if not blog_id:
        return None
    r = _get(f"https://m.blog.naver.com/{blog_id}", proxy=proxy, timeout=timeout)
    if r is None or r.status_code != 200:
        return None
    html = r.text
    m = re.search(r"([\d,]+)\s*명의 이웃", html)
    if not m:
        return None  # 页面结构变了或博客不存在
    neighbors = int(m.group(1).replace(",", ""))
    name = ""
    t = re.search(r"<title>(.*?)</title>", html, re.S)
    if t:
        name = t.group(1).replace(" : 네이버 블로그", "").replace(" : NAVER 블로그", "").strip()
    desc = ""
    d = re.search(r'property="og:description" content="([^"]*)"', html)
    if d:
        desc = html_lib.unescape(d.group(1)).replace("\n", " ").strip()[:200]
    return {"blog_id": blog_id, "name": name, "neighbors": neighbors, "description": desc}


def _decode_cafe(r: requests.Response) -> str:
    try:
        return r.content.decode("cp949", errors="ignore")
    except Exception:
        return r.text


def fetch_cafe_article(url: str, proxy: str = "", timeout: int = 20,
                       cafe_name_fallback: str = "") -> dict | None:
    """抓 cafe 公开帖子（不需登录）拿发帖人。
    帖子页是框架页：先抓外壳拿 clubid，再抓 ArticleRead 正文页拿作者/标题
    （作者信息嵌在 JS 字符串里，引号带转义）。
    返回 {title, poster, member_url, club_id, cafe_name, excerpt}；
    帖子需登录 / 被删 / Naver 密码页拦截时返回 None。"""
    m = re.match(r"https?://(?:m\.)?cafe\.naver\.com/([A-Za-z0-9_\-]+)/(\d+)", url or "")
    if not m:
        return None
    article_id = m.group(2)

    # 第 1 步：外壳页拿 clubid
    r = _get(url, proxy=proxy, timeout=timeout)
    if r is None or r.status_code != 200:
        return None
    html = _decode_cafe(r)
    cm = re.search(r"clubid=(\d+)", html)
    if not cm:
        return None
    club_id = cm.group(1)

    # 第 2 步：正文页拿作者（密码页重试——Naver 对变动 IP 的偶发拦截）
    art_url = f"https://cafe.naver.com/ArticleRead.naver?clubid={club_id}&articleid={article_id}"
    art_html = None
    for attempt in range(3):
        ra = _get(art_url, proxy=proxy, timeout=timeout, referer=url)
        if ra is None or ra.status_code != 200:
            return None
        h = _decode_cafe(ra)
        if "비밀번호를 확인해 주세요" not in h:
            art_html = h
            break
        time.sleep(1.0 + attempt)
    if art_html is None:
        return None

    pm = re.search(
        r'작성자</strong>\s*<a href=\\?"(https://cafe\.naver\.com/ca-fe/cafes/(\d+)/members/[^"\\]+)\\?"'
        r'[^>]*>([^<]+)</a>', art_html)
    if not pm:
        return None
    member_url, poster = pm.group(1), pm.group(3).strip()

    # 标题：优先 title 标签「帖子名(cafe名) : 네이버 카페」，否则正文 tit-box
    title, cafe_name = "", (cafe_name_fallback or "").strip()
    t = re.search(r"<title>(.*?)</title>", art_html, re.S)
    if t:
        raw_title = html_lib.unescape(t.group(1)).strip()
        tm = re.match(r"(.*)\((.*?)\)\s*:\s*네이버 카페", raw_title)
        if tm:
            title, cafe_name = tm.group(1).strip(), tm.group(2).strip()
        elif raw_title and raw_title != "카페":
            title = raw_title.replace(" : 네이버 블로그", "").strip()
    if not title:
        tm2 = re.search(r'class="b m-tcol-c">([^<]+)<', art_html)
        if tm2:
            title = html_lib.unescape(tm2.group(1)).strip()

    # 正文摘录：去标签后的前 300 字（给 AI 判断内容用）
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", art_html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    return {"title": title, "poster": poster, "member_url": member_url,
            "club_id": club_id, "cafe_name": cafe_name, "excerpt": text[:300]}


def find_blog_by_nickname(nickname: str, client_id: str, client_secret: str,
                          proxy: str = "") -> str:
    """用昵称搜博客，找到同名博主就返回她的主页链接（cafe 昵称常和博客同名）。
    找不到返回空串。"""
    if not naver_ready(client_id, client_secret) or not (nickname or "").strip():
        return ""
    items, _ = _api_search("blog", nickname.strip(), client_id, client_secret,
                           display=20, sort="sim", proxy=proxy)
    for it in items:
        if (it.get("bloggername") or "").strip() == nickname.strip():
            link = (it.get("bloggerlink") or "").rstrip("/")
            if link:
                return link
    return ""


# ============================================================
# 候选构造（整形成与 YouTube 频道兼容的 dict）
# ============================================================

def _nv_id(prefix: str, key: str) -> str:
    return f"{prefix}_{hashlib.md5(key.encode('utf-8')).hexdigest()[:12]}"


def naver_scores(relevance) -> dict:
    """Naver 候选的评分：只按 AI 相关度计总分（邻居数只做门槛，不进分）。"""
    try:
        rel = max(0, min(100, int(round(float(relevance)))))
    except (TypeError, ValueError):
        rel = 50
    return {"relevance_raw": rel, "relevance": rel,
            "data_health_raw": 0, "data_health": 0,
            "frequency_raw": 0, "frequency": 0,
            "commercial_raw": 0, "commercial": 0,
            "total": rel}


def make_blogger_candidate(blogger: dict, stats: dict | None, posts: list) -> dict:
    """博主型候选（来自博客搜索 API，有邻居数）"""
    blog_id = parse_blog_id(blogger.get("home") or "")
    titles = [p["title"] for p in posts if p.get("title")][:6]
    descs = " / ".join(p["description"] for p in posts[:2] if p.get("description"))[:250]
    c = {
        "channel_id": f"NVB_{blog_id}",
        "channel_name": blogger.get("name", ""),
        "channel_url": blogger.get("home", ""),
        "about_url": "",
        "description": f"[Naver博客] {stats.get('description', '') if stats else ''} {descs}".strip(),
        "subscribers": stats.get("neighbors", 0) if stats else 0,
        "neighbors_known": bool(stats),
        "recent_titles": titles,
        "platform": "naver_blog",
        "source": "blog_search",
        "post_count": len(posts),
        "last_post": max((p.get("postdate", "") for p in posts), default=""),
        "emails": [],
    }
    return c


def make_cafe_candidate(person: dict) -> dict:
    """cafe 活跃成员型候选（来自帖子页抓取，邻居数待补）"""
    titles = person.get("titles", [])[:6]
    c = {
        "channel_id": _nv_id("NVC", person["member_url"]),
        "channel_name": person.get("name", ""),
        "channel_url": person.get("member_url", ""),
        "about_url": "",
        "description": ("[Naver Cafe] " + "、".join(sorted(person.get("cafes", set())))
                        + f"｜帖子摘录：{person.get('excerpt', '')[:180]}").strip(),
        "subscribers": person.get("neighbors", 0),
        "neighbors_known": bool(person.get("neighbors")),
        "recent_titles": titles,
        "platform": "naver_cafe",
        "source": "cafe_posts",
        "cafe_names": sorted(person.get("cafes", set())),
        "post_count": person.get("count", len(titles)),
        "article_links": person.get("links", [])[:5],
        "emails": [],
    }
    if person.get("blog_home"):
        c["blog_home"] = person["blog_home"]
        c["about_url"] = person["blog_home"]
    return c


# ============================================================
# 主流程：关键词挖掘
# ============================================================

def mine_by_keyword(keyword: str, client_id: str, client_secret: str, proxy: str = "",
                    fetch_posters: bool = True, enrich_blogs: bool = True,
                    match_cafe_blogs: bool = True, progress_cb=None) -> dict:
    """一次完整挖掘：
    1) cafearticle API 搜帖子 → 抓帖子页拿发帖人 → 按人聚合（cafe 候选）
    2) blog API 搜帖子 → 按博主聚合 → 抓博客主页拿邻居数（博主候选）
    3) cafe 候选用同名昵称找博客，找到就补邻居数
    返回 {cafe_candidates, blogger_candidates, cafe_posts, errors}
    """
    def _say(m):
        if progress_cb:
            try:
                progress_cb(m)
            except Exception:
                pass

    errors = []
    has_key = naver_ready(client_id, client_secret)

    # ---------- 1. cafe 帖子 ----------
    cafe_posts, err = ([], "未配置 Naver Key") if not has_key else search_cafe_articles(
        keyword, client_id, client_secret, pages=3, proxy=proxy)
    if err:
        errors.append(f"cafe搜索：{err}")
    _say(f"cafe 帖子 {len(cafe_posts)} 条")

    people = {}  # member_url -> person
    if fetch_posters and cafe_posts:
        batch = cafe_posts[:MAX_POSTER_FETCH]
        _say(f"正在打开帖子页识别发帖人（{len(batch)} 条）…")
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(fetch_cafe_article, p["link"], proxy, 20,
                              p.get("cafename", "")): p for p in batch}
            for fut in as_completed(futs):
                p = futs[fut]
                try:
                    info = fut.result()
                except Exception:
                    info = None
                if not info:
                    continue
                person = people.setdefault(info["member_url"], {
                    "name": info["poster"], "member_url": info["member_url"],
                    "cafes": set(), "titles": [], "links": [], "excerpt": "",
                    "count": 0, "neighbors": 0})
                if info["cafe_name"]:
                    person["cafes"].add(info["cafe_name"])
                if p["title"] and p["title"] not in person["titles"]:
                    person["titles"].append(p["title"])
                if p["link"] not in person["links"]:
                    person["links"].append(p["link"])
                person["count"] += 1
                if not person["excerpt"]:
                    person["excerpt"] = info.get("excerpt", "")

    cafe_candidates = [make_cafe_candidate(p) for p in people.values()]

    # ---------- 2. 博主 ----------
    blogger_candidates = []
    if has_key:
        blog_posts, err2 = search_blog_posts(keyword, client_id, client_secret,
                                             pages=3, proxy=proxy)
        if err2:
            errors.append(f"博客搜索：{err2}")
        _say(f"博客帖 {len(blog_posts)} 条，正在按博主聚合…")
        bloggers = {}
        for p in blog_posts:
            home = (p.get("bloggerlink", "") or "").rstrip("/")
            # 同一博主的 blog.naver.com 与 m.blog.naver.com 归一，避免聚成两人
            home = re.sub(r"^https?://m\.blog\.naver\.com", "https://blog.naver.com", home)
            if not home:
                continue
            b = bloggers.setdefault(home, {"name": p["bloggername"], "home": home,
                                           "posts": []})
            b["posts"].append(p)
        top = sorted(bloggers.values(), key=lambda b: len(b["posts"]), reverse=True)
        top = top[:MAX_BLOG_ENRICH]
        if enrich_blogs and top:
            _say(f"正在查 {len(top)} 位博主的邻居数…")
            with ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(get_blog_stats, b["home"], proxy): b for b in top}
                for fut in as_completed(futs):
                    b = futs[fut]
                    try:
                        b["stats"] = fut.result()
                    except Exception:
                        b["stats"] = None
        for b in top:
            blogger_candidates.append(make_blogger_candidate(b, b.get("stats"), b["posts"]))

    # ---------- 3. cafe 候选补博客（同名匹配） ----------
    if match_cafe_blogs and has_key:
        need = [c for c in cafe_candidates if not c["neighbors_known"]][:20]
        if need:
            _say(f"正在给 {len(need)} 位 cafe 成员找同名博客…")
            for c in need:
                home = find_blog_by_nickname(c["channel_name"], client_id, client_secret,
                                             proxy=proxy)
                if not home:
                    continue
                stats = get_blog_stats(home, proxy=proxy)
                if stats:
                    c["blog_home"] = home
                    c["about_url"] = home
                    c["subscribers"] = stats["neighbors"]
                    c["neighbors_known"] = True
                time.sleep(0.2)

    cafe_candidates.sort(key=lambda c: (c["neighbors_known"], c["post_count"]), reverse=True)
    blogger_candidates.sort(key=lambda c: c["subscribers"], reverse=True)
    return {"cafe_candidates": cafe_candidates, "blogger_candidates": blogger_candidates,
            "cafe_posts": cafe_posts, "errors": errors}


# ============================================================
# 主流程：手动名单（C 路径）
# ============================================================

def resolve_manual_list(text: str, client_id: str, client_secret: str,
                        proxy: str = "", progress_cb=None) -> tuple[list, list]:
    """解析粘贴的名单（每行一个）：
    - 博客链接 / blogId → 直接查邻居数（不需要 key）
    - cafe 帖子链接 → 抓发帖人，再找同名博客
    - 纯昵称 → 用博客搜索找同名（需要 key）
    返回 (候选列表, 失败列表[{line, reason}])
    """
    def _say(m):
        if progress_cb:
            try:
                progress_cb(m)
            except Exception:
                pass

    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    candidates, failed = [], []
    seen = set()
    for i, line in enumerate(lines[:60]):
        _say(f"处理 {i + 1}/{len(lines)}：{line[:30]}")
        cand = None
        if re.match(r"https?://(m\.)?cafe\.naver\.com/", line):
            info = fetch_cafe_article(line, proxy=proxy)
            if not info:
                failed.append({"line": line, "reason": "帖子打不开（需登录/已删除）"})
                continue
            person = {"name": info["poster"], "member_url": info["member_url"],
                      "cafes": {info["cafe_name"]} if info["cafe_name"] else set(),
                      "titles": [info["title"]] if info["title"] else [],
                      "links": [line], "excerpt": info.get("excerpt", ""),
                      "count": 1, "neighbors": 0}
            home = find_blog_by_nickname(info["poster"], client_id, client_secret, proxy=proxy)
            if home:
                stats = get_blog_stats(home, proxy=proxy)
                if stats:
                    person["blog_home"] = home
                    person["neighbors"] = stats["neighbors"]
            cand = make_cafe_candidate(person)
        else:
            blog_id = parse_blog_id(line)
            if blog_id:
                stats = get_blog_stats(blog_id, proxy=proxy)
                if not stats:
                    failed.append({"line": line, "reason": "博客主页打不开或不存在"})
                    continue
                cand = make_blogger_candidate(
                    {"name": stats["name"], "home": f"https://blog.naver.com/{stats['blog_id']}"},
                    stats, [])
            else:
                home = find_blog_by_nickname(line, client_id, client_secret, proxy=proxy)
                if not home:
                    failed.append({"line": line,
                                   "reason": "找不到同名博客（直接贴博客链接最准）"})
                    continue
                stats = get_blog_stats(home, proxy=proxy)
                cand = make_blogger_candidate({"name": line, "home": home}, stats, [])
        if cand and cand["channel_id"] not in seen:
            seen.add(cand["channel_id"])
            candidates.append(cand)
    return candidates, failed


# ============================================================
# 刷新（网红库里 Naver 记录用）
# ============================================================

def refresh_naver_record(record: dict, proxy: str = "") -> dict | None:
    """重新查博客邻居数。返回 {neighbors, name, description} 或 None。"""
    url = record.get("about_url") or record.get("channel_url") or ""
    blog_id = parse_blog_id(url)
    if blog_id:
        return get_blog_stats(blog_id, proxy=proxy)
    return None
