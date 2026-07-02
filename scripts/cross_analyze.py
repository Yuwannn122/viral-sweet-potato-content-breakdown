"""
Cross-Blogger Landscape Analysis · 赛道竞争格局分析
加载多位博主的结构化数据，产出横向对比数据底稿，供 AI 撰写最终对比报告。

复用 deep_analyze.py 的所有无状态分析函数，对每位博主独立计算后横向对比。

用法：
    # 自动发现 data_dir 下所有 *_analysis.json
    python cross_analyze.py --data-dir ./data --output-dir ./output

    # 指定博主列表
    python cross_analyze.py --bloggers "博主A,博主B" --data-dir ./data --output-dir ./output

    # 包含自己账号的差异化分析
    python cross_analyze.py --data-dir ./data --output-dir ./output --self "我自己"
"""

import json
import os
import sys
import re
import argparse
from datetime import datetime
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.common import safe_filename, parse_count
from utils.md_to_docx import md_to_docx
from deep_analyze import (
    extract_title_patterns,
    extract_emoji_patterns,
    extract_cta_patterns,
    analyze_content_structure,
    extract_comment_sentiment,
    extract_posting_heatmap,
    detect_posting_frequency,
    SENTIMENT_LEXICON,
)


# ============================================================
#  数据加载
# ============================================================

def load_blogger_data(data_dir, blogger_name):
    """
    加载一位博主的全量数据（analysis.json + notes_details.json）。

    注意：analyze.py 保存的 _analysis.json 中 notes 不含 desc 和 comments，
    因此需要同时加载 _notes_details.json 来获取原始正文和评论。

    Args:
        data_dir: 数据目录路径
        blogger_name: 博主名（用于匹配文件名，支持 safe_name 和原始名）

    Returns:
        dict — {
            "name": str,           # 博主名（从数据中提取的真实昵称）
            "safe_name": str,      # safe_filename 处理后的名称
            "analysis": dict,      # 完整 _analysis.json 内容
            "stats": dict,         # analysis["stats"]
            "notes": list[dict],   # analysis["notes"]（已含 category）
            "notes_count": int,
            "details": list[dict], # _notes_details.json 原始数据（可能为空列表）
            "details_available": bool,
            "categories": dict,    # category_stats
            "top10": list[dict],   # TOP10 笔记
            "tag_freq": list,      # 标签频率
        }
        如果 _analysis.json 不存在则返回 None。
    """
    safe = safe_filename(blogger_name)

    # 尝试匹配文件：优先精确 safe_name，其次模糊匹配
    analysis_path = None
    details_path = None

    analysis_candidate = os.path.join(data_dir, f"{safe}_analysis.json")
    if os.path.isfile(analysis_candidate):
        analysis_path = analysis_candidate
        details_candidate = os.path.join(data_dir, f"{safe}_notes_details.json")
        if os.path.isfile(details_candidate):
            details_path = details_candidate
    else:
        # 模糊匹配：在 data_dir 中搜索包含 blogger_name 的 analysis 文件
        if os.path.isdir(data_dir):
            for f in sorted(os.listdir(data_dir)):
                if "_analysis.json" in f and safe_filename(blogger_name)[:6] in f:
                    analysis_path = os.path.join(data_dir, f)
                    details_candidate = analysis_path.replace("_analysis.json", "_notes_details.json")
                    if os.path.isfile(details_candidate):
                        details_path = details_candidate
                    break

    if not analysis_path:
        return None

    # 加载 analysis.json
    with open(analysis_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)

    # 加载 notes_details.json（可选）
    details = []
    details_available = False
    if details_path:
        try:
            with open(details_path, "r", encoding="utf-8") as f:
                details = json.load(f)
            details_available = True
        except (json.JSONDecodeError, IOError):
            details = []

    # 提取真实昵称：优先从 details 中取，其次从文件名推断
    nickname = blogger_name
    if details:
        for item in details[:1]:
            note_data = item.get("data", {}).get("note", item)
            user = note_data.get("user", {})
            nn = user.get("nickname", user.get("nickName", ""))
            if nn:
                nickname = nn
                break

    notes = analysis.get("notes", [])

    return {
        "name": nickname,
        "safe_name": safe,
        "analysis": analysis,
        "stats": analysis.get("stats", {}),
        "notes": notes,
        "notes_count": len(notes),
        "details": details,
        "details_available": details_available,
        "categories": analysis.get("category_stats", {}),
        "top10": analysis.get("top10", []),
        "tag_freq": analysis.get("tag_freq", []),
    }


def discover_bloggers(data_dir):
    """
    自动发现 data_dir 下所有 *_analysis.json 对应的博主。

    Returns:
        list[str] — 博主 safe_name 列表
    """
    bloggers = []
    if not os.path.isdir(data_dir):
        return bloggers
    for f in sorted(os.listdir(data_dir)):
        if f.endswith("_analysis.json"):
            name = f.replace("_analysis.json", "")
            if name and name not in bloggers:
                bloggers.append(name)
    return bloggers


# ============================================================
#  辅助函数
# ============================================================

def _get_descs_from_details(details):
    """从 notes_details 中提取所有正文文本。"""
    descs = []
    for item in details:
        if "_error" in item:
            continue
        note_data = item.get("data", {}).get("note", item)
        desc = note_data.get("desc", "") or ""
        descs.append(desc)
    return descs


def _get_titles_from_notes(notes):
    """从 analysis notes 中提取标题列表。"""
    return [n.get("title", "") for n in notes if n.get("title")]


def _get_notes_with_time(notes):
    """过滤出有时间戳的笔记。"""
    return [n for n in notes if n.get("time", 0) > 0]


def _safe_pct(part, total):
    """安全计算百分比。"""
    if total <= 0:
        return 0.0
    return round(part / total * 100, 1)


# ============================================================
#  章节构建函数（每个返回独立 Markdown 字符串）
# ============================================================

def build_horizontal_comparison(all_data):
    """
    一、横向对比总览

    产出每位博主的关键指标对比表 + 核心发现。
    """
    lines = [
        "## 一、横向对比总览",
        "",
        "| 维度 | " + " | ".join(d["name"] for d in all_data) + " |",
        "|------|" + "|".join(["------"] * len(all_data)) + "|",
    ]

    # 笔记总数
    row = "| 笔记总数 | " + " | ".join(str(d["stats"].get("total", 0)) for d in all_data) + " |"
    lines.append(row)

    # 视频/图文比
    row = "| 视频/图文 | " + " | ".join(
        f"{d['stats'].get('video_count', 0)}/{d['stats'].get('normal_count', 0)}"
        for d in all_data
    ) + " |"
    lines.append(row)

    # 总获赞
    row = "| 总获赞 | " + " | ".join(
        f"{d['stats'].get('total_likes', 0):,}" for d in all_data
    ) + " |"
    lines.append(row)

    # 均赞
    row = "| 均赞 | " + " | ".join(
        f"{d['stats'].get('avg_likes', 0):,}" for d in all_data
    ) + " |"
    lines.append(row)

    # 均收藏
    row = "| 均收藏 | " + " | ".join(
        f"{d['stats'].get('avg_collects', 0):,}" for d in all_data
    ) + " |"
    lines.append(row)

    # 均评论
    row = "| 均评论 | " + " | ".join(
        f"{d['stats'].get('avg_comments', 0):,}" for d in all_data
    ) + " |"
    lines.append(row)

    # 爆款率 (>3x 均赞)
    row_parts = []
    for d in all_data:
        avg_likes = d["stats"].get("avg_likes", 1) or 1
        threshold = avg_likes * 3
        hit_count = sum(1 for n in d["notes"] if n.get("likes", 0) >= threshold)
        rate = _safe_pct(hit_count, d["notes_count"])
        row_parts.append(f"{rate}%（{hit_count}条）")
    row = "| 爆款率（>3x均赞） | " + " | ".join(row_parts) + " |"
    lines.append(row)

    # 超级爆款率 (>10x 均赞)
    row_parts = []
    for d in all_data:
        avg_likes = d["stats"].get("avg_likes", 1) or 1
        threshold = avg_likes * 10
        hit_count = sum(1 for n in d["notes"] if n.get("likes", 0) >= threshold)
        rate = _safe_pct(hit_count, d["notes_count"])
        row_parts.append(f"{rate}%（{hit_count}条）")
    row = "| 超级爆款率（>10x） | " + " | ".join(row_parts) + " |"
    lines.append(row)

    # 整体藏赞比
    row = "| 整体藏赞比 | " + " | ".join(
        f"{d['stats'].get('total_collects', 0) / max(d['stats'].get('total_likes', 1), 1):.2f}"
        for d in all_data
    ) + " |"
    lines.append(row)

    # 更新频率
    freq_parts = []
    for d in all_data:
        notes_with_time = _get_notes_with_time(d["notes"])
        freq_info = detect_posting_frequency(notes_with_time)
        freq_parts.append(freq_info.get("pattern", "数据不足"))
    row = "| 更新频率 | " + " | ".join(freq_parts) + " |"
    lines.append(row)

    # TOP3 领域
    cat_parts = []
    for d in all_data:
        top_cats = sorted(d["categories"].items(), key=lambda x: x[1].get("count", 0), reverse=True)[:3]
        cat_str = "、".join(c[0] for c in top_cats) if top_cats else "未分类"
        cat_parts.append(cat_str)
    row = "| TOP3 领域 | " + " | ".join(cat_parts) + " |"
    lines.append(row)

    lines.append("")
    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：基于以上数据，2-3 条最关键洞察）*")
    lines.append("")

    return "\n".join(lines)


def build_title_strategy_comparison(all_data):
    """
    二、标题策略对比

    对每位博主运行 extract_title_patterns()，产出 8 种标题模式对比表。
    """
    all_patterns = [
        "数字型", "疑问型", "感叹型", "教程型",
        "列表型", "对比型", "故事型", "悬念型",
    ]

    # 为每位博主计算标题模式
    blogger_patterns = {}
    for d in all_data:
        titles = _get_titles_from_notes(d["notes"])
        if titles:
            blogger_patterns[d["name"]] = extract_title_patterns(titles)
        else:
            blogger_patterns[d["name"]] = {}

    lines = [
        "## 二、标题策略对比",
        "",
        "| 标题模式 | " + " | ".join(d["name"] for d in all_data) + " |",
        "|----------|" + "|".join(["------"] * len(all_data)) + "|",
    ]

    for pattern in all_patterns:
        parts = []
        for d in all_data:
            pd = blogger_patterns.get(d["name"], {}).get(pattern, {})
            pct = pd.get("pct", 0)
            parts.append(f"{pct}%" if pct > 0 else "-")
        lines.append(f"| {pattern} | " + " | ".join(parts) + " |")

    lines.append("")
    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：各博主标题策略的差异化特征）*")
    lines.append("")

    return "\n".join(lines)


def build_content_structure_comparison(all_data):
    """
    三、内容结构对比

    需要 notes_details.json 中的 desc 字段。如果某博主无 details 数据则标注"数据不可用"。
    """
    lines = [
        "## 三、内容结构对比",
        "",
    ]

    # 检查数据可用性
    available = []
    unavailable = []
    for d in all_data:
        if d["details_available"] and d["details"]:
            available.append(d)
        else:
            unavailable.append(d)

    if unavailable:
        names = "、".join(d["name"] for d in unavailable)
        lines.append(f"> ⚠️ 以下博主缺少原始笔记详情（notes_details.json），内容结构数据不可用：{names}")
        lines.append("")

    if not available:
        lines.append("> 没有可用的内容结构数据。")
        lines.append("")
        return "\n".join(lines)

    # ASL / 长度分布 对比
    lines.append("### 正文结构对比")
    lines.append("")
    lines.append("| 指标 | " + " | ".join(d["name"] for d in available) + " |")
    lines.append("|------|" + "|".join(["------"] * len(available)) + "|")

    # 平均正文长度
    len_parts = []
    for d in available:
        descs = _get_descs_from_details(d["details"])
        struct = analyze_content_structure(descs)
        len_parts.append(f"{struct['avg_length']}字")
    lines.append("| 平均正文长度 | " + " | ".join(len_parts) + " |")

    # 短/中/长文比例
    ratio_parts = []
    for d in available:
        descs = _get_descs_from_details(d["details"])
        struct = analyze_content_structure(descs)
        total = len(descs) or 1
        ratio_parts.append(
            f"{_safe_pct(struct['short_count'], total)}/"
            f"{_safe_pct(struct['medium_count'], total)}/"
            f"{_safe_pct(struct['long_count'], total)}"
        )
    lines.append("| 短/中/长文比例 | " + " | ".join(ratio_parts) + " |")

    # 列表格式使用率
    list_parts = []
    for d in available:
        descs = _get_descs_from_details(d["details"])
        struct = analyze_content_structure(descs)
        total = len(descs) or 1
        list_parts.append(f"{_safe_pct(struct['has_list_count'], total)}%")
    lines.append("| 列表格式使用率 | " + " | ".join(list_parts) + " |")

    # 数字小标题使用率
    heading_parts = []
    for d in available:
        descs = _get_descs_from_details(d["details"])
        struct = analyze_content_structure(descs)
        total = len(descs) or 1
        heading_parts.append(f"{_safe_pct(struct['has_number_heading'], total)}%")
    lines.append("| 数字小标题使用率 | " + " | ".join(heading_parts) + " |")

    lines.append("")

    # Emoji 使用对比
    lines.append("### Emoji 使用对比")
    lines.append("")
    lines.append("| 指标 | " + " | ".join(d["name"] for d in available) + " |")
    lines.append("|------|" + "|".join(["------"] * len(available)) + "|")

    emoji_parts = []
    top_emoji_parts = []
    for d in available:
        descs = _get_descs_from_details(d["details"])
        emoji_info = extract_emoji_patterns(descs)
        emoji_parts.append(f"{emoji_info['emoji_usage_pct']}%")
        top = " ".join(e[0] for e in emoji_info.get("top_emojis", [])[:3]) or "-"
        top_emoji_parts.append(top)
    lines.append("| Emoji 使用率 | " + " | ".join(emoji_parts) + " |")
    lines.append("| TOP3 Emoji | " + " | ".join(top_emoji_parts) + " |")

    lines.append("")

    # CTA 对比
    lines.append("### CTA 策略对比")
    lines.append("")
    cta_types = ["关注引导", "收藏引导", "点赞引导", "评论引导", "转发引导", "私信引导"]
    lines.append("| CTA 类型 | " + " | ".join(d["name"] for d in available) + " |")
    lines.append("|----------|" + "|".join(["------"] * len(available)) + "|")

    for cta in cta_types:
        cta_parts = []
        for d in available:
            descs = _get_descs_from_details(d["details"])
            cta_info = extract_cta_patterns(descs)
            cd = cta_info.get(cta, {})
            pct = cd.get("pct", 0)
            cta_parts.append(f"{pct}%" if pct > 0 else "-")
        lines.append(f"| {cta} | " + " | ".join(cta_parts) + " |")

    lines.append("")
    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：各博主内容结构和互动引导的差异化特征）*")
    lines.append("")

    return "\n".join(lines)


def build_comment_sentiment_comparison(all_data):
    """
    四、评论区情感对比

    需要 notes_details.json 中的评论数据。
    """
    lines = [
        "## 四、评论区情感对比",
        "",
    ]

    available = [d for d in all_data if d["details_available"] and d["details"]]

    if not available:
        lines.append("> 没有可用的评论数据。")
        lines.append("")
        return "\n".join(lines)

    # 为每位博主运行情感分析
    sentiment_results = {}
    for d in available:
        sentiment_results[d["name"]] = extract_comment_sentiment(d["details"])

    lines.append("| 指标 | " + " | ".join(d["name"] for d in available) + " |")
    lines.append("|------|" + "|".join(["------"] * len(available)) + "|")

    # 整体情感得分
    score_parts = []
    for d in available:
        sr = sentiment_results.get(d["name"], {})
        score = sr.get("overall_score")
        if score is not None:
            score_parts.append(f"{score:+.2f}")
        else:
            score_parts.append("N/A")
    lines.append("| 整体情感得分 | " + " | ".join(score_parts) + " |")

    # 正向评论占比
    pos_parts = []
    neu_parts = []
    neg_parts = []
    for d in available:
        sr = sentiment_results.get(d["name"], {})
        per_note = sr.get("per_note", [])
        if per_note:
            avg_pos = round(sum(p.get("positive_pct", 0) for p in per_note) / len(per_note), 1)
            avg_neu = round(sum(p.get("neutral_pct", 0) for p in per_note) / len(per_note), 1)
            avg_neg = round(sum(p.get("negative_pct", 0) for p in per_note) / len(per_note), 1)
        else:
            avg_pos = avg_neu = avg_neg = 0
        pos_parts.append(f"{avg_pos}%")
        neu_parts.append(f"{avg_neu}%")
        neg_parts.append(f"{avg_neg}%")
    lines.append("| 正向评论占比（均值） | " + " | ".join(pos_parts) + " |")
    lines.append("| 中性评论占比（均值） | " + " | ".join(neu_parts) + " |")
    lines.append("| 负向评论占比（均值） | " + " | ".join(neg_parts) + " |")

    # 分析评论总数
    total_parts = []
    for d in available:
        sr = sentiment_results.get(d["name"], {})
        total_parts.append(str(sr.get("total_comments_analyzed", 0)))
    lines.append("| 分析评论总数 | " + " | ".join(total_parts) + " |")

    # 情感标签
    label_parts = []
    for d in available:
        sr = sentiment_results.get(d["name"], {})
        per_note = sr.get("per_note", [])
        if not per_note:
            label_parts.append("无数据")
            continue
        pos_count = sum(1 for p in per_note if p.get("sentiment_label") == "正向为主")
        neg_count = sum(1 for p in per_note if p.get("sentiment_label") == "负向为主")
        if pos_count > len(per_note) * 0.6:
            label_parts.append("正向为主")
        elif neg_count > len(per_note) * 0.3:
            label_parts.append("争议较大")
        else:
            label_parts.append("中性/混合")
    lines.append("| 情感标签 | " + " | ".join(label_parts) + " |")

    lines.append("")

    # 各博主情感亮点
    lines.append("### 各博主情感亮点")
    lines.append("")
    for d in available:
        sr = sentiment_results.get(d["name"], {})
        lines.append(f"**{d['name']}**：")
        pos_examples = sr.get("positive_examples", [])
        neg_examples = sr.get("negative_examples", [])
        if pos_examples:
            lines.append(f"- 正向评论示例：「{pos_examples[0][:60]}」")
        if neg_examples:
            lines.append(f"- 负向评论示例：「{neg_examples[0][:60]}」")
        lines.append("")

    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：评论情感的赛道级规律，如'XX 赛道用户整体偏正向，争议集中在 YY 话题'）*")
    lines.append("")

    return "\n".join(lines)


def build_heatmap_comparison(all_data):
    """
    五、发布时间策略对比

    使用 analysis.json 中的 notes（含 time 和 likes）。
    """
    lines = [
        "## 五、发布时间策略对比",
        "",
    ]

    heatmap_results = {}
    for d in all_data:
        notes_with_time = _get_notes_with_time(d["notes"])
        if len(notes_with_time) >= 5:
            heatmap_results[d["name"]] = extract_posting_heatmap(notes_with_time)
        else:
            heatmap_results[d["name"]] = None

    # 最佳发布日/时段 对比
    lines.append("| 指标 | " + " | ".join(d["name"] for d in all_data) + " |")
    lines.append("|------|" + "|".join(["------"] * len(all_data)) + "|")

    day_parts = []
    time_parts = []
    window_parts = []
    for d in all_data:
        hr = heatmap_results.get(d["name"])
        if hr:
            day_parts.append(f"{hr.get('best_day', 'N/A')}（均赞{hr.get('best_day_avg_likes', 0):.0f}）")
            time_parts.append(f"{hr.get('best_hour_block', 'N/A')}（均赞{hr.get('best_hour_avg_likes', 0):.0f}）")
            windows = hr.get("optimal_windows", [])
            if windows:
                w = windows[0]
                window_parts.append(f"{w.get('day', '')} {w.get('slot', '')}（{w.get('count', 0)}条/均赞{w.get('avg_likes', 0):.0f}）")
            else:
                window_parts.append("数据不足")
        else:
            day_parts.append("数据不足")
            time_parts.append("数据不足")
            window_parts.append("数据不足")
    lines.append("| 最佳发布日 | " + " | ".join(day_parts) + " |")
    lines.append("| 最佳时段 | " + " | ".join(time_parts) + " |")
    lines.append("| 最优窗口 | " + " | ".join(window_parts) + " |")

    lines.append("")

    # 各博主最佳窗口 TOP3
    lines.append("### 各博主最佳发布窗口 TOP3")
    lines.append("")
    for d in all_data:
        hr = heatmap_results.get(d["name"])
        if not hr:
            lines.append(f"**{d['name']}**：数据不足（需≥5条带时间戳笔记）")
            lines.append("")
            continue
        lines.append(f"**{d['name']}**：")
        lines.append("")
        lines.append("| 排名 | 日期 | 时段 | 笔记数 | 均赞 |")
        lines.append("|------|------|------|--------|------|")
        for i, w in enumerate(hr.get("optimal_windows", [])[:3]):
            lines.append(f"| {i+1} | {w['day']} | {w['slot']} | {w['count']} | {w['avg_likes']:.0f} |")
        lines.append("")

    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：发布时间策略的赛道共性规律和个体差异）*")
    lines.append("")

    return "\n".join(lines)


def build_category_overlap_analysis(all_data):
    """
    六、内容领域重叠分析

    产出领域重叠矩阵 + 独有领域 + 潜力赛道。
    """
    lines = [
        "## 六、内容领域重叠分析",
        "",
    ]

    # 汇总所有领域
    all_categories = set()
    for d in all_data:
        all_categories.update(d["categories"].keys())

    # 领域重叠矩阵
    lines.append("### 领域覆盖矩阵")
    lines.append("")
    header = "| 领域 | " + " | ".join(d["name"] for d in all_data) + " | 覆盖博主数 | 赛道总规模 |"
    sep = "|------|" + "|".join(["------"] * len(all_data)) + "|------|------|"
    lines.append(header)
    lines.append(sep)

    for cat in sorted(all_categories, key=lambda c: sum(
        d["categories"].get(c, {}).get("count", 0) for d in all_data
    ), reverse=True):
        parts = []
        total_count = 0
        covered = 0
        for d in all_data:
            cd = d["categories"].get(cat, {})
            count = cd.get("count", 0)
            parts.append(f"{count}条" if count > 0 else "-")
            total_count += count
            if count > 0:
                covered += 1
        lines.append(f"| {cat} | " + " | ".join(parts) + f" | {covered} | {total_count}条 |")

    lines.append("")

    # 独有领域
    lines.append("### 各博主独有领域")
    lines.append("")
    for d in all_data:
        others_cats = set()
        for d2 in all_data:
            if d2["name"] != d["name"]:
                others_cats.update(d2["categories"].keys())
        unique = {c: s for c, s in d["categories"].items() if c not in others_cats and s.get("count", 0) > 0}
        if unique:
            lines.append(f"**{d['name']}** 独有：")
            for cat, cs in sorted(unique.items(), key=lambda x: x[1].get("count", 0), reverse=True):
                lines.append(f"- {cat}：{cs['count']}条，均赞{cs.get('avg_likes', 0):,}")
            lines.append("")
        else:
            lines.append(f"**{d['name']}**：无独有领域")
            lines.append("")

    # 潜力赛道（高均赞 + 低覆盖）
    lines.append("### 潜力赛道（高需求 × 低覆盖）")
    lines.append("")
    lines.append("| 领域 | 覆盖博主数 | 赛道总笔记数 | 赛道均赞 | 评价 |")
    lines.append("|------|-----------|------------|---------|------|")

    for cat in sorted(all_categories):
        covered = 0
        total_notes = 0
        total_likes = 0
        for d in all_data:
            cd = d["categories"].get(cat, {})
            count = cd.get("count", 0)
            if count > 0:
                covered += 1
                total_notes += count
                total_likes += cd.get("avg_likes", 0) * count
        avg_likes = total_likes / total_notes if total_notes > 0 else 0
        if avg_likes > 0:
            if covered == 1 and total_notes >= 3:
                evaluation = "🔥 高潜力（仅1人覆盖）"
            elif avg_likes >= 100:
                evaluation = "⭐ 值得关注（高互动赛道）"
            elif covered <= len(all_data) // 2 + 1:
                evaluation = "💡 可考虑切入"
            else:
                evaluation = "竞争饱和"
            lines.append(f"| {cat} | {covered}/{len(all_data)} | {total_notes} | {avg_likes:.0f} | {evaluation} |")

    lines.append("")
    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：内容领域的竞争格局和空白地带分析）*")
    lines.append("")

    return "\n".join(lines)


def extract_aggregate_comment_questions(all_data):
    """
    七、赛道级用户诉求聚合

    跨博主汇总评论区高频提问，产出赛道 TOP10 内容机会。
    """
    lines = [
        "## 七、赛道级用户诉求聚合",
        "",
    ]

    available = [d for d in all_data if d["details_available"] and d["details"]]

    if not available:
        lines.append("> 没有可用的评论数据。")
        lines.append("")
        return "\n".join(lines)

    # 跨博主汇总所有提问
    all_questions = []
    question_patterns = [
        r"(怎么|如何|怎样|什么|哪里|哪个|多少|能不能|可以.*吗|有没有)['一-鿿]*[？?]?",
        r"(求|想要|需要|蹲).{0,15}(链接|教程|方法|推荐|牌子|同款)",
        r"(有人|有没有人|谁).{0,10}(告诉|知道|说)",
    ]

    total_comments = 0
    for d in available:
        for item in d["details"]:
            if "_error" in item:
                continue
            comments_data = item.get("data", {}).get("comments", item.get("comments", {}))
            comments = comments_data.get("list", []) if isinstance(comments_data, dict) else []
            for c in comments:
                total_comments += 1
                content = c.get("content", "")
                if not content:
                    continue
                for pat in question_patterns:
                    m = re.search(pat, content)
                    if m:
                        all_questions.append({
                            "question": m.group()[:60],
                            "blogger": d["name"],
                            "content": content[:80],
                        })
                        break

    lines.append(f"> 基于 {len(available)} 位博主共 {total_comments} 条评论提取")
    lines.append("")

    if not all_questions:
        lines.append("未检测到明显的高频提问。")
        lines.append("")
        return "\n".join(lines)

    # 聚类相似问题
    clusters = Counter()
    for q in all_questions:
        core = q["question"]
        for stop in ["怎么", "如何", "怎样", "什么", "哪里", "哪个", "可以", "能不能", "有没有"]:
            core = core.replace(stop, "")
        core = core.strip()[:20]
        if len(core) >= 2:
            clusters[core] += 1

    lines.append("| # | 用户问题方向 | 出现频次 | 代表性评论 | 内容机会 |")
    lines.append("|---|------------|---------|-----------|---------|")
    for i, (core, freq) in enumerate(clusters.most_common(10)):
        # 找代表性评论
        example = ""
        for q in all_questions:
            if core in q["question"] or q["question"] in core:
                example = q["content"]
                break
        opportunity = "直接选题（用户明确表达需求）" if freq >= 3 else "潜在选题（需验证需求强度）"
        lines.append(f"| {i+1} | {core} | {freq}次 | {example[:40]} | {opportunity} |")

    lines.append("")
    lines.append("### 核心发现")
    lines.append("")
    lines.append("> *（AI 执行时填充：赛道级用户未满足需求的总览和优先级建议）*")
    lines.append("")

    return "\n".join(lines)


def build_self_differentiation(all_data, self_name):
    """
    八、差异化机会分析（仅当 --self 提供时启用）

    你的账号 vs 赛道均值 + 差距分析 + 定位建议。
    """
    lines = [
        "## 八、差异化机会分析",
        "",
        f"> 对比账号：**{self_name}** vs 赛道平均水平",
        "",
    ]

    # 找到 self 数据
    self_data = None
    others = []
    for d in all_data:
        if d["name"] == self_name or d["safe_name"] == safe_filename(self_name):
            self_data = d
        else:
            others.append(d)

    if not self_data:
        lines.append(f"> ⚠️ 未找到「{self_name}」的数据，无法进行差异化分析。")
        lines.append("")
        return "\n".join(lines)

    if not others:
        lines.append("> 没有其他博主数据可供对比。")
        lines.append("")
        return "\n".join(lines)

    # 赛道均值
    def avg_of(key):
        vals = [d["stats"].get(key, 0) for d in others]
        return round(sum(vals) / len(vals)) if vals else 0

    def safe_ratio(part, total):
        return part / total if total > 0 else 0

    # 你的账号 vs 赛道均值
    lines.append("### 你的账号 vs 赛道均值")
    lines.append("")
    lines.append("| 维度 | 你 | 赛道均值 | 差距 | 评价 |")
    lines.append("|------|-----|---------|------|------|")

    dimensions = [
        ("笔记数", "total", lambda v, a: f"{'✅ 高产' if v > a else '⚠️ 偏低'}" if a > 0 else "-"),
        ("均赞", "avg_likes", lambda v, a: f"{'✅ 高于均值' if v > a else '⚠️ 低于均值'}" if a > 0 else "-"),
        ("均收藏", "avg_collects", lambda v, a: f"{'✅ 高于均值' if v > a else '⚠️ 低于均值'}" if a > 0 else "-"),
        ("均评论", "avg_comments", lambda v, a: f"{'✅ 互动更强' if v > a else '⚠️ 互动偏弱'}" if a > 0 else "-"),
    ]

    for label, key, judge in dimensions:
        self_val = self_data["stats"].get(key, 0)
        avg_val = avg_of(key)
        gap = f"+{self_val - avg_val}" if self_val >= avg_val else str(self_val - avg_val)
        lines.append(f"| {label} | {self_val} | {avg_val} | {gap} | {judge(self_val, avg_val)} |")

    lines.append("")

    # 差距分析
    lines.append("### 差距分析")
    lines.append("")
    lines.append("> *（AI 执行时填充：针对你的弱项，分析最强博主的具体做法 + 可执行建议）*")
    lines.append("")

    for label, key, _ in dimensions:
        self_val = self_data["stats"].get(key, 0)
        avg_val = avg_of(key)
        if self_val < avg_val and avg_val > 0:
            best = max(others, key=lambda d: d["stats"].get(key, 0))
            lines.append(f"- **{label}**：你 {self_val} vs 最强 {best['name']} {best['stats'].get(key, 0)} — [AI填充具体分析和建议]")
    lines.append("")

    # 你未覆盖的高需求话题
    lines.append("### 你未覆盖的高需求话题")
    lines.append("")

    self_cats = set(self_data["categories"].keys())
    opportunities = []
    for d in others:
        for cat, cs in d["categories"].items():
            if cat not in self_cats and cs.get("count", 0) >= 3:
                opportunities.append({
                    "category": cat,
                    "blogger": d["name"],
                    "count": cs["count"],
                    "avg_likes": cs.get("avg_likes", 0),
                })

    if opportunities:
        opportunities.sort(key=lambda x: x["avg_likes"], reverse=True)
        lines.append("| 领域 | 已被谁覆盖 | 笔记数 | 均赞 | 建议 |")
        lines.append("|------|-----------|--------|------|------|")
        for opp in opportunities[:8]:
            suggestion = "🔥 优先切入" if opp["avg_likes"] >= 100 else "💡 可考虑" if opp["avg_likes"] >= 50 else "📋 观察"
            lines.append(f"| {opp['category']} | {opp['blogger']} | {opp['count']} | {opp['avg_likes']:.0f} | {suggestion} |")
    else:
        lines.append("> 你已覆盖赛道的全部高需求话题。")
    lines.append("")

    # 定位建议
    lines.append("### 你的定位建议")
    lines.append("")
    lines.append("> *（AI 执行时填充：2-3 段战略性建议——你的当前优势、优先攻击哪个空白区、如何与每位竞品差异化）*")
    lines.append("")

    return "\n".join(lines)


# ============================================================
#  数据底稿组装 + AI 任务生成
# ============================================================

def generate_data_primer(all_data, self_name, output_dir):
    """
    组装完整数据底稿 Markdown，并生成配套的 AI 分析任务文件。

    Returns:
        str — 数据底稿 Markdown 文件路径
    """
    blogger_names = "、".join(d["name"] for d in all_data)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# 赛道竞争格局 — 数据底稿",
        "",
        f"> 生成时间：{now_str}",
        f"> 分析博主：{blogger_names}",
        f"> 博主数量：{len(all_data)}",
        "",
        "> ⚠️ 本文档是**数据底稿**（脚本自动生成），包含结构化数据和统计表格。",
        "> 深度洞察、因果分析、策略建议由 AI 在最终报告中补充。",
        "",
        "---",
        "",
    ]

    # 一、横向对比总览
    lines.append(build_horizontal_comparison(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 二、标题策略对比
    lines.append(build_title_strategy_comparison(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 三、内容结构对比
    lines.append(build_content_structure_comparison(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 四、评论区情感对比
    lines.append(build_comment_sentiment_comparison(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 五、发布时间策略对比
    lines.append(build_heatmap_comparison(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 六、内容领域重叠分析
    lines.append(build_category_overlap_analysis(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 七、赛道级用户诉求聚合
    lines.append(extract_aggregate_comment_questions(all_data))
    lines.append("")
    lines.append("---")
    lines.append("")

    # 八、差异化机会分析（条件性）
    if self_name:
        lines.append(build_self_differentiation(all_data, self_name))

    primer_md = "\n".join(lines)

    # 保存数据底稿
    os.makedirs(output_dir, exist_ok=True)
    process_dir = os.path.join(output_dir, "_过程文件", "原始素材")
    os.makedirs(process_dir, exist_ok=True)

    primer_path = os.path.join(process_dir, "赛道竞争格局_数据底稿.md")
    with open(primer_path, "w", encoding="utf-8") as f:
        f.write(primer_md)

    # 同时保存到 output 根目录
    primer_root_path = os.path.join(output_dir, "赛道竞争格局_对比报告.md")
    with open(primer_root_path, "w", encoding="utf-8") as f:
        f.write(primer_md)

    # 生成 AI 分析任务
    ai_prompt = generate_ai_task(all_data, self_name)
    ai_path = os.path.join(process_dir, "赛道竞争格局_AI分析任务.md")
    with open(ai_path, "w", encoding="utf-8") as f:
        f.write(ai_prompt)

    print(f"  📄 数据底稿: {primer_path}")
    print(f"  📄 数据底稿(根): {primer_root_path}")
    print(f"  📄 AI分析任务: {ai_path}")

    return primer_path


def generate_ai_task(all_data, self_name):
    """
    生成 AI 深度分析任务指令，AI 读取数据底稿后按此指令产出最终报告。
    """
    blogger_names = "、".join(d["name"] for d in all_data)

    lines = [
        f"# 赛道竞争格局 — AI 分析任务",
        "",
        f"## 任务",
        f"基于「赛道竞争格局_数据底稿.md」中的结构化数据，撰写一份完整的**赛道竞争格局对比报告**。",
        "",
        f"## 分析范围",
        f"- 分析博主：{blogger_names}",
        f"- 博主数量：{len(all_data)}",
    ]
    if self_name:
        lines.append(f"- 对比账号：{self_name}（差异化分析）")

    lines.extend([
        "",
        "## 你需要做什么",
        "",
        "### 1. 填充所有「核心发现」段落",
        "数据底稿中每个章节末尾都有 `> *(AI 执行时填充: ...)*` 标记。你需要将其替换为 2-4 条有数据支撑的核心洞察。",
        "每条发现必须引用具体数据，禁止模糊描述。",
        "",
        "### 2. 撰写「赛道竞争格局总结」",
        "在报告开头新增一段 3-5 段的执行摘要，包含：",
        "- 赛道整体特征（供给端 + 需求端）",
        "- 各博主的核心差异化定位（每人一句话）",
        "- 赛道最大的机会窗口",
        "",
        "### 3. 撰写「爆款规律对比」",
        "新增一章，横跨所有博主的 TOP10 爆款，提炼：",
        "- 赛道级爆款的共性特征（标题/封面/结构/情绪）",
        "- 各博主爆款的差异化要素",
        "- 低赞内容的共性避坑点",
        "",
        "### 4. 撰写「你的行动建议」（如有 --self）",
        "针对差异化机会分析中的数据，给出 5 条具体、可执行、有优先级的行动建议。",
        "每条建议格式：做什么 → 为什么（数据支撑）→ 怎么做（具体步骤）。",
        "",
        "## 写作准则（同博主拆解的 8 条标准）",
        "1. 有观点不骑墙 — 每个数据章节后必须有核心发现",
        "2. 有对比有洞察 — 不描述数据，解释差异背后的原因",
        "3. 有针对性建议 — 每条建议具体到可执行的动作",
        "4. 有因果解释 — 爆款原因用因果链，引评论附「→ 这说明...」",
        "5. 有层次感 — 重点博主深度展开，次要博主精简带过",
        "6. 有金句记忆点 — 结尾产出「赛道底层公式」",
        "7. 有数据锚点 — 禁止「表现较好」「比较活跃」等模糊用语",
        "8. 格式有节奏 — 数据=表格，分析=段落加粗，结论=引用块",
        "",
        "## 产出格式",
        "将最终报告保存为 Markdown，然后转 Word：",
        "```python",
        "from scripts.utils.md_to_docx import md_to_docx",
        "md_to_docx('赛道竞争格局_对比报告.md', '赛道竞争格局_对比报告.docx')",
        "```",
    ])

    return "\n".join(lines)


def generate_final_report(primer_path, output_dir):
    """
    将数据底稿转为 Word 文档。

    注意：数据底稿仍含 AI 占位符，AI 分析后才算最终报告。
    此函数生成的是"骨架版"Word，供 AI 覆盖。
    """
    docx_path = os.path.join(output_dir, "赛道竞争格局_对比报告.docx")
    try:
        md_to_docx(primer_path, docx_path)
        size_kb = os.path.getsize(docx_path) / 1024
        print(f"  📄 DOCX: {docx_path} ({size_kb:.0f}KB)")
        return docx_path
    except Exception as e:
        print(f"  ❌ DOCX 生成失败: {e}")
        return None


# ============================================================
#  主函数
# ============================================================

def cross_analyze(data_dir, output_dir, blogger_names=None, self_name=None):
    """
    执行跨博主横向对比分析。

    Args:
        data_dir: 数据目录路径
        output_dir: 输出目录路径
        blogger_names: 博主名列表（None = 自动发现）
        self_name: 自己的博主名（用于差异化分析）
    """
    os.makedirs(output_dir, exist_ok=True)

    # 确定博主列表
    if blogger_names:
        names = [n.strip() for n in blogger_names if n.strip()]
    else:
        names = discover_bloggers(data_dir)

    if not names:
        print("❌ 未找到任何博主数据。请检查 data_dir 路径。")
        return None

    # 如果有 self_name，追加到列表（避免重复）
    all_names = list(names)
    if self_name and self_name not in all_names:
        all_names.append(self_name)

    # 加载所有博主数据
    all_data = []
    missing = []
    for name in all_names:
        data = load_blogger_data(data_dir, name)
        if data:
            all_data.append(data)
        else:
            missing.append(name)

    if missing:
        print(f"⚠️  以下博主数据不可用，已排除：{', '.join(missing)}")

    if len(all_data) < 2:
        print(f"❌ 至少需要 2 位博主的有效数据，当前仅 {len(all_data)} 位。")
        return None

    print(f"\n{'='*60}")
    print(f"📊 赛道竞争格局分析")
    print(f"   数据目录: {data_dir}")
    print(f"   分析博主 ({len(all_data)}位): {', '.join(d['name'] for d in all_data)}")
    if self_name:
        self_found = any(d["name"] == self_name or d["safe_name"] == safe_filename(self_name) for d in all_data)
        if self_found:
            print(f"   对比账号: {self_name}（差异化分析已启用）")
        else:
            print(f"   ⚠️ 对比账号「{self_name}」数据未找到，跳过差异化分析")
    print(f"   输出目录: {output_dir}")
    print(f"{'='*60}\n")

    # 生成数据底稿
    primer_path = generate_data_primer(all_data, self_name, output_dir)

    # 生成 Word 骨架
    generate_final_report(primer_path, output_dir)

    print(f"\n✅ 赛道竞争格局分析完成！")
    print(f"   数据底稿: {primer_path}")
    print(f"   AI 执行: 读取数据底稿 → 填充核心发现 → 撰写执行摘要 → 覆盖 Word")
    return {"primer_path": primer_path, "blogger_count": len(all_data)}


# ============================================================
#  CLI
# ============================================================
if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="赛道竞争格局分析 — 跨博主横向对比",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 自动发现 data_dir 下所有博主
  python cross_analyze.py --data-dir ./data --output-dir ./output

  # 指定博主列表
  python cross_analyze.py --bloggers "博主A,博主B,博主C" --data-dir ./data --output-dir ./output

  # 包含自己账号的差异化分析
  python cross_analyze.py --data-dir ./data --output-dir ./output --self "我自己"
        """,
    )
    parser.add_argument("--data-dir", default="./data", help="数据目录路径")
    parser.add_argument("--output-dir", "-o", default="./output", help="输出目录路径")
    parser.add_argument("--bloggers", help="博主名列表（逗号分隔），不指定则自动发现")
    parser.add_argument("--self", dest="self_name", help="自己的博主名（用于差异化分析）")
    args = parser.parse_args()

    blogger_list = None
    if args.bloggers:
        blogger_list = [n.strip() for n in args.bloggers.split(",") if n.strip()]

    cross_analyze(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        blogger_names=blogger_list,
        self_name=args.self_name,
    )
