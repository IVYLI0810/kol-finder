"""
YouTube Data API 工具模块
功能：关键词搜索、频道验证、活跃度检测、自动评分、邮箱扫描、配额管理
"""

import requests
import re
import time
from datetime import datetime, timedelta, timezone

# ============================================================
# 配额管理
# ============================================================

class QuotaTracker:
    """追踪 YouTube API 配额使用情况（每日上限 10,000 units）"""

    DAILY_LIMIT = 10000

    def __init__(self):
        self.used = 0
        self.log = []
        # 最近一次 API 失败原因（人话）。只在失败时写入，
        # 由调用方在每次搜索开始前清空，避免旧错误误导。
        self.last_error = ""

    def consume(self, units: int, action: str):
        self.used += units
        self.log.append({"time": datetime.now().strftime("%H:%M:%S"), "units": units, "action": action})

    @property
    def remaining(self):
        return max(0, self.DAILY_LIMIT - self.used)

    def can_afford(self, units: int) -> bool:
        return self.remaining >= units


# ============================================================
# 默认配置（可在网站设置中覆盖）
# ============================================================

DEFAULT_CONFIG = {
    # 订阅量范围（上限提到5万：3K-50K 是团队目标区间，中腰部也要覆盖）
    "min_subs": 3000,
    "max_subs": 50000,
    # 活跃天数
    "days_active": 30,
    # 评分阈值（小博主商业化普遍为0，线太高会漏掉好人，45更合理）
    "score_threshold": 45,
    # 第二期评分权重（四维加权）：
    # 垂类相关度由 AI 判定（占大头，内容对口最重要）；种草关键词维度退役
    "weights": {
        "relevance": 50,         # 垂类相关度（AI判定）
        "data_health": 20,       # 数据健康度
        "frequency": 15,         # 活跃度（更新频率）
        "commercial": 15,        # 商业化历史
    },
    # AI 相关度低于这个分 → 不进主列表，收进待定区人工翻（小保险，防跑偏）
    "ai_min_relevance": 40,
    # 去重时间窗口（天）
    "dedup_rules": {
        "onboarded_days": -1,    # 已引入：永久屏蔽（-1表示永久）
        "rejected_days": 30,     # 已拒绝：30天后重新出现
        "emailed_days": 7,       # 已发邮件：7天后重新出现
        "discovered_days": 7,    # 新发现：7天后重新出现
        "eliminated_days": 90,   # 已淘汰：90天后重新出现（换季/回归的博主给二次机会）
    },
    # ---------- 挖掘强度（第二期新增） ----------
    # 每个关键词抓多少候选视频（YouTube 每页固定50条，100=翻2页，配额×2）
    "results_per_keyword": 100,
    # 搜索时间窗（近N天发布的视频）。窗口越大挖得越多，不额外花配额
    "window_days": 60,
    # Shorts 专项：额外搜一遍短视频，专捞只做 Shorts 的小博主（每词+100配额）
    "shorts_mode": True,
    # 双排序：同词按"时间+相关性"各搜一遍，挖到更多不同类型的频道（每词+100配额）
    "dual_order": False,
}

# ============================================================
# 垂类关键词映射
# ============================================================

CATEGORY_KEYWORDS = {
    "家居收纳": ["자취방", "원룸", "수납", "정리", "인테리어", "집꾸미기", "다이소", "방꾸미기", "혼자 사는", "작은 방", "살림", "정리정돈"],
    "平价美妆": ["가성비 화장품", "학생 메이크업", "올리브영", "데일리 메이크업", "로드샵", "맑은 메이크업", "출근 메이크업", "화장품 추천", "선크림", "립", "파운데이션"],
    "宿舍好物": ["대학생 필수템", "기숙사", "개강 준비물", "대학생 브이로그", "기숙사 꾸미기", "자취생"],
    "通勤配件": ["직장인 가방", "출근 가방", "미니백", "통근룩", "왓츠인마이백", "가벼운 가방", "데일리백", "출근룩"],
    "宠物用品": ["고양이", "강아지", "반려동물", "펫용품", "펫테리어", "집사", "냥이", "멍이"],
    "学生用品": ["문구", "공부 브이로그", "필통", "아이패드 공부", "다이소 문구", "스터디", "공부템"],
}

# 种草/性价比关键词
VALUE_KEYWORDS = [
    "가성비", "학생", "자취", "다이소", "로드샵", "저렴", "꿀템", "인생템",
    "필수템", "추천", "리뷰", "후기", "언박싱", "haul", "만원", "직장인",
    "데일리", "실용", "템", "쇼핑", "구매",
]

# 商业化标记关键词
COMMERCIAL_KEYWORDS = [
    "협찬", "광고", "sponsored", "#ad", "제공", "체험단", "이벤트",
    "구매링크", "할인코드", "프로모션", "제휴",
]

# 商品链接域名（出现在描述中说明有商业化）
PRODUCT_LINK_DOMAINS = [
    "coupang.com", "naver.com/shop", "smartstore.naver.com",
    "musinsa.com", "oliveyoung.co.kr", "yes24.com",
    "11st.co.kr", "gmarket.co.kr", "sivillage.com",
]

# 邮箱正则
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


# ============================================================
# API 基础调用
# ============================================================

BASE_URL = "https://www.googleapis.com/youtube/v3"


def _classify_error(resp) -> str:
    """把 YouTube API 的错误响应翻译成人话或内部标记。
    返回特殊标记："quota"=配额真耗尽，"rate_limited"=限流可重试，"server"=服务端故障可重试；
    其余直接返回可展示给用户的中文原因。
    """
    try:
        info = resp.json()
        err = info.get("error", {})
        errors = err.get("errors") or [{}]
        reason = errors[0].get("reason", "")
        message = err.get("message", "")
    except Exception:
        reason, message = "", ""

    code = resp.status_code
    if code == 403:
        if reason in ("quotaExceeded", "dailyLimitExceeded"):
            return "quota"
        if reason in ("userRateLimitExceeded", "rateLimitExceeded"):
            return "rate_limited"  # 每秒限流，可重试
        if reason == "accessNotGranted":
            return "这个 Key 还没开通 YouTube Data API v3，去 Google Cloud Console「API 和服务→库」里点启用"
        if reason in ("ipRefererMismatch", "blocked", "forbidden"):
            return "API Key 被 IP/域名 限制了，去 Google Cloud Console「凭据」里编辑这个 Key 放开限制"
        return f"访问被拒绝（{reason or code}），检查 Key 是否有效"
    if code == 400:
        if "key" in message.lower() or "api key" in message.lower():
            return "API Key 无效，检查一下是不是复制全了、有没有多余空格"
        return f"请求有误：{message or '参数问题'}"
    if code == 429:
        return "rate_limited"
    if code >= 500:
        return "server"  # YouTube 服务端临时故障，可重试
    return f"YouTube 接口异常（HTTP {code}），稍后再试"


def _get(url: str, params: dict, api_key: str, quota: QuotaTracker, cost: int, action: str,
         max_retries: int = 2) -> dict | None:
    """通用 GET 请求：配额检查 + 自动重试 + 错误翻译成人话。
    成功返回数据 dict；失败返回 None，并把原因写入 quota.last_error。
    重试策略：网络超时/限流/5xx 最多重试 max_retries 次（递增等待）；
    Key 无效、API 未启用这类错误重试也没用，直接返回。
    """
    if not quota.can_afford(cost):
        quota.last_error = "今日配额不足，换个 Key 或明天再试"
        return None
    params["key"] = api_key
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=15)
        except requests.exceptions.RequestException:
            if attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            quota.last_error = "网络不通（连不上 YouTube 接口），检查网络/代理后重试"
            return None

        if resp.status_code == 200:
            quota.consume(cost, action)
            return resp.json()

        kind = _classify_error(resp)
        if kind == "quota":
            quota.used = QuotaTracker.DAILY_LIMIT
            quota.last_error = "今日 YouTube 配额已用完（10,000 units），明天自动恢复，或换一个 API Key"
            return None
        if kind in ("rate_limited", "server"):
            if attempt < max_retries:
                time.sleep(2.0 * (attempt + 1))
                continue
            quota.last_error = "YouTube 接口限流或临时故障，稍等一两分钟再试"
            return None
        # Key 无效 / API 未启用 / IP 限制等：重试无意义
        quota.last_error = kind
        return None
    return None


# ============================================================
# 搜索模块
# ============================================================

def search_videos(keyword: str, api_key: str, quota: QuotaTracker,
                  max_results: int = 50, order: str = "date",
                  window_days: int = 60, shorts_only: bool = False) -> list[dict]:
    """
    按关键词搜索视频，支持翻页：YouTube 每页固定最多 50 条、100 units，
    想抓 100/150 条就翻页 2/3 次，抓满 max_results 或没有下一页为止。
    shorts_only=True 时只搜 Shorts 短视频（videoDuration=short）。
    消耗：100 units/页
    默认按上传时间排序 + 限近N天：小博主活跃更新更容易被搜到，
    大频道的老热门视频不再霸占前排，候选池里小频道比例显著提高。
    """
    published_after = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    results = []
    seen_video_ids = set()
    page_token = None

    while len(results) < max_results:
        page_size = min(50, max_results - len(results))
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "maxResults": page_size,
            "order": order,
            "publishedAfter": published_after,
            "regionCode": "KR",
            "relevanceLanguage": "ko",
        }
        if shorts_only:
            params["videoDuration"] = "short"
        if page_token:
            params["pageToken"] = page_token

        data = _get(f"{BASE_URL}/search", params, api_key, quota, 100, f"搜索: {keyword}")
        if not data:
            break  # 失败原因已记录在 quota.last_error

        for item in data.get("items", []):
            snippet = item["snippet"]
            thumbs = snippet.get("thumbnails", {})
            vid = item["id"]["videoId"]
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            results.append({
                "video_id": vid,
                "title": snippet["title"],
                "channel_id": snippet["channelId"],
                "channel_name": snippet["channelTitle"],
                "published_at": snippet["publishedAt"],
                "description": snippet.get("description", ""),
                "thumbnail_url": thumbs.get("medium", thumbs.get("default", {})).get("url", ""),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break  # 没有下一页了

    return results


# ============================================================
# 频道信息模块
# ============================================================

def get_channels(channel_ids: list[str], api_key: str, quota: QuotaTracker) -> dict:
    """
    批量获取频道详情（最多50个/次）
    消耗：1 unit/次
    """
    if not channel_ids:
        return {}

    results = {}
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i:i+50]
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": ",".join(batch),
        }
        data = _get(f"{BASE_URL}/channels", params, api_key, quota, 1, f"频道详情x{len(batch)}")
        if not data:
            continue

        for item in data.get("items", []):
            cid = item["id"]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            uploads_playlist = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads", "")
            results[cid] = {
                "channel_id": cid,
                "channel_name": snippet.get("title", ""),
                "channel_url": f"https://www.youtube.com/channel/{cid}",
                "about_url": f"https://www.youtube.com/channel/{cid}/about",
                "description": snippet.get("description", ""),
                "country": snippet.get("country", ""),
                "created_at": snippet.get("publishedAt", ""),
                "subscribers": int(stats.get("subscriberCount", 0)),
                "total_videos": int(stats.get("videoCount", 0)),
                "total_views": int(stats.get("viewCount", 0)),
                "uploads_playlist_id": uploads_playlist,
                "avatar_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            }
    return results


def resolve_channel_ids(raw_ids: list[str], api_key: str, quota: QuotaTracker) -> tuple[list[str], list[str]]:
    """
    把混合输入统一解析成有效的 UC 频道ID。
    支持：UC频道ID / /channel/UC... 链接 / @handle（裸写或 youtube.com/@xxx 链接）。
    @handle 通过官方 forHandle 接口反查频道ID，消耗 1 unit/个。
    返回：(去重后的有效频道ID列表, 无法解析的原始行列表)
    """
    valid = []
    failed_lines = []
    for raw in raw_ids:
        rid = str(raw).strip()
        if not rid:
            continue
        # 1) 直接就是频道ID
        if rid.startswith("UC") and len(rid) == 24:
            valid.append(rid)
            continue
        # 2) /channel/UC... 链接里提取
        m = re.search(r'/channel/(UC[\w-]+)', rid)
        if m:
            valid.append(m.group(1))
            continue
        # 3) @handle（裸写，或链接里的 youtube.com/@xxx）
        m = re.search(r'@([\w.\-]+)', rid)
        if m:
            handle = m.group(1)
            params = {"part": "id", "forHandle": "@" + handle}
            data = _get(f"{BASE_URL}/channels", params, api_key, quota, 1, f"解析@{handle}")
            items = data.get("items", []) if data else []
            if items:
                valid.append(items[0]["id"])
            else:
                failed_lines.append(rid)
            continue
        # 4) 其他格式（视频链接等）无法识别
        failed_lines.append(rid)

    # 去重（保持顺序）
    seen = set()
    ordered = []
    for v in valid:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered, failed_lines


# ============================================================
# 活跃度检测 + 数据采集
# ============================================================

def get_recent_uploads(uploads_playlist_id: str, api_key: str, quota: QuotaTracker,
                       max_results: int = 10) -> list[dict]:
    """获取频道最近上传的视频列表，消耗：1 unit"""
    if not uploads_playlist_id:
        return []
    params = {
        "part": "snippet,contentDetails",
        "playlistId": uploads_playlist_id,
        "maxResults": max_results,
    }
    data = _get(f"{BASE_URL}/playlistItems", params, api_key, quota, 1, "最近上传")
    if not data:
        return []

    videos = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        thumbs = snippet.get("thumbnails", {})
        videos.append({
            "video_id": item["contentDetails"]["videoId"],
            "title": snippet["title"],
            "published_at": snippet["publishedAt"],
            "description": snippet.get("description", ""),
            "thumbnail_url": thumbs.get("medium", thumbs.get("default", {})).get("url", ""),
        })
    return videos


def get_video_stats(video_ids: list[str], api_key: str, quota: QuotaTracker) -> dict:
    """批量获取视频播放量等数据，消耗：1 unit/次（最多50个）"""
    if not video_ids:
        return {}

    results = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        params = {
            "part": "statistics,snippet",
            "id": ",".join(batch),
        }
        data = _get(f"{BASE_URL}/videos", params, api_key, quota, 1, f"视频数据x{len(batch)}")
        if not data:
            continue

        for item in data.get("items", []):
            vid = item["id"]
            stats = item.get("statistics", {})
            snippet = item.get("snippet", {})
            results[vid] = {
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
                "title": snippet.get("title", ""),
                "tags": snippet.get("tags", []),
                "description": snippet.get("description", ""),
            }
    return results


# ============================================================
# 邮箱扫描
# ============================================================

def extract_emails(texts: list[str]) -> list[str]:
    """从多段文本中提取邮箱地址"""
    emails = set()
    for text in texts:
        if text:
            found = EMAIL_REGEX.findall(text)
            for email in found:
                # 过滤掉明显不是邮箱的（如 example@... 或文件名）
                if not any(skip in email.lower() for skip in ["example", "test", "image", "photo"]):
                    emails.add(email.lower())
    return list(emails)


# ============================================================
# 商业化历史检测
# ============================================================

def detect_commercial_history(descriptions: list[str], tags_list: list[list[str]]) -> dict:
    """
    检测频道是否有商业化历史
    返回：{"has_commercial": bool, "evidence": list[str], "score": int}
    """
    all_text = " ".join(descriptions).lower()
    all_tags = " ".join(" ".join(t) for t in tags_list).lower()
    combined = f"{all_text} {all_tags}"

    evidence = []

    # 检查商业化关键词
    for kw in COMMERCIAL_KEYWORDS:
        if kw.lower() in combined:
            evidence.append(kw)

    # 检查商品链接
    for domain in PRODUCT_LINK_DOMAINS:
        if domain in combined:
            evidence.append(f"商品链接({domain})")

    has_commercial = len(evidence) > 0

    # 评分：有明确广告标记=满分，有商品链接=高分，有暗示=中分
    if any(kw in evidence for kw in ["협찬", "광고", "sponsored", "#ad"]):
        score = 25
    elif any("商品链接" in e for e in evidence):
        score = 20
    elif evidence:
        score = 15
    else:
        score = 5  # 没有商业化痕迹也给基础分（新博主也可能愿意接）

    return {"has_commercial": has_commercial, "evidence": evidence[:5], "score": score}


# ============================================================
# 频道完整验证流程
# ============================================================

def _median(values: list) -> float:
    """求中位数（空列表返回0）。比平均值更抗单条爆款/冷门的干扰。"""
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2


def verify_channel(channel_info: dict, api_key: str, quota: QuotaTracker,
                   config: dict = None) -> dict | None:
    """
    对单个频道做完整验证和数据采集
    返回增强后的频道信息，不活跃返回 None
    """
    if config is None:
        config = DEFAULT_CONFIG

    days_active = config.get("days_active", 30)

    # 获取最近上传
    uploads = get_recent_uploads(channel_info["uploads_playlist_id"], api_key, quota, max_results=10)
    if not uploads:
        return None

    # 检查活跃度
    latest_upload = uploads[0]["published_at"]
    latest_date = datetime.fromisoformat(latest_upload.replace("Z", "+00:00"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_active)

    if latest_date < cutoff:
        return None  # 不活跃

    # 获取最近视频的播放数据
    video_ids = [v["video_id"] for v in uploads]
    video_stats = get_video_stats(video_ids, api_key, quota)

    # 计算近30天数据
    recent_views = []
    all_views = []          # 全部拉到的视频播放量（≤10条），用于中位数健康度
    recent_titles = []
    recent_descriptions = []
    recent_thumbnails = []
    recent_tags = []

    for v in uploads:
        pub_date = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        vid = v["video_id"]
        if vid in video_stats:
            all_views.append(video_stats[vid]["views"])
        if pub_date >= cutoff and vid in video_stats:
            recent_views.append(video_stats[vid]["views"])
            recent_titles.append(v["title"])
            recent_descriptions.append(video_stats[vid].get("description", ""))
            recent_tags.append(video_stats[vid].get("tags", []))
        recent_thumbnails.append({
            "title": v["title"],
            "url": v["thumbnail_url"],
            "date": v["published_at"][:10],
        })

    avg_views = int(sum(recent_views) / len(recent_views)) if recent_views else 0
    subscribers = channel_info["subscribers"]
    # 数据健康度用「近10条中位数」算播/订比：
    # 平均值容易被一条爆款拉飞，也被冷门视频拉垮；中位数才是这个频道的真实常态水平
    median_views = _median(all_views)
    view_sub_ratio = (median_views / subscribers * 100) if subscribers > 0 else 0

    # 邮箱扫描（从频道描述 + 视频描述中提取）
    all_texts_for_email = [channel_info.get("description", "")] + recent_descriptions
    emails = extract_emails(all_texts_for_email)

    # 商业化历史检测
    commercial = detect_commercial_history(recent_descriptions, recent_tags)

    # 组装结果
    channel_info.update({
        "last_upload": latest_upload[:10],
        "last_upload_days_ago": (datetime.now(timezone.utc) - latest_date).days,
        "recent_uploads_count": len(uploads),
        "recent_video_count_30d": len(recent_views),
        "avg_views_30d": avg_views,
        "median_views": int(median_views),   # 近10条中位数（播/订比按它算）
        "view_sub_ratio": round(view_sub_ratio, 1),
        "recent_titles": recent_titles[:5],
        "recent_thumbnails": recent_thumbnails[:5],
        # 简介和标签用于垂类"三合一"判断（截断省内存，关键词一般在前300字）
        "recent_descriptions": [d[:300] for d in recent_descriptions[:5]],
        "recent_tags": recent_tags[:5],
        "emails": emails,
        "commercial_history": commercial,
    })
    return channel_info


# ============================================================
# 自动评分模块（可配置权重）
# ============================================================

def score_channel(channel_info: dict, config: dict = None) -> dict:
    """
    第二期评分：四维加权（每维先算 0-100 原始分，再按权重折算）。
    默认权重：垂类相关度50 / 数据健康度20 / 活跃度15 / 商业化15（设置页可调）。

    垂类相关度来自 AI 分析（ai_relevance 字段）；AI 没跑或失败时按中性50计，
    不影响挖掘流程。种草关键词、关键词匹配垂直度两个旧维度已退役。

    返回 dict 里每个维度有两个值：
      xxx_raw  = 0-100 原始分（给人看的真实水平）
      xxx      = 按权重折算后的贡献分（四项相加=总分）
    """
    if config is None:
        config = DEFAULT_CONFIG
    weights = {**DEFAULT_CONFIG["weights"], **config.get("weights", {})}

    scores = {}

    # 1. 垂类相关度（AI判定，0-100）
    w = weights.get("relevance", 50)
    raw_rel = channel_info.get("ai_relevance", 50)
    try:
        raw_rel = max(0, min(100, int(round(float(raw_rel)))))
    except (TypeError, ValueError):
        raw_rel = 50
    scores["relevance_raw"] = raw_rel
    scores["relevance"] = round(raw_rel * w / 100)

    # 2. 数据健康度：播/订比（近10条中位数）分档
    w = weights.get("data_health", 20)
    ratio = channel_info.get("view_sub_ratio", 0)
    if ratio >= 10:
        raw_data = 100
    elif ratio >= 5:
        raw_data = 75
    elif ratio >= 2:
        raw_data = 50
    elif ratio >= 1:
        raw_data = 35
    else:
        raw_data = 20
    scores["data_health_raw"] = raw_data
    scores["data_health"] = round(raw_data * w / 100)

    # 3. 活跃度：近30天更新条数分档（满档≥4条：小博主周更就算稳定）
    w = weights.get("frequency", 15)
    recent_count = channel_info.get("recent_video_count_30d", 0)
    if recent_count >= 4:
        raw_freq = 100
    elif recent_count == 3:
        raw_freq = 80
    elif recent_count == 2:
        raw_freq = 65
    elif recent_count == 1:
        raw_freq = 40
    else:
        raw_freq = 15
    scores["frequency_raw"] = raw_freq
    scores["frequency"] = round(raw_freq * w / 100)

    # 4. 商业化历史：检测器输出 5/15/20/25 → 折算成 0-100
    w = weights.get("commercial", 15)
    raw_comm_source = channel_info.get("commercial_history", {}).get("score", 5)
    raw_comm = round(raw_comm_source / 25 * 100)
    scores["commercial_raw"] = raw_comm
    scores["commercial"] = round(raw_comm * w / 100)

    # 总分 = 四项贡献分相加（权重和正常是100；如果被调过，按比例归一）
    total = scores["relevance"] + scores["data_health"] + scores["frequency"] + scores["commercial"]
    total_w = (weights.get("relevance", 50) + weights.get("data_health", 20)
               + weights.get("frequency", 15) + weights.get("commercial", 15))
    if total_w and total_w != 100:
        total = round(total * 100 / total_w)
    scores["total"] = total

    return scores


def split_main_pending(results: list[dict], min_score: int, ai_gate: int) -> tuple[list, list]:
    """
    把挖掘结果分流成（主列表, 待定区）。任何一条没过线都进待定区（不直接丢人）：
      ① 综合评分 < min_score
      ② AI 实际分析过 且 相关度 < ai_gate（垂类明显跑偏的小保险）
    ai_gate 设为 0 表示关闭相关度红线。AI 没分析过的频道不受红线影响。
    """
    main, pending = [], []
    for r in results:
        total = r.get("scores", {}).get("total", 0)
        low_score = total < min_score
        low_rel = bool(r.get("ai_analyzed")) and r.get("ai_relevance", 100) < ai_gate
        (pending if (low_score or low_rel) else main).append(r)
    return main, pending


# ============================================================
# 去重判断
# ============================================================

def should_exclude(channel_id: str, db_records: list[dict], config: dict = None) -> bool:
    """
    判断某频道是否应被排除（已在库中且未过冷却期）
    db_records: 公共库中的所有记录
    config: 去重规则配置
    """
    if config is None:
        config = DEFAULT_CONFIG

    rules = config.get("dedup_rules", DEFAULT_CONFIG["dedup_rules"])
    today = datetime.now()

    for record in db_records:
        if record.get("channel_id") != channel_id:
            continue

        status = record.get("status", "新发现")
        # 获取状态变更日期（或添加日期）
        date_str = record.get("status_date") or record.get("added_date", "")
        if not date_str:
            return False  # 没有日期信息：放出来让人工判断，别悄悄藏掉
        try:
            status_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return False  # 日期格式坏了：同样放出来，别误伤

        days_since = (today - status_date).days

        if status == "已引入":
            limit = rules.get("onboarded_days", -1)
            if limit == -1:
                return True  # 永久屏蔽
            return days_since < limit

        elif status == "已拒绝":
            limit = rules.get("rejected_days", 30)
            return days_since < limit

        elif status == "已发邮件":
            limit = rules.get("emailed_days", 7)
            return days_since < limit

        elif status == "新发现":
            limit = rules.get("discovered_days", 7)
            return days_since < limit

        elif status == "已淘汰":
            limit = rules.get("eliminated_days", 90)
            if limit == -1:
                return True  # 也支持配成永久
            return days_since < limit

    return False  # 不在库中，不排除


# ============================================================
# 完整搜索+验证流程
# ============================================================

def estimate_search_cost(config: dict = None) -> int:
    """预估单个关键词一次搜索的配额成本（只算搜索，不含逐频道验证约2-3 units/频道）。
    翻页每页100 units；Shorts专项+1页；双排序再+1页。
    """
    if config is None:
        config = DEFAULT_CONFIG
    pages = max(1, -(-int(config.get("results_per_keyword", 100)) // 50))  # 向上取整
    cost = pages * 100
    if config.get("shorts_mode", True):
        cost += 100
    if config.get("dual_order", False):
        cost += 100
    return cost


def _merge_videos(base: list[dict], extra: list[dict]) -> list[dict]:
    """合并两次搜索的视频列表，按 video_id 去重（保持顺序）"""
    seen = {v["video_id"] for v in base}
    merged = list(base)
    for v in extra:
        if v["video_id"] not in seen:
            seen.add(v["video_id"])
            merged.append(v)
    return merged


def search_and_verify(keyword: str, api_key: str, quota: QuotaTracker,
                      config: dict = None, db_records: list[dict] = None,
                      order: str = "date", status_cb=None) -> list[dict]:
    """
    完整流程：搜索（可翻页+Shorts专项+双排序）→ 提取频道 → 去重 → 验证 → 评分
    order: "date" 按时间（小博主更多）/ "relevance" 按相关性（更对口）
    status_cb: 可选回调 status_cb(str)，把进度实时传给界面显示

    第二期起：不再需要人工指定垂类——这里先按中性相关度打分，
    界面层会用 AI 重新分析垂类/相关度并刷新评分。

    注意：这里不再按阈值丢人——所有验证通过的活跃频道都会返回，
    高分进主列表、低分进「待定区」由人工翻看，避免把潜力博主悄悄埋掉。
    """
    if config is None:
        config = DEFAULT_CONFIG
    if db_records is None:
        db_records = []

    def _say(msg: str):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass

    min_subs = config.get("min_subs", 3000)
    max_subs = config.get("max_subs", 50000)
    results_per_keyword = int(config.get("results_per_keyword", 100))
    window_days = int(config.get("window_days", 60))
    shorts_mode = bool(config.get("shorts_mode", True))
    dual_order = bool(config.get("dual_order", False))

    # Step 1: 搜索视频（翻页抓满配置条数）
    _say(f"正在搜索视频（最多 {results_per_keyword} 条）…")
    videos = search_videos(keyword, api_key, quota,
                           max_results=results_per_keyword, order=order,
                           window_days=window_days)

    # Step 1b: Shorts 专项——专门捞只做短视频的小博主
    if shorts_mode:
        _say("Shorts 专项搜索中（短视频博主）…")
        shorts = search_videos(keyword, api_key, quota,
                               max_results=50, order=order,
                               window_days=window_days, shorts_only=True)
        videos = _merge_videos(videos, shorts)

    # Step 1c: 双排序——换一种排序再搜一遍，挖不同类型的频道
    if dual_order:
        other_order = "relevance" if order == "date" else "date"
        _say("换一种排序再搜一遍…")
        extra = search_videos(keyword, api_key, quota,
                              max_results=50, order=other_order,
                              window_days=window_days)
        videos = _merge_videos(videos, extra)

    if not videos:
        return []

    # Step 2: 提取唯一频道ID
    channel_ids = list(dict.fromkeys(v["channel_id"] for v in videos))

    # Step 3: 去重过滤
    channel_ids = [cid for cid in channel_ids if not should_exclude(cid, db_records, config)]
    if not channel_ids:
        return []

    # Step 4: 批量获取频道信息
    _say(f"正在拉取 {len(channel_ids)} 个候选频道的资料…")
    channels = get_channels(channel_ids, api_key, quota)
    if not channels:
        return []

    # Step 5: 按订阅量初筛
    candidates = []
    for cid, info in channels.items():
        if min_subs <= info["subscribers"] <= max_subs:
            if info.get("country", "") in ("KR", ""):
                candidates.append(info)

    # Step 6: 逐个验证活跃度 + 评分（全部保留，阈值分流交给界面）
    verified = []
    total = len(candidates)
    for i, ch in enumerate(candidates):
        if not quota.can_afford(3):
            quota.last_error = quota.last_error or "配额不足，部分候选频道未完成验证"
            break
        _say(f"正在逐个验证活跃度（{i + 1}/{total}）…")
        result = verify_channel(ch, api_key, quota, config)
        if result:
            result["scores"] = score_channel(result, config)
            result["search_keyword"] = keyword
            result["category"] = ""  # 垂类由 AI 在界面层回填
            verified.append(result)

    # 按总分排序
    verified.sort(key=lambda x: x["scores"]["total"], reverse=True)
    return verified
