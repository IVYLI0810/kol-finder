"""
Supabase 数据库模块
功能：公共网红库的读写、去重查询、状态更新、批量导入
"""

from datetime import datetime
import json
from supabase import create_client, Client


def _name_filter(q: str) -> str:
    """名字/频道ID 模糊搜索的 PostgREST or 过滤串。
    去掉会破坏 or() 语法的字符（逗号/括号/引号）。"""
    import re
    q = re.sub(r'[(),"\']', "", q.strip()).strip()
    return f"channel_name.ilike.*{q}*,channel_id.ilike.*{q}*"


def enrich_import_channels(channels: dict, api_key: str, quota, config: dict = None) -> dict:
    """
    批量导入的频道补全：走和挖掘站一样的「验证采集 → AI 垂类 → 自动评分」流程，
    补齐粉丝数、近30天播放、播订比、邮箱、商业历史、评分、AI 垂类等字段。
    和挖掘的区别：不活跃/没有上传的频道不丢弃（allow_inactive），照常保留能拿到的数据。
    单个频道补全失败只保留基础信息，不打断整个导入。
    channels: cid → 频道信息 dict，就地修改后原样返回。
    """
    if not channels:
        return channels

    from youtube_api import verify_channel, score_channel

    # 1) 逐个频道采集视频/播放/邮箱/商业化数据（不活跃也保留）
    for cid in list(channels.keys()):
        info = channels[cid]
        try:
            channels[cid] = verify_channel(info, api_key, quota, config, allow_inactive=True) or info
        except Exception:
            channels[cid] = info

    enriched = list(channels.values())

    # 2) AI 垂类分析（未配置 key 时自动给中性值，不阻断）
    try:
        from ai_analyzer import analyze_channels
        analyze_channels(enriched)
    except Exception:
        pass

    # 3) 自动评分（AI 垂类写进 category=带货垂类，content_category=内容垂类，和挖掘流程保持一致）
    for info in enriched:
        if info.get("ai_category"):
            info["category"] = info["ai_category"]
        if info.get("ai_content_category"):
            info["content_category"] = info["ai_content_category"]
        try:
            info["scores"] = score_channel(info, config)
        except Exception:
            info["scores"] = {"total": 0}

    return channels


class InfluencerDB:
    """公共网红数据库（基于 Supabase）"""

    TABLE_NAME = "influencers"
    MEMBERS_TABLE = "members"  # 团队成员名单（只存名字，方便下拉选择）
    KEYWORDS_TABLE = "keywords"  # 团队自定义关键词库（可增删，全队共享）
    SETTINGS_TABLE = "user_settings"  # 个人筛选设置（每人一行，互不干扰）

    def __init__(self, url: str, key: str):
        """
        初始化数据库连接
        url: Supabase 项目 URL（如 https://xxxx.supabase.co）
        key: Supabase anon/public key
        """
        self.client: Client = create_client(url, key)
        self.last_error = None  # 记录最近一次错误信息

    # ============================================================
    # 查询
    # ============================================================

    def get_all(self) -> list[dict]:
        """获取所有网红记录"""
        try:
            result = self.client.table(self.TABLE_NAME).select("*").execute()
            return result.data or []
        except Exception:
            return []

    def get_by_status(self, status: str) -> list[dict]:
        """按状态查询"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("status", status)
                .execute()
            )
            return result.data or []
        except Exception:
            return []

    def get_by_category(self, category: str) -> list[dict]:
        """按垂类查询"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("*")
                .eq("category", category)
                .execute()
            )
            return result.data or []
        except Exception:
            return []

    # ============================================================
    # 分页查询（免费版下减少单次传输量和内存占用）
    # ============================================================

    # 列表页只需要这些轻量字段，不要 thumbnails / recent_titles 等大字段
    LIGHT_FIELDS = (
        "channel_id,channel_name,channel_url,category,content_category,subscribers,"
        "score_total,status,discovered_by,emails,notes,added_date,"
        "status_date,last_upload,last_checked,email_sent_date,introduced_date"
    )
    # 兼容尚未添加新列的库（首次升级时）：introduced_date / content_category 可能还没建
    LIGHT_FIELDS_FALLBACK = LIGHT_FIELDS.replace(",introduced_date", "").replace(",content_category", "")

    SORT_COLUMNS = {
        "添加时间": "added_date",
        "评分": "score_total",
        "订阅量": "subscribers",
        "最近更新": "last_upload",
    }

    # 搜索去重只需要这几个字段，避免搜索时全量拉取大表
    DEDUP_FIELDS = "channel_id,status,status_date,added_date"

    def get_dedup_records(self) -> list[dict]:
        """获取用于搜索去重的轻量记录（不含 thumbnails 等大字段）"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select(self.DEDUP_FIELDS)
                .execute()
            )
            return result.data or []
        except Exception:
            return []

    def count_records(self, status: str = None, category: list[str] = None,
                      content_category: list[str] = None,
                      discoverer: str = None, discoverer_name: str = "",
                      name_query: str = "") -> int:
        """按当前筛选条件计数（用于分页）"""
        try:
            query = self.client.table(self.TABLE_NAME).select("*", count="exact")
            if status and status != "全部":
                query = query.eq("status", status)
            if category:
                query = query.in_("category", category)
            if content_category:
                query = query.in_("content_category", content_category)
            if discoverer and discoverer != "全部":
                if discoverer == "只看我的":
                    query = query.eq("discovered_by", discoverer_name)
                else:
                    query = query.eq("discovered_by", discoverer)
            if name_query:
                query = query.or_(_name_filter(name_query))
            result = query.execute()
            return result.count or 0
        except Exception:
            return 0

    def count_by_status(self) -> dict:
        """一次请求统计全部状态分布（只拉 status 单列，比逐状态 count 快）。
        返回 {"total": N, "新发现": n1, "已发邮件": n2, ...}"""
        out = {"total": 0}
        try:
            rows, off = [], 0
            while True:
                r = (self.client.table(self.TABLE_NAME)
                     .select("status")
                     .range(off, off + 999)
                     .execute())
                batch = r.data or []
                rows += batch
                off += len(batch)
                if len(batch) < 1000:
                    break
            for x in rows:
                out["total"] += 1
                s = x.get("status") or "新发现"
                out[s] = out.get(s, 0) + 1
        except Exception:
            pass
        return out

    def _build_paginated_query(self, fields: str, page: int, page_size: int,
                               status: str, category: list[str],
                               content_category: list[str],
                               discoverer: str, discoverer_name: str,
                               sort_by: str, descending: bool,
                               name_query: str = ""):
        """构建设分页查询（不执行）。"""
        query = self.client.table(self.TABLE_NAME).select(fields)

        if status and status != "全部":
            query = query.eq("status", status)
        if category:
            query = query.in_("category", category)
        if content_category:
            query = query.in_("content_category", content_category)
        if discoverer and discoverer != "全部":
            if discoverer == "只看我的":
                query = query.eq("discovered_by", discoverer_name)
            else:
                query = query.eq("discovered_by", discoverer)
        if name_query:
            query = query.or_(_name_filter(name_query))

        sort_col = self.SORT_COLUMNS.get(sort_by, "added_date")
        query = query.order(sort_col, desc=descending)

        start = (page - 1) * page_size
        end = start + page_size - 1
        return query.range(start, end)

    def get_records_paginated(self, page: int = 1, page_size: int = 30,
                              status: str = None, category: list[str] = None,
                              content_category: list[str] = None,
                              discoverer: str = None, discoverer_name: str = "",
                              sort_by: str = "添加时间", descending: bool = True,
                              name_query: str = "") -> list[dict]:
        """
        分页获取网红记录，筛选和排序都在 Supabase 服务端完成。
        只返回列表页需要的轻量字段，减少网络传输和内存占用。
        """
        try:
            query = self._build_paginated_query(
                self.LIGHT_FIELDS, page, page_size, status, category,
                content_category, discoverer, discoverer_name, sort_by, descending,
                name_query=name_query,
            )
            result = query.execute()
            return result.data or []
        except Exception:
            # 首次升级时新列（introduced_date/content_category）可能还不存在，
            # 先回退到基础字段，保证旧数据能正常显示；等新列加好后会自动显示完整信息。
            try:
                query = self._build_paginated_query(
                    self.LIGHT_FIELDS_FALLBACK, page, page_size, status, category,
                    None, discoverer, discoverer_name, sort_by, descending,
                    name_query=name_query,
                )
                result = query.execute()
                return result.data or []
            except Exception:
                return []

    def get_channel_ids(self) -> set[str]:
        """获取库中所有频道ID（用于去重）"""
        try:
            result = self.client.table(self.TABLE_NAME).select("channel_id").execute()
            return {r["channel_id"] for r in (result.data or [])}
        except Exception:
            return set()

    def exists(self, channel_id: str) -> bool:
        """检查某频道是否已在库中"""
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .select("channel_id")
                .eq("channel_id", channel_id)
                .execute()
            )
            return len(result.data or []) > 0
        except Exception:
            return False

    # ============================================================
    # 新增
    # ============================================================

    def add_influencer(self, channel_data: dict, discovered_by: str = "") -> bool:
        """
        添加新网红到公共库
        channel_data: 频道信息（来自 youtube_api 的验证结果）
        discovered_by: 挖掘人名字
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        record = {
            "channel_id": channel_data.get("channel_id", ""),
            "channel_name": channel_data.get("channel_name", ""),
            "channel_url": channel_data.get("channel_url", ""),
            "about_url": channel_data.get("about_url", ""),
            "category": channel_data.get("category", ""),
            "content_category": channel_data.get("content_category", "")
            or channel_data.get("ai_content_category", ""),
            "subscribers": channel_data.get("subscribers", 0),
            "avg_views_30d": channel_data.get("avg_views_30d", 0),
            "view_sub_ratio": channel_data.get("view_sub_ratio", 0),
            "last_upload": channel_data.get("last_upload", ""),
            "score_total": channel_data.get("scores", {}).get("total", 0),
            # 第二期：评分明细 + AI 分析结果（双垂类/相关度/标签）一起存档，信息不丢
            "score_detail": json.dumps({
                "scores": channel_data.get("scores", {}),
                "ai_category": channel_data.get("ai_category", ""),
                "ai_content_category": channel_data.get("ai_content_category", ""),
                "ai_relevance": channel_data.get("ai_relevance", ""),
                "ai_tags": channel_data.get("ai_tags", []),
                "ai_analyzed": channel_data.get("ai_analyzed", False),
            }, ensure_ascii=False),
            "emails": ", ".join(channel_data.get("emails", [])),
            "has_commercial": channel_data.get("commercial_history", {}).get("has_commercial", False),
            "commercial_evidence": ", ".join(channel_data.get("commercial_history", {}).get("evidence", [])),
            "recent_titles": " / ".join(channel_data.get("recent_titles", [])[:3]),
            "thumbnails": str(channel_data.get("recent_thumbnails", [])),
            "status": "新发现",
            "status_date": now,
            "discovered_by": discovered_by,
            "email_sent_date": None,
            "introduced_date": None,
            "notes": "",
            "added_date": now,
            "last_checked": now,
        }
        try:
            self.client.table(self.TABLE_NAME).insert(record).execute()
            self.last_error = None
            return True
        except Exception as e:
            # content_category 新列还没建时降级重试一次（去掉该列），不阻塞入库
            if "content_category" in record:
                try:
                    record2 = {k: v for k, v in record.items() if k != "content_category"}
                    self.client.table(self.TABLE_NAME).insert(record2).execute()
                    self.last_error = None
                    return True
                except Exception:
                    pass
            self.last_error = str(e)
            return False

    def bulk_add(self, records: list[dict], discovered_by: str = "") -> int:
        """批量添加，返回成功数量"""
        success = 0
        for data in records:
            if self.add_influencer(data, discovered_by):
                success += 1
        return success

    # ============================================================
    # 更新
    # ============================================================

    def update_status(self, channel_id: str, new_status: str) -> bool:
        """更新网红状态"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_data = {
            "status": new_status,
            "status_date": now,
        }
        # 如果标记为"已发邮件"，记录发送日期
        if new_status == "已发邮件":
            update_data["email_sent_date"] = now
        # 如果标记为"已引入"，记录引入日期
        if new_status == "已引入":
            update_data["introduced_date"] = now

        try:
            self.client.table(self.TABLE_NAME).update(update_data).eq("channel_id", channel_id).execute()
            return True
        except Exception:
            return False

    def update_notes(self, channel_id: str, notes: str) -> bool:
        """更新备注"""
        try:
            self.client.table(self.TABLE_NAME).update({"notes": notes}).eq("channel_id", channel_id).execute()
            return True
        except Exception:
            return False

    def update_last_checked(self, channel_id: str, still_active: bool, new_data: dict = None) -> bool:
        """复查后更新"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_data = {"last_checked": now}

        if not still_active:
            update_data["status"] = "已淘汰"
            update_data["status_date"] = now
        elif new_data:
            update_data["subscribers"] = new_data.get("subscribers", 0)
            update_data["avg_views_30d"] = new_data.get("avg_views_30d", 0)
            update_data["view_sub_ratio"] = new_data.get("view_sub_ratio", 0)
            update_data["last_upload"] = new_data.get("last_upload", "")
            update_data["score_total"] = new_data.get("scores", {}).get("total", 0)
            # 刷新时重跑了 AI → 把最新的双垂类标签也存下来
            if new_data.get("ai_analyzed"):
                if new_data.get("ai_category"):
                    update_data["category"] = new_data["ai_category"]
                if new_data.get("ai_content_category"):
                    update_data["content_category"] = new_data["ai_content_category"]

        try:
            self.client.table(self.TABLE_NAME).update(update_data).eq("channel_id", channel_id).execute()
            return True
        except Exception:
            # content_category 新列还没建时降级重试一次（去掉该列），保证基础数据照常更新
            if "content_category" in update_data:
                try:
                    update_data2 = {k: v for k, v in update_data.items() if k != "content_category"}
                    self.client.table(self.TABLE_NAME).update(update_data2).eq("channel_id", channel_id).execute()
                    return True
                except Exception:
                    pass
            return False

    # ============================================================
    # 导入已有名单
    # ============================================================

    def import_existing(self, channel_ids: list[str], api_key: str, quota,
                        status: str = "已发邮件", imported_by: str = "",
                        line_dates: dict = None, update_existing: bool = False,
                        line_by: dict = None) -> dict:
        """
        导入已有网红名单（通过频道ID或链接）
        line_dates: 原始行文本（去掉日期后的链接部分）→ 发邮件日期（YYYY-MM-DD）
        line_by: 链接 → 挖掘人（空着算导入操作人 imported_by）
        update_existing: 库里已有的博主是否顺便更新状态和发邮件日期
        返回：{"success": int, "updated": int, "skipped": int, "failed": int, "failed_lines": [str]}
        """
        from youtube_api import get_channels, resolve_channel_ids

        line_dates = line_dates or {}
        line_by = line_by or {}
        result = {"success": 0, "updated": 0, "skipped": 0, "failed": 0, "failed_lines": []}

        # 先把混合格式（UC ID / @handle / 各种链接 / 视频链接）统一解析成频道ID
        # 实在无法识别的行计入 failed 并记录原文，不再静默吞掉
        resolved_ids, unresolvable, raw_by_id = resolve_channel_ids(channel_ids, api_key, quota)
        result["failed"] += len(unresolvable)
        result["failed_lines"] = list(unresolvable)

        # 区分已存在 / 新博主
        existing_ids = [cid for cid in resolved_ids if self.exists(cid)]
        new_ids = [cid for cid in resolved_ids if not self.exists(cid)]
        result["skipped"] = len(existing_ids)

        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        def _sent_date_for(cid: str) -> str:
            """按原始行找到这行写的发邮件日期，没写就按今天。"""
            raw = raw_by_id.get(cid, "")
            return (line_dates.get(raw) or today)

        # 已有博主：按开关决定是否同步更新状态和发邮件日期
        if update_existing and existing_ids:
            for cid in existing_ids:
                update_data = {"status": status, "status_date": now}
                if status == "已发邮件":
                    update_data["email_sent_date"] = _sent_date_for(cid)
                try:
                    self.client.table(self.TABLE_NAME).update(update_data).eq("channel_id", cid).execute()
                    result["updated"] += 1
                except Exception:
                    result["failed"] += 1

        if not new_ids:
            return result

        # 批量获取频道信息，然后走和挖掘一样的补全（播放/邮箱/评分/AI 垂类）
        channels = get_channels(new_ids, api_key, quota)
        channels = enrich_import_channels(channels, api_key, quota)

        for cid, info in channels.items():
            record = {
                "channel_id": cid,
                "channel_name": info.get("channel_name", ""),
                "channel_url": info.get("channel_url", ""),
                "about_url": info.get("about_url", ""),
                "category": info.get("category", ""),
                "content_category": info.get("content_category", "")
                or info.get("ai_content_category", ""),
                "subscribers": info.get("subscribers", 0),
                "avg_views_30d": info.get("avg_views_30d", 0),
                "view_sub_ratio": info.get("view_sub_ratio", 0),
                "last_upload": info.get("last_upload", ""),
                "score_total": info.get("scores", {}).get("total", 0),
                "score_detail": json.dumps({
                    "scores": info.get("scores", {}),
                    "ai_category": info.get("ai_category", ""),
                    "ai_content_category": info.get("ai_content_category", ""),
                    "ai_relevance": info.get("ai_relevance", ""),
                    "ai_tags": info.get("ai_tags", []),
                    "ai_analyzed": info.get("ai_analyzed", False),
                }, ensure_ascii=False),
                "emails": ", ".join(info.get("emails", [])),
                "has_commercial": info.get("commercial_history", {}).get("has_commercial", False),
                "commercial_evidence": ", ".join(info.get("commercial_history", {}).get("evidence", [])),
                "recent_titles": " / ".join(info.get("recent_titles", [])[:3]),
                "thumbnails": str(info.get("recent_thumbnails", [])),
                "status": status,
                "status_date": now,
                "discovered_by": line_by.get(raw_by_id.get(cid, "")) or imported_by,
                "email_sent_date": _sent_date_for(cid) if status == "已发邮件" else None,
                "introduced_date": None,
                "notes": "批量导入",
                "added_date": now,
                "last_checked": now,
            }
            try:
                self.client.table(self.TABLE_NAME).insert(record).execute()
                result["success"] += 1
            except Exception:
                # content_category 新列还没建时降级重试一次（去掉该列）
                if "content_category" in record:
                    try:
                        record2 = {k: v for k, v in record.items() if k != "content_category"}
                        self.client.table(self.TABLE_NAME).insert(record2).execute()
                        result["success"] += 1
                        continue
                    except Exception:
                        pass
                result["failed"] += 1

        return result

    # ============================================================
    # 旧数据一键补全
    # ============================================================

    def backfill_sparse(self, api_key: str, quota, status_cb=None, limit: int = 0) -> dict:
        """
        把库里评分明细为空的旧记录补全成和挖掘一样的全量数据（粉丝/播放/邮箱/评分/AI垂类）。
        幂等：只碰 score_detail 为空的记录，补过的不再动；YouTube 已删除的频道自动跳过。
        status_cb(pct, text) 用于页面进度条。limit>0 时只补前 limit 条（测试/限量用）。
        返回 {"total", "done", "gone", "failed"}。
        """
        from youtube_api import get_channels, verify_channel, score_channel
        from ai_analyzer import analyze_channels

        def _say(pct, text):
            if status_cb:
                try:
                    status_cb(pct, text)
                except Exception:
                    pass

        rows = self.get_all()

        def _is_sparse(r):
            sd = r.get("score_detail")
            if isinstance(sd, dict):
                return not sd
            return not str(sd or "").strip().startswith("{")

        sparse = [r for r in rows if _is_sparse(r) and r.get("channel_id")]
        if limit:
            sparse = sparse[:limit]
        res = {"total": len(sparse), "done": 0, "gone": 0, "failed": 0}
        if not sparse:
            _say(1.0, "没有需要补全的记录")
            return res

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        _say(0.02, f"共 {res['total']} 个待补全，开始…")
        CHUNK = 8
        for i in range(0, len(sparse), CHUNK):
            chunk = sparse[i:i + CHUNK]
            cids = [r["channel_id"] for r in chunk]
            try:
                chs = get_channels(cids, api_key, quota)
            except Exception:
                chs = {}
                res["failed"] += len(chunk)

            enriched = []
            for r in chunk:
                info = chs.get(r["channel_id"])
                if not info:
                    res["gone"] += 1  # 频道已被 YouTube 删除/不存在
                    continue
                try:
                    full = verify_channel(info, api_key, quota, allow_inactive=True) or info
                except Exception:
                    full = info
                enriched.append((r, full))

            if enriched:
                dicts = [f for _, f in enriched]
                try:
                    analyze_channels(dicts)
                except Exception:
                    pass
                for r, f in enriched:
                    try:
                        if f.get("ai_category"):
                            f["category"] = f["ai_category"]
                        if f.get("ai_content_category"):
                            f["content_category"] = f["ai_content_category"]
                        try:
                            f["scores"] = score_channel(f)
                        except Exception:
                            f["scores"] = {"total": 0}
                        emails = f.get("emails") or []
                        ch = f.get("commercial_history") or {}
                        upd = {
                            "category": str(f.get("category") or ""),
                            "content_category": str(f.get("content_category") or ""),
                            "subscribers": f.get("subscribers") or 0,
                            "avg_views_30d": f.get("avg_views_30d") or 0,
                            "view_sub_ratio": f.get("view_sub_ratio") or 0,
                            "last_upload": str(f.get("last_upload") or ""),
                            "score_total": (f.get("scores") or {}).get("total", 0),
                            "score_detail": json.dumps({
                                "scores": f.get("scores") or {},
                                "ai_category": f.get("ai_category") or "",
                                "ai_content_category": f.get("ai_content_category") or "",
                                "ai_relevance": f.get("ai_relevance", ""),
                                "ai_tags": f.get("ai_tags") or [],
                                "ai_analyzed": bool(f.get("ai_analyzed", False)),
                            }, ensure_ascii=False, default=str),
                            "emails": ", ".join(str(e) for e in emails),
                            "has_commercial": bool(ch.get("has_commercial", False)),
                            "commercial_evidence": ", ".join(str(e) for e in (ch.get("evidence") or [])),
                            "recent_titles": " / ".join(str(t) for t in (f.get("recent_titles") or [])[:3]),
                            "thumbnails": str(f.get("recent_thumbnails") or []),
                            "last_checked": now,
                        }
                        try:
                            self.client.table(self.TABLE_NAME).update(upd).eq("channel_id", r["channel_id"]).execute()
                        except Exception:
                            # content_category 新列还没建时降级重试一次（去掉该列）
                            upd2 = {k: v for k, v in upd.items() if k != "content_category"}
                            self.client.table(self.TABLE_NAME).update(upd2).eq("channel_id", r["channel_id"]).execute()
                        res["done"] += 1
                    except Exception:
                        res["failed"] += 1

            _say(min(0.99, (i + CHUNK) / len(sparse)),
                 f"进度 {min(i + CHUNK, len(sparse))}/{len(sparse)} ｜ 已补 {res['done']} ｜ 消失 {res['gone']} ｜ 失败 {res['failed']}")
        return res

    # ============================================================
    # 删除
    # ============================================================

    def remove(self, channel_id: str) -> bool:
        """从库中移除"""
        try:
            self.client.table(self.TABLE_NAME).delete().eq("channel_id", channel_id).execute()
            return True
        except Exception:
            return False

    def batch_update_status(self, channel_ids: list[str], new_status: str) -> int:
        """批量更新状态，返回成功更新的数量"""
        if not channel_ids:
            return 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        update_data = {"status": new_status, "status_date": now}
        if new_status == "已发邮件":
            update_data["email_sent_date"] = now
        if new_status == "已引入":
            update_data["introduced_date"] = now
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .update(update_data)
                .in_("channel_id", channel_ids)
                .execute()
            )
            return len(result.data or [])
        except Exception:
            return 0

    def batch_remove(self, channel_ids: list[str]) -> int:
        """批量删除，返回成功删除的数量"""
        if not channel_ids:
            return 0
        try:
            result = (
                self.client.table(self.TABLE_NAME)
                .delete()
                .in_("channel_id", channel_ids)
                .execute()
            )
            return len(result.data or [])
        except Exception:
            return 0

    # ============================================================
    # 成员名单
    # ============================================================

    def get_members(self) -> list[str]:
        """获取所有团队成员名字（按加入顺序）"""
        try:
            result = (
                self.client.table(self.MEMBERS_TABLE)
                .select("name")
                .order("id")
                .execute()
            )
            return [r["name"] for r in (result.data or []) if r.get("name")]
        except Exception:
            return []

    def add_member(self, name: str) -> bool:
        """添加新成员（名字已存在则视为成功）"""
        name = (name or "").strip()
        if not name:
            return False
        if name in self.get_members():
            return True
        try:
            self.client.table(self.MEMBERS_TABLE).insert(
                {"name": name, "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            ).execute()
            return True
        except Exception:
            return False

    def remove_members(self, names: list[str]) -> bool:
        """删除成员名字（批量）"""
        names = [str(n).strip() for n in (names or []) if str(n or "").strip()]
        if not names:
            return True
        try:
            self.client.table(self.MEMBERS_TABLE).delete().in_("name", names).execute()
            return True
        except Exception:
            return False

    def rename_member(self, old_name: str, new_name: str) -> tuple:
        """给成员改名，并把旧名下的数据（挖到的网红、个人设置）一起迁到新名。
        返回 (是否成功, 错误信息)。"""
        old_name = (old_name or "").strip()
        new_name = (new_name or "").strip()
        if not old_name or not new_name:
            return False, "名字不能为空"
        if old_name == new_name:
            return False, "新名字和旧名字一样"
        members = self.get_members()
        if old_name not in members:
            return False, f"名单里没有「{old_name}」"
        if new_name in members:
            return False, f"「{new_name}」已在名单里，不能改成它"
        try:
            self.client.table(self.MEMBERS_TABLE).update({"name": new_name}).eq("name", old_name).execute()
        except Exception:
            return False, "改名失败，请稍后再试"
        # 旧名下的数据搬家（个别失败不影响改名主流程）
        try:
            self.client.table(self.TABLE_NAME).update({"discovered_by": new_name}).eq("discovered_by", old_name).execute()
        except Exception:
            pass
        try:
            self.client.table(self.SETTINGS_TABLE).update({"member_name": new_name}).eq("member_name", old_name).execute()
        except Exception:
            pass
        return True, ""

    # ============================================================
    # 关键词库（可增删 · 全队共享）
    # ============================================================

    def get_keywords(self) -> dict[str, list[str]]:
        """读取公共库里的关键词，返回 {垂类: [关键词, ...]}"""
        try:
            result = (
                self.client.table(self.KEYWORDS_TABLE)
                .select("*")
                .order("id")
                .execute()
            )
            kw_map: dict[str, list[str]] = {}
            for r in (result.data or []):
                cat = r.get("category", "")
                kw = r.get("keyword", "")
                if cat and kw:
                    kw_map.setdefault(cat, [])
                    if kw not in kw_map[cat]:
                        kw_map[cat].append(kw)
            return kw_map
        except Exception:
            return {}

    def add_keyword(self, category: str, keyword: str) -> bool:
        """添加一个关键词到公共库"""
        category = (category or "").strip()
        keyword = (keyword or "").strip()
        if not category or not keyword:
            return False
        try:
            self.client.table(self.KEYWORDS_TABLE).insert(
                {"category": category, "keyword": keyword,
                 "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            ).execute()
            return True
        except Exception:
            return False

    def delete_keyword(self, category: str, keyword: str) -> bool:
        """从公共库删除一个关键词"""
        try:
            (
                self.client.table(self.KEYWORDS_TABLE)
                .delete()
                .eq("category", category)
                .eq("keyword", keyword)
                .execute()
            )
            return True
        except Exception:
            return False

    def seed_keywords(self, default_library: dict[str, list[str]]) -> bool:
        """第一次使用时，把内置默认词库批量写入公共库"""
        rows = [
            {"category": cat, "keyword": kw,
             "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
            for cat, kws in default_library.items()
            for kw in kws
        ]
        if not rows:
            return False
        try:
            self.client.table(self.KEYWORDS_TABLE).insert(rows).execute()
            return True
        except Exception:
            return False

    # ============================================================
    # 统计
    # ============================================================

    def get_stats(self) -> dict:
        """获取库统计信息"""
        all_records = self.get_all()
        stats = {
            "total": len(all_records),
            "新发现": 0,
            "已发邮件": 0,
            "已引入": 0,
            "已拒绝": 0,
            "已淘汰": 0,
        }
        for r in all_records:
            status = r.get("status", "")
            if status in stats:
                stats[status] += 1
        return stats

    # ============================================================
    # 个人筛选设置（每人一行，互不干扰）
    # ============================================================

    def get_user_settings(self, member_name: str) -> dict | None:
        """
        读取某成员的个人筛选设置。
        返回 dict（她的自定义配置）或 None（从未保存过，应使用默认值）。
        """
        if not member_name:
            return None
        try:
            result = (
                self.client.table(self.SETTINGS_TABLE)
                .select("config_json")
                .eq("member_name", member_name)
                .execute()
            )
            rows = result.data or []
            if not rows:
                return None
            raw = rows[0].get("config_json", "{}")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def save_user_settings(self, member_name: str, config: dict) -> bool:
        """
        保存某成员的个人筛选设置（有则更新，无则新增）。
        """
        if not member_name:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        payload = {
            "config_json": json.dumps(config, ensure_ascii=False),
            "updated_at": now,
        }
        try:
            # 先尝试更新
            result = (
                self.client.table(self.SETTINGS_TABLE)
                .update(payload)
                .eq("member_name", member_name)
                .execute()
            )
            if result.data:
                return True
            # 没有已有记录 → 新增
            payload["member_name"] = member_name
            self.client.table(self.SETTINGS_TABLE).insert(payload).execute()
            return True
        except Exception:
            return False
