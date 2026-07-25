"""
Supabase 数据库模块
功能：公共网红库的读写、去重查询、状态更新、批量导入
"""

from datetime import datetime
from supabase import create_client, Client


class InfluencerDB:
    """公共网红数据库（基于 Supabase）"""

    TABLE_NAME = "influencers"
    MEMBERS_TABLE = "members"  # 团队成员名单（只存名字，方便下拉选择）

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
        返回：{"success": int, "skipped": int, "failed": int}
        """
        from youtube_api import get_channels

        result = {"success": 0, "skipped": 0, "failed": 0}

        # 过滤已存在的
        new_ids = [cid for cid in channel_ids if not self.exists(cid)]
        result["skipped"] = len(channel_ids) - len(new_ids)

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
                "email_sent_date": None,
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
