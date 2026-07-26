"""
KOL Finder - 韩国YouTube网红挖掘工具
Streamlit 主应用 v2.0
"""

import streamlit as st
import pandas as pd
import json
import re
import html as html_lib
from datetime import datetime, timedelta
from io import BytesIO

from youtube_api import (
    QuotaTracker, search_and_verify, get_channels, verify_channel,
    score_channel, search_videos, should_exclude,
    CATEGORY_KEYWORDS, VALUE_KEYWORDS, DEFAULT_CONFIG,
)

# ============================================================
# 团队公共库配置（写死在代码里，所有人共用，不用每次填）
# Supabase 的 anon key 是设计成可以公开的，只能读写咱们建的表，放心。
# ============================================================
SUPABASE_URL = "https://webjrwzorxxlqrcrrnro.supabase.co"
SUPABASE_KEY = "sb_publishable_eUDicGLoUiNhPO04S6iz8g_UX_SkSCH"  # 团队公共key，已配置好

# ============================================================
# 页面配置
# ============================================================

st.set_page_config(
    page_title="KOL Finder",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# 低饱和毛玻璃风样式（雾感粉 · 毛玻璃 · 星星闪烁）
# ============================================================

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@700;800&display=swap');

    /* ---------- 全局底色：纯色粉（卡通像素风 · 无毛玻璃无渐变） ---------- */
    .stApp {
        background: #f5a3b8;
        background-attachment: fixed;
    }
    footer { visibility: hidden; }

    h1, h2, h3, h4 {
        font-family: 'Baloo 2', -apple-system, 'PingFang SC', sans-serif;
        color: #1c1c1e; font-weight: 800; letter-spacing: -0.01em;
    }
    p, span, div, label, td, th, a, li {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', 'PingFang SC', sans-serif;
    }

    /* ---------- 顶部 hero：黑圆标 + 黄投影标题（卡通像素风） ---------- */
    .app-hero { text-align: center; padding: 8px 0 4px; position: relative; }
    .app-hero .hero-logo {
        width: 64px; height: 64px; margin: 0 auto 16px; border-radius: 50%;
        background: #1c1c1e; color: #f5c542; display: flex; align-items: center; justify-content: center;
        font-size: 26px; border: 4px solid #1c1c1e; box-shadow: 5px 5px 0 rgba(28,28,30,.3);
    }
    .app-hero .hero-title {
        font-size: 30px; font-weight: 800; color: #1c1c1e; margin: 0 0 8px;
        font-family: 'Baloo 2', -apple-system, 'PingFang SC', sans-serif;
        letter-spacing: 1px; text-shadow: 3px 3px 0 #f5c542;
    }
    .app-hero .hero-sub { font-size: 14px; color: #a05c74; font-weight: 700; margin: 0; }
    /* 星星：紫+黄 · 随机闪烁 */
    .app-hero .hero-star { position: absolute; font-size: 20px; animation: twinkle 2.6s ease-in-out infinite; }
    .app-hero .hero-star-l { left: 22%; top: 14px; color: #8674d6; animation-delay: 0s; animation-duration: 2.2s; }
    .app-hero .hero-star-r { right: 22%; top: 14px; color: #f5c542; animation-delay: .8s; animation-duration: 3.1s; }
    .app-hero .hero-star-2 { left: 30%; top: 66px; color: #f5c542; font-size: 14px; animation-delay: 1.4s; animation-duration: 2.7s; }
    .app-hero .hero-star-3 { right: 30%; top: 70px; color: #8674d6; font-size: 15px; animation-delay: .4s; animation-duration: 3.4s; }
    .app-hero .hero-star-4 { left: 16%; top: 52px; color: #8674d6; font-size: 13px; animation-delay: 1.9s; animation-duration: 2.4s; }
    .app-hero .hero-star-5 { right: 15%; top: 48px; color: #f5c542; font-size: 12px; animation-delay: 1.1s; animation-duration: 2.9s; }
    @keyframes twinkle {
        0%, 100% { opacity: .2; transform: scale(.75) rotate(-10deg); }
        50% { opacity: 1; transform: scale(1.2) rotate(10deg); }
    }

    /* ---------- 频道卡片：纯色 + 粗黑描边 + 硬阴影（卡通像素风） ---------- */
    .channel-card {
        background: #fffdf7;
        border: 3px solid #1c1c1e; border-radius: 18px; padding: 24px 28px;
        margin-bottom: 18px; box-shadow: 6px 6px 0 #1c1c1e;
    }
    .channel-card:hover { box-shadow: 6px 6px 0 #1c1c1e; }

    .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
    .card-name { font-size: 18px; font-weight: 800; color: #1c1c1e; letter-spacing: -0.01em; line-height: 1.35; }
    .card-links { text-align: right; white-space: nowrap; }
    .card-links a { font-size: 13px; font-weight: 800; text-decoration: none; }
    .card-links .link-home { color: #8674d6; }
    .card-links .link-about { color: #a05c74; }

    .rank-circle {
        display: inline-flex; align-items: center; justify-content: center;
        width: 32px; height: 32px; border-radius: 50%; font-size: 14px; font-weight: 800;
        background: #f5c542; color: #1c1c1e; margin-right: 10px; flex-shrink: 0;
        border: 3px solid #1c1c1e;
    }

    .score-badge {
        display: inline-block; padding: 8px 16px; border-radius: 12px;
        font-size: 16px; font-weight: 800; line-height: 1; border: 3px solid #1c1c1e;
    }
    .score-high { background: #8674d6; color: #fff; }
    .score-mid { background: #f5c542; color: #1c1c1e; }
    .score-low { background: #ffd9e3; color: #1c1c1e; }

    .tag-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .cat-tag {
        display: inline-block; padding: 4px 13px; border-radius: 999px;
        font-size: 12px; font-weight: 800; background: #8674d6; color: #fff;
        border: 2px solid #1c1c1e;
    }
    .commercial-badge {
        display: inline-block; padding: 4px 13px; border-radius: 999px;
        font-size: 12px; font-weight: 800; background: #f5c542; color: #1c1c1e;
        border: 2px solid #1c1c1e;
    }

    .stat-grid { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }
    .stat-pill {
        flex: 1; min-width: 110px; border-radius: 12px; padding: 10px 14px;
        font-size: 13px; font-weight: 700; color: #1c1c1e; border: 2px solid #1c1c1e;
    }
    .stat-pill .k { display: block; font-size: 11px; font-weight: 700; color: #a05c74; margin-top: 2px; }
    .stat-p1 { background: #ffd9e3; }
    .stat-p2 { background: #e6e0f5; }
    .stat-p3 { background: #fdf0cd; }
    .stat-p4 { background: #ffd9e3; }

    .email-line { font-size: 13px; color: #1c1c1e; margin-bottom: 6px; }
    .email-line .email-chip {
        display: inline-block; font-weight: 800; background: #e6e0f5; color: #1c1c1e;
        padding: 5px 14px; border-radius: 999px; border: 2px solid #1c1c1e;
    }
    .titles-line { font-size: 12px; color: #a05c74; margin-top: 6px; line-height: 1.6; font-weight: 600; }
    .score-detail-line { font-size: 11px; color: #a05c74; margin-top: 4px; }

    .thumb-row { display: flex; gap: 10px; margin-top: 12px; overflow-x: auto; }
    .thumb-item { flex-shrink: 0; text-align: center; }
    .thumb-item img { width: 130px; height: 73px; object-fit: cover; border-radius: 12px; border: 3px solid #1c1c1e; }
    .thumb-item span { font-size: 10px; color: #a05c74; display: block; margin-top: 3px; font-weight: 600; }

    /* ---------- 状态标签（网红库）：纯色 + 黑描边 ---------- */
    .status-tag {
        display: inline-block; padding: 3px 12px; border-radius: 999px;
        font-size: 12px; font-weight: 800; border: 2px solid #1c1c1e;
    }
    .status-new { background: #8674d6; color: #fff; }
    .status-emailed { background: #f5c542; color: #1c1c1e; }
    .status-onboard { background: #7fd8a4; color: #1c1c1e; }
    .status-reject { background: #ffd9e3; color: #1c1c1e; }

    /* ---------- 网红库三列小卡片：把 Streamlit 容器变成卡片 ----------
       原理：卡片容器内第一个元素是隐藏的 .kol-card-marker，
       用 :has() 选中"直接子级含该标记"的容器（不会误伤外层列）。 */
    .kol-card-marker { display: none; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) {
        background: #fffdf7;
        border: 3px solid #1c1c1e; border-radius: 18px;
        box-shadow: 6px 6px 0 #1c1c1e;
        padding: 10px;
    }
    /* 卡片内部紧凑排版（卡片变窄，内容要小） */
    .kol-name { font-size: 15px; font-weight: 800; color: #1c1c1e; line-height: 1.3; word-break: break-word; }
    .kol-home { font-size: 12px; font-weight: 800; color: #8674d6; text-decoration: none; white-space: nowrap; }
    .kol-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
    .kol-stats { font-size: 12px; color: #1c1c1e; margin-top: 6px; font-weight: 700; }
    .kol-sub { font-size: 11px; color: #a05c74; margin-top: 2px; font-weight: 600; }
    .kol-email { margin-top: 4px; font-size: 12px; }
    .kol-email .email-chip { font-size: 11px; padding: 2px 9px; }
    .kol-notes { font-size: 11px; color: #a05c74; margin-top: 6px; font-weight: 600; word-break: break-word; }
    .kol-divider { border: none; border-top: 2px solid #1c1c1e; opacity: .15; margin: 2px 0; }

    /* ---------- 卡片紧凑化：压缩内部垂直间距，让卡片变矮 ---------- */
    /* 容器内元素间距收紧 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) { gap: 6px; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) > .element-container { margin: 0 !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) [data-testid="stHorizontalBlock"] { margin: 0 !important; gap: 6px; }
    /* 卡片内控件统一缩到 34px（比全局 44px 矮一截） */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) [data-testid="stSelectbox"] [role="group"],
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) div[data-baseweb="select"] > div { min-height: 34px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stTextInput input { height: 34px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stButton button[data-testid="stBaseButton-primary"] { width: 34px !important; height: 34px !important; }

    /* ---------- 侧边栏：纯浅粉 + 粗黑右边框（无毛玻璃） ---------- */
    section[data-testid="stSidebar"] {
        background-color: #ffd9e3;
        border-right: 4px solid #1c1c1e;
    }

    /* ---------- 按钮：黑色胶囊 + 黑描边 + 硬阴影（卡通像素风）
       注意：1.60 里 button 被 tooltip span 包了三层，不是 .stButton 直接子元素，
       必须用后代选择器（空格），用 > 会完全匹配不到！ ---------- */
    .stButton button, .stDownloadButton button {
        border-radius: 999px !important; height: 44px; padding: 0 26px;
        font-weight: 800; font-family: 'Baloo 2', -apple-system, 'PingFang SC', sans-serif;
        border: 3px solid #1c1c1e !important;
        background: #1c1c1e !important;
        color: #fff !important;
        box-shadow: 4px 4px 0 rgba(28,28,30,.35);
        transition: all .12s;
        display: inline-flex; align-items: center; justify-content: center;
    }
    .stButton button p, .stDownloadButton button p { margin: 0; color: inherit; }
    .stButton button:hover, .stDownloadButton button:hover {
        background: #33333a !important; color: #fff !important;
        box-shadow: 4px 4px 0 rgba(28,28,30,.35);
    }
    .stButton button:active, .stDownloadButton button:active {
        transform: translate(3px,3px); box-shadow: none !important;
    }
    /* ---------- 图标按钮（🔄/🗑/×）：白底圆形 + 黑描边 + 硬阴影 ---------- */
    .stButton button[data-testid="stBaseButton-primary"] {
        width: 44px !important; height: 44px !important; padding: 0 !important;
        border-radius: 50% !important;
        background: #fff !important;
        color: #1c1c1e !important; border: 3px solid #1c1c1e !important;
        box-shadow: 3px 3px 0 #1c1c1e;
    }
    .stButton button[data-testid="stBaseButton-primary"]:hover {
        background: #ffd9e3 !important; color: #1c1c1e !important;
        box-shadow: 3px 3px 0 #1c1c1e;
    }
    .stButton button[data-testid="stBaseButton-primary"]:active {
        transform: translate(2px,2px); box-shadow: none !important;
    }

    /* ---------- Tabs：4个均分胶囊 · 白底=未选中 · 黑底=选中 · 黑描边+硬阴影 ---------- */
    .stTabs [role="tablist"] {
        gap: 12px; border-bottom: none;
        background: transparent; padding: 0;
        display: flex;
    }
    .stTabs [role="tab"] {
        flex: 1;
        border-radius: 999px !important; padding: 11px 0 !important;
        font-weight: 800; font-family: 'Baloo 2', -apple-system, 'PingFang SC', sans-serif;
        background: #fff !important;
        color: #1c1c1e !important; border: 3px solid #1c1c1e !important;
        justify-content: center;
        box-shadow: 4px 4px 0 #1c1c1e;
        transition: all .12s;
    }
    .stTabs [role="tab"]:hover { background: #ffd9e3 !important; color: #1c1c1e !important; }
    .stTabs [role="tab"][aria-selected="true"] {
        background: #1c1c1e !important;
        color: #ffffff !important;
        box-shadow: 4px 4px 0 rgba(28,28,30,.35);
    }
    .stTabs [role="tab"] p { color: inherit; }
    /* 隐藏默认下划线指示器（1.60 新结构） */
    .stTabs .react-aria-SelectionIndicator { display: none !important; }

    /* ---------- 指标卡：纯色 + 黑描边 + 硬阴影 ---------- */
    div[data-testid="stMetric"] {
        background: #fffdf7;
        border: 3px solid #1c1c1e; border-radius: 14px; padding: 16px 20px;
        box-shadow: 4px 4px 0 #1c1c1e;
    }
    div[data-testid="stMetricLabel"] { color: #a05c74; font-weight: 700; }
    div[data-testid="stMetricValue"] {
        color: #1c1c1e; font-weight: 800;
        font-family: 'Baloo 2', -apple-system, 'PingFang SC', sans-serif;
    }

    /* ---------- 输入框/数字框：白底 + 黑描边 + 硬阴影 ---------- */
    .stTextInput input, .stNumberInput input {
        border-radius: 12px !important; height: 44px;
        border: 3px solid #1c1c1e !important; background: #fff !important;
        box-shadow: 3px 3px 0 #1c1c1e; font-weight: 700;
    }
    .stTextArea textarea {
        border-radius: 14px !important;
        border: 3px solid #1c1c1e !important; background: #fff !important;
        box-shadow: 3px 3px 0 #1c1c1e;
    }
    .stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {
        border-color: #8674d6 !important; box-shadow: 3px 3px 0 #8674d6;
    }
    /* 数字框：隐藏 −/+ 按钮（1.60 改名为 stNumberInputStepUp/Down） */
    [data-testid="stNumberInputStepUp"], [data-testid="stNumberInputStepDown"] {
        display: none !important;
    }
    .stNumberInput input { padding-right: 20px !important; }
    /* ---------- 下拉框/多选框：白底 + 黑描边 + 硬阴影（1.60 React Aria 结构） ---------- */
    [data-testid="stSelectbox"] [role="group"],
    [data-testid="stMultiSelect"] [role="group"],
    div[data-baseweb="select"] > div {
        border-radius: 12px !important; min-height: 44px;
        border: 3px solid #1c1c1e !important; background: #fff !important;
        box-shadow: 3px 3px 0 #1c1c1e; font-weight: 700;
    }
    div[data-baseweb="popover"] > ul { border-radius: 14px; border: 3px solid #1c1c1e; }

    /* ---------- 滑杆：颜色由 .streamlit/config.toml 的 primaryColor 统一控制（雾灰紫），
       旧的 data-baseweb="slider" 选择器在 1.60 已失效，无需再写 ---------- */

    /* ---------- 提示条 / 展开器 / 代码块：黑描边 + 硬阴影 ---------- */
    div[data-testid="stAlert"], .stAlert {
        border-radius: 14px !important; border: 3px solid #1c1c1e !important;
        box-shadow: 4px 4px 0 rgba(28,28,30,.25);
    }
    /* 1.60: stExpander 的 testid 从 <details> 挪到外层 <div>，选择器不限定标签 */
    [data-testid="stExpander"] {
        border-radius: 14px !important; border: 3px solid #1c1c1e !important;
        background: #fffdf7 !important; box-shadow: 4px 4px 0 rgba(28,28,30,.25);
    }
    /* 展开器里的删除小圆按钮（词库×）：缩到30px */
    [data-testid="stExpander"] .stButton button[data-testid="stBaseButton-primary"] {
        width: 30px !important; height: 30px !important; font-size: 13px;
    }
    pre {
        border-radius: 12px !important; border: 3px solid #1c1c1e !important;
        background: #ffd9e3 !important;
    }

    hr { border-color: #1c1c1e; border-width: 2px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 预置关键词库
# ============================================================

KEYWORD_LIBRARY = {
    "家居收纳": [
        "자취방 꾸미기 가성비", "원룸 수납 정리", "자취생 필수템 추천",
        "다이소 수납템", "집꾸미기 브이로그", "작은 방 인테리어",
        "혼자 사는 여자 방 꾸미기", "정리정돈 꿀팁", "미니멀 라이프 자취",
    ],
    "平价美妆": [
        "가성비 화장품 추천", "학생 메이크업 화장품", "올리브영 추천템",
        "데일리 메이크업 학생", "출근 메이크업 추천", "로드샵 화장품 추천",
        "만원 이하 화장품", "화장품 언박싱 추천",
    ],
    "宿舍好物": [
        "대학생 필수템 추천", "기숙사 필수템", "개강 준비물 리스트",
        "기숙사 꾸미기 템", "대학생 브이로그 자취", "자취생 꿀템 추천",
        "대학생 개강 준비",
    ],
    "通勤配件": [
        "직장인 가방 추천 여자", "출근 가방 미니백", "왓츠인마이백 직장인",
        "가벼운 미니백 추천", "가성비 데일리백", "직장인 출근룩 가방",
        "통근룩 코디 추천",
    ],
    "宠物用品": [
        "고양이 필수템 추천", "강아지 용품 추천", "펫용품 가성비",
        "펫테리어", "집사 브이로그", "고양이 용품 언박싱",
        "반려동물 용품 추천",
    ],
    "学生用品": [
        "문구 추천 학생", "공부 브이로그 문구템", "다이소 문구 추천",
        "필통 꾸미기", "아이패드 공부템", "스터디 위드 미 공부",
        "문구 언박싱 추천",
    ],
}


def _safe(text) -> str:
    """
    清理动态文本，防止破坏卡片排版。
    视频标题里常带 | 竖线、< > 符号、换行等，直接塞进HTML会让排版引擎
    误判，导致卡片变成一堆代码。这里统一转义/替换掉这些"捣乱"字符。
    """
    if text is None:
        return ""
    text = str(text)
    text = html_lib.escape(text)          # 转义 < > & " '
    text = text.replace("|", "｜")        # 竖线换成全角，避免被当成表格
    text = text.replace("\n", " ")        # 换行换成空格
    return text


def _render_html(html_str: str):
    """
    安全渲染自定义HTML，防止被Markdown误判成代码块（卡片变一堆代码）。
    两个坑：
    ① 纯空白行会被Markdown当成"空行"——HTML块遇到空行就终止，其后内容
       全部变成原始代码显示。当频道没有商业化历史时 comm_html 为空，它所在
       的行就成了纯空白行，正是"卡片变代码"反复复发的根因。
    ② 层级缩进（行首多个空格）可能被Markdown当成缩进代码块。
    统一处理：删掉纯空白行 + 去掉每行行首缩进（空白对HTML渲染无意义）。
    """
    lines = [line.strip() for line in html_str.split("\n") if line.strip()]
    st.markdown("\n".join(lines), unsafe_allow_html=True)


# ============================================================
# Session State 初始化
# ============================================================

if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "supabase_url" not in st.session_state:
    st.session_state.supabase_url = SUPABASE_URL
if "supabase_key" not in st.session_state:
    st.session_state.supabase_key = SUPABASE_KEY
if "db" not in st.session_state:
    st.session_state.db = None  # InfluencerDB 实例
if "quota" not in st.session_state:
    st.session_state.quota = QuotaTracker()
if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "search_log" not in st.session_state:
    st.session_state.search_log = []
if "config" not in st.session_state:
    st.session_state.config = DEFAULT_CONFIG.copy()
if "user_name" not in st.session_state:
    st.session_state.user_name = ""
# 本地模式备用数据
if "local_db" not in st.session_state:
    st.session_state.local_db = []


# ============================================================
# 数据库连接
# ============================================================

def get_db():
    """获取数据库实例（Supabase 或本地模式）"""
    # Key 还是占位符（没配置）时不连接，走本地模式
    if st.session_state.supabase_key == "PASTE_YOUR_ANON_KEY_HERE":
        return None
    if st.session_state.supabase_url and st.session_state.supabase_key:
        try:
            from database import InfluencerDB
            if st.session_state.db is None:
                st.session_state.db = InfluencerDB(
                    st.session_state.supabase_url, st.session_state.supabase_key
                )
            return st.session_state.db
        except Exception:
            return None
    return None


def get_all_records() -> list[dict]:
    """获取所有网红记录（Supabase 或本地）"""
    db = get_db()
    if db:
        return db.get_all()
    return st.session_state.local_db


def get_full_keyword_library() -> dict:
    """
    获取完整关键词库（全队共享版）。
    优先用公共库里的（大家可以随时增删）；
    公共库表还是空的（第一次用）→ 自动把内置默认词库写进去；
    连不上公共库 → 退回内置默认词库，保证随时有词可用。
    """
    db = get_db()
    if db:
        db_kws = db.get_keywords()
        if db_kws:
            return db_kws
        # 表是空的（第一次使用），用内置默认词库初始化一次
        db.seed_keywords(KEYWORD_LIBRARY)
        return KEYWORD_LIBRARY
    return KEYWORD_LIBRARY


# ============================================================
# 侧边栏
# ============================================================

with st.sidebar:
    # ---------- 名字：下拉快选 / 新成员登记，记住在网址里 ----------
    st.markdown("### 👋 先选个名字")
    st.caption("填一次，以后刷新都记得你")

    # 从网址参数恢复名字（刷新不丢）
    url_name = st.query_params.get("u", "")
    if url_name and not st.session_state.user_name:
        st.session_state.user_name = url_name

    db_for_members = get_db()
    members = db_for_members.get_members() if db_for_members else []

    NEW = "➕ 我是新成员"
    display_members = list(members)
    if st.session_state.user_name and st.session_state.user_name not in display_members:
        display_members.append(st.session_state.user_name)

    options = display_members + [NEW]
    if st.session_state.user_name in display_members:
        default_idx = display_members.index(st.session_state.user_name)
    else:
        default_idx = len(display_members)  # 默认落在"新成员"

    chosen = st.selectbox("你是谁？", options, index=default_idx, key="who_select")
    st.caption("👆 老成员：直接点开选自己的名字；新成员：选「我是新成员」")

    if chosen == NEW:
        new_name = st.text_input("输入你的名字", key="new_name_input",
                                 placeholder="例如：小美")
        st.caption("✍️ 只有第一次用才需要输，点下面「记住我」后，下次直接选名字")
        if st.button("✅ 记住我", key="save_name", use_container_width=True):
            if new_name.strip():
                if db_for_members:
                    db_for_members.add_member(new_name.strip())
                st.session_state.user_name = new_name.strip()
                st.query_params["u"] = new_name.strip()
                # 清空控件记忆，让下拉框回到"已选中"状态
                for k in ("who_select", "new_name_input"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()
            else:
                st.warning("先输入名字哦")
    else:
        if chosen != st.session_state.user_name:
            st.session_state.user_name = chosen
            st.query_params["u"] = chosen

    if st.session_state.user_name and chosen == st.session_state.user_name:
        pass  # 名字已生效（下拉框会显示选中状态），不再额外弹问候框，保持侧边栏干净

    # ---------- YouTube API Key：每次自己填，不存数据库 ----------
    st.markdown("")
    st.markdown("#### 🔑 YouTube API Key")
    api_key_input = st.text_input(
        "API Key", value=st.session_state.api_key, type="password",
        label_visibility="collapsed",
        help="Google Cloud Console 获取，免费10,000 units/天。为安全起见不存数据库，每次自己填。",
        placeholder="粘贴你的 YouTube API Key",
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
        st.session_state.quota = QuotaTracker()

    # ---------- 如何获取 API Key：点击展开看步骤 ----------
    with st.expander("📖 如何获取 API Key？（点我看步骤）"):
        st.markdown("""
**1.** 打开 **console.cloud.google.com**，用 Google 账号登录

**2.** 顶部选择或新建一个项目（例如叫 KOL-Finder）

**3.** 左侧菜单「API 和服务」→「库」，搜索 **YouTube Data API v3**，点「启用」

**4.** 左侧「凭据」→「+ 创建凭据」→「**API 密钥**」

**5.** 复制密钥粘贴到上面输入框即可（免费 10,000 units/天，够全队用）
""")

    # ---------- 公共库：已写死在代码里，只显示状态 ----------
    st.markdown("")
    st.markdown("#### 🗄 团队公共库")
    db = get_db()
    if SUPABASE_KEY == "PASTE_YOUR_ANON_KEY_HERE":
        st.warning("⚠️ 还没配置公共库，请联系管理员填Key")
    elif db:
        st.success("✅ 已连上，全队共享")
        st.caption("大家挖到的博主都存在这里，自动同步、自动去重，不用你配置。")
    else:
        st.error("❌ 连接失败，请联系管理员")

    # ---------- 配额（精简成一行小字，去掉标题和进度条） ----------
    quota = st.session_state.quota
    st.caption(f"📊 今日已用 {quota.used:,} / {QuotaTracker.DAILY_LIMIT:,} units")
    if quota.remaining < 500:
        st.warning("⚠️ 配额即将用完")


# ============================================================
# 主区域
# ============================================================

# 完整关键词库（全队共享版，只读一次，供下面所有页面用）
KW_LIB = get_full_keyword_library()

st.markdown("""
<div class="app-hero">
    <span class="hero-star hero-star-l">✦</span>
    <span class="hero-star hero-star-r">✦</span>
    <span class="hero-star hero-star-2">✦</span>
    <span class="hero-star hero-star-3">✦</span>
    <span class="hero-star hero-star-4">✦</span>
    <span class="hero-star hero-star-5">✦</span>
    <div class="hero-logo">✦</div>
    <div class="hero-title">KOL Finder</div>
    <div class="hero-sub">韩国 YouTube 网红挖掘 · 自动验证活跃 · 智能评分 · 公共库去重</div>
</div>
""", unsafe_allow_html=True)
st.markdown("")

tab_search, tab_database, tab_import, tab_settings = st.tabs([
    "🔎 搜索挖掘", "📁 网红库", "📥 批量导入", "⚙️ 筛选设置"
])

# ============================================================
# Tab 1: 搜索挖掘
# ============================================================

with tab_search:
    st.markdown("### 按关键词搜索活跃博主")
    st.markdown("自动过滤：不活跃 / 订阅量不符 / 已在库中的博主")
    st.markdown("")

    if not st.session_state.api_key:
        st.info("👈 请先在左侧填入 YouTube API Key")
    else:
        # ---------- 垂类选择 ----------
        category_select = st.selectbox(
            "垂类", options=list(KW_LIB.keys()),
            help="切换垂类后，下方推荐关键词会跟着变",
        )

        # ---------- 推荐关键词 · 一键点选 ----------
        st.markdown("✨ **推荐关键词** · 点击任意一个直接搜索")
        chip_kws = KW_LIB[category_select]
        for row_start in range(0, len(chip_kws), 3):
            chip_cols = st.columns(3)
            for j, kw in enumerate(chip_kws[row_start:row_start + 3]):
                with chip_cols[j]:
                    if st.button(kw, key=f"kwchip_{category_select}_{row_start + j}",
                                 use_container_width=True):
                        st.session_state.pending_kw = kw

        st.markdown("")

        # ---------- 自定义关键词 ----------
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            keyword_input = st.text_input(
                "搜索关键词", placeholder="也可以输入自定义关键词，例：자취방 꾸미기 가성비",
                label_visibility="collapsed",
            )
        with col2:
            search_btn = st.button("🔍 搜索", use_container_width=True)
        with col3:
            batch_btn = st.button("⚡ 批量", use_container_width=True,
                                  help="使用当前垂类全部预置关键词搜索")

        st.markdown("")

        # 获取库中记录用于去重
        db_records = get_all_records()

        # 搜索触发：优先用点击的推荐词，其次用自定义输入
        search_keyword = None
        if st.session_state.get("pending_kw"):
            search_keyword = st.session_state.pop("pending_kw")
        elif search_btn and keyword_input.strip():
            search_keyword = keyword_input.strip()

        # 单个搜索
        if search_keyword:
            with st.spinner(f"正在搜索「{search_keyword}」并验证活跃度..."):
                results = search_and_verify(
                    keyword=search_keyword,
                    category=category_select,
                    api_key=st.session_state.api_key,
                    quota=st.session_state.quota,
                    config=st.session_state.config,
                    db_records=db_records,
                )
                st.session_state.search_results = results
                st.session_state.search_log.append({
                    "keyword": search_keyword, "category": category_select,
                    "time": datetime.now().strftime("%H:%M"), "results": len(results),
                })
                if results:
                    st.success(f"✅ 找到 {len(results)} 个符合条件的活跃博主")
                else:
                    st.warning("未找到符合条件的博主（可能都已不活跃或已在库中）")

        # 批量搜索
        if batch_btn:
            keywords = KW_LIB[category_select]
            all_results = []
            progress = st.progress(0)
            status_text = st.empty()

            for i, kw in enumerate(keywords):
                if not st.session_state.quota.can_afford(110):
                    status_text.warning(f"⚠️ 配额不足，已完成 {i}/{len(keywords)}")
                    break
                status_text.text(f"搜索中 ({i+1}/{len(keywords)}): {kw}")
                results = search_and_verify(
                    keyword=kw, category=category_select,
                    api_key=st.session_state.api_key,
                    quota=st.session_state.quota,
                    config=st.session_state.config,
                    db_records=db_records,
                )
                all_results.extend(results)
                progress.progress((i + 1) / len(keywords))

            # 去重
            seen = set()
            unique = []
            for r in all_results:
                if r["channel_id"] not in seen:
                    seen.add(r["channel_id"])
                    unique.append(r)
            unique.sort(key=lambda x: x["scores"]["total"], reverse=True)
            st.session_state.search_results = unique
            status_text.success(f"✅ 批量完成，共 {len(unique)} 个活跃博主")

        # ---------- 搜索结果（和搜索同页展示） ----------
        if st.session_state.search_results:
            st.markdown("---")
            st.markdown("### 🎯 搜索结果")

            results = st.session_state.search_results

            # 筛选
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                min_score_filter = st.slider("最低评分", 0, 100,
                                             st.session_state.config.get("score_threshold", 45), step=5)
            with col_f2:
                sort_by = st.selectbox("排序", ["综合评分", "订阅量", "近30天均播", "最近更新"])

            filtered = [r for r in results if r["scores"]["total"] >= min_score_filter]
            sort_keys = {
                "综合评分": lambda x: x["scores"]["total"],
                "订阅量": lambda x: x["subscribers"],
                "近30天均播": lambda x: x["avg_views_30d"],
                "最近更新": lambda x: x["last_upload"],
            }
            filtered.sort(key=sort_keys[sort_by], reverse=True)

            st.markdown(f"共 {len(filtered)} 个博主")
            st.markdown("")

            # 频道卡片
            for idx, ch in enumerate(filtered):
                score = ch["scores"]["total"]
                score_class = "score-high" if score >= 70 else ("score-mid" if score >= 50 else "score-low")
                commercial = ch.get("commercial_history", {})
                has_comm = commercial.get("has_commercial", False)
                emails = ch.get("emails", [])
                email_display = emails[0] if emails else "未公开"
                thumbnails = ch.get("recent_thumbnails", [])

                # 缩略图HTML
                thumb_html = ""
                if thumbnails:
                    items = ""
                    for t in thumbnails[:4]:
                        items += f'<div class="thumb-item"><img src="{t["url"]}" alt=""><span>{t["date"]}</span></div>'
                    thumb_html = f'<div class="thumb-row">{items}</div>'

                # 商业化标记
                comm_html = ""
                if has_comm:
                    evidence = ", ".join(commercial.get("evidence", [])[:3])
                    comm_html = f'<span class="commercial-badge">💰 有商业合作 ({_safe(evidence)})</span>'

                # 代表视频标题（清理特殊符号，防止破坏排版）
                titles_clean = " / ".join(_safe(t) for t in ch.get("recent_titles", [])[:3])

                _render_html(f"""
                <div class="channel-card">
                    <div class="card-head">
                        <div style="display:flex; align-items:flex-start;">
                            <span class="rank-circle">{idx+1}</span>
                            <div>
                                <div class="card-name">{_safe(ch['channel_name'])}</div>
                                <div class="tag-row" style="margin-top:8px; margin-bottom:0;">
                                    <span class="cat-tag">📂 {_safe(ch.get('category', ''))}</span>
                                    {comm_html}
                                </div>
                            </div>
                        </div>
                        <div style="display:flex; align-items:center; gap:14px;">
                            <span class="score-badge {score_class}">{score}</span>
                            <div class="card-links">
                                <a class="link-home" href="{ch['channel_url']}" target="_blank">主页 ↗</a><br>
                                <a class="link-about" href="{ch.get('about_url', ch['channel_url'])}" target="_blank">简介页 ↗</a>
                            </div>
                        </div>
                    </div>
                    <div class="stat-grid">
                        <div class="stat-pill stat-p1">📺 {ch['subscribers']:,}<span class="k">订阅数</span></div>
                        <div class="stat-pill stat-p2">👁 {ch['avg_views_30d']:,}<span class="k">30天均播</span></div>
                        <div class="stat-pill stat-p3">📈 {ch['view_sub_ratio']}%<span class="k">播/订比</span></div>
                        <div class="stat-pill stat-p4">🕐 {ch['last_upload_days_ago']}天前<span class="k">最近更新</span></div>
                    </div>
                    <div class="email-line">📧 联系邮箱 <span class="email-chip">{_safe(email_display)}</span></div>
                    <div class="titles-line">代表视频：{titles_clean}</div>
                    <div class="score-detail-line">
                        评分明细 · 垂直{ch['scores']['verticality']} ＋ 商业{ch['scores']['commercial']} ＋
                        数据{ch['scores']['data_health']} ＋ 频率{ch['scores']['frequency']} ＋
                        关键词{ch['scores']['keywords']}
                    </div>
                    {thumb_html}
                </div>
                """)

                # 操作按钮
                col_a1, col_a2, col_a3 = st.columns([1, 1, 3])
                with col_a1:
                    if st.button("✅ 加入网红库", key=f"add_{idx}", use_container_width=True):
                        db = get_db()
                        if db:
                            if db.add_influencer(ch, st.session_state.user_name):
                                st.success(f"已添加「{ch['channel_name']}」")
                            else:
                                st.error(f"添加失败：{db.last_error or '未知错误，请检查数据库连接'}")
                        else:
                            # 本地模式
                            ch["status"] = "新发现"
                            ch["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            ch["discovered_by"] = st.session_state.user_name
                            st.session_state.local_db.append(ch)
                            st.success(f"已添加「{ch['channel_name']}」（本地模式）")
                with col_a2:
                    if st.button("跳过", key=f"skip_{idx}", use_container_width=True):
                        st.session_state.search_results.remove(ch)
                        st.rerun()
                st.markdown("")

            # 批量操作
            st.markdown("---")
            col_ba1, col_ba2 = st.columns(2)
            with col_ba1:
                if st.button("✅ 全部加入网红库", use_container_width=True):
                    db = get_db()
                    added = 0
                    for ch in filtered:
                        if db:
                            if db.add_influencer(ch, st.session_state.user_name):
                                added += 1
                        else:
                            ch["status"] = "新发现"
                            ch["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            ch["discovered_by"] = st.session_state.user_name
                            st.session_state.local_db.append(ch)
                            added += 1
                    st.success(f"已添加 {added} 个博主")
            with col_ba2:
                if filtered:
                    export_data = []
                    for ch in filtered:
                        export_data.append({
                            "频道名": ch["channel_name"], "主页链接": ch["channel_url"],
                            "垂类": ch.get("category", ""), "订阅量": ch["subscribers"],
                            "近30天均播": ch["avg_views_30d"], "评分": ch["scores"]["total"],
                            "联系邮箱": ", ".join(ch.get("emails", [])) or "未公开",
                            "有商业合作": "是" if ch.get("commercial_history", {}).get("has_commercial") else "否",
                            "最近更新": ch["last_upload"],
                            "代表视频": " / ".join(ch.get("recent_titles", [])[:3]),
                        })
                    buffer = BytesIO()
                    pd.DataFrame(export_data).to_excel(buffer, index=False, engine="openpyxl")
                    st.download_button(
                        "📥 导出结果 (Excel)", data=buffer.getvalue(),
                        file_name=f"搜索结果_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )
        elif not st.session_state.search_log:
            st.info("💡 点击上方推荐关键词，或输入自定义关键词后点「搜索」")

        # 搜索历史
        if st.session_state.search_log:
            st.markdown("")
            st.markdown("#### 📜 最近搜索")
            for log in reversed(st.session_state.search_log[-8:]):
                st.caption(f"{log['time']} · {log['keyword']} · {log['category']} · {log['results']}个结果")


# ============================================================
# Tab 2: 网红库
# ============================================================

with tab_database:
    st.markdown("### 网红库")
    st.markdown("")

    records = get_all_records()

    if not records:
        st.info("网红库为空。搜索后点击「加入网红库」，或使用「📥 批量导入」添加已有合作博主。")
    else:
        # 统计
        stats = {"total": len(records), "新发现": 0, "已发邮件": 0, "已引入": 0, "已拒绝": 0, "已淘汰": 0}
        for r in records:
            s = r.get("status", "")
            if s in stats:
                stats[s] += 1

        cols = st.columns(6)
        labels = ["总数", "新发现", "已发邮件", "已引入", "已拒绝", "已淘汰"]
        keys = ["total", "新发现", "已发邮件", "已引入", "已拒绝", "已淘汰"]
        for col, label, key in zip(cols, labels, keys):
            with col:
                st.metric(label, stats[key])

        st.markdown("")

        # 筛选
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            filter_status = st.selectbox("状态", ["全部", "新发现", "已发邮件", "已引入", "已拒绝", "已淘汰"])
        with col_f2:
            filter_cat = st.multiselect("垂类", options=list(KW_LIB.keys()), default=[], placeholder="全部垂类")
        with col_f3:
            # 挖掘人筛选：全部 / 只看我的 / 各个挖过博主的同事名字（自动从记录收集）
            discoverers = sorted({r.get("discovered_by", "") for r in records if r.get("discovered_by")})
            filter_discoverer = st.selectbox(
                "👤 挖掘人", ["全部", "只看我的"] + discoverers,
                help="「只看我的」= 只显示你挖的博主；也可以选同事名字看 TA 挖了谁",
            )
        with col_f4:
            db_sort = st.selectbox("排序", ["添加时间", "评分", "订阅量", "最近更新"], key="db_sort")

        filtered_db = records
        if filter_status != "全部":
            filtered_db = [r for r in filtered_db if r.get("status") == filter_status]
        if filter_cat:
            filtered_db = [r for r in filtered_db if r.get("category") in filter_cat]
        if filter_discoverer == "只看我的":
            filtered_db = [r for r in filtered_db if r.get("discovered_by") == st.session_state.user_name]
        elif filter_discoverer != "全部":
            filtered_db = [r for r in filtered_db if r.get("discovered_by") == filter_discoverer]

        sort_map = {
            "添加时间": lambda x: x.get("added_date", ""),
            "评分": lambda x: x.get("score_total", 0) if isinstance(x.get("score_total"), (int, float)) else 0,
            "订阅量": lambda x: x.get("subscribers", 0),
            "最近更新": lambda x: x.get("last_upload", ""),
        }
        filtered_db.sort(key=sort_map[db_sort], reverse=True)

        st.markdown(f"显示 {len(filtered_db)} / {len(records)} 条")
        st.markdown("")

        # 列表（三列小卡片，打标按键全部收进卡片内）
        num_cols = 3
        total_db = len(filtered_db)
        for row_start in range(0, total_db, num_cols):
            cols = st.columns(num_cols)
            for j in range(num_cols):
                idx = row_start + j
                if idx >= total_db:
                    break
                rec = filtered_db[idx]
                with cols[j]:
                    with st.container():
                        # 隐藏标记：让外层容器变成卡片（见CSS :has()规则）
                        st.markdown('<div class="kol-card-marker"></div>', unsafe_allow_html=True)

                        status = rec.get("status", "新发现")
                        status_class = {"新发现": "status-new", "已发邮件": "status-emailed",
                                       "已引入": "status-onboard", "已拒绝": "status-reject",
                                       "已淘汰": "status-reject"}.get(status, "status-new")

                        name = rec.get("channel_name", "未知")
                        url = rec.get("channel_url", "#")
                        subs = rec.get("subscribers", 0)
                        score = rec.get("score_total", "-")
                        cat = rec.get("category", "")
                        discoverer = rec.get("discovered_by", "")
                        email = rec.get("emails", "")
                        notes = rec.get("notes", "")

                        # 卡片信息（紧凑版）
                        _render_html(f"""
                        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
                            <span class="kol-name">{_safe(name)}</span>
                            <a class="kol-home" href="{url}" target="_blank">主页 ↗</a>
                        </div>
                        <div class="kol-tags">
                            <span class="status-tag {status_class}">{status}</span>
                            <span class="cat-tag">📂 {_safe(cat)}</span>
                        </div>
                        <div class="kol-stats">📺 {subs:,} 订阅 · ⭐ 评分 {score}</div>
                        {'<div class="kol-sub">👤 挖掘人：' + _safe(discoverer) + '</div>' if discoverer else ''}
                        {'<div class="kol-email">📧 <span class="email-chip">' + _safe(email) + '</span></div>' if email else ''}
                        <hr class="kol-divider">
                        """)

                        # 状态下拉
                        new_status = st.selectbox(
                            "状态", ["新发现", "已发邮件", "已引入", "已拒绝", "已淘汰"],
                            index=["新发现", "已发邮件", "已引入", "已拒绝", "已淘汰"].index(status),
                            key=f"st_{idx}", label_visibility="collapsed",
                        )
                        if new_status != status:
                            db = get_db()
                            cid = rec.get("channel_id", "")
                            if db:
                                db.update_status(cid, new_status)
                            else:
                                for lr in st.session_state.local_db:
                                    if lr.get("channel_id") == cid:
                                        lr["status"] = new_status
                                        lr["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            st.rerun()

                        # 复查 / 删除 / 备注
                        c_rc, c_rm, c_nt = st.columns([1, 1, 4])
                        with c_rc:
                            if st.button("🔄", key=f"rc_{idx}", help="复查活跃度", type="primary"):
                                if st.session_state.api_key:
                                    with st.spinner("复查中..."):
                                        chs = get_channels([rec.get("channel_id", "")], st.session_state.api_key, st.session_state.quota)
                                        if chs:
                                            ch_info = list(chs.values())[0]
                                            result = verify_channel(ch_info, st.session_state.api_key, st.session_state.quota, st.session_state.config)
                                            db = get_db()
                                            cid = rec.get("channel_id", "")
                                            if result:
                                                result["scores"] = score_channel(result, rec.get("category"), st.session_state.config)
                                                if db:
                                                    db.update_last_checked(cid, True, result)
                                                st.success(f"✅ {name} 仍然活跃")
                                            else:
                                                if db:
                                                    db.update_last_checked(cid, False)
                                                st.warning(f"⚠️ {name} 已不活跃")
                                else:
                                    st.error("需要API Key")
                        with c_rm:
                            if st.button("🗑", key=f"rm_{idx}", help="从库中移除", type="primary"):
                                db = get_db()
                                cid = rec.get("channel_id", "")
                                if db:
                                    db.remove(cid)
                                else:
                                    st.session_state.local_db = [r for r in st.session_state.local_db if r.get("channel_id") != cid]
                                st.rerun()
                        with c_nt:
                            note_val = st.text_input("备注", value=notes, key=f"nt_{idx}",
                                                     placeholder="例：已发邮件、回复快、要价高...",
                                                     label_visibility="collapsed")
                            if note_val != notes:
                                db = get_db()
                                cid = rec.get("channel_id", "")
                                if db:
                                    db.update_notes(cid, note_val)
                                else:
                                    for lr in st.session_state.local_db:
                                        if lr.get("channel_id") == cid:
                                            lr["notes"] = note_val

        # 导出
        st.markdown("---")
        if records:
            export_rows = []
            for r in records:
                export_rows.append({
                    "频道名": r.get("channel_name", ""), "链接": r.get("channel_url", ""),
                    "垂类": r.get("category", ""), "订阅量": r.get("subscribers", 0),
                    "评分": r.get("score_total", ""), "状态": r.get("status", ""),
                    "邮箱": r.get("emails", ""), "挖掘人": r.get("discovered_by", ""),
                    "备注": r.get("notes", ""), "添加日期": r.get("added_date", ""),
                    "发邮件日期": r.get("email_sent_date", ""),
                })
            buffer = BytesIO()
            pd.DataFrame(export_rows).to_excel(buffer, index=False, engine="openpyxl")
            st.download_button(
                "📥 导出网红库 (Excel)", data=buffer.getvalue(),
                file_name=f"网红库_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# ============================================================
# Tab 3: 批量导入
# ============================================================

with tab_import:
    st.markdown("### 批量导入已有合作博主")
    st.markdown("把频道主页链接或频道ID粘贴进来，导入后搜索时会自动跳过这些人。")
    st.markdown("")

    st.markdown("**支持的格式（每行一个）：**")
    st.code("""https://www.youtube.com/channel/UCxxxxxxxxxxxx
https://www.youtube.com/@频道名
UCxxxxxxxxxxxx""", language=None)
    st.markdown("")

    import_text = st.text_area(
        "粘贴链接或ID", height=200,
        placeholder="每行一个频道链接或ID...",
    )

    col_i1, col_i2 = st.columns([1, 1])
    with col_i1:
        import_status = st.selectbox("导入后标记为", ["已引入", "已拒绝", "已发邮件", "新发现"])
    with col_i2:
        st.markdown("")
        st.markdown("")

    if st.button("📥 开始导入", use_container_width=True):
        if not import_text.strip():
            st.warning("请先粘贴链接或ID")
        elif not st.session_state.api_key:
            st.error("需要 YouTube API Key 来查询频道信息")
        else:
            # 解析输入
            lines = [l.strip() for l in import_text.strip().split("\n") if l.strip()]
            channel_ids = []
            for line in lines:
                # 提取频道ID
                if line.startswith("UC") and len(line) == 24:
                    channel_ids.append(line)
                elif "/channel/" in line:
                    match = re.search(r'/channel/(UC[\w-]+)', line)
                    if match:
                        channel_ids.append(match.group(1))
                elif line.startswith("@"):
                    # @handle 格式，需要通过搜索获取ID（消耗配额）
                    channel_ids.append(line)  # 后续处理
                else:
                    channel_ids.append(line)

            if not channel_ids:
                st.error("未能解析出有效的频道ID")
            else:
                db = get_db()
                with st.spinner(f"正在导入 {len(channel_ids)} 个频道..."):
                    if db:
                        result = db.import_existing(
                            channel_ids, st.session_state.api_key,
                            st.session_state.quota, status=import_status,
                            imported_by=st.session_state.user_name,
                        )
                        st.success(f"✅ 导入完成：成功 {result['success']}，跳过（已存在）{result['skipped']}，失败 {result['failed']}")
                    else:
                        # 本地模式
                        chs = get_channels(channel_ids, st.session_state.api_key, st.session_state.quota)
                        added = 0
                        for cid, info in chs.items():
                            info["status"] = import_status
                            info["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            info["discovered_by"] = st.session_state.user_name
                            info["notes"] = "批量导入"
                            st.session_state.local_db.append(info)
                            added += 1
                        st.success(f"✅ 已导入 {added} 个频道（本地模式）")


# ============================================================
# Tab 4: 筛选设置
# ============================================================

with tab_settings:
    st.markdown("### 筛选设置")
    st.markdown("所有参数可随时调整，适应不同挖掘需求。")
    st.markdown("")

    config = st.session_state.config

    # 基础参数
    st.markdown("#### 📐 基础参数")
    col_p1, col_p2, col_p3 = st.columns(3)
    with col_p1:
        new_min = st.number_input("最小订阅量", value=config["min_subs"], step=500)
    with col_p2:
        new_max = st.number_input("最大订阅量", value=config["max_subs"], step=5000)
    with col_p3:
        new_days = st.number_input("活跃天数（近N天有更新）", value=config["days_active"], step=7)

    new_threshold = st.slider("评分阈值（低于此分不展示）", 0, 100, config["score_threshold"], step=5)

    # 评分权重
    st.markdown("")
    st.markdown("#### ⚖️ 评分权重（总分100）")
    weights = config["weights"]
    col_w1, col_w2, col_w3 = st.columns(3)
    with col_w1:
        w_vert = st.slider("内容垂直度", 0, 40, weights["verticality"])
        w_comm = st.slider("商业化历史", 0, 40, weights["commercial"])
    with col_w2:
        w_data = st.slider("数据健康度", 0, 40, weights["data_health"])
        w_freq = st.slider("更新频率", 0, 40, weights["frequency"])
    with col_w3:
        w_kw = st.slider("种草关键词", 0, 40, weights["keywords"])

    total_w = w_vert + w_comm + w_data + w_freq + w_kw
    if total_w != 100:
        st.warning(f"⚠️ 当前权重总和 = {total_w}，建议调整为100")
    else:
        st.success(f"✅ 权重总和 = 100")

    # 去重规则
    st.markdown("")
    st.markdown("#### 🔁 去重规则（多少天后重新出现）")
    rules = config["dedup_rules"]
    col_d1, col_d2, col_d3, col_d4 = st.columns(4)
    with col_d1:
        d_onboard = st.number_input("已引入（-1=永久）", value=rules["onboarded_days"], step=1)
    with col_d2:
        d_reject = st.number_input("已拒绝（天）", value=rules["rejected_days"], step=7)
    with col_d3:
        d_email = st.number_input("已发邮件（天）", value=rules["emailed_days"], step=1)
    with col_d4:
        d_discover = st.number_input("新发现（天）", value=rules["discovered_days"], step=1)

    # 保存按钮
    st.markdown("")
    if st.button("💾 保存设置", use_container_width=True):
        st.session_state.config = {
            "min_subs": new_min,
            "max_subs": new_max,
            "days_active": new_days,
            "score_threshold": new_threshold,
            "weights": {
                "verticality": w_vert, "commercial": w_comm,
                "data_health": w_data, "frequency": w_freq, "keywords": w_kw,
            },
            "dedup_rules": {
                "onboarded_days": d_onboard, "rejected_days": d_reject,
                "emailed_days": d_email, "discovered_days": d_discover,
            },
        }
        st.success("✅ 设置已保存")

    # 关键词库（可增删 · 全队共享）
    st.markdown("")
    st.markdown("#### 📝 预置关键词库")
    st.caption("➕➖ 随时增删，改动存进公共库，全队 10 个人同步共享")
    db_kw = get_db()
    for cat, kws in KW_LIB.items():
        with st.expander(f"{cat}（{len(kws)}个）"):
            for kw in kws:
                c_del, c_kw = st.columns([0.4, 9.6])
                with c_del:
                    if st.button("×", key=f"kwdel_{cat}_{kw}", type="primary",
                                 help=f"删除「{kw}」"):
                        if db_kw and db_kw.delete_keyword(cat, kw):
                            st.rerun()
                with c_kw:
                    st.caption(f"• {kw}")
            st.markdown("")
            c_in, c_btn = st.columns([4, 1])
            with c_in:
                new_kw = st.text_input(
                    "新关键词", key=f"kwnew_{cat}",
                    placeholder="输入新关键词…", label_visibility="collapsed",
                )
            with c_btn:
                if st.button("➕ 添加", key=f"kwadd_{cat}", use_container_width=True):
                    if new_kw.strip():
                        if db_kw and db_kw.add_keyword(cat, new_kw.strip()):
                            st.rerun()
