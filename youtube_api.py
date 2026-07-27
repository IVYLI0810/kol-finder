"""
YouTube Data API 工具模块
功能：关键词搜索、频道验证、活跃度检测、自动评分、邮箱扫描、配额管理
"""

import requests
import re
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
    # 订阅量范围
    "min_subs": 3000,
    "max_subs": 20000,
    # 活跃天数
    "days_active": 30,
    # 评分阈值（小博主商业化普遍为0，线太高会漏掉好人，45更合理）
    "score_threshold": 45,
    # 评分权重（垂直度提到35：内容对口最重要；商业化降到15：小博主没接过广告很正常）
    "weights": {
        "verticality": 35,       # 内容垂直度
        "commercial": 15,        # 商业化历史
        "data_health": 20,       # 数据健康度
        "frequency": 15,         # 更新频率
        "keywords": 15,          # 种草关键词
    },
    # 去重时间窗口（天）
    "dedup_rules": {
        "onboarded_days": -1,    # 已引入：永久屏蔽（-1表示永久）
        "rejected_days": 30,     # 已拒绝：30天后重新出现
        "emailed_days": 7,       # 已发邮件：7天后重新出现
        "discovered_days": 7,    # 新发现：7天后重新出现
    },
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


def _get(url: str, params: dict, api_key: str, quota: QuotaTracker, cost: int, action: str) -> dict | None:
    """通用 GET 请求，带配额检查"""
    if not quota.can_afford(cost):
        return None
    params["key"] = api_key
    try:
        resp = requests.get(url, params=params, timeout=15)
    except requests.exceptions.RequestException:
        return None
    if resp.status_code == 200:
        quota.consume(cost, action)
        return resp.json()
    elif resp.status_code == 403:
        quota.used = QuotaTracker.DAILY_LIMIT
        return None
    else:
        return None


# ============================================================
# 搜索模块
# ============================================================

def search_videos(keyword: str, api_key: str, quota: QuotaTracker,
                  max_results: int = 25, order: str = "date") -> list[dict]:
    """
    按关键词搜索视频
    消耗：100 units/次
    默认按上传时间排序 + 限近60天：小博主活跃更新更容易被搜到，
    大频道的老热门视频不再霸占前排，候选池里小频道比例显著提高。
    """
    published_after = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {
        "part": "snippet",
        "q": keyword,
        "type": "video",
        "maxResults": max_results,
        "order": order,
        "publishedAfter": published_after,
        "regionCode": "KR",
        "relevanceLanguage": "ko",
    }
    data = _get(f"{BASE_URL}/search", params, api_key, quota, 100, f"搜索: {keyword}")
    if not data:
        return []

    results = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        thumbs = snippet.get("thumbnails", {})
        results.append({
            "video_id": item["id"]["videoId"],
            "title": snippet["title"],
            "channel_id": snippet["channelId"],
            "channel_name": snippet["channelTitle"],
            "published_at": snippet["publishedAt"],
            "description": snippet.get("description", ""),
            "thumbnail_url": thumbs.get("medium", thumbs.get("default", {})).get("url", ""),
        })
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
    recent_titles = []
    recent_descriptions = []
    recent_thumbnails = []
    recent_tags = []

    for v in uploads:
        pub_date = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        vid = v["video_id"]
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
    view_sub_ratio = (avg_views / subscribers * 100) if subscribers > 0 else 0

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

def score_channel(channel_info: dict, category: str = None, config: dict = None) -> dict:
    """
    对频道进行自动评分（满分100，权重可配置）
    """
    if config is None:
        config = DEFAULT_CONFIG

    weights = config.get("weights", DEFAULT_CONFIG["weights"])
    titles_text = " ".join(channel_info.get("recent_titles", []))
    desc_text = channel_info.get("description", "")
    all_text = f"{titles_text} {desc_text}".lower()

    scores = {}

    # 1. 内容垂直度（三合一：标题+简介+标签，任一命中即算"对口"）
    w = weights.get("verticality", 35)
    if category and category in CATEGORY_KEYWORDS:
        keywords = CATEGORY_KEYWORDS[category]
        titles = channel_info.get("recent_titles", [])
        descs = channel_info.get("recent_descriptions", [])
        tags = channel_info.get("recent_tags", [])
        if titles:
            match_count = 0
            for i, title in enumerate(titles):
                desc = descs[i] if i < len(descs) else ""
                tag_text = " ".join(tags[i]) if i < len(tags) else ""
                combined = f"{title} {desc} {tag_text}".lower()
                if any(kw.lower() in combined for kw in keywords):
                    match_count += 1
            ratio = match_count / len(titles)
        else:
            ratio = 0
        scores["verticality"] = round(ratio * w)
        scores["verticality_ratio"] = round(ratio * 100)  # 百分比，供参考
    else:
        scores["verticality"] = round(w * 0.5)  # 未指定垂类给中间分
        scores["verticality_ratio"] = 50

    # 2. 商业化历史
    w = weights.get("commercial", 15)
    commercial = channel_info.get("commercial_history", {})
    raw_commercial = commercial.get("score", 5)
    scores["commercial"] = round(raw_commercial / 25 * w)  # 按权重缩放

    # 3. 数据健康度
    w = weights.get("data_health", 20)
    ratio = channel_info.get("view_sub_ratio", 0)
    if ratio >= 10:
        scores["data_health"] = w
    elif ratio >= 5:
        scores["data_health"] = round(w * 0.75)
    elif ratio >= 2:
        scores["data_health"] = round(w * 0.5)
    else:
        scores["data_health"] = round(w * 0.25)

    # 4. 更新频率
    w = weights.get("frequency", 15)
    recent_count = channel_info.get("recent_video_count_30d", 0)
    if recent_count >= 8:
        scores["frequency"] = w
    elif recent_count >= 4:
        scores["frequency"] = round(w * 0.8)
    elif recent_count >= 2:
        scores["frequency"] = round(w * 0.55)
    elif recent_count >= 1:
        scores["frequency"] = round(w * 0.35)
    else:
        scores["frequency"] = round(w * 0.15)

    # 5. 种草关键词
    w = weights.get("keywords", 15)
    kw_matched = sum(1 for kw in VALUE_KEYWORDS if kw in all_text)
    scores["keywords"] = min(w, kw_matched * 3)

    # 总分
    scores["total"] = (
        scores["verticality"] + scores["commercial"] +
        scores["data_health"] + scores["frequency"] + scores["keywords"]
    )

    return scores


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
            return True  # 没有日期信息，保守排除
        try:
            status_date = datetime.strptime(date_str[:10], "%Y-%m-%d")
        except ValueError:
            return True

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

    return False  # 不在库中，不排除


# ============================================================
# 完整搜索+验证流程
# ============================================================

def search_and_verify(keyword: str, category: str, api_key: str, quota: QuotaTracker,
                      config: dict = None, db_records: list[dict] = None) -> list[dict]:
    """
    完整流程：搜索 → 提取频道 → 去重 → 验证 → 评分
    """
    if config is None:
        config = DEFAULT_CONFIG
    if db_records is None:
        db_records = []

    min_subs = config.get("min_subs", 3000)
    max_subs = config.get("max_subs", 20000)
    threshold = config.get("score_threshold", 60)

    # Step 1: 搜索视频（搜索接口固定100单位/次，抓50个不增加配额，候选池翻倍）
    videos = search_videos(keyword, api_key, quota, max_results=50)
    if not videos:
        return []

    # Step 2: 提取唯一频道ID
    channel_ids = list(dict.fromkeys(v["channel_id"] for v in videos))

    # Step 3: 去重过滤
    channel_ids = [cid for cid in channel_ids if not should_exclude(cid, db_records, config)]
    if not channel_ids:
        return []

    # Step 4: 批量获取频道信息
    channels = get_channels(channel_ids, api_key, quota)
    if not channels:
        return []

    # Step 5: 按订阅量初筛
    candidates = []
    for cid, info in channels.items():
        if min_subs <= info["subscribers"] <= max_subs:
            if info.get("country", "") in ("KR", ""):
                candidates.append(info)

    # Step 6: 逐个验证活跃度 + 评分
    verified = []
    for ch in candidates:
        if not quota.can_afford(3):
            break
        result = verify_channel(ch, api_key, quota, config)
        if result:
            result["scores"] = score_channel(result, category, config)
            # 只保留达到阈值的
            if result["scores"]["total"] >= threshold:
                result["search_keyword"] = keyword
                result["category"] = category
                verified.append(result)

    # 按总分排序
    verified.sort(key=lambda x: x["scores"]["total"], reverse=True)
    return verified
