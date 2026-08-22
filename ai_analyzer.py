# -*- coding: utf-8 -*-
"""
百炼（qwen）AI 分析模块 —— 双标签版
====================================
挖掘完成后，把候选博主批量交给 AI，每个频道判四件事：
1. 内容垂类 content_cat：这个频道在拍什么（17 选 1，描述内容本身）
2. 带货垂类 commerce_cat：这个频道的观众最可能买哪类商品（速卖通官方26类）
3. 相关度 relevance 0-100：适不适合给我们带货
4. 标签 tags：2 个中文关键词，一眼看懂频道内容

为什么要两个垂类标签：
- 以前只有一个标签，"拍什么"和"卖什么"被迫二选一，
  比如日常vlog博主既不是家居号也不是美妆号，AI只能硬塞，判错率高。
- 现在拆开：内容垂类描述"拍什么"，带货垂类回答"挂什么商品链接"，
  带货垂类跟着"观众会买什么"走，两个标签之间用映射表约束，AI 不能乱飞。

设计原则：
- AI 失败绝不阻塞挖掘：失败的批次给中性分（相关度50），并把原因说清楚
- Key 本地从 ai_config_local.py 读、云上从 Streamlit Secrets 读，不写进代码
- 批量调用（一次分析多个频道），省时间省费用
- 代码层兜底裁决：AI 返回违反映射表的组合会被拉回默认值，非带货向内容强制压分
"""

import json
import os
import re
import time

import requests

# ---------- 配置读取 ----------
# 本地：ai_config_local.py（不上传 GitHub）
# 云上（Streamlit Cloud）：Settings → Secrets 里配 DASHSCOPE_API_KEY
#   （名字沿用历史，实际支持任意 OpenAI 兼容服务：百炼/智谱等，
#    用 DASHSCOPE_BASE_URL + DASHSCOPE_MODEL 指定服务和模型）
try:
    from ai_config_local import (
        DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, DASHSCOPE_MODEL, AI_ENABLED,
    )
    THINKING_ENABLED = False  # 本地模式默认关闭思考模式
except ImportError:
    DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL = "", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_MODEL, AI_ENABLED = "qwen-plus", False
    # 没有本地配置文件时（比如部署在云上），尝试 Secrets / 环境变量
    try:
        def _secret(name):
            """环境变量优先，其次 Streamlit Secrets"""
            v = os.environ.get(name, "")
            if not v:
                import streamlit as st
                v = st.secrets.get(name, "") or ""
            return str(v).strip()

        _key = _secret("DASHSCOPE_API_KEY")
        _url = _secret("DASHSCOPE_BASE_URL")
        _model = _secret("DASHSCOPE_MODEL")
        if _url:
            DASHSCOPE_BASE_URL = _url
        if _model:
            DASHSCOPE_MODEL = _model
        if _key:
            DASHSCOPE_API_KEY = _key
            AI_ENABLED = True
        # 新一代模型（glm-5.x）默认带"思考模式"：做分类这种简单任务时
        # 思考模式会拖慢速度、还可能把输出额度耗光导致截断，默认关闭
        try:
            THINKING_ENABLED = _secret("DASHSCOPE_THINKING").strip() == "1"
        except Exception:
            THINKING_ENABLED = False
    except Exception:
        pass

# 抑制 verify=False 时的安全警告（本机证书链问题的兜底方案）
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# ============================================================
# 标签一：内容垂类（17 类，描述"频道在拍什么"）
# 界面显示韩文，判定说明用中文写给 AI 看
# ============================================================

CONTENT_CATEGORY_TABLE = [
    "일상/자취 브이로그", "홈/인테리어", "뷰티", "패션/코디", "음식",
    "반려동물", "디지털/테크", "게임", "운동/피트니스", "아웃도어/캠핑",
    "육아/패밀리", "취미/수집/장난감", "DIY/핸드메이드", "공부/지식",
    "자동차/바이크", "엔터테인먼트", "기타",
]

# 每个内容垂类的判定标准（给 AI 看：拍什么内容算这类）
CONTENT_GUIDE = {
    "일상/자취 브이로그": "独居日常、生活记录、one room vlog、上班/上学日常，家是主要拍摄背景，内容杂但围绕个人生活",
    "홈/인테리어": "房间改造、收纳整理、room tour、家居好物分享、布置装饰，内容主题就是「家」本身",
    "뷰티": "化妆教程、护肤、美甲美发、香水、美容仪器、医美个护等美妆向内容",
    "패션/코디": "ootd、服装haul、搭配示范、试穿测评，内容主角是衣服鞋包首饰等穿搭单品",
    "음식": "料理做饭、吃播、烘焙、零食测评、探店、食材采购，内容主角是食物",
    "반려동물": "猫狗小宠水族爬宠等宠物日常、宠物用品开箱，内容主角是宠物",
    "디지털/테크": "数码产品测评、科技好物开箱、桌面setup、电子设备教程",
    "게임": "游戏实况、游戏攻略、电竞解说，内容主角是游戏本身",
    "운동/피트니스": "健身训练、普拉提、瑜伽、居家锻炼、运动饮食，内容主角是训练",
    "아웃도어/캠핑": "露营、徒步、骑行、钓鱼、登山等户外活动，车中泊装备也归这类",
    "육아/패밀리": "育儿日常、辅食制作、童装分享、孕期记录，内容主角是孩子/家庭",
    "취미/수집/장난감": "盲盒、手办、积木拼搭、玩具测评、收藏展示，内容主角是收藏品和玩具",
    "DIY/핸드메이드": "手工制作、缝纫、编织、绘画、旧物改造，内容主角是动手做东西",
    "공부/지식": "study with me、文具手账分享、学习方法、考试备考记录",
    "자동차/바이크": "车评、改装、车内好物、摩托骑行记录，内容主角是车",
    "엔터테인먼트": "搞笑、短剧、整蛊、音乐翻唱、dance cover、明星向娱乐内容",
    "기타": "新闻、政治、宗教、财经、猎奇、影视解说等非带货向内容，或实在归不了类",
}

# ============================================================
# 标签二：带货垂类（速卖通官方26个一级类目 + 기타 兜底）
# 来源：速卖通官方类目树（韩国站），2026-08-22
# ============================================================

AI_CATEGORY_TABLE = [
    "여성 의류", "남성 의류", "뷰티 & 헬스", "홈 & 가든", "반려동물 용품",
    "완구 & 게임", "식품 & 장보기", "스포츠 & 아웃도어", "휴대폰 & 액세서리",
    "전자제품", "가전제품", "주얼리 & 액세서리", "가방 & 캐리어", "신발",
    "유아 & 출산", "가구", "공구 & 홈인테리어", "자동차 부품", "오토바이 & 파워스포츠",
    "사무 & 학용품", "공예 & 재봉", "헤어 익스텐션 & 가발", "서적 & 미디어",
    "특수 의류 & 코스프레", "산업 & 과학", "기타",
]

# 韩文垂类 → 英文官方名（导出用）
CATEGORY_EN_MAP = {
    "여성 의류": "Women's Clothing",
    "남성 의류": "Men's Clothing",
    "뷰티 & 헬스": "Beauty & Health",
    "홈 & 가든": "Patio, Lawn & Garden",
    "반려동물 용품": "Pet Supplies",
    "완구 & 게임": "Toys & Games",
    "식품 & 장보기": "Food & Grocery",
    "스포츠 & 아웃도어": "Sports & Outdoors",
    "휴대폰 & 액세서리": "Cell Phones & Accessories",
    "전자제품": "Electronics",
    "가전제품": "Appliances",
    "주얼리 & 액세서리": "Jewelry & Accessories",
    "가방 & 캐리어": "Bags & Luggage",
    "신발": "Shoes",
    "유아 & 출산": "Baby & Maternity",
    "가구": "Furniture",
    "공구 & 홈인테리어": "Tools & Home Improvement",
    "자동차 부품": "Automotive",
    "오토바이 & 파워스포츠": "Motorcycles & Powersports",
    "사무 & 학용품": "Office & School Supplies",
    "공예 & 재봉": "Arts, Crafts & Sewing",
    "헤어 익스텐션 & 가발": "Hair Extensions & Wigs",
    "서적 & 미디어": "Books & Media",
    "특수 의류 & 코스프레": "Novelty & Special Use",
    "산업 & 과학": "Business, Industry & Science",
    "기타": "Other",
}

# ============================================================
# 两个标签之间的映射表（团队确认版）
# 内容垂类 → 默认带货垂类；内容偏向时允许改判到「改判备选」里的值
# ============================================================

CONTENT_TO_COMMERCE = {
    "일상/자취 브이로그": "홈 & 가든",
    "홈/인테리어": "홈 & 가든",
    "뷰티": "뷰티 & 헬스",
    "패션/코디": "여성 의류",   # 默认女装（目标观众以女性为主）；明确男装频道改 남성 의류
    "음식": "식품 & 장보기",
    "반려동물": "반려동물 용품",
    "디지털/테크": "전자제품",
    "게임": "기타",
    "운동/피트니스": "스포츠 & 아웃도어",
    "아웃도어/캠핑": "스포츠 & 아웃도어",
    "육아/패밀리": "유아 & 출산",
    "취미/수집/장난감": "완구 & 게임",
    "DIY/핸드메이드": "공예 & 재봉",
    "공부/지식": "사무 & 학용품",
    "자동차/바이크": "자동차 부품",
    "엔터테인먼트": "기타",
    "기타": "기타",
}

# 每个内容垂类允许的带货垂类全集（默认 + 映射表里的改判路线）
ALLOWED_COMMERCE = {
    "일상/자취 브이로그": {"홈 & 가든", "식품 & 장보기", "가전제품"},
    "홈/인테리어": {"홈 & 가든", "가구"},
    "뷰티": {"뷰티 & 헬스", "헤어 익스텐션 & 가발"},
    "패션/코디": {"여성 의류", "남성 의류", "가방 & 캐리어", "신발", "주얼리 & 액세서리"},
    "음식": {"식품 & 장보기", "홈 & 가든", "가전제품"},
    "반려동물": {"반려동물 용품"},
    "디지털/테크": {"전자제품", "휴대폰 & 액세서리", "사무 & 학용품", "가전제품"},
    "게임": {"기타"},
    "운동/피트니스": {"스포츠 & 아웃도어", "여성 의류", "남성 의류"},
    "아웃도어/캠핑": {"스포츠 & 아웃도어"},
    "육아/패밀리": {"유아 & 출산", "완구 & 게임"},
    "취미/수집/장난감": {"완구 & 게임"},
    "DIY/핸드메이드": {"공예 & 재봉", "공구 & 홈인테리어"},
    "공부/지식": {"사무 & 학용품", "기타", "서적 & 미디어"},
    "자동차/바이크": {"자동차 부품", "오토바이 & 파워스포츠"},
    "엔터테인먼트": {"기타"},
    "기타": {"기타"},
}

# 非带货向内容：带货垂类强制 기타，相关度封顶 39（全局规则二，代码强制执行）
NON_COMMERCIAL_CONTENT = {"게임", "엔터테인먼트", "기타"}

# 冷门带货垂类：不设对应内容垂类，只有明确命中才允许（如 cosplay→특수 의류）
# AI 明确给出这几个值时不受 ALLOWED_COMMERCE 约束
RARE_COMMERCE = {"특수 의류 & 코스프레", "산업 & 과학", "서적 & 미디어", "헤어 익스텐션 & 가발"}

# 给 AI 看的映射表全文（写进 prompt）
MAPPING_TABLE_TEXT = """- 일상/자취 브이로그 → 默认 홈 & 가든；做饭买菜占大头→식품 & 장보기；开箱测评小家电为主→가전제품
- 홈/인테리어 → 默认 홈 & 가든；内容全是大件家具选购布置→가구
- 뷰티 → 默认 뷰티 & 헬스；假发/接发造型为主→헤어 익스텐션 & 가발
- 패션/코디 → 默认 여성 의류（受众明确是男性→남성 의류）；包包为主→가방 & 캐리어；球鞋鞋测为主→신발；首饰搭配为主→주얼리 & 액세서리；混着来的综合haul→归衣服
- 음식 → 默认 식품 & 장보기；主角变厨具餐具→홈 & 가든；主角是空气炸锅等电器→가전제품
- 반려동물 → 반려동물 용품（锁定不换）
- 디지털/테크 → 默认 전자제품；手机壳充电耳机手机测评→휴대폰 & 액세서리；键盘显示器书桌setup→사무 & 학용품；家电测评→가전제품
- 게임 → 기타（一律기타；实为游戏外设测评的，内容垂类就该判디지털/테크）
- 운동/피트니스 → 默认 스포츠 & 아웃도어；重心在运动服穿搭→여성/남성 의류
- 아웃도어/캠핑 → 스포츠 & 아웃도어（锁定不换，车中泊装备仍归这类）
- 육아/패밀리 → 默认 유아 & 출산；玩具开箱占大头→완구 & 게임
- 취미/수집/장난감 → 완구 & 게임（锁定不换）
- DIY/핸드메이드 → 默认 공예 & 재봉；装修木工水电等硬改造→공구 & 홈인테리어
- 공부/지식 → 默认 사무 & 학용품；纯讲课科普无消费场景→기타；纯荐书→서적 & 미디어
- 자동차/바이크 → 默认 자동차 부품；摩托/动力运动为主→오토바이 & 파워스포츠
- 엔터테인먼트 → 기타（一律기타，相关度压低）
- 기타 → 기타（一律기타）"""

# AI 常写错的表外值 → 规范名归一（内容垂类）
CONTENT_ALIAS = {
    "일상": "일상/자취 브이로그", "브이로그": "일상/자취 브이로그",
    "자취": "일상/자취 브이로그", "자취 브이로그": "일상/자취 브이로그",
    "일상 브이로그": "일상/자취 브이로그", "vlog": "일상/자취 브이로그",
    "홈": "홈/인테리어", "인테리어": "홈/인테리어", "홈인테리어": "홈/인테리어",
    "홈 & 가든": "홈/인테리어", "홈&가든": "홈/인테리어", "방 꾸미기": "홈/인테리어",
    "화장품": "뷰티", "메이크업": "뷰티", "뷰티&헬스": "뷰티", "뷰티 & 헬스": "뷰티",
    "미용": "뷰티", "뷰티/헬스": "뷰티", "skincare": "뷰티",
    "패션": "패션/코디", "코디": "패션/코디", "穿搭": "패션/코디", "패션/스타일": "패션/코디",
    "요리": "음식", "먹방": "음식", "음식/먹방": "음식", "베이킹": "음식", "맛집": "음식",
    "동물": "반려동물", "펫": "반려동물", "고양이": "반려동물", "강아지": "반려동물",
    "반려동물 용품": "반려동물",
    "디지털": "디지털/테크", "테크": "디지털/테크", "it": "디지털/테크", "테크놀로지": "디지털/테크",
    "전자제품": "디지털/테크", "기술": "디지털/테크", "리뷰": "디지털/테크",
    "게이밍": "게임", "e스포츠": "게임", "게임 방송": "게임",
    "운동": "운동/피트니스", "피트니스": "운동/피트니스", "헬스": "운동/피트니스",
    "健身": "운동/피트니스", "스포츠": "운동/피트니스",
    "캠핑": "아웃도어/캠핑", "아웃도어": "아웃도어/캠핑", "등산": "아웃도어/캠핑",
    "낚시": "아웃도어/캠핑", "자전거": "아웃도어/캠핑", "하이킹": "아웃도어/캠핑",
    "스포츠 & 아웃도어": "아웃도어/캠핑",
    "육아": "육아/패밀리", "패밀리": "육아/패밀리", "가족": "육아/패밀리", "맘": "육아/패밀리",
    "취미": "취미/수집/장난감", "수집": "취미/수집/장난감", "장난감": "취미/수집/장난감",
    "피규어": "취미/수집/장난감", "盲盒": "취미/수집/장난감",
    "공예": "DIY/핸드메이드", "핸드메이드": "DIY/핸드메이드", "수공예": "DIY/핸드메이드",
    "手工": "DIY/핸드메이드", "diy": "DIY/핸드메이드",
    "공부": "공부/지식", "학습": "공부/지식", "스터디": "공부/지식", "교육": "공부/지식",
    "지식": "공부/지식", "study": "공부/지식",
    "자동차": "자동차/바이크", "바이크": "자동차/바이크", "오토바이": "자동차/바이크",
    "모터사이클": "자동차/바이크", "카라이프": "자동차/바이크",
    "엔터": "엔터테인먼트", "개그": "엔터테인먼트", "코미디": "엔터테인먼트",
    "예능": "엔터테인먼트", "음악": "엔터테인먼트", "댄스": "엔터테인먼트",
    "뉴스": "기타", "정치": "기타", "시사": "기타", "종교": "기타",
}

# AI 常写错的表外值 → 规范名归一（带货垂类）
COMMERCE_ALIAS = {
    "캠핑": "스포츠 & 아웃도어", "아웃도어": "스포츠 & 아웃도어", "스포츠": "스포츠 & 아웃도어",
    "화장품": "뷰티 & 헬스", "뷰티": "뷰티 & 헬스", "미용": "뷰티 & 헬스", "네일": "뷰티 & 헬스",
    "헬스": "뷰티 & 헬스", "뷰티&헬스": "뷰티 & 헬스",
    "의류": "여성 의류", "패션": "여성 의류", "옷": "여성 의류", "여성패션": "여성 의류",
    "식품": "식품 & 장보기", "음식": "식품 & 장보기", "장보기": "식품 & 장보기",
    "홈": "홈 & 가든", "인테리어": "홈 & 가든", "생활용품": "홈 & 가든", "홈&가든": "홈 & 가든",
    "반려동물": "반려동물 용품", "애완동물": "반려동물 용품", "펫": "반려동물 용품",
    "장난감": "완구 & 게임", "완구": "완구 & 게임", "피규어": "완구 & 게임",
    "문구": "사무 & 학용품", "사무": "사무 & 학용품", "컴퓨터 및 오피스": "사무 & 학용품",
    "가전": "가전제품", "전자": "전자제품", "전자제품": "전자제품",
    "전화 및 통신 액세서리": "휴대폰 & 액세서리", "폰": "휴대폰 & 액세서리",
    "도구": "공구 & 홈인테리어", "공구": "공구 & 홈인테리어",
    "오토바이": "오토바이 & 파워스포츠", "자동차": "자동차 부품",
    "의복&부속품": "주얼리 & 액세서리", "액세서리": "주얼리 & 액세서리",
    "신발": "신발", "가방": "가방 & 캐리어",
}

# 相关度低于这个分 → 不进主列表，收进待定区人工翻（阈值可在设置页调）
DEFAULT_AI_MIN_RELEVANCE = 40

# 一次 AI 调用分析多少个频道（双标签输出更长，5 个一批防截断）
AI_BATCH_SIZE = 5


def ai_ready() -> bool:
    """AI 分析是否可用（开关打开 + Key 已配置）"""
    return bool(AI_ENABLED and DASHSCOPE_API_KEY)


def _clamp_relevance(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 50


def _norm_content_category(cat: str) -> str:
    """把 AI 返回的内容垂类规范化到 17 类表；表外值先查别名表，还不认识就归「기타」
    （内容垂类是封闭集合，宁可归기타也不放脏值进筛选器）"""
    cat = (cat or "").strip()
    if not cat:
        return ""
    if cat in CONTENT_CATEGORY_TABLE:
        return cat
    key = cat.lower().replace(" ", "")
    for std in CONTENT_CATEGORY_TABLE:
        if key == std.lower().replace(" ", ""):
            return std
    alias = CONTENT_ALIAS.get(cat.lower().strip())
    if alias:
        return alias
    # 宽松别名：去空格/&后再查一次
    alias = CONTENT_ALIAS.get(cat.lower().replace(" ", "").replace("&", ""))
    if alias:
        return alias
    return "기타"


def _norm_category(cat: str) -> str:
    """把 AI 返回的带货垂类规范化到官方26类；表外值查别名表，还不认识就原样返回
    （加标注由界面显示，自动入库前调用方须再过滤一次）"""
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
    alias = COMMERCE_ALIAS.get(cat.lower().strip()) or COMMERCE_ALIAS.get(key)
    if alias:
        return alias
    return cat


def adjudicate_labels(content_cat: str, commerce_cat: str, relevance: int) -> tuple[str, str, int]:
    """代码层裁决（不信任 AI 100% 守规矩）：
    1. 非带货向内容（游戏/娱乐/其他）→ 带货垂类强制 기타，相关度封顶39
    2. 带货垂类不在该内容垂类的允许集合里 → 拉回默认映射（冷门明确命中除外）
    3. 内容垂类未知 → 带货垂类保留、不硬改（已在 _norm 阶段归기타）
    返回 (内容垂类, 带货垂类, 相关度)。
    """
    relevance = _clamp_relevance(relevance)
    content_cat = _norm_content_category(content_cat)

    if content_cat in NON_COMMERCIAL_CONTENT:
        return content_cat, "기타", min(relevance, 39)

    commerce_cat = _norm_category(commerce_cat)
    allowed = ALLOWED_COMMERCE.get(content_cat)
    if allowed:
        if commerce_cat not in allowed and commerce_cat not in RARE_COMMERCE:
            commerce_cat = CONTENT_TO_COMMERCE.get(content_cat, "기타")
    return content_cat, commerce_cat, relevance


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


def _extract_json_object(text: str) -> dict | None:
    """从模型回复里提取第一个能解析成功的 JSON 对象（括号配对扫描，容忍代码块/前后杂文）。"""
    if not text:
        return None
    t = text.strip()
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    start = t.find("{")
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
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            data = json.loads(t[start:i + 1])
                            return data if isinstance(data, dict) else None
                        except (json.JSONDecodeError, ValueError):
                            break
        start = t.find("{", start + 1)
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
    brief = {
        "idx": idx,
        "频道名": ch.get("channel_name", ""),
        "频道简介": desc,
        "最近视频标题": titles,
        "视频标签": tags,
        "视频描述摘录": vid_descs[:300],
    }
    # YouTube 官方分类（创作者自选，仅作佐证，AI 可自行判断是否采信）
    if ch.get("yt_category"):
        brief["频道自选分类"] = ch["yt_category"]
    if ch.get("yt_video_categories"):
        brief["近期视频分类"] = ch["yt_video_categories"]
    return brief


def _build_prompt(briefs: list[dict]) -> str:
    content_cats = "、".join(CONTENT_CATEGORY_TABLE)
    content_guide = "\n".join(f"- {c}：{CONTENT_GUIDE.get(c, '')}" for c in CONTENT_CATEGORY_TABLE)
    commerce_cats = "、".join(AI_CATEGORY_TABLE)
    payload = json.dumps(briefs, ensure_ascii=False, indent=1)
    return f"""你是资深韩国YouTube电商网红营销选号专家。

我们的客户：AliExpress（速卖通）韩国站。
目标观众：18-34岁韩国女性为主，但全品类博主也有合作价值。
想推广的商品：速卖通全品类平价商品（服饰、家居、美妆、数码、食品、宠物、文具等）。
合作形式：博主在YouTube视频里挂我们的商品标签带货（种草/开箱haul/测评/日常vlog植入等）。

下面给你 {len(briefs)} 个候选YouTube频道的信息（JSON数组，idx是编号）。每个频道按四步判断：

【第1步 content_cat 内容垂类】这个频道主要在拍什么内容。必须从下面17个里选一个，一字不差地写：
{content_cats}

每个内容垂类的判定标准（看频道拍什么）：
{content_guide}

【第2步 commerce_cat 带货垂类】这个频道的观众最可能买哪类商品、最适合挂哪类商品链接。
必须从下面26个速卖通官方类目里选一个，一字不差地写：
{commerce_cats}

先按内容垂类找到默认带货垂类，内容明显偏向时按改判规则换（只能用允许的备选）：
{MAPPING_TABLE_TEXT}

三条全局规则：
1. 带货垂类永远跟着"观众会买什么"走，不跟着"视频拍什么"走——拿不准时回到这条。
2. 非带货向内容（게임、엔터테인먼트、기타）带货垂类强制기타，相关度不得超过39，不要硬塞。
3. 平手时看主角：视频里被展示、被讲解最多的东西属于哪个类目就选哪个；还分不出就选默认值。

另外4个冷门类目（특수 의류 & 코스프레、산업 & 과학、서적 & 미디어、헤어 익스텐션 & 가발）
没有默认映射，只有内容明确命中才允许选（如cosplay博主→특수 의류 & 코스프레），其余情况不要选它们。

【第3步 relevance 相关度】整数0-100，这个频道适不适合上面说的带货合作——
- 80-100：内容本身就是种草/消费/生活方式类（家居、美妆、好物开箱、日常用品、宠物、文具、穿搭等），观众又以年轻女性为主
- 60-79：内容与消费、生活方式相关，植入商品不突兀
- 40-59：沾边但不典型，或观众人群不完全匹配
- 0-39：明显不相关，或受众完全不是目标人群（게임/엔터테인먼트/기타必须在这档）

【第4步 tags】用2个中文关键词概括频道内容（每个不超过6个字），例如 ["独居日常","收纳好物"]

补充说明：频道信息里若带「频道自选分类」「近期视频分类」，那是创作者在YouTube后台自己选的官方分类，
可作参考佐证，但可能选错或过于笼统（大量频道都挂People & Blogs），以实际内容为准。

严格按JSON数组输出，不要输出任何其他文字，格式：
[{{"idx":0,"content_cat":"홈/인테리어","commerce_cat":"홈 & 가든","relevance":85,"tags":["独居日常","收纳好物"]}}]

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
    # 新一代模型（glm-5.x）带可选"思考模式"：做垂类分类这种简单任务时
    # 思考模式会拖慢速度、还可能耗光输出额度导致 JSON 被截断。
    # 默认不传该参数（即不思考）；Secrets 里 DASHSCOPE_THINKING="1" 可开启。
    if str(DASHSCOPE_MODEL).startswith("glm-5") and THINKING_ENABLED:
        body["thinking"] = {"type": "enabled"}

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
    ch["ai_content_category"] = ""
    ch["ai_category"] = ""
    ch["ai_relevance"] = 50
    ch["ai_tags"] = []


def analyze_channels(channels: list[dict], status_cb=None,
                     batch_size: int = AI_BATCH_SIZE) -> tuple[int, int, str]:
    """
    对已验证的频道批量做 AI 分析，结果直接写回每个频道 dict：
      ai_analyzed / ai_content_category（内容垂类） / ai_category（带货垂类）
      ai_relevance / ai_tags
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
        _say(f"🤖 AI 正在判定内容垂类与带货垂类（{bi + 1}/{len(batches)} 批）…")
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
            # 双标签裁决：内容垂类约束带货垂类，非带货向内容强制压分
            content_cat, commerce_cat, relevance = adjudicate_labels(
                str(item.get("content_cat", "") or item.get("content_category", "")),
                str(item.get("commerce_cat", "") or item.get("category", "")),
                item.get("relevance", 50),
            )
            ch["ai_analyzed"] = True
            ch["ai_content_category"] = content_cat
            ch["ai_category"] = commerce_cat
            ch["ai_relevance"] = relevance
            tags = item.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            ch["ai_tags"] = [str(t).strip() for t in tags[:2] if str(t).strip()]
            ok_count += 1

    if fail_count == 0:
        note = f"AI分析完成：{ok_count} 个博主已定双垂类并打分"
    elif ok_count == 0:
        note = f"AI分析失败（{errors[0] if errors else '未知原因'}），本次按中性分处理"
    else:
        note = f"AI分析部分完成：{ok_count} 个成功，{fail_count} 个失败按中性分处理"
    return ok_count, fail_count, note


# ============================================================
# AI 生成搜索关键词（给一个垂类，产出韩语YouTube搜索词）
# ============================================================

def generate_keywords(vertical: str, count: int = 9, timeout: int = 60) -> tuple[list, str]:
    """根据用户给的垂类，让 AI 生成韩语 YouTube 搜索关键词。

    返回 (关键词列表, 错误信息)；成功时错误信息为空字符串。
    AI 失败不阻塞：调用方拿到空列表+错误文案，界面提示即可。
    """
    vertical = (vertical or "").strip()
    if not vertical:
        return [], "请先输入一个垂类，比如：家居收纳"
    if not ai_ready():
        return [], "AI未配置（本地 ai_config_local.py 或云上 Secrets 缺 DASHSCOPE_API_KEY）"

    prompt = f"""你是韩国YouTube搜索词专家，服务AliExpress韩国站的网红挖掘团队。

任务：围绕垂类「{vertical}」，生成 {count} 个韩语YouTube搜索关键词，用来搜出这个垂类里的个人中小博主（适合带货种草合作的）。

要求：
1. 每个关键词是韩国人真会在YouTube搜的短语，2-5个词，像「자취방 꾸미기 가성비」「다이소 수납템」这种风格
2. 偏向个人创作者内容（日常vlog、开箱haul、测评、教程、好物推荐），避开品牌名/官方频道词/明星名
3. 覆盖不同角度：场景词、人群词、好物词、平价词、教程词等，互相别重复
4. 只输出JSON字符串数组，不要任何其他文字，例如：["자취방 꾸미기 가성비", "다이소 수납템"]"""

    content, err = _call_qwen(prompt, timeout=timeout)
    if err:
        return [], err
    arr = _extract_json_array(content)
    if not arr:
        return [], "AI回复无法解析，请重试一次"
    kws, seen = [], set()
    for item in arr:
        if not isinstance(item, str):
            continue
        kw = item.strip().strip('"').strip()
        if kw and kw not in seen and not kw.startswith("["):
            seen.add(kw)
            kws.append(kw)
        if len(kws) >= max(6, count):
            break
    if not kws:
        return [], "AI没给出可用关键词，请换个说法重试"
    return kws, ""


def generate_bd_email_ai(ch: dict, sender: str, kkt: str, baseline: str,
                         extra_req: str = "", timeout: int = 90) -> tuple[str, str, str]:
    """AI 一键定制韩语 BD 邮件（邀请合作向，不推商品）。

    ch: 网红记录（channel_name/ai_content_category/ai_category/category/ai_tags/subscribers）
    sender: 落款名；kkt: 카카오톡 ID；baseline: 团队官方模板正文（结构与关键信息基准）
    extra_req: 用户附加要求（语气/跟进背景/特别强调点等），尽量满足
    返回 (主题, 正文, 错误信息)；失败时前两项为空串，调用方回退模板版。
    """
    if not ai_ready():
        return "", "", "AI未配置（缺 DASHSCOPE_API_KEY）"
    name = (ch.get("channel_name") or "").strip() or "크리에이터"
    content_cat = (ch.get("ai_content_category") or ch.get("content_category") or "").strip()
    cat = (ch.get("ai_category") or ch.get("category") or "").strip()
    tags = [t for t in (ch.get("ai_tags") or []) if t][:2]
    subs = ch.get("subscribers") or 0
    sender = (sender or "").strip() or "담당자"
    req_block = ""
    if (extra_req or "").strip():
        req_block = (f"\n[用户附加要求]\n{extra_req.strip()}\n"
                     "附加要求尽量满足；但若与「严禁编造事实」冲突，以不编造为准。\n")

    prompt = f"""你是AliExpress韩国网红营销团队的韩语商务邮件专家。

任务：对照下面的「官方模板」，为这位博主定制一封韩语合作邀请邮件，并写一个主题。

[博主信息]
频道名：{name}
内容垂类（频道拍什么内容）：{content_cat or '未知'}
带货垂类（适合挂的商品类目）：{cat or '未知'}
内容标签：{'、'.join(tags) if tags else '无'}
订阅量：{subs if subs else '未知'}

[硬性规则]
1. 邮件主目的是「诚挚邀请合作」。不要向对方推荐任何具体商品、不要指派带货任务；商品相关表述保留模板里「约2,500万个商品中自由选择」的原意。
2. 保留模板的整体结构与全部关键信息：크리에이터가 하실 일 三步、크리에이터가 얻으실 혜택 四条（含制作费、手续费5~13%等数字）、参考视频三条链接、카카오톡联系段、落款。数字与链接一字不改。
3. 只定制开头问候与「为什么选你」段落：结合博主的内容垂类/标签，自然、具体地写出对其内容方向的关注和契合点；品类契合的表述用带货垂类。严禁编造信息里没有的具体视频标题、播放量、评论等事实。
4. 韩语商务敬语，真诚简洁；总篇幅与模板相差不超过两成。
5. 落款固定写「{sender}」，카카오톡 ID 固定写「{kkt}」；开头自我介绍句固定写「알리익스프레스 마케팅팀 {sender}입니다.」，逐字照抄，不得重复或叠加词汇。
{req_block}

[官方模板]
{baseline}

[输出] 只输出一个JSON对象，不要任何其他文字：
{{"subject": "邮件主题", "body": "邮件正文全文"}}"""

    content, err = _call_qwen(prompt, timeout=timeout)
    if err:
        return "", "", err
    obj = _extract_json_object(content)
    if not obj or not str(obj.get("body", "")).strip():
        return "", "", "AI回复无法解析，请重试一次"
    return str(obj.get("subject", "")).strip(), str(obj["body"]).strip(), ""


# ============================================================
# 离线自测（python3 ai_analyzer.py）
# ============================================================
if __name__ == "__main__":
    print(f"AI 可用: {ai_ready()} | 模型: {DASHSCOPE_MODEL}")
    print(f"内容垂类 {len(CONTENT_CATEGORY_TABLE)} 个: {CONTENT_CATEGORY_TABLE}")
    print(f"带货垂类 {len(AI_CATEGORY_TABLE)} 个")
    demo = [
        {
            "channel_name": "자취연구소",
            "description": "자취방 꾸미기, 다이소 수납템 추천, 원룸 인테리어 브이로그",
            "recent_titles": ["자취방 수납템 추천", "다이소 꿀템 하울", "원룸 인테리어"],
            "recent_tags": [["자취", "수납", "다이소"], ["인테리어"]],
            "recent_descriptions": ["자취생 필수 수납템 추천 영상입니다."],
        },
        {
            "channel_name": "게임방송국",
            "description": "롤 하이라이트, 배그 실황, 게임 리뷰 채널",
            "recent_titles": ["롤 pentakill 모음", "배그 듀오 실황"],
            "recent_tags": [["게임", "lol"], ["배그"]],
            "recent_descriptions": ["게임 하이라이트 영상입니다."],
        },
    ]
    ok, fail, note = analyze_channels(demo, status_cb=print)
    print(note)
    for ch in demo:
        print({k: ch.get(k) for k in
               ("ai_analyzed", "ai_content_category", "ai_category", "ai_relevance", "ai_tags")})
