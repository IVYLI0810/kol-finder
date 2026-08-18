#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YTS 履约同步（只读宜搭，不改 YTS 任何数据）

从 YTS 的宜搭底库（与 YTS 主站同一张表）读取网红流程数据，
找出「履约中」网红（有归属月份 且 合作阶段未完成），供挖掘系统自动标记「已引入」。

钥匙只从 环境变量 / Streamlit Secrets（YIDA_ACCESS_KEY_ID / YIDA_ACCESS_KEY_SECRET）读取，
本地兜底 yida_config_local.py（不入仓库），绝不写进代码。
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# 宜搭表单常量（与 YTS 主站 yts_yida_store 保持一致，非机密）
APP_TYPE = "APP_N85O3OPKB9OO52S4KCTD"
SYSTEM_TOKEN = "XE7668C13088ICWHNJPXODYLFX8Y2Y3Z02NSMBT"
FORM_UUID = "FORM-2A64DBB4851A4301BAA4C0A5C39E752DHXL0"
ACCOUNT_ID = "550448"
ENDPOINT = "aliding.aliyuncs.com"

# 同步需要的字段：代码名 -> fieldId
_SYNC_FIELDS = {
    "channel_id": "textField_msn2qhnb",
    "channel_name": "textField_msn2qhnd",
    "channel_url": "textField_msn2qhnh",
    "category": "selectField_msn2qhnj",
    "recruiter": "textField_msn2qhnl",
    "subscribers": "numberField_msn2qhnp",
    "email": "textField_mswndfpt",
    "plan_month": "textField_mswndfpl",
    "stage": "selectField_mspwxzct",
}
_ID_TO_CODE = {v: k for k, v in _SYNC_FIELDS.items()}


def _load_keys():
    """优先环境变量/Secrets，本地兜底 yida_config_local.py"""
    ak = os.environ.get("YIDA_ACCESS_KEY_ID", "")
    sk = os.environ.get("YIDA_ACCESS_KEY_SECRET", "")
    if ak and sk:
        return ak, sk
    try:
        from yida_config_local import YIDA_CONFIG
        return (str(YIDA_CONFIG.get("access_key_id", "")),
                str(YIDA_CONFIG.get("access_key_secret", "")))
    except ImportError:
        return "", ""


def yts_available() -> bool:
    """宜搭钥匙是否已配置"""
    ak, sk = _load_keys()
    return bool(ak and sk)


class YTSReader:
    """宜搭只读客户端（aliding 网关，与 YTS 主站同一套）"""

    def __init__(self):
        from alibabacloud_aliding20230426.client import Client
        from alibabacloud_aliding20230426 import models as aliding_models
        from alibabacloud_tea_openapi import models as open_api_models
        from alibabacloud_tea_util import models as util_models

        ak, sk = _load_keys()
        config = open_api_models.Config(access_key_id=ak, access_key_secret=sk)
        config.endpoint = ENDPOINT
        self._client = Client(config)
        self._m = aliding_models
        # 超时兜底：宜搭慢/断网时不拖垮页面
        self._runtime = util_models.RuntimeOptions(
            connect_timeout=8000, read_timeout=20000)

    def _search_page(self, page: int, size: int = 100) -> dict:
        req = self._m.SearchFormDatasRequest(
            app_type=APP_TYPE,
            system_token=SYSTEM_TOKEN,
            form_uuid=FORM_UUID,
            language="zh_CN",
            current_page=page,
            page_size=size,
            search_field_json=json.dumps({}, ensure_ascii=False),
        )
        headers = self._m.SearchFormDatasHeaders(
            account_context=self._m.SearchFormDatasHeadersAccountContext(
                account_id=ACCOUNT_ID))
        resp = self._client.search_form_datas_with_options(
            req, headers, self._runtime)
        return resp.body.to_map()

    @staticmethod
    def _to_rec(inst: dict) -> dict:
        raw = inst.get("FormData") or inst.get("formData") or {}
        rec = {}
        for fid, value in raw.items():
            code = _ID_TO_CODE.get(fid)
            if code:
                rec[code] = value
        return rec

    def fetch_all(self) -> list:
        """全量分页拉取（只取同步需要的字段）"""
        def fetch(page):
            data = self._search_page(page)
            return data.get("Data") or data.get("data") or []

        results = []
        rows = fetch(1)
        results.extend(self._to_rec(r) for r in rows)
        # aliding 响应不带 TotalCount，以「不满一页」为结束条件
        next_page = 2
        while len(rows) == 100:
            with ThreadPoolExecutor(max_workers=4) as ex:
                batch = list(ex.map(fetch, range(next_page, next_page + 4)))
            for rows in batch:
                results.extend(self._to_rec(r) for r in rows)
                if len(rows) < 100:
                    break
            next_page += 4
        return results


def is_fulfilled(rec: dict) -> bool:
    """履约中 = 有归属月份 且 合作阶段未完成（与 YTS 口径一致）"""
    return bool((rec.get("plan_month") or "").strip()) \
        and (rec.get("stage") or "") != "已完成"


def run_sync(db) -> dict:
    """
    执行一次同步（需要传入挖掘系统数据库实例）。
    返回 {"marked", "created", "terminated", "fulfilled_total"}。
    """
    reader = YTSReader()
    yida_records = reader.fetch_all()

    fulfilled = [r for r in yida_records if is_fulfilled(r)]
    fulfilled_ids = {r.get("channel_id") for r in fulfilled if r.get("channel_id")}
    yida_map = {r.get("channel_id"): r for r in yida_records if r.get("channel_id")}

    kol_records = db.get_all()
    kol_map = {r.get("channel_id"): r for r in kol_records if r.get("channel_id")}

    marked = created = terminated = 0

    # 1) 履约中的网红 -> 标记已引入 / 自动补建
    for y in fulfilled:
        cid = y.get("channel_id")
        if not cid:
            continue
        rec = kol_map.get(cid)
        if rec is not None:
            if rec.get("status") != "已引入":
                if db.update_status(cid, "已引入"):
                    marked += 1
        else:
            if db.add_influencer_from_yts(y):
                created += 1
                kol_map[cid] = {"channel_id": cid, "status": "已引入", "notes": ""}

    # 2) 退出履约检查：只处理已是「已引入」的记录，状态不回退
    stamp = datetime.now().strftime("%m-%d")
    for cid, rec in kol_map.items():
        if rec.get("status") != "已引入" or cid in fulfilled_ids:
            continue
        y = yida_map.get(cid)
        if y and (y.get("stage") or "") == "已完成":
            continue  # 正常做完关单，不打扰
        notes = rec.get("notes") or ""
        if "合作意外终止" in notes:
            continue  # 已标注过，不重复
        new_notes = (notes + "\n" if notes else "") + \
            f"[{stamp} YTS退出履约] 合作意外终止（YTS同步自动标注）"
        if db.update_notes(cid, new_notes):
            terminated += 1

    return {"marked": marked, "created": created, "terminated": terminated,
            "fulfilled_total": len(fulfilled_ids)}
