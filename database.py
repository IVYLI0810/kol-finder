"""
Supabase 数据库模块
功能：公共网红库的读写、去重查询、状态更新、批量导入
"""

from datetime import datetime
import json
from supabase import create_client, Client


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
        "channel_id,channel_name,channel_url,category,subscribers,"
        "score_total,status,discovered_by,emails,notes,added_date,"
        "status_date,last_upload,last_checked,email_sent_date,introduced_date"
    )
    # 兼容尚未添加 introduced_date 列的库（首次升级时）
    LIGHT_FIELDS_FALLBACK = LIGHT_FIELDS.replace(",introduced_date", "")

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
                      discoverer: str = None, discoverer_name: str = "") -> int:
        """按当前筛选条件计数（用于分页）"""
        try:
            query = self.client.table(self.TABLE_NAME).select("*", count="exact")
            if status and status != "全部":
                query = query.eq("status", status)
            if category:
                query = query.in_("category", category)
            if discoverer and discoverer != "全部":
                if discoverer == "只看我的":
                    query = query.eq("discovered_by", discoverer_name)
                else:
                    query = query.eq("discovered_by", discoverer)
            result = query.execute()
            return result.count or 0
        except Exception:
            return 0

    def _build_paginated_query(self, fields: str, page: int, page_size: int,
                               status: str, category: list[str],
                               discoverer: str, discoverer_name: str,
                               sort_by: str, descending: bool):
        """构建设分页查询（不执行）。"""
        query = self.client.table(self.TABLE_NAME).select(fields)

        if status and status != "全部":
            query = query.eq("status", status)
        if category:
            query = query.in_("category", category)
        if discoverer and discoverer != "全部":
            if discoverer == "只看我的":
                query = query.eq("discovered_by", discoverer_name)
            else:
                query = query.eq("discovered_by", discoverer)

        sort_col = self.SORT_COLUMNS.get(sort_by, "added_date")
        query = query.order(sort_col, desc=descending)

        start = (page - 1) * page_size
        end = start + page_size - 1
        return query.range(start, end)

    def get_records_paginated(self, page: int = 1, page_size: int = 30,
                              status: str = None, category: list[str] = None,
                              discoverer: str = None, discoverer_name: str = "",
                              sort_by: str = "添加时间", descending: bool = True) -> list[dict]:
        """
        分页获取网红记录，筛选和排序都在 Supabase 服务端完成。
        只返回列表页需要的轻量字段，减少网络传输和内存占用。
        """
        try:
            query = self._build_paginated_query(
                self.LIGHT_FIELDS, page, page_size, status, category,
                discoverer, discoverer_name, sort_by, descending,
            )
            result = query.execute()
            return result.data or []
        except Exception:
            # 首次升级时 introduced_date 列可能还不存在，先回退到基础字段，
            # 保证旧数据能正常显示；等新列加好后会自动显示完整日期。
            try:
                query = self._build_paginated_query(
                    self.LIGHT_FIELDS_FALLBACK, page, page_size, status, category,
                    discoverer, discoverer_name, sort_by, descending,
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
            "subscribers": channel_data.get("subscribers", 0),
            "avg_views_30d": channel_data.get("avg_views_30d", 0),
            "view_sub_ratio": channel_data.get("view_sub_ratio", 0),
            "last_upload": channel_data.get("last_upload", ""),
            "score_total": channel_data.get("scores", {}).get("total", 0),
            "score_detail": str(channel_data.get("scores", {})),
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

        try:
            self.client.table(self.TABLE_NAME).update(update_data).eq("channel_id", channel_id).execute()
            return True
        except Exception:
            return False

    # ============================================================
    # 导入已有名单
    # ============================================================

    def import_existing(self, channel_ids: list[str], api_key: str, quota,
                        status: str = "已引入", imported_by: str = "") -> dict:
        """
        导入已有网红名单（通过频道ID或链接）
        返回：{"success": int, "skipped": int, "failed": int, "failed_lines": [str]}
        """
        from youtube_api import get_channels, resolve_channel_ids

        result = {"success": 0, "skipped": 0, "failed": 0, "failed_lines": []}

        # 先把混合格式（UC ID / @handle / 链接）统一解析成频道ID
        # 无法识别的行（如视频链接）计入 failed 并记录原文，不再静默吞掉
        resolved_ids, unresolvable = resolve_channel_ids(channel_ids, api_key, quota)
        result["failed"] += len(unresolvable)
        result["failed_lines"] = list(unresolvable)

        # 过滤已存在的
        new_ids = [cid for cid in resolved_ids if not self.exists(cid)]
        result["skipped"] = len(resolved_ids) - len(new_ids)

        if not new_ids:
            return result

        # 批量获取频道信息
        channels = get_channels(new_ids, api_key, quota)

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for cid, info in channels.items():
            record = {
                "channel_id": cid,
                "channel_name": info.get("channel_name", ""),
                "channel_url": info.get("channel_url", ""),
                "about_url": info.get("about_url", ""),
                "category": "",
                "subscribers": info.get("subscribers", 0),
                "avg_views_30d": 0,
                "view_sub_ratio": 0,
                "last_upload": "",
                "score_total": 0,
                "score_detail": "",
                "emails": "",
                "has_commercial": False,
                "commercial_evidence": "",
                "recent_titles": "",
                "thumbnails": "",
                "status": status,
                "status_date": now,
                "discovered_by": imported_by,
                "email_sent_date": now if status == "已引入" else None,
                "introduced_date": now if status == "已引入" else None,
                "notes": "批量导入（已有合作）",
                "added_date": now,
                "last_checked": now,
            }
            try:
                self.client.table(self.TABLE_NAME).insert(record).execute()
                result["success"] += 1
            except Exception:
                result["failed"] += 1

        return result

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
