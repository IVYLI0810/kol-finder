#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kol-finder · YTS 履约同步（Phase 1 换库版）

功能等价于原 yts_sync.py，但底层不再翻宜搭（10-20s 慢），
改成读同一个 Supabase 项目的 public.collabs 表 → 数百毫秒返回。
主站"自动标记已引入 / 退出履约 / 补建网红行"三条逻辑保持不变。

需要 kol-finder/database.py 里存在 `InfluencerDB.add_influencer_from_yts(rec)`
（本次改造同时补上，修掉历史遗留 bug）。
"""
import json
import os
import re as _re
import time
from datetime import datetime

import requests


# ---------- 与 kol-bd 同项目 · 与 yts_roster 保持同一份 key ----------
def _supa():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        try:
            from yida_config_local import SUPABASE_CONFIG as local  # type: ignore
            url = url or local.get("url", "")
            key = key or local.get("key", "")
        except ImportError:
            pass
    if not url:
        url = "https://webjrwzorxxlqrcrrnro.supabase.co"
    if not key:
        key = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"
    return url.rstrip("/"), key


_SUPA_URL, _SUPA_KEY = _supa()
_H = {"apikey": _SUPA_KEY, "Authorization": f"Bearer {_SUPA_KEY}"}


# ---------- 归一化（保留原逻辑）----------
def _norm_refs(*parts):
    refs = set()
    for s in parts:
        if not s:
            continue
        s = str(s).strip().lower()
        if not s:
            continue
        s = _re.sub(r"^https?://", "", s)
        s = _re.sub(r"^www\.", "", s)
        s = s.rstrip("/")
        s = _re.sub(r"^(youtube\.com|youtu\.be)/", "", s)
        m = _re.match(r"^(?:channel/|c/|user/)?(@?[a-z0-9._-]+)$", s)
        if m:
            refs.add(m.group(1).lstrip("@"))
    return refs


# ---------- Supabase 读 collabs ----------
def fetch_all_collabs():
    """拉全表 collabs（含所有月份行 + 裸行），过滤已软删的。
    字段就是代码名，直接给 run_sync 用。"""
    rows, off, limit = [], 0, 500
    while True:
        r = requests.get(f"{_SUPA_URL}/rest/v1/collabs",
                         params={"select": "*",
                                 "deleted": "eq.false",
                                 "order": "channel_id.asc",
                                 "offset": off, "limit": limit},
                         headers=_H, timeout=20)
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if len(page) < limit:
            break
        off += limit
    return rows


def is_fulfilled(rec):
    """有归属月份 且 未闭环 → 履约中；与旧版口径一致"""
    pm = str(rec.get("plan_month") or "").strip()
    st = (rec.get("stage") or "").strip()
    return bool(pm) and st != "已完成"


# ---------- 主入口 ----------
def run_sync(db) -> dict:
    """被 kol-finder/app.py 每 300s（或按钮触发）调用；
    db = kol-finder database.InfluencerDB 实例（同项目 Supabase）"""
    try:
        collabs = fetch_all_collabs()
    except Exception as e:
        return {"error": f"读取 YTS 合作表失败: {e}"}

    ful = [c for c in collabs if is_fulfilled(c)]
    yida_map = {}
    fulfilled_ids = set()
    for c in ful:
        cid = (c.get("channel_id") or "").strip()
        if not cid:
            continue
        yida_map[cid] = c
        fulfilled_ids.add(cid)

    try:
        kol_records = db.get_all(include_deleted=True)
    except Exception as e:
        return {"error": f"读取挖掘站网红库失败: {e}"}
    kol_map = {(r.get("channel_id") or "").strip(): r for r in kol_records}

    # 建一份"归一化标识 → kol channel_id"倒排，用于兜底匹配（URL 大小写/前缀差异）
    kol_norm_index = {}
    for cid, r in kol_map.items():
        for ref in _norm_refs(cid, r.get("channel_url")):
            kol_norm_index.setdefault(ref, cid)

    marked = created = skipped = ignored = terminated = 0
    for cid in fulfilled_ids:
        y = yida_map[cid]
        db_rec = kol_map.get(cid)
        if db_rec is None:
            # 归一化命中：URL/handle 相同但 channel_id 拼写不同 → 用现有那行
            for ref in _norm_refs(y.get("channel_id"), y.get("channel_url")):
                hit = kol_norm_index.get(ref)
                if hit:
                    db_rec = kol_map.get(hit)
                    break
        if db_rec is None:
            # 库内没这条频道 → 从 YTS 补建
            try:
                db.add_influencer_from_yts(y)
                created += 1
            except Exception:
                skipped += 1
            continue

        st = db_rec.get("status") or ""
        if st in ("已拒绝", "已淘汰"):
            ignored += 1
            continue
        if st == "已删除":
            skipped += 1
            continue
        if st in ("新发现", "已发邮件"):
            try:
                db.update_status(cid, "已引入")
                marked += 1
            except Exception:
                skipped += 1

    # 曾经是"已引入"但现在从 YTS 履约名单里消失 → 标注 + 退回
    ful_set = fulfilled_ids
    for cid, r in kol_map.items():
        if (r.get("status") or "") != "已引入":
            continue
        if cid in ful_set:
            continue
        # YTS 有该行但 stage=已完成/月份被清空/或整行删了，都属于"退出履约"
        term_note = (f"[{datetime.now().strftime('%m-%d')} YTS退出履约] "
                     f"合作意外终止（YTS同步自动标注）")
        try:
            existing = (r.get("notes") or "")
            if "合作意外终止" not in existing:
                db.update_notes(cid, (existing + "\n" if existing else "") + term_note)
                terminated += 1
            if cid in yida_map:
                # YTS 里还存在但已不履约 → 退回"已发邮件"
                db.revert_from_introduced(cid)
        except Exception:
            pass

    # 3) Phase 2 归属回填：collabs.recruiter（YTS 权威）→ influencers.discovered_by
    #    让挖掘站显示的挖掘人始终跟 YTS 一致（谁最后触达，两边都变谁）。
    by_cid = {}
    for c in collabs:
        cid = (c.get("channel_id") or "").strip()
        if cid:
            by_cid.setdefault(cid, []).append(c)
    recruited = 0
    for cid, rows in by_cid.items():
        cand = [x for x in rows if (x.get("recruiter") or "").strip()]
        if not cand:
            continue
        active = [x for x in cand
                  if (x.get("stage") or "").strip() != "已完成"]
        pick_pool = active or cand
        pick_pool.sort(key=lambda x: str(x.get("plan_month") or "").strip())
        auth_rec = (pick_pool[-1].get("recruiter") or "").strip()
        kol = kol_map.get(cid)
        if kol and (kol.get("discovered_by") or "").strip() != auth_rec:
            try:
                if db.set_discovered_by(cid, auth_rec):
                    recruited += 1
            except Exception:
                pass

    return {"marked": marked, "created": created, "skipped": skipped,
            "ignored": ignored, "terminated": terminated,
            "recruited": recruited,
            "fulfilled_total": len(ful)}


# ---------- 兼容老 API（app.py 有 from yts_sync import YTSReader 之类调用时兜底）----------
class YTSReader:
    """旧 API 占位。新代码用 fetch_all_collabs()。"""

    def __init__(self, *a, **k):
        pass

    def fetch_all(self):
        return fetch_all_collabs()


if __name__ == "__main__":
    import database as D
    url, key = _supa()
    db = D.InfluencerDB(url, key)
    print(json.dumps(run_sync(db), ensure_ascii=False, indent=1))
