"""
KOL Finder - 韩国YouTube网红挖掘工具
Streamlit 主应用 v2.0
"""

import streamlit as st
import pandas as pd
import json
import re
import html as html_lib
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import BytesIO

import requests

from streamlit_local_storage import LocalStorage

from youtube_api import (
    QuotaTracker, search_and_verify, get_channels, verify_channel,
    score_channel, search_videos, should_exclude, resolve_channel_ids,
    CATEGORY_KEYWORDS, VALUE_KEYWORDS, DEFAULT_CONFIG, estimate_search_cost,
    split_main_pending, split_line_date, split_line_meta, parse_import_excel,
)
from ai_analyzer import (analyze_channels, ai_ready, AI_CATEGORY_TABLE, DASHSCOPE_MODEL,
                         generate_keywords, generate_bd_email_ai)

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
    /* 字体不引外部资源（国内连谷歌字体库会白屏等半天），用系统圆体栈 */

    /* ---------- 全局底色：纯色粉（卡通像素风 · 无毛玻璃无渐变） ---------- */
    .stApp {
        background: #f5a3b8;
        background-attachment: fixed;
    }
    footer { visibility: hidden; }

    /* ---------- 弹窗遮罩：周围变暗的经典 popup 效果 ---------- */
    /* Streamlit 默认遮罩是白色半透明（看着像变亮），改成深色半透明 */
    .stDialog {
        background: rgba(28, 28, 30, 0.55) !important;
    }

    h1, h2, h3, h4 {
        font-family: ui-rounded, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', -apple-system, sans-serif;
        color: #1c1c1e; font-weight: 800; letter-spacing: -0.01em;
    }
    p, span, div, label, td, th, a, li {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', 'PingFang SC', sans-serif;
    }

    /* ---------- 顶部 hero：黑圆标 + 黄投影标题（卡通像素风） ---------- */
    .app-hero { text-align: center; padding: 14px 0 6px; position: relative; }
    .app-hero .hero-logo {
        width: 96px; height: 96px; margin: 0 auto 18px; border-radius: 50%;
        background: #1c1c1e; color: #f5c542; display: flex; align-items: center; justify-content: center;
        font-size: 40px; border: 5px solid #1c1c1e; box-shadow: 6px 6px 0 rgba(28,28,30,.3);
    }
    .app-hero .hero-title {
        font-size: 44px; font-weight: 800; color: #1c1c1e; margin: 0 0 10px;
        font-family: ui-rounded, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', -apple-system, sans-serif;
        letter-spacing: 1px; text-shadow: 4px 4px 0 #f5c542;
    }
    .app-hero .hero-sub { font-size: 16px; color: #a05c74; font-weight: 700; margin: 0; }
    /* 星星：紫+黄 · 随机闪烁 */
    .app-hero .hero-star { position: absolute; font-size: 24px; animation: twinkle 2.6s ease-in-out infinite; }
    .app-hero .hero-star-l { left: 20%; top: 20px; color: #8674d6; animation-delay: 0s; animation-duration: 2.2s; }
    .app-hero .hero-star-r { right: 20%; top: 20px; color: #f5c542; animation-delay: .8s; animation-duration: 3.1s; }
    .app-hero .hero-star-2 { left: 28%; top: 92px; color: #f5c542; font-size: 16px; animation-delay: 1.4s; animation-duration: 2.7s; }
    .app-hero .hero-star-3 { right: 28%; top: 96px; color: #8674d6; font-size: 17px; animation-delay: .4s; animation-duration: 3.4s; }
    .app-hero .hero-star-4 { left: 14%; top: 68px; color: #8674d6; font-size: 15px; animation-delay: 1.9s; animation-duration: 2.4s; }
    .app-hero .hero-star-5 { right: 13%; top: 62px; color: #f5c542; font-size: 14px; animation-delay: 1.1s; animation-duration: 2.9s; }
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
    .rel-badge {
        display: inline-block; padding: 4px 13px; border-radius: 999px;
        font-size: 12px; font-weight: 800; background: #fffdf7; color: #8674d6;
        border: 2px solid #8674d6;
    }
    .ai-tag {
        display: inline-block; padding: 4px 11px; border-radius: 999px;
        font-size: 12px; font-weight: 700; background: #fff0f4; color: #a05c74;
        border: 2px dashed #d98ba3;
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
    .status-date {
        font-size: 10.5px; color: #a05c74; font-weight: 700;
        margin-top: 4px; line-height: 1.2;
    }

    /* ---------- 网红库三列小卡片：把 Streamlit 容器变成卡片 ----------
       原理：卡片容器内第一个元素是隐藏的 .kol-card-marker，
       用 :has() 选中"直接子级含该标记"的容器（不会误伤外层列）。 */
    .kol-card-marker { display: none; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) {
        background: #fffdf7;
        border: 3px solid #1c1c1e; border-radius: 18px;
        box-shadow: 6px 6px 0 #1c1c1e;
        padding: 14px;
    }
    /* 卡片内部紧凑排版（卡片变窄，内容要小） */
    .kol-name { font-size: 15px; font-weight: 800; color: #1c1c1e; line-height: 1.3; word-break: break-word; }
    .kol-home { font-size: 12px; font-weight: 800; color: #8674d6; text-decoration: none; white-space: nowrap; }
    .kol-tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
    .kol-stats { font-size: 12px; color: #1c1c1e; margin-top: 8px; font-weight: 700; }
    .kol-sub { font-size: 11px; color: #a05c74; margin-top: 8px; font-weight: 600; }
    .kol-email { margin-top: 8px; font-size: 12px; }
    .kol-email .email-chip { font-size: 11px; padding: 3px 10px; }
    .kol-notes { font-size: 11px; color: #a05c74; margin-top: 6px; font-weight: 600; word-break: break-word; }
    .kol-divider { border: none; border-top: 2px solid #1c1c1e; opacity: .15; margin: 8px 0; }

    /* ---------- 卡片紧凑化：压缩内部垂直间距，让卡片变矮 ---------- */
    /* 容器内元素间距收紧 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) { gap: 8px; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) > .element-container { margin: 0 !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) [data-testid="stHorizontalBlock"] { margin: 0 !important; gap: 8px; }
    /* 分隔线：Streamlit 会给 markdown 里的 hr 默认 32px 上下外边距（卡片里多出64px空白），
       必须用卡片作用域 + !important 压回；设为 8px 与各行间距一致 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) hr.kol-divider { margin: 8px 0 !important; }
    /* 卡片内控件统一 40px：图标按钮设 34px 会被 Streamlit 的 min-height:40px 撑成椭圆，
       所以宽高都锁定 40px 保证正圆；下拉框/备注框一并对齐 40px */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) [data-testid="stSelectbox"] [role="group"],
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) div[data-baseweb="select"] > div { min-height: 40px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stTextInput input { height: 40px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stButton button[data-testid="stBaseButton-primary"] { width: 40px !important; height: 40px !important; min-height: 40px !important; }

    /* ---------- 卡片模式改三列：整体再缩小一号（对应预览稿）----------
       覆盖上方的 40px 控件为 32/34px，padding/字号同步收紧，紧凑但不挤 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) { padding: 12px; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) [data-testid="stSelectbox"] [role="group"],
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) div[data-baseweb="select"] > div { min-height: 34px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stTextInput input { height: 34px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stButton button[data-testid="stBaseButton-primary"] { width: 32px !important; height: 32px !important; min-height: 32px !important; font-size: 13px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-card-marker) .stButton button:not([data-testid="stBaseButton-primary"]) { height: 34px !important; min-height: 34px !important; font-size: 12.5px !important; }
    .kol-name { font-size: 14px; }
    .kol-stats { font-size: 11.5px; }

    /* ---------- 列表模式：一行一个博主（窄表格行 · 内容上下居中）----------
       原理同卡片：行容器内第一个元素是隐藏的 .kol-row-marker */
    .kol-row-marker { display: none; }
    /* ---------- 关键词分组行：白胶囊=未选中 / 黑胶囊=选中（同顶部Tab语言） ---------- */
    .kwgroup-marker { display: none; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kwgroup-marker) .stButton button[data-testid="stBaseButton-primary"] {
        width: 100% !important; height: 44px !important; min-height: 44px !important;
        border-radius: 999px !important; padding: 0 10px !important;
        background: #1c1c1e !important; color: #fff !important;
    }
    [data-testid="stVerticalBlock"]:has(> .element-container .kwgroup-marker) .stButton button:not([data-testid="stBaseButton-primary"]) {
        background: #fff !important; color: #1c1c1e !important;
    }
    [data-testid="stVerticalBlock"]:has(> .element-container .kwgroup-marker) .stButton button:not([data-testid="stBaseButton-primary"]):hover {
        background: #ffd9e3 !important; color: #1c1c1e !important;
    }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) {
        background: #fffdf7;
        border: 2.5px solid #1c1c1e; border-radius: 12px;
        box-shadow: 3px 3px 0 rgba(28,28,30,.55);
        padding: 3px 14px;
        gap: 0 !important;
    }
    /* 容器内元素不留额外外边距、列间距收紧 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) > .element-container { margin: 0 !important; }
    /* 各列内容上下居中：列本身居中对齐 + 列内内容也居中 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) [data-testid="stHorizontalBlock"] { margin: 0 !important; gap: 10px; align-items: center !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) [data-testid="stHorizontalBlock"] [data-testid="stVerticalBlock"] { justify-content: center !important; }
    /* 上下居中修复：Streamlit 把每个文字格子的高度锁成单行高（约24px），而"昵称+邮箱"是两行（约40px），
       多出的内容向下溢出、显得文字整体偏下。这里只把"文字格子"(.stMarkdown)上移 8px 补偿，
       让"昵称+邮箱"整体落在行的几何中心。
       注意：千万不能把这个位移加在 stHorizontalBlock 上——操作按钮那一列里还嵌套了一个小横向区块，
       会被移两次、导致按钮比文字高出一截；按钮和状态下拉本身位置是准的，不需要动。
       若以后调字号导致偏移变化，只需微调这个 -8px。 */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) .stMarkdown { transform: translateY(-8px); }
    /* 行内文字样式（字号收小、行距收紧，整行更窄） */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) .stMarkdown p { margin: 0 !important; line-height: 1.25; }
    .row-name a { font-size: 13px; font-weight: 800; color: #1c1c1e; text-decoration: none; }
    .row-name a:hover { color: #8674d6; }
    .row-email { font-size: 10.5px; color: #6b5a9e; word-break: break-all; }
    .row-num { font-size: 12px; color: #1c1c1e; font-weight: 700; }
    .row-who { font-size: 11.5px; color: #a05c74; font-weight: 600; }
    .row-cat { font-size: 10px !important; padding: 2px 8px !important; }
    /* 行内控件缩小：下拉 28px、圆钮 24px、邮件按钮 24px */
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) [data-testid="stSelectbox"] [role="group"],
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) div[data-baseweb="select"] > div { min-height: 28px !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) .stButton button[data-testid="stBaseButton-primary"] { width: 24px !important; height: 24px !important; min-height: 24px !important; font-size: 11px !important; padding: 0 !important; }
    [data-testid="stVerticalBlock"]:has(> .element-container .kol-row-marker) .stButton button:not([data-testid="stBaseButton-primary"]) { height: 24px !important; min-height: 24px !important; font-size: 11px !important; padding: 0 9px !important; }

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
        font-weight: 800; font-family: ui-rounded, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', -apple-system, sans-serif;
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
        font-weight: 800; font-family: ui-rounded, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', -apple-system, sans-serif;
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
        font-family: ui-rounded, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', -apple-system, sans-serif;
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
    /* ---------- 密码框（API Key）：眼睛图标和输入框在同一个 flex 容器里，
       默认描边只画在 input 上，右侧眼睛图标那段没描边（胶囊断裂）。
       解决：把描边挪到外层容器，眼睛图标也圈进同一个白底胶囊；
       内层 input 去掉自己的描边，高度留给外层边框。 ---------- */
    [data-testid="stTextInputRootElement"]:has(input[type="password"]) {
        border: 3px solid #1c1c1e !important; border-radius: 12px !important;
        background: #fff !important; box-shadow: 3px 3px 0 #1c1c1e;
        height: 44px; align-items: center;
    }
    [data-testid="stTextInputRootElement"]:has(input[type="password"]) input {
        border: none !important; box-shadow: none !important;
        background: transparent !important; border-radius: 0 !important;
        height: 38px !important;
    }
    [data-testid="stTextInputRootElement"]:has(input[type="password"]):focus-within {
        border-color: #8674d6 !important; box-shadow: 3px 3px 0 #8674d6;
    }
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


def _status_date_html(status: str, email_sent_date, introduced_date) -> str:
    """根据状态返回小字日期 HTML（用于已发邮件 / 已引入下方）。"""
    date_str = ""
    if status == "已发邮件" and email_sent_date:
        date_str = f"📧 {str(email_sent_date)[:10]}"
    elif status == "已引入" and introduced_date:
        date_str = f"🤝 {str(introduced_date)[:10]}"
    if date_str:
        return f'<div class="status-date">{date_str}</div>'
    return ""


def _apply_status_date(record: dict, new_status: str):
    """本地模式下，根据新状态补录发邮件/引入时间。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    record["status"] = new_status
    record["status_date"] = now
    if new_status == "已发邮件":
        record["email_sent_date"] = now
    if new_status == "已引入":
        record["introduced_date"] = now


def _append_reason(old_notes: str, new_status: str, reason: str) -> str:
    """把拒绝/淘汰原因拼进备注（带日期标记，方便以后翻查）。"""
    tag = "拒绝原因" if new_status == "已拒绝" else "淘汰原因"
    stamp = datetime.now().strftime("%m-%d")
    entry = f"[{stamp}{tag}] {reason.strip()}"
    old_notes = (old_notes or "").strip()
    return f"{old_notes}\n{entry}" if old_notes else entry


def _apply_status_change(rec: dict, new_status: str, reason: str = ""):
    """应用单条状态变更（自动判断 DB/本地模式）；填了原因就追加到备注。"""
    cid = rec.get("channel_id", "")
    _db = get_db()
    if _db:
        _db.update_status(cid, new_status)
        if reason.strip():
            _db.update_notes(cid, _append_reason(rec.get("notes", "") or "", new_status, reason))
    else:
        for lr in st.session_state.local_db:
            if lr.get("channel_id") == cid:
                _apply_status_date(lr, new_status)
                if reason.strip():
                    lr["notes"] = _append_reason(lr.get("notes", "") or "", new_status, reason)
                break
    _count_records.clear()
    _get_paginated_records.clear()
    _get_dedup_records.clear()


def _enrich_with_ai(results: list, status_box=None) -> str:
    """第二期核心：挖掘完成后把结果批量交给 AI——定垂类、打相关度、出标签，
    然后用四维权重重算评分并重新排序。返回 AI 说明文字供界面显示。
    AI 未配置/失败时内部会给中性值，不影响主流程。"""
    if not results:
        return ""

    def _say(m):
        if status_box is not None:
            try:
                status_box.info(f"🔍 {m}")
            except Exception:
                pass

    _ok, _fail, note = analyze_channels(results, status_cb=_say)
    for r in results:
        if r.get("ai_category"):
            r["category"] = r["ai_category"]
        r["scores"] = score_channel(r, st.session_state.config)
    results.sort(key=lambda x: x["scores"]["total"], reverse=True)
    return note


def _refresh_one_channel(channel_id: str, channel_name: str, category: str, owner: str = "") -> tuple[bool, str]:
    """刷新单个网红的基础数据（订阅/均播/评分/最近更新）。

    返回 (成功?, 提示消息)。成功时会更新数据库并清空相关缓存。
    只有该网红的挖掘人（discovered_by）与当前登录用户一致时才允许刷新。
    """
    user_name = st.session_state.get("user_name", "")
    if owner and owner != user_name:
        return False, f"只能刷新自己挖掘的网红（{channel_name} 由 {owner} 负责）"

    if not st.session_state.get("api_key"):
        return False, "需要 API Key，请先在左侧填入后再刷新"

    with st.spinner(f"刷新 {channel_name} 中..."):
        chs = get_channels([channel_id], st.session_state.api_key, st.session_state.quota)
        if not chs:
            return False, f"⚠️ {channel_name}：无法获取频道信息"

        ch_info = list(chs.values())[0]
        result = verify_channel(ch_info, st.session_state.api_key, st.session_state.quota, st.session_state.config)
        _db = get_db()

        if result:
            # 第二期：刷新时也跑一次 AI（单个频道，几秒钟），保证垂类/相关度是最新的
            if ai_ready():
                analyze_channels([result])
                if result.get("ai_category"):
                    result["category"] = result["ai_category"]
            result["scores"] = score_channel(result, st.session_state.config)
            if _db:
                _db.update_last_checked(channel_id, True, result)
            else:
                # 本地模式：直接更新内存里的测试数据
                for lr in st.session_state.local_db:
                    if lr.get("channel_id") == channel_id:
                        lr["subscribers"] = result.get("subscribers", lr.get("subscribers", 0))
                        lr["avg_views_30d"] = result.get("avg_views_30d", lr.get("avg_views_30d", 0))
                        lr["view_sub_ratio"] = result.get("view_sub_ratio", lr.get("view_sub_ratio", 0))
                        lr["last_upload"] = result.get("last_upload", lr.get("last_upload", ""))
                        lr["score_total"] = result["scores"].get("total", lr.get("score_total", 0))
                        lr["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                        break
            _count_records.clear()
            _get_paginated_records.clear()
            _get_dedup_records.clear()
            return True, f"✅ {channel_name}：数据已刷新"
        else:
            if _db:
                _db.update_last_checked(channel_id, False)
            _count_records.clear()
            _get_paginated_records.clear()
            _get_dedup_records.clear()
            return True, f"⚠️ {channel_name}：已标记为不活跃"


# ============================================================
# 批量操作辅助函数
# ============================================================

def _init_batch_state():
    """确保 batch_selected 集合存在"""
    if "batch_selected" not in st.session_state:
        st.session_state.batch_selected = set()


def _on_batch_check(cid: str):
    """单个勾选框变化时的回调（Streamlit on_change）"""
    _init_batch_state()
    if st.session_state.get(f"bchk_{cid}", False):
        st.session_state.batch_selected.add(cid)
    else:
        st.session_state.batch_selected.discard(cid)


def _clear_batch_selection():
    """清空所有批量勾选状态"""
    cids = list(st.session_state.get("batch_selected", set()))
    st.session_state.batch_selected = set()
    for cid in cids:
        key = f"bchk_{cid}"
        if key in st.session_state:
            st.session_state[key] = False


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
    st.session_state.local_db = [
        {
            "channel_id": "test_email_001",
            "channel_name": "测试频道-已发邮件",
            "channel_url": "https://www.youtube.com/@testemail",
            "category": "平价美妆",
            "subscribers": 12000,
            "score_total": 82,
            "status": "已发邮件",
            "discovered_by": "测试员",
            "emails": "test@example.com",
            "notes": "本地测试数据",
            "added_date": "2026-08-01 10:00",
            "status_date": "2026-08-05 14:30",
            "last_upload": "2026-08-04",
            "last_checked": "2026-08-05 14:30",
            "email_sent_date": "2026-08-05",
            "introduced_date": None,
        },
        {
            "channel_id": "test_onboard_002",
            "channel_name": "测试频道-已发邮件2",
            "channel_url": "https://www.youtube.com/@testonboard",
            "category": "家居收纳",
            "subscribers": 8500,
            "score_total": 78,
            "status": "已发邮件",
            "discovered_by": "测试员",
            "emails": "onboard@example.com",
            "notes": "本地测试数据",
            "added_date": "2026-08-02 09:00",
            "status_date": "2026-08-06 11:00",
            "last_upload": "2026-08-03",
            "last_checked": "2026-08-06 11:00",
            "email_sent_date": "2026-08-05",
            "introduced_date": "2026-08-06",
        },
    ]


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


@st.cache_data(ttl=45, show_spinner=False)
def _count_records(db_url, db_key, status, category_tuple, discoverer, discoverer_name):
    """带缓存的筛选计数（内部临时创建 DB 连接，避免 session_state 不可哈希问题）"""
    from database import InfluencerDB
    db = InfluencerDB(db_url, db_key)
    return db.count_records(
        status=status,
        category=list(category_tuple) if category_tuple else None,
        discoverer=discoverer,
        discoverer_name=discoverer_name,
    )


@st.cache_data(ttl=45, show_spinner=False)
def _get_paginated_records(db_url, db_key, page, page_size, status, category_tuple,
                           discoverer, discoverer_name, sort_by, descending):
    """带缓存的分页查询（内部临时创建 DB 连接）"""
    from database import InfluencerDB
    db = InfluencerDB(db_url, db_key)
    return db.get_records_paginated(
        page=page,
        page_size=page_size,
        status=status,
        category=list(category_tuple) if category_tuple else None,
        discoverer=discoverer,
        discoverer_name=discoverer_name,
        sort_by=sort_by,
        descending=descending,
    )


@st.cache_data(ttl=300, show_spinner=False)
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


@st.cache_data(ttl=60, show_spinner=False)
def _get_dedup_records(db_url, db_key):
    """带缓存的去重轻量记录查询（搜索页用，避免全表拉取）"""
    from database import InfluencerDB
    db = InfluencerDB(db_url, db_key)
    return db.get_dedup_records()


# ============================================================
# BD 邮件草稿生成（基于团队验证过的韩语话术模板，做个性化填充）
# ============================================================

# 中文垂类 → 韩语品类（用于邮件里"你的频道和XX品类很契合"这句）
CATEGORY_KO = {
    "家居收纳": "홈/인테리어",
    "平价美妆": "뷰티",
    "宿舍好物": "홈/인테리어",
    "通勤配件": "패션",
    "宠物用品": "리빙",
    "学生用品": "문구",
}


def generate_email_draft(ch: dict, user_name: str, kkt_id: str) -> tuple[str, str]:
    """
    根据网红信息生成个性化韩语 BD 邮件草稿。
    返回 (主题, 正文)。话术结构保留团队模板，仅做个性化填充。
    """
    name = ch.get("channel_name", "크리에이터")
    category = ch.get("category", "")
    # 老的中文垂类走映射表；AI 判定的新垂类本身就是韩文品类名，直接用
    cat_ko = CATEGORY_KO.get(category, "") or category
    sender = user_name or "마케팅팀 담당자"
    kkt = kkt_id or "（카카오톡 ID）"

    # 品类契合句（有垂类才加，避免生硬）
    cat_line = ""
    if cat_ko:
        cat_line = (f"\n특히 {name}님의 채널은 저희가 중점적으로 모집하고 있는 "
                    f"{cat_ko} 카테고리와 톤앤매너가 매우 잘 맞아, "
                    f"이번 프로모션에 최적의 파트너라고 판단했습니다.\n")

    subject = f"[협업 제안] {name}님과 알리익스프레스 유튜브 쇼핑 제휴를 함께하고 싶습니다"

    body = f"""안녕하세요, {name}님.
알리익스프레스 마케팅팀 {sender}입니다.

평소 {name}님의 유튜브 콘텐츠를 즐겁게 보고 있으며, 올리신 영상에서 보여준 센스와 시청자분들의 반응에 큰 관심을 가지게 되어 연락드렸습니다.

저희 알리익스프레스가 현재 유튜브 쇼핑 태그를 활용한 크리에이터 제휴 프로모션을 진행하고 있는데, {name}님의 채널 톤앤매너와 매우 잘 어울릴 것 같아 협업 제안을 드리게 되었습니다.
{cat_line}
자유로운 형식의 영상 제작으로 안정적인 제작비와 추가 수익을 얻으실 수 있는 협업인 만큼, 아래 내용을 검토해 보시고 긍정적인 검토 부탁드립니다.

[크리에이터가 하실 일] (매우 간단합니다!)
저희는 크리에이터의 자유로운 스타일을 최대한 존중합니다.
상품 선택 및 구매: 유튜브 쇼핑 스튜디오 내 태그 등록 가능한 알리익스프레스 상품(약 2,500만 개) 중 채널에 맞는 제품 자유롭게 선택
영상 제작 및 업로드: 제품 언박싱, 리뷰, haul 등 자유로운 형식의 영상 제작
유튜브 쇼핑 태그 등록: 영상 하단 또는 설명란에 해당 제품 태그 연결

[크리에이터가 얻으실 혜택]
1. 영상 제작비 지원 (상품 구매비 포함)
채널 규모 및 콘텐츠 포맷에 맞춰 합리적인 수준의 제작비를 지원하며, 실제 상황에 따라 협의 가능합니다.
2. 유튜브 쇼핑 태그 판매 수익 (판매 수수료 5~13% 지급)
여성향 카테고리(뷰티, 패션, 홈 등)는 평균 10% 이상의 높은 수수료를 제공합니다.
판매가 발생할 때마다 유튜브를 통해 직접 정산받으시므로, 한 번 올린 영상이 장기적인 파이프라인 수익이 됩니다.
3. 인기 크리에이터 대상 '장기 파트너십' 체결
단기 1회성이 아닌, 콘텐츠 성과가 좋을 경우 분기/연간 단위의 장기 계약을 통해 안정적이고 지속적인 수익을 보장해 드립니다.
4. 단독 기획전(공동구매) 초대 및 전사적 마케팅 지원
우수 파트너로 선정 시, 알리익스프레스 공식 단독 기획전 참여 기회 부여 (단독 할인코드 및 더 높은 수익률 보장)
플랫폼 내/외부 미디어 자원을 활용한 채널 홍보 지원으로 신규 구독자 유입 및 채널 성장을 돕습니다.

[진행 가능 카테고리 및 참고 영상]
주요 카테고리: 뷰티 / 패션 / 홈 / 주방 / 육아 / 인테리어 / 문구 / 완구 / 네일 / 자동차 / 아웃도어 / 커피 등 카테고리
참고 영상 (이런 형태로 제작해 주시면 됩니다):
하봄: https://youtube.com/shorts/xIetj_6u_uo
푸짐스: https://youtube.com/shorts/S3BT8PiziC0
켈리아: https://www.youtube.com/shorts/W6bs2y-ab70

협업에 관심이 있으시거나, 희망하시는 영상 제작 조건이 있으시면 편하게 회신 주시거나 아래 카카오톡으로 연락 부탁드립니다.
(이메일보다 카카오톡으로 빠르게 안내해 드릴 수 있습니다.)
카카오톡 ID: {kkt}

크리에이터님과 함께 알리익스프레스가 성장할 수 있기를 기대하겠습니다.
감사합니다.
{sender} 드림"""

    return subject, body


@st.dialog("📧 BD邮件草稿", width="large")
def bd_email_dialog(rec):
    """弹窗展示个性化 BD 邮件：秒开模板版，可一键AI定制；主题可改，正文一键复制。"""
    cid = rec.get("channel_id", "")
    # 落款优先用"邮件署名"（韩文/英文名），没填才回退到内部中文名
    sender = st.session_state.config.get("sender_name", "") or st.session_state.user_name
    kkt = st.session_state.config.get("kkt_id", "")
    subj_t, body_t = generate_email_draft(rec, sender, kkt)
    sk, bk = f"dlg_subj_{cid}", f"dlg_body_{cid}"
    st.session_state.setdefault(sk, subj_t)
    st.session_state.setdefault(bk, body_t)

    st.caption("已自动填入该博主信息和你的专属署名。想要更定制的版本，点「✨ 一键AI定制」。")

    req = st.text_input(
        "✍️ 附加要求（可选 · 写给AI看）",
        key=f"aimail_req_{cid}",
        placeholder="例：语气更活泼 / 强调制作费可谈 / 这是第二次跟进，上封邮件对方没回",
    )

    c1, c2 = st.columns([1, 2])
    with c1:
        ai_btn = st.button("✨ 一键AI定制", key=f"aimail_{cid}", use_container_width=True)
    with c2:
        st.caption("🤖 AI 按该博主垂类/标签+你的附加要求定制开头和「为什么选你」，模板骨架与关键信息不变")
    if ai_btn:
        with st.spinner("🤖 AI 正在定制这封邮件…"):
            s2, b2, err = generate_bd_email_ai(rec, sender, kkt, body_t, extra_req=req)
        if err:
            st.warning(f"AI 定制没成功（{err}），已保留模板版")
        else:
            st.session_state[sk] = s2
            st.session_state[bk] = b2
            st.toast("✅ AI 定制完成，可继续微调后复制")

    st.text_input("邮件主题（可改）", key=sk)

    with st.expander("✏️ 微调正文（可选 · 展开编辑）"):
        st.text_area("正文", key=bk, height=240, label_visibility="collapsed")
        st.caption("改完后，下方复制块会同步更新")

    st.markdown("##### 📋 邮件正文（点右上角图标一键复制）")
    st.code(st.session_state[bk], language=None)


# ---------- 缩略图服务端代理 ----------
# 浏览器（尤其国内网络）常常直连不了 YouTube 图床 i.ytimg.com，
# 改成服务器端下载、base64 内嵌到页面里；云上服务器在海外，必然可达。
_THUMB_CACHE: dict = {}
_THUMB_DEAD = False

def _thumb_data_uris(urls: list) -> list:
    global _THUMB_DEAD
    if _THUMB_DEAD:
        return [None for _ in urls]
    todo = [u for u in urls if u and u not in _THUMB_CACHE]
    if todo:
        def _fetch(u):
            for verify in (True, False):
                try:
                    r = requests.get(u, timeout=5, verify=verify)
                    if r.status_code == 200 and r.content:
                        return u, f"data:image/jpeg;base64,{base64.b64encode(r.content).decode()}"
                except Exception:
                    continue
            return u, None
        with ThreadPoolExecutor(max_workers=10) as ex:
            for u, uri in ex.map(_fetch, todo):
                _THUMB_CACHE[u] = uri
        if all(_THUMB_CACHE.get(u) is None for u in todo):
            _THUMB_DEAD = True  # 服务器也够不到图床，后续直接跳过，不拖慢页面
    return [_THUMB_CACHE.get(u) for u in urls]


def _render_result_card(ch: dict, rank: int, key_prefix: str):
    """渲染一张搜索结果卡片 + 操作按钮（主列表和待定区共用）。
    key_prefix 用于区分区域，避免按钮 key 冲突。"""
    score = ch["scores"]["total"]
    score_class = "score-high" if score >= 70 else ("score-mid" if score >= 50 else "score-low")
    commercial = ch.get("commercial_history", {})
    has_comm = commercial.get("has_commercial", False)
    emails = ch.get("emails", [])
    email_display = emails[0] if emails else "未公开"
    thumbnails = ch.get("recent_thumbnails", [])

    # 缩略图HTML（服务器端下载内嵌，浏览器不用直连YouTube图床）
    thumb_html = ""
    if thumbnails:
        items = ""
        _urls = _thumb_data_uris([t["url"] for t in thumbnails[:2]])
        for t, _u in zip(thumbnails[:2], _urls):
            if not _u:
                continue
            items += f'<div class="thumb-item"><img src="{_u}" alt="" loading="lazy" decoding="async"><span>{t["date"]}</span></div>'
        if items:
            thumb_html = f'<div class="thumb-row">{items}</div>'

    # 商业化标记
    comm_html = ""
    if has_comm:
        evidence = ", ".join(commercial.get("evidence", [])[:3])
        comm_html = f'<span class="commercial-badge">💰 有商业合作 ({_safe(evidence)})</span>'

    # AI 垂类 + 相关度 + 关键词标签（第二期）
    ai_cat = ch.get("category", "") or "未判定"
    rel_html = ""
    if ch.get("ai_analyzed"):
        rel_html = f'<span class="rel-badge">🎯 AI相关度 {ch.get("ai_relevance", "-")}</span>'
    tag_html = "".join(
        f'<span class="ai-tag">#{_safe(t)}</span>' for t in (ch.get("ai_tags") or [])[:2]
    )

    # 代表视频标题（清理特殊符号，防止破坏排版）
    titles_clean = " / ".join(_safe(t) for t in ch.get("recent_titles", [])[:3])

    _render_html(f"""
    <div class="channel-card">
        <div class="card-head">
            <div style="display:flex; align-items:flex-start;">
                <span class="rank-circle">{rank}</span>
                <div>
                    <div class="card-name">{_safe(ch['channel_name'])}</div>
                    <div class="tag-row" style="margin-top:8px; margin-bottom:0;">
                        <span class="cat-tag">🤖 {_safe(ai_cat)}</span>
                        {rel_html}
                        {tag_html}
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
            评分明细 · 垂类{ch['scores']['relevance']} ＋ 数据{ch['scores']['data_health']} ＋
            活跃{ch['scores']['frequency']} ＋ 商业{ch['scores']['commercial']}
        </div>
        {thumb_html}
    </div>
    """)

    # 操作按钮
    col_a1, col_a2, col_a3 = st.columns([1, 1, 1.3])
    with col_a1:
        if st.button("✅ 加入网红库", key=f"{key_prefix}add_{rank}", use_container_width=True):
            db = get_db()
            if db:
                if db.add_influencer(ch, st.session_state.user_name):
                    st.success(f"已加入网红库：「{ch['channel_name']}」标记为「新发现」")
                    _count_records.clear()
                    _get_paginated_records.clear()
                    _get_dedup_records.clear()
                else:
                    st.error(f"添加失败：{db.last_error or '未知错误，请检查数据库连接'}")
            else:
                # 本地模式
                ch["status"] = "新发现"
                ch["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                ch["discovered_by"] = st.session_state.user_name
                st.session_state.local_db.append(ch)
                _get_dedup_records.clear()
                st.success(f"已加入网红库：「{ch['channel_name']}」标记为「新发现」（本地模式）")
    with col_a2:
        if st.button("跳过", key=f"{key_prefix}skip_{rank}", use_container_width=True):
            st.session_state.search_results.remove(ch)
            st.rerun()
    with col_a3:
        if st.button("📧 生成BD邮件", key=f"{key_prefix}genmail_{rank}", use_container_width=True):
            bd_email_dialog(ch)
    st.markdown("")


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

    # ---------- 名单管理：删掉不用/写错的名字 ----------
    if db_for_members and members:
        with st.expander("🗑️ 删除名单里的名字"):
            st.caption("只把名字从下拉框移除；她挖到的网红仍留在库里。想把数据转到新名字下，用下面的「改名字」。")
            removable = [m for m in members if m != st.session_state.user_name]
            if removable:
                del_names = st.multiselect("选要删的名字（可多选）", removable, key="del_members")
                if st.button("🗑️ 删除选中的名字", key="del_members_btn", use_container_width=True):
                    if del_names:
                        if db_for_members.remove_members(del_names):
                            st.success(f"已删除：{' / '.join(del_names)}")
                            st.rerun()
                        else:
                            st.error("删除失败，请稍后再试")
                    else:
                        st.warning("先勾选要删的名字")
            else:
                st.caption("没有其他名字可删（自己正在用的名字不能删）")

        with st.expander("✏️ 改名字"):
            st.caption("改名后，旧名下挖到的网红和个人设置会一起搬到新名字下")
            ren_old = st.selectbox("改谁的名字", members, key="ren_old")
            ren_new = st.text_input("新名字", key="ren_new", placeholder="输入新名字")
            if st.button("✏️ 确认改名", key="ren_btn", use_container_width=True):
                ok, err = db_for_members.rename_member(ren_old, ren_new)
                if ok:
                    new_stripped = ren_new.strip()
                    if st.session_state.user_name == ren_old.strip():
                        st.session_state.user_name = new_stripped
                        st.query_params["u"] = new_stripped
                    for k in ("ren_old", "ren_new", "who_select"):
                        if k in st.session_state:
                            del st.session_state[k]
                    st.success(f"已改成「{new_stripped}」，旧名下的网红和设置也搬好了")
                    st.rerun()
                else:
                    st.error(err)

    if st.session_state.user_name and chosen == st.session_state.user_name:
        pass  # 名字已生效（下拉框会显示选中状态），不再额外弹问候框，保持侧边栏干净

    # ---------- BD邮件身份：署名 + 卡考Talk ID（生成韩语BD邮件时用） ----------
    st.markdown("")
    st.markdown("#### 📧 BD邮件身份")
    st.caption("生成韩语 BD 邮件时用，每人各填各的，互不影响")

    _cfg = st.session_state.config
    _ukey = st.session_state.user_name or "guest"

    sb_sender = st.text_input(
        "邮件署名（韩文/英文名）",
        value=_cfg.get("sender_name", ""),
        key=f"sb_sender_{_ukey}",
        placeholder="例如：만의 或 Ivy",
        help="BD 邮件落款用这个名字（韩国博主看），不显示你的内部中文名。没填则回退到内部名。",
    )
    if sb_sender != _cfg.get("sender_name", ""):
        st.session_state.config["sender_name"] = sb_sender

    sb_kkt = st.text_input(
        "카카오톡 ID",
        value=_cfg.get("kkt_id", ""),
        key=f"sb_kkt_{_ukey}",
        placeholder="例如：ivy_aliexpress",
        help="BD 邮件末尾附上这个 ID，方便博主加你。",
    )
    if sb_kkt != _cfg.get("kkt_id", ""):
        st.session_state.config["kkt_id"] = sb_kkt

    if st.button("💾 保存我的BD身份", key="save_bd_id", use_container_width=True):
        st.session_state.config["sender_name"] = sb_sender.strip()
        st.session_state.config["kkt_id"] = sb_kkt.strip()
        _db_id = get_db()
        if _db_id and st.session_state.user_name:
            if _db_id.save_user_settings(st.session_state.user_name, st.session_state.config):
                st.success("✅ BD身份已保存，下次打开自动加载")
            else:
                st.warning("⚠️ 本次生效，但未能存入数据库（刷新后恢复）")
        elif not st.session_state.user_name:
            st.warning("⚠️ 请先在上面选好你的名字，才能保存")
        else:
            st.success("✅ 已保存（本地模式，刷新后恢复）")

    # ---------- YouTube API Key：可记住在自己浏览器，刷新不用重填 ----------
    st.markdown("")
    st.markdown("#### 🔑 YouTube API Key")

    # 浏览器记忆组件：Key 只存在你自己电脑的浏览器里，不上传服务器/数据库
    _ls = LocalStorage(key="yt_key_store")
    _stored_key = _ls.getItem("yt_api_key")
    # 打开页面时：浏览器里记住过 Key 且当前还没填，就自动回填
    if _stored_key and not st.session_state.api_key:
        st.session_state.api_key = _stored_key
        st.session_state.quota = QuotaTracker()

    api_key_input = st.text_input(
        "API Key", value=st.session_state.api_key, type="password",
        label_visibility="collapsed",
        help="Google Cloud Console 获取，免费10,000 units/天。点「记住」后只存在你自己浏览器，刷新不用重填。",
        placeholder="粘贴你的 YouTube API Key",
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
        st.session_state.quota = QuotaTracker()

    _c_remember, _c_forget = st.columns([1, 1])
    with _c_remember:
        if st.button("记住", key="remember_key", use_container_width=True,
                     help="把 Key 存进你自己电脑的浏览器，刷新不用重填。不上传服务器。"):
            if api_key_input.strip():
                _ls.setItem("yt_api_key", api_key_input.strip(), key="do_remember")
                st.success("✅ 已记住，以后刷新自动填好")
            else:
                st.warning("先粘贴 Key 再点记住哦")
    with _c_forget:
        if st.button("忘掉", key="forget_key", use_container_width=True,
                     help="把这个浏览器里记住的 Key 清掉"):
            _ls.deleteItem("yt_api_key", key="do_forget")
            st.session_state.api_key = ""
            st.session_state.quota = QuotaTracker()
            st.warning("已忘掉，下次要重新粘贴")
    st.caption("🔒 Key 只存在你自己浏览器，不上传服务器，全队互不影响")

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


# ---------- 加载个人筛选设置（切换名字时从数据库读取，互不干扰） ----------
if st.session_state.user_name:
    _loaded_for = st.session_state.get("_settings_loaded_for", "")
    if _loaded_for != st.session_state.user_name:
        _db_settings = get_db()
        if _db_settings:
            _personal = _db_settings.get_user_settings(st.session_state.user_name)
            if _personal:
                # 用个人设置覆盖默认值（支持部分字段，缺的用默认）
                _merged = DEFAULT_CONFIG.copy()
                _merged.update({k: v for k, v in _personal.items() if k in _merged})
                if "weights" in _personal:
                    _merged["weights"] = {**DEFAULT_CONFIG["weights"], **_personal["weights"]}
                if "dedup_rules" in _personal:
                    _merged["dedup_rules"] = {**DEFAULT_CONFIG["dedup_rules"], **_personal["dedup_rules"]}
                # BD邮件身份（署名 + 卡考Talk ID）也从个人档案恢复
                _merged["sender_name"] = _personal.get("sender_name", "")
                _merged["kkt_id"] = _personal.get("kkt_id", "")
                # 网红库显示模式（卡片/列表）也从个人档案恢复，默认列表
                _merged["view_mode"] = _personal.get("view_mode", "list")
                st.session_state.config = _merged
        st.session_state._settings_loaded_for = st.session_state.user_name
        # 加载完刷新一次，让侧边栏"BD邮件身份"立刻显示当前身份的值
        st.rerun()


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
        # ---------- AI 生成关键词：给个垂类，AI 现写韩语搜索词 ----------
        st.markdown("✨ **AI 生成关键词** · 告诉它想挖的垂类，自动产出韩语搜索词（点任意一个直接搜索）")
        _gc1, _gc2 = st.columns([4, 1])
        with _gc1:
            _ai_vertical = st.text_input(
                "垂类", key="ai_vertical_input", label_visibility="collapsed",
                placeholder="输入垂类，例：家居收纳 / 美甲 / 露营装备 / 文具",
            )
        with _gc2:
            _gen_btn = st.button("✨ 生成关键词", use_container_width=True)
        if _gen_btn:
            if not _ai_vertical.strip():
                st.warning("先输入一个想挖的垂类，比如：家居收纳")
            else:
                with st.spinner(f"🤖 AI 正在围绕「{_ai_vertical.strip()}」想搜索词…"):
                    _gen_kws, _gen_err = generate_keywords(_ai_vertical)
                if _gen_err:
                    st.error(f"😅 生成失败：{_gen_err}（下面预置关键词组照常可用）")
                else:
                    st.session_state.ai_kws = _gen_kws
                    st.session_state.ai_kws_for = _ai_vertical.strip()
        if st.session_state.get("ai_kws"):
            st.caption(f"🤖 根据「{st.session_state.get('ai_kws_for', '')}」生成 · 点任意一个直接搜索，⚡批量会挖这一组")
            for row_start in range(0, len(st.session_state.ai_kws), 3):
                chip_cols = st.columns(3)
                for j, kw in enumerate(st.session_state.ai_kws[row_start:row_start + 3]):
                    with chip_cols[j]:
                        if st.button(kw, key=f"aikw_{row_start + j}", use_container_width=True):
                            st.session_state.pending_kw = kw

        # ---------- 预置关键词组（折叠，保持页面简洁） ----------
        # 第二期起取消了"先选垂类"：点任意关键词直接搜，挖到的博主由 AI 自动判定垂类和相关度
        if "kw_group" not in st.session_state or st.session_state.kw_group not in KW_LIB:
            st.session_state.kw_group = next(iter(KW_LIB))
        with st.expander("📚 现成关键词组（6 组实战验证过的）· 点开选用", expanded=False):
            _group_names = list(KW_LIB.keys())
            with st.container():
                st.markdown('<div class="kwgroup-marker"></div>', unsafe_allow_html=True)
                _gcols = st.columns(len(_group_names))
                for _gi, _g in enumerate(_group_names):
                    with _gcols[_gi]:
                        if st.button(_g, key=f"kwgroup_{_g}", use_container_width=True,
                                     type="primary" if _g == st.session_state.kw_group else "secondary"):
                            st.session_state.kw_group = _g
            _sel_kws = KW_LIB[st.session_state.kw_group]
            st.caption(f"🗂 {st.session_state.kw_group} · 点任意一个直接搜索")
            for row_start in range(0, len(_sel_kws), 3):
                chip_cols = st.columns(3)
                for j, kw in enumerate(_sel_kws[row_start:row_start + 3]):
                    with chip_cols[j]:
                        if st.button(kw, key=f"kwchip_{st.session_state.kw_group}_{row_start + j}",
                                     use_container_width=True):
                            st.session_state.pending_kw = kw
        st.markdown("")

        # ---------- 搜索模式：按时间（小博主多）/ 按相关性（更对口） ----------
        if "search_order" not in st.session_state:
            st.session_state.search_order = "🕐 按时间（新视频优先，小博主更多）"
        order_choice = st.radio(
            "搜索模式",
            ["🕐 按时间（新视频优先，小博主更多）", "🎯 按相关性（内容更对口）"],
            index=0 if st.session_state.search_order.startswith("🕐") else 1,
            horizontal=True,
            help=f"按时间：搜最近 {st.session_state.config.get('window_days', 60)} 天的新视频，活跃小博主更容易被挖到；按相关性：搜最匹配的视频，内容更精准但大频道偏多。两种配额消耗相同。",
        )
        st.session_state.search_order = order_choice
        search_order_api = "date" if order_choice.startswith("🕐") else "relevance"

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
                                  help="有AI生成的关键词时，把生成的一组全挖一遍；没有则挖全部预置关键词（配额消耗大，建议配额充足时用）")

        st.markdown("")

        # 获取库中记录用于去重（只拉去重必需的轻量字段，避免全表传输）
        db = get_db()
        if db:
            db_records = _get_dedup_records(
                st.session_state.supabase_url, st.session_state.supabase_key
            )
        else:
            db_records = st.session_state.local_db

        # 搜索触发：优先用点击的推荐词，其次用自定义输入
        search_keyword = None
        if st.session_state.get("pending_kw"):
            search_keyword = st.session_state.pop("pending_kw")
        elif search_btn and keyword_input.strip():
            search_keyword = keyword_input.strip()

        # 单个搜索
        if search_keyword:
            st.session_state.quota.last_error = ""
            _status_box = st.empty()
            _status_box.info(f"🔍 正在搜索「{search_keyword}」…")
            results = search_and_verify(
                keyword=search_keyword,
                api_key=st.session_state.api_key,
                quota=st.session_state.quota,
                config=st.session_state.config,
                db_records=db_records,
                order=search_order_api,
                status_cb=lambda m: _status_box.info(f"🔍 {m}"),
            )
            # 第二期：挖完交给 AI 定垂类、打相关度、出标签，再按新权重重排
            _ai_note = _enrich_with_ai(results, _status_box) if results else ""
            st.session_state.search_results = results
            st.session_state.search_log.append({
                "keyword": search_keyword,
                "time": datetime.now().strftime("%H:%M"), "results": len(results),
            })
            st.session_state.search_log = st.session_state.search_log[-10:]
            if results:
                _status_box.success(f"✅ 找到 {len(results)} 个符合条件的活跃博主")
                if _ai_note:
                    st.caption(f"🤖 {_ai_note}")
            else:
                _err = st.session_state.quota.last_error
                if _err:
                    _status_box.error(f"❌ {_err}")
                else:
                    _status_box.warning("未找到符合条件的博主（可能都已不活跃或已在库中）")

        # 批量搜索
        if batch_btn:
            if st.session_state.get("ai_kws"):
                keywords = list(st.session_state.ai_kws)
                _batch_desc = f"AI生成的 {len(keywords)} 个关键词（「{st.session_state.get('ai_kws_for', '')}」）"
            else:
                keywords = [kw for kws in KW_LIB.values() for kw in kws]
                _batch_desc = f"全部预置关键词 {len(keywords)} 个"
            all_results = []
            errors_seen = []
            st.session_state.quota.last_error = ""
            # 每个关键词的成本 = 搜索成本（翻页/Shorts/双排序）+ 验证缓冲（约50频道×3）
            per_kw_cost = estimate_search_cost(st.session_state.config) + 150
            progress = st.progress(0)
            status_text = st.empty()
            status_text.info(f"⚡ 开始批量挖掘：{_batch_desc}")

            for i, kw in enumerate(keywords):
                if not st.session_state.quota.can_afford(per_kw_cost):
                    status_text.warning(f"⚠️ 配额不足，已完成 {i}/{len(keywords)}，剩余关键词先跳过")
                    break
                status_text.info(f"🔍 搜索中 ({i + 1}/{len(keywords)}): {kw} · 已找到 {len(all_results)} 人")
                results = search_and_verify(
                    keyword=kw,
                    api_key=st.session_state.api_key,
                    quota=st.session_state.quota,
                    config=st.session_state.config,
                    db_records=db_records,
                    order=search_order_api,
                    status_cb=lambda m, _i=i, _kw=kw: status_text.info(
                        f"({_i + 1}/{len(keywords)} · {_kw}) {m}"),
                )
                if st.session_state.quota.last_error:
                    if st.session_state.quota.last_error not in errors_seen:
                        errors_seen.append(st.session_state.quota.last_error)
                    st.session_state.quota.last_error = ""
                all_results.extend(results)
                progress.progress((i + 1) / len(keywords))

            # 去重
            seen = set()
            unique = []
            for r in all_results:
                if r["channel_id"] not in seen:
                    seen.add(r["channel_id"])
                    unique.append(r)
            # 第二期：合并后统一交给 AI 分析，再按新权重重排
            _ai_note_batch = _enrich_with_ai(unique, status_text) if unique else ""
            st.session_state.search_results = unique
            status_text.success(f"✅ 批量完成，共 {len(unique)} 个活跃博主")
            if _ai_note_batch:
                st.caption(f"🤖 {_ai_note_batch}")
            if errors_seen:
                st.warning("⚠️ 部分关键词遇到问题：" + "；".join(errors_seen[:2]) +
                           "（其余关键词已正常完成）")

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

            ai_gate = int(st.session_state.config.get("ai_min_relevance", 40))
            filtered, pending = split_main_pending(results, min_score_filter, ai_gate)
            sort_keys = {
                "综合评分": lambda x: x["scores"]["total"],
                "订阅量": lambda x: x["subscribers"],
                "近30天均播": lambda x: x["avg_views_30d"],
                "最近更新": lambda x: x["last_upload"],
            }
            filtered.sort(key=sort_keys[sort_by], reverse=True)

            if pending:
                st.markdown(f"共 {len(filtered)} 个博主 · 另有 {len(pending)} 个（评分未过线或AI相关度偏低），收在下方待定区")
            else:
                st.markdown(f"共 {len(filtered)} 个博主")
            st.markdown("")

            # 频道卡片（主列表）
            for idx, ch in enumerate(filtered):
                _render_result_card(ch, idx + 1, "m")

            # 待定区：未达最低评分、或 AI 相关度偏低的博主，默认折叠，留给人工翻看
            if pending:
                with st.expander(f"🕵️ 待定区 · {len(pending)} 个待人工翻看（评分未过线或AI相关度<{ai_gate}，不直接丢弃）"):
                    st.caption("这些博主没过线上的标准，但可能值得看一眼——看中了直接点「加入网红库」。")
                    pending.sort(key=lambda x: x["scores"]["total"], reverse=True)
                    for pi, ch in enumerate(pending):
                        _render_result_card(ch, pi + 1, "p")

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
                    st.success(f"已添加 {added} 个博主，均标记为「新发现」")
            with col_ba2:
                if filtered:
                    export_data = []
                    for ch in filtered:
                        export_data.append({
                            "频道名": ch["channel_name"], "主页链接": ch["channel_url"],
                            "垂类(AI判定)": ch.get("category", ""),
                            "AI相关度": ch.get("ai_relevance", "") if ch.get("ai_analyzed") else "",
                            "AI标签": " / ".join(ch.get("ai_tags", [])),
                            "订阅量": ch["subscribers"],
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
                st.caption(f"{log['time']} · {log['keyword']} · {log['results']}个结果")


# ============================================================
# Tab 2: 网红库
# ============================================================

with tab_database:
    st.markdown("### 网红库")
    st.markdown("")

    # 状态变更的成功提示统一在这里显示（操作时先写入 session，rerun 后弹出，避免提示消失）
    _chg_msg = st.session_state.pop("_status_change_msg", None)
    if _chg_msg:
        st.success(_chg_msg)

    db = get_db()
    user_name = st.session_state.user_name or ""

    # 初始化筛选/分页状态
    _db_defaults = {
        "filter_status": "全部",
        "filter_cat": [],
        "filter_discoverer": "全部",
        "db_sort": "添加时间",
        "db_page": 1,
        "db_page_size": 30,
    }
    for k, v in _db_defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # view_mode 优先用个人配置，默认列表模式
    if "view_mode" not in st.session_state:
        st.session_state.view_mode = st.session_state.config.get("view_mode", "list")

    def _reset_db_page():
        st.session_state.db_page = 1

    def _save_note(cid: str):
        """备注框 on_change 回调：只在失焦/回车时保存"""
        val = st.session_state.get(f"nt_{cid}", "")
        _db = get_db()
        if _db:
            _db.update_notes(cid, val)
        else:
            for lr in st.session_state.local_db:
                if lr.get("channel_id") == cid:
                    lr["notes"] = val
        _count_records.clear()
        _get_paginated_records.clear()
        _get_dedup_records.clear()

    # 挖掘人选项（用成员表，避免全量扫 influencers）
    if db:
        discoverer_options = ["全部", "只看我的"] + db.get_members()
    else:
        discoverer_options = ["全部", "只看我的"] + sorted({
            r.get("discovered_by", "") for r in st.session_state.local_db if r.get("discovered_by")
        })

    # 统计（按状态计数，不走全量拉取）
    if db:
        total_count = _count_records(
            st.session_state.supabase_url, st.session_state.supabase_key,
            "全部", tuple(), "全部", "",
        )
        status_counts = {}
        for s in ["新发现", "已发邮件"]:
            status_counts[s] = _count_records(
                st.session_state.supabase_url, st.session_state.supabase_key,
                s, tuple(), "全部", "",
            )
    else:
        all_local = st.session_state.local_db
        total_count = len(all_local)
        status_counts = {s: 0 for s in ["新发现", "已发邮件"]}
        for r in all_local:
            s = r.get("status", "")
            if s in status_counts:
                status_counts[s] += 1

    if total_count == 0:
        st.info("网红库为空。搜索后点击「加入网红库」，或使用「📥 批量导入」添加已有合作博主。")
    else:
        cols = st.columns(3)
        labels = ["总数", "新发现", "已发邮件"]
        keys = ["total", "新发现", "已发邮件"]
        values = [total_count] + [status_counts[k] for k in keys[1:]]
        for col, label, val in zip(cols, labels, values):
            with col:
                st.metric(label, val)

        st.markdown("")

        # 筛选
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            st.selectbox(
                "状态", ["全部", "新发现", "已发邮件"],
                key="filter_status", on_change=_reset_db_page,
            )
        with col_f2:
            st.multiselect(
                "垂类", options=AI_CATEGORY_TABLE + list(KW_LIB.keys()),
                default=[], placeholder="全部垂类",
                help="新挖掘的博主垂类由 AI 判定（韩文品类名），老博主是原来的中文垂类",
                key="filter_cat", on_change=_reset_db_page,
            )
        with col_f3:
            st.selectbox(
                "👤 挖掘人", discoverer_options,
                help="「只看我的」= 只显示你挖的博主；也可以选同事名字看 TA 挖了谁",
                key="filter_discoverer", on_change=_reset_db_page,
            )
        with col_f4:
            st.selectbox(
                "排序", ["添加时间", "评分", "订阅量", "最近更新"],
                key="db_sort", on_change=_reset_db_page,
            )

        # 当前筛选条件
        status = st.session_state.filter_status
        category = tuple(st.session_state.filter_cat) if st.session_state.filter_cat else tuple()
        discoverer = st.session_state.filter_discoverer
        sort_by = st.session_state.db_sort
        page_size = st.session_state.db_page_size
        page = st.session_state.db_page

        # 获取分页记录
        if db:
            filtered_count = _count_records(
                st.session_state.supabase_url, st.session_state.supabase_key,
                status, category, discoverer, user_name,
            )
            total_pages = max(1, (filtered_count + page_size - 1) // page_size)
            if page > total_pages:
                st.session_state.db_page = total_pages
            page = max(1, min(page, total_pages))
            records_page = _get_paginated_records(
                st.session_state.supabase_url, st.session_state.supabase_key,
                page, page_size, status, category, discoverer, user_name, sort_by, True,
            )
        else:
            sort_map = {
                "添加时间": lambda x: x.get("added_date", ""),
                "评分": lambda x: x.get("score_total", 0) if isinstance(x.get("score_total"), (int, float)) else 0,
                "订阅量": lambda x: x.get("subscribers", 0),
                "最近更新": lambda x: x.get("last_upload", ""),
            }
            local = st.session_state.local_db[:]
            if status != "全部":
                local = [r for r in local if r.get("status") == status]
            if st.session_state.filter_cat:
                local = [r for r in local if r.get("category") in st.session_state.filter_cat]
            if discoverer == "只看我的":
                local = [r for r in local if r.get("discovered_by") == user_name]
            elif discoverer != "全部":
                local = [r for r in local if r.get("discovered_by") == discoverer]
            local.sort(key=sort_map[sort_by], reverse=True)
            filtered_count = len(local)
            total_pages = max(1, (filtered_count + page_size - 1) // page_size)
            if page > total_pages:
                st.session_state.db_page = total_pages
            page = max(1, min(page, total_pages))
            start = (page - 1) * page_size
            records_page = local[start:start + page_size]

        # 显示模式切换
        _vm_saved = st.session_state.view_mode
        col_vm, col_cnt = st.columns([4, 2])
        with col_vm:
            view_mode_label = st.radio(
                "显示模式", ["🗂 卡片模式", "📋 列表模式"],
                horizontal=True,
                index=0 if _vm_saved == "card" else 1,
                key="db_view_radio",
                label_visibility="collapsed",
                help="卡片模式适合逐个看详情；列表模式适合快速扫全库、批量改状态",
            )
        with col_cnt:
            st.markdown(f"显示 {filtered_count} / {total_count} 条 · 第 {page} / {total_pages} 页")
        view_mode = "card" if view_mode_label == "🗂 卡片模式" else "list"
        if view_mode != _vm_saved:
            st.session_state.view_mode = view_mode
            st.session_state.config["view_mode"] = view_mode
            _db_vm = get_db()
            if _db_vm and user_name:
                _db_vm.save_user_settings(user_name, st.session_state.config)
        st.markdown("")

        # 分页控件
        p_col1, p_col2, p_col3, p_col4 = st.columns([1, 1, 2, 1])
        with p_col1:
            def _prev_page():
                st.session_state.db_page = max(1, st.session_state.db_page - 1)
            st.button("◀ 上一页", disabled=(page <= 1), on_click=_prev_page, key="db_prev_page", use_container_width=True)
        with p_col2:
            def _next_page():
                st.session_state.db_page = min(total_pages, st.session_state.db_page + 1)
            st.button("下一页 ▶", disabled=(page >= total_pages), on_click=_next_page, key="db_next_page", use_container_width=True)
        with p_col3:
            st.markdown(
                f"<div style='text-align:center; padding-top:8px; font-weight:700;'>第 {page} / {total_pages} 页</div>",
                unsafe_allow_html=True,
            )
        with p_col4:
            st.selectbox(
                "每页条数", [20, 30, 50],
                key="db_page_size", on_change=_reset_db_page, label_visibility="collapsed",
            )

        # ---------- 批量操作工具条 ----------
        _init_batch_state()
        _batch_sel = st.session_state.batch_selected

        col_sa, col_info, col_sp = st.columns([1.2, 2, 3])
        with col_sa:
            if st.button("☑ 全选当前页", key="batch_select_all", use_container_width=True):
                for r in records_page:
                    cid = r.get("channel_id", "")
                    if cid:
                        st.session_state.batch_selected.add(cid)
                        st.session_state[f"bchk_{cid}"] = True
                st.rerun()
        with col_info:
            if _batch_sel:
                st.markdown(f"已选 **{len(_batch_sel)}** 人")
                if st.button("❎ 取消选择", key="batch_clear"):
                    _clear_batch_selection()
                    st.rerun()

        # 选中后显示批量操作按钮
        if _batch_sel:
            st.markdown("")
            bc1, bc2, bc3, bc4, bc5 = st.columns([2, 1.4, 1.4, 1.4, 1.4])
            with bc1:
                batch_new_status = st.selectbox(
                    "目标状态", ["已发邮件", "新发现"],
                    key="batch_status_select", label_visibility="collapsed",
                )
            with bc2:
                do_batch_status = st.button("✏️ 批量改状态", key="batch_do_status", use_container_width=True)
            with bc3:
                do_batch_refresh = st.button("🔄 刷新选中", key="batch_do_refresh", use_container_width=True)
            with bc4:
                do_batch_delete = st.button("🗑 批量删除", key="batch_do_delete", use_container_width=True, type="primary")
            with bc5:
                do_batch_export = st.button("📥 导出选中", key="batch_do_export", use_container_width=True)

            # 批量改状态（已拒绝/已淘汰必须填原因并二次确认，其余状态立即生效）
            def _batch_apply(new_status: str, reason: str = ""):
                _db_b = get_db()
                cids = list(_batch_sel)
                reason = reason.strip()
                rec_map_b = {}
                if reason:
                    all_recs_b = get_all_records() if _db_b else st.session_state.local_db
                    rec_map_b = {r.get("channel_id", ""): r for r in all_recs_b}
                if _db_b:
                    n = _db_b.batch_update_status(cids, new_status)
                    if reason:
                        for cid in cids:
                            old = (rec_map_b.get(cid, {}).get("notes", "") or "")
                            _db_b.update_notes(cid, _append_reason(old, new_status, reason))
                else:
                    for lr in st.session_state.local_db:
                        if lr.get("channel_id") in _batch_sel:
                            _apply_status_date(lr, new_status)
                            if reason:
                                lr["notes"] = _append_reason(lr.get("notes", "") or "", new_status, reason)
                    n = len(cids)
                _count_records.clear()
                _get_paginated_records.clear()
                _get_dedup_records.clear()
                _clear_batch_selection()
                st.session_state.pop("_batch_reason_needed", None)
                suffix = "，原因已记入备注" if reason else ""
                st.session_state["_status_change_msg"] = f"✅ 已将 {n} 人状态改为「{new_status}」{suffix}"
                st.rerun()

            if do_batch_status:
                if batch_new_status in ("已拒绝", "已淘汰"):
                    st.session_state["_batch_reason_needed"] = True
                else:
                    _batch_apply(batch_new_status)

            if st.session_state.get("_batch_reason_needed"):
                if batch_new_status not in ("已拒绝", "已淘汰"):
                    # 目标状态换成了不需要原因的，自动退出填原因状态
                    st.session_state.pop("_batch_reason_needed", None)
                else:
                    st.warning(f"✍️ 将 {len(_batch_sel)} 人标为「{batch_new_status}」需要填写原因（会记入备注，方便以后复盘）")
                    _batch_reason = st.text_input(
                        "原因（必填）", key="batch_reason_input",
                        placeholder="例：内容不垂直 / 要价太高 / 长期不回复…",
                    )
                    brc1, brc2, _ = st.columns([1, 1, 4])
                    with brc1:
                        if st.button("✅ 确认修改", key="batch_reason_ok", use_container_width=True, type="primary"):
                            if _batch_reason.strip():
                                _batch_apply(batch_new_status, _batch_reason)
                            else:
                                st.session_state["_batch_reason_err"] = True
                    with brc2:
                        if st.button("取消", key="batch_reason_cancel", use_container_width=True):
                            st.session_state.pop("_batch_reason_needed", None)
                            st.rerun()
                    if st.session_state.pop("_batch_reason_err", False):
                        st.warning("⚠️ 请先填写原因再确认")

            # 批量刷新数据（只能刷新自己挖掘的）
            if do_batch_refresh:
                if not st.session_state.get("api_key"):
                    st.error("需要 API Key，请先在左侧填入后再刷新")
                else:
                    user_name = st.session_state.get("user_name", "")
                    all_recs = get_all_records() if db else st.session_state.local_db
                    sel_map = {r.get("channel_id", ""): r for r in all_recs if r.get("channel_id") in _batch_sel}
                    own_cids = []
                    skipped_names = []
                    for cid in _batch_sel:
                        rec = sel_map.get(cid, {})
                        if rec.get("discovered_by") == user_name:
                            own_cids.append(cid)
                        else:
                            skipped_names.append(rec.get("channel_name", cid))

                    refreshed = 0
                    failed_names = []
                    if own_cids:
                        progress = st.progress(0, text="准备刷新...")
                        for i, cid in enumerate(own_cids):
                            rec = sel_map[cid]
                            cn = rec.get("channel_name", cid)
                            progress.progress((i + 1) / len(own_cids), text=f"刷新 {cn} ...")
                            ok, msg = _refresh_one_channel(
                                cid, rec.get("channel_name", ""), rec.get("category", ""), owner=user_name
                            )
                            if ok and "✅" in msg:
                                refreshed += 1
                            else:
                                failed_names.append(f"{rec.get('channel_name', cid)}")
                        progress.empty()

                    _clear_batch_selection()
                    summary = f"✅ 成功刷新 {refreshed} 人"
                    if skipped_names:
                        summary += f"，跳过 {len(skipped_names)} 人（非自己挖掘）"
                    if failed_names:
                        summary += f"，失败 {len(failed_names)} 人"
                    st.success(summary)
                    if failed_names:
                        st.error("失败：" + "、".join(failed_names[:5]))
                    st.rerun()

            # 批量删除（二次确认）
            if do_batch_delete:
                st.session_state["_batch_delete_confirm"] = True
            if st.session_state.get("_batch_delete_confirm"):
                st.warning(f"⚠️ 确定要删除选中的 {len(_batch_sel)} 人吗？此操作不可恢复！")
                dc1, dc2, _ = st.columns([1, 1, 4])
                with dc1:
                    if st.button("确定删除", key="batch_confirm_del", type="primary"):
                        _db_b = get_db()
                        cids = list(_batch_sel)
                        if _db_b:
                            n = _db_b.batch_remove(cids)
                        else:
                            st.session_state.local_db = [r for r in st.session_state.local_db if r.get("channel_id") not in _batch_sel]
                            n = len(cids)
                        _count_records.clear()
                        _get_paginated_records.clear()
                        _get_dedup_records.clear()
                        _clear_batch_selection()
                        st.session_state.pop("_batch_delete_confirm", None)
                        st.success(f"🗑 已删除 {n} 人")
                        st.rerun()
                with dc2:
                    if st.button("取消", key="batch_cancel_del"):
                        st.session_state.pop("_batch_delete_confirm", None)
                        st.rerun()

            # 导出选中
            if do_batch_export:
                all_recs = get_all_records() if db else st.session_state.local_db
                sel_rows = []
                for r in all_recs:
                    if r.get("channel_id") in _batch_sel:
                        sel_rows.append({
                            "频道名": r.get("channel_name", ""), "链接": r.get("channel_url", ""),
                            "垂类": r.get("category", ""), "订阅量": r.get("subscribers", 0),
                            "评分": r.get("score_total", ""), "状态": r.get("status", ""),
                            "邮箱": r.get("emails", ""), "挖掘人": r.get("discovered_by", ""),
                            "备注": r.get("notes", ""), "添加日期": r.get("added_date", ""),
                        })
                if sel_rows:
                    buf = BytesIO()
                    pd.DataFrame(sel_rows).to_excel(buf, index=False, engine="openpyxl")
                    st.download_button(
                        "⬇️ 点击下载选中网红 Excel", data=buf.getvalue(),
                        file_name=f"网红库_选中{len(sel_rows)}人_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="batch_download_btn",
                    )
                else:
                    st.info("选中的网红不在当前记录中（可能已被删除）")

            st.markdown("---")

        if view_mode == "card":
            # 卡片模式：三列紧凑小卡片（打标按键全部收进卡片内）
            num_cols = 3
            for row_start in range(0, len(records_page), num_cols):
                cols = st.columns(num_cols)
                for j in range(num_cols):
                    idx = row_start + j
                    if idx >= len(records_page):
                        break
                    rec = records_page[idx]
                    with cols[j]:
                        with st.container():
                            # 隐藏标记：让外层容器变成卡片（见CSS :has()规则）
                            st.markdown('<div class="kol-card-marker"></div>', unsafe_allow_html=True)

                            # 批量勾选框
                            _cid = rec.get("channel_id", "")
                            st.checkbox("选", key=f"bchk_{_cid}", on_change=_on_batch_check, args=(_cid,),
                                        help="勾选后可批量操作")

                            status = rec.get("status", "新发现")
                            status_class = {"新发现": "status-new",
                                           "已发邮件": "status-emailed"}.get(status, "status-new")

                            name = rec.get("channel_name", "未知")
                            url = rec.get("channel_url", "#")
                            subs = rec.get("subscribers", 0)
                            score = rec.get("score_total", "-")
                            cat = rec.get("category", "")
                            discoverer = rec.get("discovered_by", "")
                            email = rec.get("emails", "")
                            notes = rec.get("notes", "")

                            status_date_html = _status_date_html(status, rec.get("email_sent_date"), rec.get("introduced_date"))

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
                            {status_date_html}
                            <div class="kol-stats">📺 {subs:,} 订阅 · ⭐ 评分 {score}</div>
                            <div class="kol-sub">👤 挖掘人：{_safe(discoverer) if discoverer else '—'}</div>
                            <div class="kol-email">📧 <span class="email-chip">{_safe(email) if email else '未公开'}</span></div>
                            <hr class="kol-divider">
                            """)

                            # 状态下拉（只保留 新发现 / 已发邮件 两个状态）
                            _ST_OPTS = ["新发现", "已发邮件"]
                            if st.session_state.pop(f"revert_st_{idx}", False):
                                # 取消后还原下拉：必须把 key 设回当前状态（pop 不掉前端组件状态）
                                st.session_state[f"st_{idx}"] = status if status in _ST_OPTS else "新发现"
                            new_status = st.selectbox(
                                "状态", _ST_OPTS,
                                index=_ST_OPTS.index(status) if status in _ST_OPTS else 0,
                                key=f"st_{idx}", label_visibility="collapsed",
                            )
                            if new_status in ("已拒绝", "已淘汰") and new_status != status:
                                _reason = st.text_input(
                                    "原因（必填）", key=f"rsn_st_{idx}",
                                    placeholder="例：内容不垂直 / 要价太高…",
                                )
                                _c1, _c2, _ = st.columns([1, 1, 2])
                                with _c1:
                                    if st.button("确认", key=f"cfm_st_{idx}", use_container_width=True, type="primary"):
                                        if _reason.strip():
                                            _apply_status_change(rec, new_status, _reason)
                                            st.session_state["_status_change_msg"] = \
                                                f"✅ 「{name}」已改为 {new_status}，原因已记入备注"
                                            st.rerun()
                                        else:
                                            st.session_state[f"rsnerr_st_{idx}"] = True
                                with _c2:
                                    if st.button("取消", key=f"ccl_st_{idx}", use_container_width=True):
                                        st.session_state[f"revert_st_{idx}"] = True
                                        st.rerun()
                                if st.session_state.pop(f"rsnerr_st_{idx}", False):
                                    st.warning("⚠️ 请先填写原因再确认")
                            elif new_status != status:
                                _apply_status_change(rec, new_status)
                                st.session_state["_status_change_msg"] = f"✅ 「{name}」已改为 {new_status}"
                                st.rerun()

                            # 刷新 / 删除 / 备注
                            c_rc, c_rm, c_nt = st.columns([1, 1, 4])
                            with c_rc:
                                is_owner = discoverer == st.session_state.get("user_name", "")
                                if is_owner:
                                    do_refresh = st.button("🔄", key=f"rc_{idx}", help="刷新数据", type="primary")
                                else:
                                    st.button("🔄", key=f"rc_{idx}", help="只能刷新自己挖掘的网红", disabled=True)
                                    do_refresh = False
                            with c_rm:
                                do_remove = st.button("🗑", key=f"rm_{idx}", help="从库中移除", type="primary")
                            with c_nt:
                                st.text_input("备注", value=notes, key=f"nt_{_cid}",
                                              placeholder="例：已发邮件、回复快、要价高...",
                                              label_visibility="collapsed",
                                              on_change=_save_note, args=(_cid,))

                            # BD邮件（弹窗形式，正文一键复制）
                            if st.button("📧 生成BD邮件", key=f"genmail_db_{idx}", use_container_width=True):
                                bd_email_dialog(rec)

                            # 单条刷新处理
                            if do_refresh:
                                ok, msg = _refresh_one_channel(
                                    rec.get("channel_id", ""), name, rec.get("category", ""), owner=discoverer
                                )
                                if ok:
                                    st.success(msg)
                                else:
                                    st.error(msg)

                            # 删除处理
                            if do_remove:
                                _db = get_db()
                                cid = rec.get("channel_id", "")
                                if _db:
                                    _db.remove(cid)
                                else:
                                    st.session_state.local_db = [r for r in st.session_state.local_db if r.get("channel_id") != cid]
                                _count_records.clear()
                                _get_paginated_records.clear()
                                _get_dedup_records.clear()
                                st.rerun()
        else:
            # 列表模式：一行一个博主，字段对齐成表格，适合快速扫全库
            for idx, rec in enumerate(records_page):
                with st.container():
                    # 隐藏标记：让外层容器变成列表行（见CSS :has()规则）
                    st.markdown('<div class="kol-row-marker"></div>', unsafe_allow_html=True)

                    status = rec.get("status", "新发现")
                    name = rec.get("channel_name", "未知")
                    url = rec.get("channel_url", "#")
                    subs = rec.get("subscribers", 0)
                    score = rec.get("score_total", "-")
                    cat = rec.get("category", "")
                    discoverer = rec.get("discovered_by", "")
                    email = rec.get("emails", "")

                    # 一行八列：勾选 · 频道/邮箱 · 垂类 · 订阅 · 评分 · 状态 · 挖掘人 · 操作
                    _cid = rec.get("channel_id", "")
                    r0, r1, r2, r3, r4, r5, r6, r7 = st.columns([0.4, 2.4, 1, 0.9, 0.7, 1.2, 0.9, 1.9])
                    with r0:
                        st.checkbox("选", key=f"bchk_{_cid}", on_change=_on_batch_check, args=(_cid,),
                                    label_visibility="collapsed", help="勾选后可批量操作")
                    with r1:
                        _render_html(
                            f'<span class="row-name"><a href="{url}" target="_blank">{_safe(name)}</a></span><br>'
                            f'<span class="row-email">📧 {_safe(email) if email else "未公开"}</span>'
                        )
                    with r2:
                        _render_html(f'<span class="cat-tag row-cat">📂 {_safe(cat)}</span>')
                    with r3:
                        _render_html(f'<span class="row-num">📺 {subs:,}</span>')
                    with r4:
                        _render_html(f'<span class="row-num">⭐ {score}</span>')
                    with r5:
                        _ST_OPTS_L = ["新发现", "已发邮件"]
                        if st.session_state.pop(f"revert_lst_{idx}", False):
                            # 取消后还原下拉：必须把 key 设回当前状态（pop 不掉前端组件状态）
                            st.session_state[f"lst_{idx}"] = status if status in _ST_OPTS_L else "新发现"
                        new_status = st.selectbox(
                            "状态", _ST_OPTS_L,
                            index=_ST_OPTS_L.index(status) if status in _ST_OPTS_L else 0,
                            key=f"lst_{idx}", label_visibility="collapsed",
                        )
                        _status_date = _status_date_html(status, rec.get("email_sent_date"), rec.get("introduced_date"))
                        if _status_date:
                            _render_html(_status_date)
                    with r6:
                        _render_html(f'<span class="row-who">👤 {_safe(discoverer) if discoverer else "—"}</span>')
                    with r7:
                        a_rc, a_rm, a_ml = st.columns([1, 1, 2.4])
                        with a_rc:
                            is_owner = discoverer == st.session_state.get("user_name", "")
                            if is_owner:
                                do_refresh = st.button("🔄", key=f"lrc_{idx}", help="刷新数据", type="primary")
                            else:
                                st.button("🔄", key=f"lrc_{idx}", help="只能刷新自己挖掘的网红", disabled=True)
                                do_refresh = False
                        with a_rm:
                            do_remove = st.button("🗑", key=f"lrm_{idx}", help="从库中移除", type="primary")
                        with a_ml:
                            do_mail = st.button("📧 邮件", key=f"lmail_{idx}", use_container_width=True)
                        if do_mail:
                            bd_email_dialog(rec)

                    # 状态变更处理（整行展示，拒绝/淘汰必须填原因）
                    if new_status in ("已拒绝", "已淘汰") and new_status != status:
                        _rl = st.text_input(
                            f"将「{name}」标为 {new_status} 的原因（必填）", key=f"rsn_lst_{idx}",
                            placeholder="例：内容不垂直 / 要价太高 / 长期不回复…",
                        )
                        _lc1, _lc2, _ = st.columns([2, 2, 6])
                        with _lc1:
                            if st.button("确认修改", key=f"cfm_lst_{idx}", use_container_width=True, type="primary"):
                                if _rl.strip():
                                    _apply_status_change(rec, new_status, _rl)
                                    st.session_state["_status_change_msg"] = \
                                        f"✅ 「{name}」已改为 {new_status}，原因已记入备注"
                                    st.rerun()
                                else:
                                    st.session_state[f"rsnerr_lst_{idx}"] = True
                        with _lc2:
                            if st.button("取消", key=f"ccl_lst_{idx}", use_container_width=True):
                                st.session_state[f"revert_lst_{idx}"] = True
                                st.rerun()
                        if st.session_state.pop(f"rsnerr_lst_{idx}", False):
                            st.warning("⚠️ 请先填写原因再确认")
                    elif new_status != status:
                        _apply_status_change(rec, new_status)
                        st.session_state["_status_change_msg"] = f"✅ 「{name}」已改为 {new_status}"
                        st.rerun()

                    # 单条刷新处理
                    if do_refresh:
                        ok, msg = _refresh_one_channel(
                            rec.get("channel_id", ""), name, rec.get("category", ""), owner=discoverer
                        )
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)

                    # 删除处理
                    if do_remove:
                        _db = get_db()
                        cid = rec.get("channel_id", "")
                        if _db:
                            _db.remove(cid)
                        else:
                            st.session_state.local_db = [r for r in st.session_state.local_db if r.get("channel_id") != cid]
                        _count_records.clear()
                        _get_paginated_records.clear()
                        _get_dedup_records.clear()
                        st.rerun()

        # 导出
        st.markdown("---")
        all_records = get_all_records() if db else st.session_state.local_db
        if all_records:
            export_rows = []
            for r in all_records:
                export_rows.append({
                    "频道名": r.get("channel_name", ""), "链接": r.get("channel_url", ""),
                    "垂类": r.get("category", ""), "订阅量": r.get("subscribers", 0),
                    "评分": r.get("score_total", ""), "状态": r.get("status", ""),
                    "邮箱": r.get("emails", ""), "挖掘人": r.get("discovered_by", ""),
                    "备注": r.get("notes", ""), "添加日期": r.get("added_date", ""),
                    "发邮件日期": r.get("email_sent_date", ""),
                    "引入日期": r.get("introduced_date", ""),
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
    st.markdown("把 YouTube 链接或频道ID粘贴进来，导入后搜索时会自动跳过这些人。")
    st.markdown("")

    st.markdown("**每行一个：链接 + 空格 + 发邮件日期 + 空格 + 挖掘人（日期/挖掘人都可不写）：**")
    st.code("""https://www.youtube.com/@handle 2026-08-01 艾薇李   ← 链接 + 日期 + 挖掘人
https://www.youtube.com/@handle 2026-08-01        ← 不写挖掘人就算你的
https://www.youtube.com/@handle                   ← 不写日期就按今天
@handle 2026/7/15                                 ← 只粘贴handle也行，日期格式随意""", language=None)
    st.caption("链接什么格式都行：主页链接、/channel/UC…、老式 /user/ 和 /c/ 链接、视频/Shorts 链接（自动反查所属频道）、m./music. 开头、带参数（?si=…）都能识别。")
    st.markdown("")

    col_u1, col_u2 = st.columns([2, 1])
    with col_u1:
        up_file = st.file_uploader("方式一：上传 Excel（第1列链接，第2列日期，第3列挖掘人）", type=["xlsx", "xls"])
    with col_u2:
        _tpl_buf = BytesIO()
        pd.DataFrame([
            ["链接", "发邮件日期", "挖掘人"],
            ["https://www.youtube.com/@handle", "2026-08-01", "艾薇李"],
            ["https://www.youtube.com/@handle2", "", ""],
            ["@handle3", "2026/7/15", "小美"],
        ]).to_excel(_tpl_buf, index=False, engine="openpyxl")
        st.download_button(
            "📄 下载 Excel 模板", data=_tpl_buf.getvalue(),
            file_name="批量导入模板.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.caption("日期、挖掘人两列可空：日期空着按今天，挖掘人空着算你的")

    up_lines, up_dates, up_by = [], {}, {}
    if up_file is not None:
        try:
            up_lines, up_dates, up_by = parse_import_excel(up_file)
            if up_lines:
                st.success(f"Excel 读到 {len(up_lines)} 个链接，其中 {len(up_dates)} 个带日期、{len(up_by)} 个带挖掘人")
            else:
                st.warning("Excel 里没读到有效链接，看看是不是空表")
        except Exception:
            st.error("Excel 读取失败，请另存为 .xlsx 格式再传")

    import_text = st.text_area(
        "方式二：直接粘贴链接或ID", height=200,
        placeholder="每行一个频道链接或ID...",
    )

    col_i1, col_i2 = st.columns([1, 1])
    with col_i1:
        import_status = st.selectbox("导入后标记为", ["已发邮件", "新发现"])
    with col_i2:
        update_existing = st.checkbox(
            "库里已有的博主：顺便更新状态和日期",
            value=True,
            help="上次导入过的博主会按这次的标记和发邮件日期刷新；关掉则已有的不动",
        )

    st.caption("导入时会自动补全和挖掘一样的数据：粉丝数、近30天播放、播订比、邮箱、评分、AI垂类（比之前稍慢一点，属正常）")

    if st.button("📥 开始导入", use_container_width=True):
        # 数据来源：传了Excel就用Excel，否则用粘贴的文本
        if up_file is not None:
            lines, line_dates, line_by = up_lines, up_dates, up_by
        else:
            lines, line_dates, line_by = [], {}, {}
            for rl in [l.strip() for l in import_text.strip().split("\n") if l.strip()]:
                link, d, by = split_line_meta(rl)
                if link:
                    lines.append(link)
                    if d:
                        line_dates[link] = d
                    if by:
                        line_by[link] = by

        if not lines:
            st.warning("没有可导入的链接：看看Excel内容，或先粘贴链接")
        elif not st.session_state.api_key:
            st.error("需要 YouTube API Key 来查询频道信息")
        else:
            db = get_db()
            with st.spinner(f"正在导入 {len(lines)} 个频道，并自动补全数据（播放量/邮箱/评分/AI垂类，稍等～）"):
                if db:
                    result = db.import_existing(
                        lines, st.session_state.api_key,
                        st.session_state.quota, status=import_status,
                        imported_by=st.session_state.user_name,
                        line_dates=line_dates, update_existing=update_existing,
                        line_by=line_by,
                    )
                    parts = [f"新增 {result['success']}"]
                    if result.get("updated"):
                        parts.append(f"更新 {result['updated']}")
                    skipped_left = result["skipped"] - result.get("updated", 0)
                    if skipped_left > 0:
                        parts.append(f"跳过（已存在）{skipped_left}")
                    parts.append(f"失败 {result['failed']}")
                    msg = "✅ 导入完成：" + "，".join(parts)
                    if result["failed"] > 0:
                        msg += "（失败 = 链接格式无法识别，或频道已不存在）"
                    st.success(msg)
                    if result.get("failed_lines"):
                        st.warning(
                            "以下行导入失败，请检查后重试：\n\n"
                            + "\n\n".join(f"· {line}" for line in result["failed_lines"])
                        )
                else:
                    # 本地模式
                    resolved, bad_lines, raw_map = resolve_channel_ids(
                        lines, st.session_state.api_key, st.session_state.quota)
                    chs = get_channels(resolved, st.session_state.api_key, st.session_state.quota)
                    # 和 Supabase 模式一样走补全（播放/邮箱/评分/AI 垂类）
                    from database import enrich_import_channels
                    chs = enrich_import_channels(chs, st.session_state.api_key, st.session_state.quota)
                    today = datetime.now().strftime("%Y-%m-%d")
                    now = datetime.now().strftime("%Y-%m-%d %H:%M")
                    have = {c.get("channel_id"): c for c in st.session_state.local_db}
                    added, updated = 0, 0
                    for cid, info in chs.items():
                        sent = line_dates.get(raw_map.get(cid, "")) or today
                        if cid in have:
                            if update_existing:
                                rec = have[cid]
                                rec["status"] = import_status
                                rec["status_date"] = now
                                if import_status == "已发邮件":
                                    rec["email_sent_date"] = sent
                                updated += 1
                            continue
                        info["status"] = import_status
                        info["status_date"] = now
                        info["email_sent_date"] = sent if import_status == "已发邮件" else None
                        info["discovered_by"] = line_by.get(raw_map.get(cid, "")) or st.session_state.user_name
                        info["notes"] = "批量导入"
                        info["score_total"] = info.get("scores", {}).get("total", 0)
                        st.session_state.local_db.append(info)
                        added += 1
                    st.success(f"✅ 已导入 {added} 个频道，更新 {updated} 个（本地模式），无法识别 {len(bad_lines)} 行")
                    if bad_lines:
                        st.warning(
                            "以下行导入失败，请检查后重试：\n\n"
                            + "\n\n".join(f"· {line}" for line in bad_lines)
                        )

    st.markdown("---")
    with st.expander("🔄 一键补全旧数据（以前导入、缺播放/评分/邮箱的老记录）"):
        st.caption(
            "只动数据为空的老记录，已补全的不会重复动；YouTube 已删除的频道自动跳过。"
            "几百个要点几分钟，跑的时候别关页面。"
        )
        if st.button("🔄 开始补全", use_container_width=True):
            if not st.session_state.api_key:
                st.error("需要先填 YouTube API Key")
            else:
                _db = get_db()
                if not _db:
                    st.warning("补全要连团队公共库，本地测试模式用不了")
                else:
                    _bar = st.progress(0.02, text="正在拉取库里数据…")
                    _res = _db.backfill_sparse(
                        st.session_state.api_key, st.session_state.quota,
                        status_cb=lambda p, t: _bar.progress(p, text=t),
                    )
                    _bar.progress(1.0, text="补全完成")
                    if _res["total"] == 0:
                        st.success("✅ 库里没有等待补全的旧记录")
                    else:
                        st.success(
                            f"✅ 补全完成：补好 {_res['done']} 个，"
                            f"频道已消失跳过 {_res['gone']} 个，失败 {_res['failed']} 个"
                        )


# ============================================================
# Tab 4: 筛选设置
# ============================================================

with tab_settings:
    st.markdown("### 筛选设置")
    if st.session_state.user_name:
        st.caption(f"当前编辑的是「{st.session_state.user_name}」的个人标准，不影响其他成员")
    else:
        st.caption("⚠️ 请先在左侧选好名字，设置才能保存到你个人")
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

    # 挖掘强度（第二期：决定一次能挖多少人）
    st.markdown("")
    st.markdown("#### ⚡ 挖掘强度（决定一次能挖多少人）")
    _RPK_LABELS = ["50 条（省配额）", "100 条（推荐，数量×2）", "150 条（最大量）"]
    _RPK_VALUES = {"50 条（省配额）": 50, "100 条（推荐，数量×2）": 100, "150 条（最大量）": 150}
    _rpk_now = int(config.get("results_per_keyword", 100))
    _rpk_idx = list(_RPK_VALUES.values()).index(_rpk_now) if _rpk_now in _RPK_VALUES.values() else 1
    rpk_label = st.selectbox(
        "每个关键词抓多少候选视频",
        _RPK_LABELS, index=_rpk_idx,
        help="YouTube 每页固定 50 条：选 100 条就是翻 2 页，数量翻倍，配额消耗也翻倍",
    )
    new_results_per_keyword = _RPK_VALUES[rpk_label]

    new_shorts_mode = st.toggle(
        "Shorts 专项搜索", value=bool(config.get("shorts_mode", True)),
        help="额外搜一遍短视频，专捞只做 Shorts 的小博主（每个关键词 +100 配额）",
    )
    new_dual_order = st.toggle(
        "双排序搜索（时间＋相关性各搜一遍）", value=bool(config.get("dual_order", False)),
        help="同一个词按两种排序各搜一遍，能挖到更多不同类型的频道（每个关键词 +100 配额）",
    )
    new_window = st.number_input(
        "搜索时间窗（近N天发布的视频）", min_value=7, max_value=365,
        value=int(config.get("window_days", 60)), step=30,
        help="窗口越大挖到的人越多，不额外花配额。60天=只看最近两个月更新的",
    )
    _cost_hint = estimate_search_cost({
        "results_per_keyword": new_results_per_keyword,
        "shorts_mode": new_shorts_mode,
        "dual_order": new_dual_order,
    })
    st.caption(f"💸 按当前设置，每个关键词搜索约 {_cost_hint} 配额（不含验证，每频道约2-3）· 每天免费 10,000")

    # 评分权重（第二期：四维加权，种草关键词退役）
    st.markdown("")
    st.markdown("#### ⚖️ 评分权重（总分100）")
    if ai_ready():
        st.caption(f"🤖 AI分析已配置（{DASHSCOPE_MODEL}）：挖掘完成后自动判定垂类、打相关度、出标签")
    else:
        st.caption("🤖 AI分析未配置：挖掘照常可用，垂类相关度按中性50分计")
    weights = {**DEFAULT_CONFIG["weights"], **config.get("weights", {})}
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        w_rel = st.slider("垂类相关度（AI判定）", 0, 60, weights.get("relevance", 50),
                          help="AI 看博主内容跟我们货品的契合度。这一维占大头，最高可调到60")
        w_data = st.slider("数据健康度", 0, 40, weights.get("data_health", 20),
                           help="播/订比（按近10条中位数算，不怕爆款拉飞）")
    with col_w2:
        w_freq = st.slider("活跃度（更新频率）", 0, 40, weights.get("frequency", 15),
                           help="近30天更新条数，≥4条拿满")
        w_comm = st.slider("商业化历史", 0, 40, weights.get("commercial", 15),
                           help="有没有接过广告/带过货。小博主普遍为0，权重别太高")

    total_w = w_rel + w_data + w_freq + w_comm
    if total_w != 100:
        st.warning(f"⚠️ 当前权重总和 = {total_w}，建议调整为100")
    else:
        st.success(f"✅ 权重总和 = 100")

    new_ai_gate = st.slider(
        "AI相关度红线（低于此分进待定区）", 0, 80,
        int(config.get("ai_min_relevance", 40)), step=5,
        help="AI 判定相关度低于这条线的博主不进主列表，收进待定区人工翻（防挖偏的小保险）。拖到 0 = 关闭这条线",
    )

    # 去重规则
    st.markdown("")
    st.markdown("#### 🔁 去重规则（多少天后重新出现）")
    rules = config["dedup_rules"]
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        d_email = st.number_input("已发邮件（天）", value=rules["emailed_days"], step=1)
    with col_d2:
        d_discover = st.number_input("新发现（天）", value=rules["discovered_days"], step=1)

    # 保存按钮
    st.markdown("")
    if st.button("💾 保存我的设置", use_container_width=True):
        st.session_state.config = {
            "min_subs": new_min,
            "max_subs": new_max,
            "days_active": new_days,
            "score_threshold": new_threshold,
            # 挖掘强度（第二期新增）
            "results_per_keyword": new_results_per_keyword,
            "shorts_mode": new_shorts_mode,
            "dual_order": new_dual_order,
            "window_days": new_window,
            "weights": {
                "relevance": w_rel, "data_health": w_data,
                "frequency": w_freq, "commercial": w_comm,
            },
            "ai_min_relevance": new_ai_gate,
            "dedup_rules": {
                "onboarded_days": rules.get("onboarded_days", -1),
                "rejected_days": rules.get("rejected_days", 90),
                "emailed_days": d_email, "discovered_days": d_discover,
                "eliminated_days": rules.get("eliminated_days", 90),
            },
            # BD邮件身份在左侧身份栏维护，这里原样保留，避免保存评分设置时丢失
            "sender_name": st.session_state.config.get("sender_name", ""),
            "kkt_id": st.session_state.config.get("kkt_id", ""),
            # 网红库显示模式（卡片/列表）也原样保留
            "view_mode": st.session_state.config.get("view_mode", "card"),
        }
        # 持久化到数据库（下次打开还是你的设置）
        _db_save = get_db()
        if _db_save and st.session_state.user_name:
            ok = _db_save.save_user_settings(st.session_state.user_name, st.session_state.config)
            if ok:
                st.success(f"✅ 设置已保存到「{st.session_state.user_name}」的个人档案，下次打开自动加载")
            else:
                st.warning("⚠️ 本次生效，但未能存入数据库（刷新后会恢复默认）")
        elif not st.session_state.user_name:
            st.warning("⚠️ 请先在左侧选好你的名字，才能保存个人设置")
        else:
            st.success("✅ 设置已保存（本地模式，刷新后恢复默认）")

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
