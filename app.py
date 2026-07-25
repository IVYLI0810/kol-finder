"""
KOL Finder - 韩国YouTube网红挖掘工具
Streamlit 主应用 v2.0
"""

import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime, timedelta
from io import BytesIO

from youtube_api import (
    QuotaTracker, search_and_verify, get_channels, verify_channel,
    score_channel, search_videos, should_exclude,
    CATEGORY_KEYWORDS, VALUE_KEYWORDS, DEFAULT_CONFIG,
)

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
# 苹果极简风样式
# ============================================================

st.markdown("""
<style>
    .stApp { background-color: #f5f5f7; }
    footer { visibility: hidden; }

    h1, h2, h3 {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif;
        color: #1d1d1f; font-weight: 600;
    }
    p, span, div, label, td, th, a {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter', 'PingFang SC', sans-serif;
    }

    .channel-card {
        background: white; border-radius: 16px; padding: 22px 26px;
        margin-bottom: 14px; box-shadow: 0 1px 8px rgba(0,0,0,0.04);
        border: 1px solid #e8e8ed;
    }
    .channel-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.08); }

    .score-badge {
        display: inline-block; padding: 4px 14px; border-radius: 20px;
        font-size: 14px; font-weight: 600;
    }
    .score-high { background: #e8f5e9; color: #2e7d32; }
    .score-mid { background: #fff3e0; color: #e65100; }
    .score-low { background: #fce4ec; color: #c62828; }

    .status-tag {
        display: inline-block; padding: 3px 12px; border-radius: 12px;
        font-size: 12px; font-weight: 500;
    }
    .status-new { background: #e3f2fd; color: #1565c0; }
    .status-emailed { background: #fff3e0; color: #e65100; }
    .status-onboard { background: #e8f5e9; color: #2e7d32; }
    .status-reject { background: #fce4ec; color: #c62828; }

    .thumb-row { display: flex; gap: 8px; margin-top: 10px; overflow-x: auto; }
    .thumb-item { flex-shrink: 0; text-align: center; }
    .thumb-item img { width: 120px; height: 68px; object-fit: cover; border-radius: 8px; }
    .thumb-item span { font-size: 10px; color: #86868b; display: block; margin-top: 2px; }

    .commercial-badge {
        display: inline-block; padding: 2px 10px; border-radius: 10px;
        font-size: 11px; background: #ede7f6; color: #4527a0; margin-left: 8px;
    }

    section[data-testid="stSidebar"] {
        background-color: #ffffff; border-right: 1px solid #e8e8ed;
    }
    .stButton > button {
        border-radius: 24px; padding: 10px 28px; font-weight: 500;
        border: none; background-color: #0071e3; color: white;
    }
    .stButton > button:hover { background-color: #0077ed; }

    div[data-testid="stMetric"] {
        background: white; border-radius: 14px; padding: 16px 20px;
        box-shadow: 0 1px 6px rgba(0,0,0,0.03);
    }
    hr { border-color: #e8e8ed; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# 预置关键词库
# ============================================================

KEYWORD_LIBRARY = {
    "家居收纳": ["자취방 꾸미기 가성비", "원룸 수납 정리", "자취생 필수템 추천", "다이소 수납템", "집꾸미기 브이로그", "작은 방 인테리어", "혼자 사는 여자 방 꾸미기"],
    "平价美妆": ["가성비 화장품 추천", "학생 메이크업 화장품", "올리브영 추천템", "데일리 메이크업 학생", "출근 메이크업 추천", "맑은 메이크업", "로드샵 화장품 추천"],
    "宿舍好物": ["대학생 필수템 추천", "기숙사 필수템", "개강 준비물 리스트", "기숙사 꾸미기 템", "대학생 브이로그 자취"],
    "通勤配件": ["직장인 가방 추천 여자", "출근 가방 미니백", "통근룩 가방 추천", "왓츠인마이백 직장인", "가벼운 미니백 추천", "가성비 데일리백"],
    "宠物用品": ["고양이 필수템 추천", "강아지 용품 추천", "펫용품 가성비", "펫테리어", "집사 브이로그"],
    "学生用品": ["문구 추천 학생", "공부 브이로그 문구템", "다이소 문구 추천", "필통 꾸미기", "아이패드 공부템"],
}

# ============================================================
# Session State 初始化
# ============================================================

if "api_key" not in st.session_state:
    st.session_state.api_key = ""
if "supabase_url" not in st.session_state:
    st.session_state.supabase_url = ""
if "supabase_key" not in st.session_state:
    st.session_state.supabase_key = ""
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


# ============================================================
# 侧边栏
# ============================================================

with st.sidebar:
    st.markdown("### ⚙️ 连接设置")
    st.markdown("")

    # 用户名
    st.session_state.user_name = st.text_input(
        "你的名字", value=st.session_state.user_name,
        placeholder="用于标记\"挖掘人\"",
    )

    # YouTube API Key
    api_key_input = st.text_input(
        "YouTube API Key", value=st.session_state.api_key,
        type="password", help="Google Cloud Console 获取，免费10,000 units/天",
    )
    if api_key_input != st.session_state.api_key:
        st.session_state.api_key = api_key_input
        st.session_state.quota = QuotaTracker()

    # Supabase
    st.markdown("")
    st.markdown("#### 🗄 公共库（Supabase）")
    sb_url = st.text_input("Supabase URL", value=st.session_state.supabase_url,
                           placeholder="https://xxxx.supabase.co")
    sb_key = st.text_input("Supabase Key", value=st.session_state.supabase_key,
                           type="password", placeholder="anon public key")

    if sb_url != st.session_state.supabase_url or sb_key != st.session_state.supabase_key:
        st.session_state.supabase_url = sb_url
        st.session_state.supabase_key = sb_key
        st.session_state.db = None  # 重置连接

    db = get_db()
    if db:
        st.success("✅ 公共库已连接")
    elif sb_url and sb_key:
        st.error("❌ 连接失败，请检查URL和Key")
    else:
        st.info("💡 未连接公共库，使用本地模式（数据不共享）")

    # 配额
    st.markdown("")
    st.markdown("#### 📊 今日配额")
    quota = st.session_state.quota
    st.progress(
        min(quota.used / QuotaTracker.DAILY_LIMIT, 1.0),
        text=f"已用 {quota.used:,} / {QuotaTracker.DAILY_LIMIT:,} units"
    )
    if quota.remaining < 500:
        st.warning("⚠️ 配额即将用完")

    st.markdown("")
    st.caption("KOL Finder v2.0")


# ============================================================
# 主区域
# ============================================================

st.markdown("# 🔍 KOL Finder")
st.markdown("韩国 YouTube 网红挖掘 · 自动验证活跃 · 智能评分 · 公共库去重")
st.markdown("")

tab_search, tab_results, tab_database, tab_import, tab_settings = st.tabs([
    "🔎 搜索挖掘", "📊 搜索结果", "📁 网红库", "📥 批量导入", "⚙️ 筛选设置"
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
        col1, col2 = st.columns([3, 1])
        with col1:
            keyword_input = st.text_input(
                "搜索关键词", placeholder="例：자취방 꾸미기 가성비",
                label_visibility="collapsed",
            )
        with col2:
            category_select = st.selectbox(
                "垂类", options=list(KEYWORD_LIBRARY.keys()),
                label_visibility="collapsed",
            )

        col_b1, col_b2, col_b3 = st.columns([1, 1, 2])
        with col_b1:
            search_btn = st.button("🔍 搜索", use_container_width=True)
        with col_b2:
            batch_btn = st.button("⚡ 批量搜索", use_container_width=True,
                                  help="使用当前垂类全部预置关键词")

        st.markdown("")

        # 获取库中记录用于去重
        db_records = get_all_records()

        # 单个搜索
        if search_btn and keyword_input.strip():
            with st.spinner(f"正在搜索「{keyword_input}」并验证活跃度..."):
                results = search_and_verify(
                    keyword=keyword_input.strip(),
                    category=category_select,
                    api_key=st.session_state.api_key,
                    quota=st.session_state.quota,
                    config=st.session_state.config,
                    db_records=db_records,
                )
                st.session_state.search_results = results
                st.session_state.search_log.append({
                    "keyword": keyword_input, "category": category_select,
                    "time": datetime.now().strftime("%H:%M"), "results": len(results),
                })
                if results:
                    st.success(f"✅ 找到 {len(results)} 个符合条件的活跃博主")
                else:
                    st.warning("未找到符合条件的博主（可能都已不活跃或已在库中）")

        # 批量搜索
        if batch_btn:
            keywords = KEYWORD_LIBRARY[category_select]
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

        # 搜索历史
        if st.session_state.search_log:
            st.markdown("")
            st.markdown("#### 📜 最近搜索")
            for log in reversed(st.session_state.search_log[-8:]):
                st.caption(f"{log['time']} · {log['keyword']} · {log['category']} · {log['results']}个结果")


# ============================================================
# Tab 2: 搜索结果
# ============================================================

with tab_results:
    st.markdown("### 搜索结果")
    st.markdown("")

    if not st.session_state.search_results:
        st.info("暂无结果，请先在「🔎 搜索挖掘」中搜索")
    else:
        results = st.session_state.search_results

        # 筛选
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            min_score_filter = st.slider("最低评分", 0, 100,
                                         st.session_state.config.get("score_threshold", 60), step=5)
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
                comm_html = f'<span class="commercial-badge">💰 有商业合作 ({evidence})</span>'

            st.markdown(f"""
            <div class="channel-card">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <div>
                        <span style="font-size:17px; font-weight:600; color:#1d1d1f;">
                            {idx+1}. {ch['channel_name']}
                        </span>
                        <span class="score-badge {score_class}" style="margin-left:10px;">{score}分</span>
                        {comm_html}
                    </div>
                    <div style="text-align:right;">
                        <a href="{ch['channel_url']}" target="_blank" style="color:#0071e3; text-decoration:none; font-size:13px;">主页 ↗</a>
                        &nbsp;&nbsp;
                        <a href="{ch.get('about_url', ch['channel_url'])}" target="_blank" style="color:#86868b; text-decoration:none; font-size:13px;">简介页 ↗</a>
                    </div>
                </div>
                <div style="display:flex; gap:20px; flex-wrap:wrap; font-size:13px; color:#6e6e73;">
                    <span>📺 {ch['subscribers']:,} 订阅</span>
                    <span>👁 均播 {ch['avg_views_30d']:,}</span>
                    <span>📈 播/订比 {ch['view_sub_ratio']}%</span>
                    <span>🕐 更新 {ch['last_upload']}（{ch['last_upload_days_ago']}天前）</span>
                    <span>📂 {ch.get('category', '')}</span>
                </div>
                <div style="margin-top:8px; font-size:13px; color:#1d1d1f;">
                    📧 联系邮箱：<strong>{email_display}</strong>
                </div>
                <div style="margin-top:6px; font-size:12px; color:#86868b;">
                    代表视频：{' / '.join(ch.get('recent_titles', [])[:3])}
                </div>
                <div style="margin-top:4px; font-size:11px; color:#aeaeb2;">
                    评分：垂直{ch['scores']['verticality']} + 商业{ch['scores']['commercial']} +
                    数据{ch['scores']['data_health']} + 频率{ch['scores']['frequency']} +
                    关键词{ch['scores']['keywords']}
                </div>
                {thumb_html}
            </div>
            """, unsafe_allow_html=True)

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


# ============================================================
# Tab 3: 网红库
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
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filter_status = st.selectbox("状态", ["全部", "新发现", "已发邮件", "已引入", "已拒绝", "已淘汰"])
        with col_f2:
            filter_cat = st.multiselect("垂类", options=list(KEYWORD_LIBRARY.keys()), default=[])
        with col_f3:
            db_sort = st.selectbox("排序", ["添加时间", "评分", "订阅量", "最近更新"], key="db_sort")

        filtered_db = records
        if filter_status != "全部":
            filtered_db = [r for r in filtered_db if r.get("status") == filter_status]
        if filter_cat:
            filtered_db = [r for r in filtered_db if r.get("category") in filter_cat]

        sort_map = {
            "添加时间": lambda x: x.get("added_date", ""),
            "评分": lambda x: x.get("score_total", 0) if isinstance(x.get("score_total"), (int, float)) else 0,
            "订阅量": lambda x: x.get("subscribers", 0),
            "最近更新": lambda x: x.get("last_upload", ""),
        }
        filtered_db.sort(key=sort_map[db_sort], reverse=True)

        st.markdown(f"显示 {len(filtered_db)} / {len(records)} 条")
        st.markdown("")

        # 列表
        for idx, rec in enumerate(filtered_db):
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

            st.markdown(f"""
            <div class="channel-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-weight:600;">{name}</span>
                        <span class="status-tag {status_class}" style="margin-left:8px;">{status}</span>
                        <span style="margin-left:8px; font-size:12px; color:#86868b;">
                            {cat} · {subs:,}订阅 · 评分{score}
                            {' · 挖掘人: ' + discoverer if discoverer else ''}
                        </span>
                    </div>
                    <a href="{url}" target="_blank" style="color:#0071e3; font-size:13px; text-decoration:none;">↗</a>
                </div>
                {'<div style="margin-top:6px; font-size:12px; color:#6e6e73;">📧 ' + email + '</div>' if email else ''}
                {'<div style="margin-top:4px; font-size:12px; color:#86868b;">📝 ' + notes + '</div>' if notes else ''}
            </div>
            """, unsafe_allow_html=True)

            # 操作
            col_s1, col_s2, col_s3, col_s4 = st.columns([1.5, 1, 1, 3])
            with col_s1:
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
                        # 本地模式
                        for lr in st.session_state.local_db:
                            if lr.get("channel_id") == cid:
                                lr["status"] = new_status
                                lr["status_date"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    st.rerun()
            with col_s2:
                if st.button("🔄", key=f"rc_{idx}", help="复查活跃度"):
                    if st.session_state.api_key:
                        with st.spinner("复查中..."):
                            ch_copy = dict(rec)
                            ch_copy["uploads_playlist_id"] = ""  # 需要重新获取
                            # 简化复查：通过频道ID重新获取信息
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
            with col_s3:
                if st.button("🗑", key=f"rm_{idx}", help="从库中移除"):
                    db = get_db()
                    cid = rec.get("channel_id", "")
                    if db:
                        db.remove(cid)
                    else:
                        st.session_state.local_db = [r for r in st.session_state.local_db if r.get("channel_id") != cid]
                    st.rerun()
            with col_s4:
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
            st.markdown("")

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
# Tab 4: 批量导入
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
# Tab 5: 筛选设置
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

    # 关键词库展示
    st.markdown("")
    st.markdown("#### 📝 预置关键词库")
    for cat, kws in KEYWORD_LIBRARY.items():
        with st.expander(f"{cat}（{len(kws)}个）"):
            for kw in kws:
                st.caption(f"• {kw}")
