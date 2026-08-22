# -*- coding: utf-8 -*-
"""
双标签一键迁移：把库里「所有」记录改成新版双标签（内容垂类 + 带货垂类）
====================================================================
阶段A（机械查表，零费用）：
  category 还是老值（中文6类 / 旧韩文15类）的记录，按对照表换成
  内容垂类（写新列 content_category）+ 带货垂类（写 category，官方26类韩文名）。

阶段B（AI补全，走百炼 qwen）：
  带货垂类已经是新版、但内容垂类还空着的记录，用库里存的
  频道名 + 最近视频标题 + 旧AI标签 让 AI 补判内容垂类。
  - 已有带货垂类一律保留（当年是拿全量数据判的，比补全时信息多），AI 只补内容垂类
  - 例外：内容被判成 게임/엔터테인먼트/기타 时，按全局规则把带货垂类改成 기타 并列入复查清单
  - 带货垂类也空着的记录，AI 一次补齐两个标签

用法：
  python3 migrate_categories.py                  # 预览：值分布 + 两阶段计划（不调AI不花钱）
  python3 migrate_categories.py --apply          # 真正执行：阶段A + 阶段B
  python3 migrate_categories.py --apply --no-ai  # 只跑阶段A（机械映射）
"""

import json
import sys

from supabase import create_client

from ai_analyzer import (
    AI_BATCH_SIZE,
    AI_CATEGORY_TABLE,
    ALLOWED_COMMERCE,
    CONTENT_CATEGORY_TABLE,
    CONTENT_GUIDE,
    MAPPING_TABLE_TEXT,
    NON_COMMERCIAL_CONTENT,
    _call_qwen,
    _extract_json_array,
    adjudicate_labels,
    ai_ready,
)

# 与 app.py 保持一致（团队公共 anon key，设计上可公开）
SUPABASE_URL = "https://webjrwzorxxlqrcrrnro.supabase.co"
SUPABASE_KEY = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"

TABLE = "influencers"

# 旧值 → (内容垂类, 带货垂类)
OLD_VALUE_MAP = {
    # ---- 老的中文垂类（关键词库时代的6类） ----
    "平价美妆": ("뷰티", "뷰티 & 헬스"),
    "家居收纳": ("홈/인테리어", "홈 & 가든"),
    "宿舍好物": ("홈/인테리어", "홈 & 가든"),
    "通勤配件": ("패션/코디", "주얼리 & 액세서리"),
    "宠物用品": ("반려동물", "반려동물 용품"),
    "学生用品": ("공부/지식", "사무 & 학용품"),
    # ---- 旧韩文垂类（更早一版分类表） ----
    "네일": ("뷰티", "뷰티 & 헬스"),
    "생활용품": ("홈/인테리어", "홈 & 가든"),
    "의복 & 부속품": ("패션/코디", "주얼리 & 액세서리"),  # 有歧义（可能是服装），迁完建议人工过一遍
    "의복&부속품": ("패션/코디", "주얼리 & 액세서리"),
    "컴퓨터 및 오피스": ("디지털/테크", "사무 & 학용품"),
    "전화 및 통신 액세서리": ("디지털/테크", "휴대폰 & 액세서리"),
    "애완동물": ("반려동물", "반려동물 용품"),
    "완구 및 취미": ("취미/수집/장난감", "완구 & 게임"),
    "도구": ("DIY/핸드메이드", "공구 & 홈인테리어"),
    "음식": ("음식", "식품 & 장보기"),
    "오토바이 장비 및 부품": ("자동차/바이크", "오토바이 & 파워스포츠"),
    "오토바이": ("자동차/바이크", "오토바이 & 파워스포츠"),
}


def fetch_all(client):
    rows, off = [], 0
    while True:
        r = (client.table(TABLE)
             .select("channel_id,channel_name,category,content_category,"
                     "recent_titles,score_detail")
             .range(off, off + 999)
             .execute())
        batch = r.data or []
        rows += batch
        off += len(batch)
        if len(batch) < 1000:
            break
    return rows


# ============================================================
# 阶段B：AI 补全内容垂类
# ============================================================

def _backfill_brief(row: dict, idx: int) -> dict:
    """用库里存档的轻量信息拼一个给 AI 的简报"""
    titles = [t.strip() for t in (row.get("recent_titles") or "").split("/") if t.strip()][:6]
    tags = []
    try:
        detail = json.loads(row.get("score_detail") or "{}")
        tags = [t for t in (detail.get("ai_tags") or []) if t][:6]
    except (ValueError, TypeError):
        pass
    brief = {
        "idx": idx,
        "频道名": row.get("channel_name", ""),
        "最近视频标题": titles,
    }
    if tags:
        brief["旧AI标签"] = tags
    if (row.get("category") or "").strip():
        brief["库里已有带货垂类"] = row["category"].strip()
    return brief


def _backfill_prompt(briefs: list[dict]) -> str:
    content_cats = "、".join(CONTENT_CATEGORY_TABLE)
    content_guide = "\n".join(f"- {c}：{CONTENT_GUIDE.get(c, '')}" for c in CONTENT_CATEGORY_TABLE)
    commerce_cats = "、".join(AI_CATEGORY_TABLE)
    payload = json.dumps(briefs, ensure_ascii=False, indent=1)
    return f"""你是资深韩国YouTube电商网红营销选号专家。客户是 AliExpress（速卖通）韩国站。
下面给你 {len(briefs)} 个频道的存档信息（JSON数组，idx是编号）——只有频道名、最近视频标题，
可能有旧AI标签和库里已存的带货垂类。信息有限，按最可能的情况判断，不要输出表外值。

【第1步 content_cat 内容垂类】这个频道主要在拍什么内容。必须从下面17个里选一个，一字不差地写：
{content_cats}

每个内容垂类的判定标准（看频道拍什么）：
{content_guide}

【第2步 commerce_cat 带货垂类】这个频道的观众最可能买哪类商品、最适合挂哪类商品链接。
必须从下面26个速卖通官方类目里选一个，一字不差地写：
{commerce_cats}

映射规则（内容垂类 → 默认带货垂类，内容明显偏向时按改判规则换，只能用允许的备选）：
{MAPPING_TABLE_TEXT}

三条全局规则：
1. 带货垂类永远跟着"观众会买什么"走，不跟着"视频拍什么"走。
2. 非带货向内容（게임、엔터테인먼트、기타）带货垂类强制기타，相关度不得超过39。
3. 平手时看主角：视频里被展示、被讲解最多的东西属于哪个类目就选哪个；还分不出就选默认值。

4个冷门类目（특수 의류 & 코스프레、산업 & 과학、서적 & 미디어、헤어 익스텐션 & 가발）
只有内容明确命中才允许选，其余情况不要选。

重要：如果信息里带「库里已有带货垂类」，说明之前已人工/AI确认过带货方向，
除非与内容明显矛盾，请直接沿用该值，不要另起炉灶。

【第3步 relevance 相关度】整数0-100，这个频道适不适合速卖通带货合作
（80-100 种草/消费/生活方式类；60-79 相关不突兀；40-59 沾边不典型；0-39 不相关/受众不符）。

【第4步 tags】用2个中文关键词概括频道内容（每个不超过6个字）。

严格按JSON数组输出，不要输出任何其他文字，格式：
[{{"idx":0,"content_cat":"홈/인테리어","commerce_cat":"홈 & 가든","relevance":85,"tags":["独居日常","收纳好物"]}}]

频道信息：
{payload}"""


def backfill_ai(client, rows: list[dict]) -> dict:
    """阶段B：给缺内容垂类的记录跑 AI 补全。返回统计。"""
    stats = {"ok": 0, "failed": 0, "commerce_changed": [], "review": []}
    if not rows:
        return stats

    print(f"\n🤖 阶段B：AI 补全 {len(rows)} 条（每批{AI_BATCH_SIZE}个，约"
          f"{(len(rows) + AI_BATCH_SIZE - 1) // AI_BATCH_SIZE}批）")

    for start in range(0, len(rows), AI_BATCH_SIZE):
        batch = rows[start:start + AI_BATCH_SIZE]
        briefs = [_backfill_brief(r, i) for i, r in enumerate(batch)]
        content, err = _call_qwen(_backfill_prompt(briefs))
        parsed = _extract_json_array(content) if not err else None

        if err or parsed is None:
            stats["failed"] += len(batch)
            print(f"  ⚠️ 第{start // AI_BATCH_SIZE + 1}批失败（{err or 'JSON解析失败'}），跳过")
            continue

        by_idx = {}
        for item in parsed:
            if isinstance(item, dict) and isinstance(item.get("idx"), int):
                by_idx[item["idx"]] = item

        for i, row in enumerate(batch):
            item = by_idx.get(i)
            if not item:
                stats["failed"] += 1
                continue
            cc, comm, rel = adjudicate_labels(
                item.get("content_cat", ""), item.get("commerce_cat", ""),
                item.get("relevance", 50))
            if not cc:
                stats["failed"] += 1
                continue

            old_comm = (row.get("category") or "").strip()
            upd = {"content_category": cc}
            detail = {}
            try:
                detail = json.loads(row.get("score_detail") or "{}")
            except (ValueError, TypeError):
                detail = {}

            if not old_comm:
                # 带货垂类也空：AI 一次补齐，连同相关度/标签存档
                upd["category"] = comm
                detail.update({"ai_content_category": cc, "ai_category": comm,
                               "ai_relevance": rel,
                               "ai_tags": item.get("tags") or [],
                               "ai_analyzed": True})
                upd["score_detail"] = json.dumps(detail, ensure_ascii=False)
            else:
                # 已有带货垂类：原则上保留，仅非带货向内容按全局规则强制 기타
                if cc in NON_COMMERCIAL_CONTENT and old_comm != "기타":
                    upd["category"] = "기타"
                    detail["ai_content_category"] = cc
                    detail["ai_relevance"] = rel
                    upd["score_detail"] = json.dumps(detail, ensure_ascii=False)
                    stats["commerce_changed"].append(
                        f"{row.get('channel_name', '')}：{old_comm} → 기타（内容={cc}）")
                else:
                    detail["ai_content_category"] = cc
                    upd["score_detail"] = json.dumps(detail, ensure_ascii=False)
                    if comm and comm != old_comm and comm in (
                            ALLOWED_COMMERCE.get(cc) or set()):
                        stats["review"].append(
                            f"{row.get('channel_name', '')}：内容={cc}，库={old_comm}，AI建议={comm}")

            try:
                (client.table(TABLE).update(upd)
                 .eq("channel_id", row["channel_id"]).execute())
                stats["ok"] += 1
            except Exception as e:
                stats["failed"] += 1
                print(f"  ⚠️ {row.get('channel_name', '')} 写入失败：{e}")

        done = min(start + AI_BATCH_SIZE, len(rows))
        print(f"  进度 {done}/{len(rows)}", flush=True)

    return stats


# ============================================================
# 主流程
# ============================================================

def main():
    apply_mode = "--apply" in sys.argv
    no_ai = "--no-ai" in sys.argv

    # --model xxx：临时换模型（某个模型免费额度用完时换有额度的）
    if "--model" in sys.argv:
        import ai_analyzer as _A
        _A.DASHSCOPE_MODEL = sys.argv[sys.argv.index("--model") + 1]

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 0) 新列存在吗
    try:
        client.table(TABLE).select("content_category").limit(1).execute()
    except Exception as e:
        print("❌ content_category 列还不存在。请先去 Supabase → SQL Editor 运行：")
        print("   ALTER TABLE influencers ADD COLUMN content_category TEXT DEFAULT '';")
        print(f"（原始报错：{e}）")
        return

    rows = fetch_all(client)
    print(f"库中共 {len(rows)} 条记录\n")

    # 1) 垂类值分布
    dist: dict = {}
    for r in rows:
        c = (r.get("category") or "").strip() or "(空)"
        dist[c] = dist.get(c, 0) + 1
    print("当前 category 取值分布：")
    for c, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        mark = " ← 阶段A迁移" if c in OLD_VALUE_MAP else ""
        print(f"  {c}: {n}{mark}")

    # 2) 阶段A计划
    plan_a = [r for r in rows
              if (r.get("category") or "").strip() in OLD_VALUE_MAP
              and not (r.get("content_category") or "").strip()]
    print(f"\n【阶段A】机械映射：{len(plan_a)} 条旧值记录")
    for r in plan_a[:20]:
        old = r["category"].strip()
        cc, comm = OLD_VALUE_MAP[old]
        print(f"  {r.get('channel_name', '')[:24]:24s} | {old} → 🎬{cc} / 🛍{comm}")
    if len(plan_a) > 20:
        print(f"  … 另有 {len(plan_a) - 20} 条")

    # 3) 阶段B计划（模拟阶段A执行后仍缺内容垂类的记录）
    done_ids = {r["channel_id"] for r in plan_a}
    plan_b = [r for r in rows
              if r["channel_id"] not in done_ids
              and not (r.get("content_category") or "").strip()]
    has_comm = sum(1 for r in plan_b if (r.get("category") or "").strip())
    print(f"\n【阶段B】AI补全：{len(plan_b)} 条缺内容垂类"
          f"（{has_comm} 条保留现有带货垂类只补内容垂类，"
          f"{len(plan_b) - has_comm} 条带货垂类也空将一次补齐）")
    for r in plan_b[:10]:
        comm = (r.get("category") or "").strip() or "(空)"
        print(f"  {r.get('channel_name', '')[:24]:24s} | 🛍{comm} → 🎬待AI判定")
    if len(plan_b) > 10:
        print(f"  … 另有 {len(plan_b) - 10} 条")

    if not apply_mode:
        print("\n这是预览（dry-run）。确认无误后运行：python3 migrate_categories.py --apply")
        return

    if plan_b and not no_ai and not ai_ready():
        print("\n⚠️ 百炼 AI 未配置（缺 ai_config_local.py / 环境变量），阶段B跳过。"
              "可先跑完阶段A，AI 配好后再运行一次 --apply。")
        no_ai = True

    # 4) 执行阶段A
    ok_a, fail_a = 0, 0
    for r in plan_a:
        old = r["category"].strip()
        cc, comm = OLD_VALUE_MAP[old]
        try:
            (client.table(TABLE)
             .update({"category": comm, "content_category": cc})
             .eq("channel_id", r["channel_id"])
             .execute())
            ok_a += 1
        except Exception as e:
            fail_a += 1
            print(f"  ⚠️ {r.get('channel_name', '')} 更新失败：{e}")
    print(f"\n✅ 阶段A完成：成功 {ok_a} 条，失败 {fail_a} 条")

    # 5) 执行阶段B
    if no_ai:
        print("（--no-ai：跳过阶段B）")
        return
    stats = backfill_ai(client, plan_b)
    print(f"\n✅ 阶段B完成：成功 {stats['ok']} 条，失败 {stats['failed']} 条")
    if stats["commerce_changed"]:
        print(f"\n📌 以下 {len(stats['commerce_changed'])} 条因「非带货向内容」规则改了带货垂类，建议复查：")
        for line in stats["commerce_changed"]:
            print(f"  - {line}")
    if stats["review"]:
        print(f"\n📌 以下 {len(stats['review'])} 条 AI 建议的带货垂类与库里不同（已保留库里值），供参考：")
        for line in stats["review"][:30]:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
