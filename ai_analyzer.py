# -*- coding: utf-8 -*-
"""
百炼（qwen）AI 分析模块 —— 第二期核心
====================================
挖掘完成后，把候选博主批量交给 AI 分析三件事：
1. 定垂类：从团队自己的分类表里选一个最匹配的品类
2. 打相关度 0-100：这个频道适不适合给我们带货
3. 出 2 个关键词标签：概括频道内容，一眼看懂

设计原则：
- AI 失败绝不阻塞挖掘：失败的批次给中性分（相关度50），并把原因说清楚
- Key 本地从 ai_config_local.py 读、云上从 Streamlit Secrets 读，不写进代码
- 批量调用（一次分析多个频道），省时间省费用
"""

import json
import os
import re
import time

import requests

# ---------- 配置读取 ----------
# 本地：ai_config_local.py（不上传 GitHub）
# 云上（Streamlit Cloud）：Settings → Secrets 里配 DASHSCOPE_API_KEY
try:
    from ai_config_local import (
        DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, DASHSCOPE_MODEL, AI_ENABLED,
    )
except ImportError:
    DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL = "", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_MODEL, AI_ENABLED = "qwen-plus", False
    # 没有本地配置文件时（比如部署在云上），尝试 Secrets / 环境变量
    try:
        _key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not _key:
            import streamlit as st
            _key = st.secrets.get("DASHSCOPE_API_KEY", "") or ""
        if _key:
            DASHSCOPE_API_KEY = _key
            AI_ENABLED = True
    except Exception:
        pass

# 抑制 verify=False 时的安全警告（本机证书链问题的兜底方案）
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# ============================================================
# 团队垂类分类表（用户提供，已去重，共15个）
# ============================================================

AI_CATEGORY_TABLE = [
    "남성 의류", "여성 의류", "완구 및 취미", "의복 & 부속품", "네일",
    "생활용품", "홈 & 가든", "뷰티 & 헬스", "컴퓨터 및 오피스",
    "오토바이 장비 및 부품", "전화 및 통신 액세서리", "가구", "도구",
    "애완동물", "음식",
]

# 相关度低于这个分 → 不进主列表，收进待定区人工翻（阈值可在设置页调）
DEFAULT_AI_MIN_RELEVANCE = 40

# 一次 AI 调用分析多少个频道（太大回复会截断，太小调用次数多）
AI_BATCH_SIZE = 8


def ai_ready() -> bool:
    """AI 分析是否可用（开关打开 + Key 已配置）"""
    return bool(AI_ENABLED and DASHSCOPE_API_KEY)


def _clamp_relevance(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 50


def _norm_category(cat: str) -> str:
    """把 AI 返回的垂类规范化到分类表；表里没有就原样返回（加标注由界面显示）"""
    cat = (cat or "").strip()
    if not cat:
        return ""
    for std in AI_CATEGORY_TABLE:
        if cat == std:
            return std
    # 宽松匹配：去掉空格/&后对比
    key = cat.replace(" ", "").replace("&", "").lower()
    for std in AI_CATEGORY_TABLE:
        if key == std.replace(" ", "").replace("&", "").lower():
            return std
    return cat


def _extract_json_array(text: str) -> list | None:
    """从模型回复里提取 JSON 数组。
    模型有时会把数组输出两遍（裸文本+代码块），从第一个[到最后一个]截取会拿到坏JSON，
    所以这里用括号配对扫描，返回第一个能解析成功的完整数组。"""
    if not text:
        return None
    t = text.strip()
    # 整体就是合法 JSON → 直接返回
    try:
        data = json.loads(t)
        return data if isinstance(data, list) else None
    except (json.JSONDecodeError, ValueError):
        pass

    start = t.find("[")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            c = t[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(t[start:i + 1])
                            return data if isinstance(data, list) else None
                        except (json.JSONDecodeError, ValueError):
                            break
        start = t.find("[", start + 1)
    return None


def _channel_brief(ch: dict, idx: int) -> dict:
    """把一个频道的信息压缩成给 AI 看的简报（控制 token 消耗）"""
    desc = (ch.get("description") or "").replace("\n", " ").strip()[:250]
    titles = [t for t in (ch.get("recent_titles") or [])[:6] if t]
    # 标签拍平去重，最多15个
    tags, seen = [], set()
    for tag_list in (ch.get("recent_tags") or [])[:5]:
        for tag in tag_list or []:
            tag = str(tag).strip()
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)
            if len(tags) >= 15:
                break
        if len(tags) >= 15:
            break
    vid_descs = " ".join(d.replace("\n", " ")[:150] for d in (ch.get("recent_descriptions") or [])[:2])
    return {
        "idx": idx,
        "频道名": ch.get("channel_name", ""),
        "频道简介": desc,
        "最近视频标题": titles,
        "视频标签": tags,
        "视频描述摘录": vid_descs[:300],
    }


def _build_prompt(briefs: list[dict]) -> str:
    cats = "、".join(AI_CATEGORY_TABLE)
    payload = json.dumps(briefs, ensure_ascii=False, indent=1)
    return f"""你是资深韩国YouTube电商网红营销选号专家。

我们的客户：AliExpress（速卖通）韩国站。
目标观众：18-34岁韩国女性为主。
想推广的商品：平价服饰、家居收纳/家居好物、平价美妆、生活日用、宠物用品、文具学生用品、通勤包袋配饰等（轻便、高性价比商品为主）。
合作形式：博主在YouTube视频里挂我们的商品标签带货（种草/开箱haul/测评/日常vlog植入等）。

下面给你 {len(briefs)} 个候选YouTube频道的信息（JSON数组，idx是编号）。请逐个判断三件事：

1. category：这个频道最适合挂哪类商品的链接。必须从下面列表里选一个，一字不差地写：
{cats}

2. relevance：整数0-100，这个频道适不适合上面说的带货合作——
- 80-100：内容本身就是种草/消费/生活方式类（家居、美妆、好物开箱、日常用品、宠物、文具、穿搭等），观众又以年轻女性为主
- 60-79：内容与消费、生活方式相关，植入商品不突兀
- 40-59：沾边但不典型，或观众人群不完全匹配
- 0-39：明显不相关（游戏、新闻、政治、体育赛事解说、纯搞笑、音乐翻唱、猎奇等），或受众完全不是目标人群

3. tags：用2个中文关键词概括频道内容（每个不超过6个字），例如 ["独居日常","收纳好物"]

严格按JSON数组输出，不要输出任何其他文字，格式：
[{{"idx":0,"category":"홈 & 가든","relevance":85,"tags":["独居日常","收纳好物"]}}]

候选频道信息：
{payload}"""


def _call_qwen(prompt: str, timeout: int = 90) -> tuple[str, str]:
    """调用 qwen，返回 (回复文本, 错误原因)。错误原因为空=成功。
    带一次重试；本机证书链异常时自动降级为不校验证书。"""
    url = DASHSCOPE_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": DASHSCOPE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 2500,
    }

    last_err = ""
    for attempt in range(2):  # 最多试2次
        for verify in (True, False):  # 证书校验失败时降级重试
            try:
                resp = requests.post(url, headers=headers, json=body,
                                     timeout=timeout, verify=verify)
                break
            except requests.exceptions.SSLError:
                if verify:
                    continue  # 换 verify=False 再试
                last_err = "SSL证书问题（降级后仍失败）"
                resp = None
            except requests.exceptions.RequestException as e:
                last_err = f"网络问题：{type(e).__name__}"
                resp = None
                break
        if resp is None:
            if attempt == 0:
                time.sleep(1.5)
                continue
            return "", last_err or "网络不通"

        if resp.status_code == 200:
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content, ""
            except (ValueError, KeyError, IndexError):
                last_err = "AI返回格式异常"
        elif resp.status_code == 401:
            return "", "AI Key无效（401），检查百炼凭证"
        elif resp.status_code == 429:
            last_err = "AI接口限流（429）"
        else:
            last_err = f"AI接口异常（HTTP {resp.status_code}）"

        if attempt == 0:
            time.sleep(1.5)
    return "", last_err or "AI调用失败"


def _set_neutral(ch: dict):
    """AI 没分析到的频道：给中性值，不阻塞流程"""
    ch["ai_analyzed"] = False
    ch["ai_category"] = ""
    ch["ai_relevance"] = 50
    ch["ai_tags"] = []


def analyze_channels(channels: list[dict], status_cb=None,
                     batch_size: int = AI_BATCH_SIZE) -> tuple[int, int, str]:
    """
    对已验证的频道批量做 AI 分析，结果直接写回每个频道 dict：
      ai_analyzed / ai_category / ai_relevance / ai_tags
    返回 (成功数, 失败数, 说明文字)。

    AI 未配置或全部失败时，所有频道保持中性值（相关度50、无垂类），
    挖掘流程不受影响——只是少了 AI 这一层判断。
    """
    if not channels:
        return 0, 0, ""

    if not ai_ready():
        for ch in channels:
            _set_neutral(ch)
        return 0, len(channels), "未配置AI（不影响挖掘，相关度按中性50计）"

    def _say(msg: str):
        if status_cb:
            try:
                status_cb(msg)
            except Exception:
                pass

    ok_count, fail_count = 0, 0
    batches = [channels[i:i + batch_size] for i in range(0, len(channels), batch_size)]
    errors = []

    for bi, batch in enumerate(batches):
        _say(f"🤖 AI 正在分析垂类与相关度（{bi + 1}/{len(batches)} 批）…")
        briefs = [_channel_brief(ch, i) for i, ch in enumerate(batch)]
        content, err = _call_qwen(_build_prompt(briefs))

        parsed = None
        if not err:
            parsed = _extract_json_array(content)
            if parsed is None:
                err = "AI回复无法解析"

        if err:
            errors.append(err)
            for ch in batch:
                _set_neutral(ch)
            fail_count += len(batch)
            continue

        # 按 idx 对齐回去
        by_idx = {}
        for item in parsed:
            if isinstance(item, dict) and "idx" in item:
                try:
                    by_idx[int(item["idx"])] = item
                except (TypeError, ValueError):
                    continue

        for i, ch in enumerate(batch):
            item = by_idx.get(i)
            if not item:
                _set_neutral(ch)
                fail_count += 1
                continue
            ch["ai_analyzed"] = True
            ch["ai_category"] = _norm_category(str(item.get("category", "")))
            ch["ai_relevance"] = _clamp_relevance(item.get("relevance", 50))
            tags = item.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            ch["ai_tags"] = [str(t).strip() for t in tags[:2] if str(t).strip()]
            ok_count += 1

    if fail_count == 0:
        note = f"AI分析完成：{ok_count} 个博主已定垂类并打分"
    elif ok_count == 0:
        note = f"AI分析失败（{errors[0] if errors else '未知原因'}），本次按中性分处理"
    else:
        note = f"AI分析部分完成：{ok_count} 个成功，{fail_count} 个失败按中性分处理"
    return ok_count, fail_count, note


# ============================================================
# 离线自测（python3 ai_analyzer.py）
# ============================================================
if __name__ == "__main__":
    print(f"AI 可用: {ai_ready()} | 模型: {DASHSCOPE_MODEL}")
    print(f"垂类表 {len(AI_CATEGORY_TABLE)} 个: {AI_CATEGORY_TABLE}")
    demo = [{
        "channel_name": "자취연구소",
        "description": "자취방 꾸미기, 다이소 수납템 추천, 원룸 인테리어 브이로그",
        "recent_titles": ["자취방 수납템 추천", "다이소 꿀템 하울", "원룸 인테리어"],
        "recent_tags": [["자취", "수납", "다이소"], ["인테리어"]],
        "recent_descriptions": ["자취생 필수 수납템 추천 영상입니다."],
    }]
    ok, fail, note = analyze_channels(demo, status_cb=print)
    print(note)
    for ch in demo:
        print({k: ch.get(k) for k in ("ai_analyzed", "ai_category", "ai_relevance", "ai_tags")})
