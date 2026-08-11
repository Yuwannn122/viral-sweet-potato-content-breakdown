"""数据可视化面板 v7 — 标准化 JSON payload，JS 动态渲染，账号切换器"""
import json, os, sys, argparse
from datetime import datetime
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_all_data(data_dir, blogger_names=None):
    """加载所有博主数据。与 v6 兼容，新增 top10 字段。"""
    from deep_analyze import (extract_comment_sentiment, extract_posting_heatmap,
                               detect_posting_frequency, extract_title_patterns, classify_content_track)
    from cross_analyze import discover_bloggers, load_blogger_data
    from analyze_viral_post import classify_hook_type

    if blogger_names:
        names = [n.strip() for n in blogger_names if n.strip()]
    else:
        names = discover_bloggers(data_dir)

    all_data = []
    for name in names:
        raw = load_blogger_data(data_dir, name)
        if not raw:
            continue
        notes = raw["notes"]
        freq = detect_posting_frequency(notes)
        sentiment = extract_comment_sentiment(raw["details"]) if raw["details_available"] else {}
        heatmap = extract_posting_heatmap(notes) if len(notes) >= 5 else {}
        titles = [n.get("title", "") for n in notes if n.get("title")]
        title_pats = extract_title_patterns(titles) if titles else {}
        track_dist = Counter()
        for n in notes:
            t = classify_content_track(n.get("title", ""), "", n.get("tags", []))
            track_dist[t.get("primary_track", "综合")] += 1
        hook_dist = Counter()
        for n in notes:
            hook_dist[classify_hook_type(n.get("title", ""), "").get("hook_type", "利益型")] += 1
        descs = []
        for item in raw["details"]:
            nd = item.get("data", {}).get("note", item)
            descs.append(nd.get("desc", "") or "")
        from deep_analyze import extract_cta_patterns, analyze_content_structure, extract_emoji_patterns
        cta_info = extract_cta_patterns(descs) if descs else {}
        struct_info = analyze_content_structure(descs) if descs else {}
        emoji_info = extract_emoji_patterns(descs) if descs else {}
        tl = raw["stats"].get("total_likes", 1) or 1
        tc = raw["stats"].get("total_collects", 0)
        sl_ratio = round(tc / tl, 2)
        if sl_ratio > 0.6:
            rl = "实用工具型"
        elif sl_ratio > 0.33:
            rl = "实用驱动型"
        elif sl_ratio > 0.2:
            rl = "均衡型"
        elif sl_ratio > 0.1:
            rl = "情绪共鸣型"
        else:
            rl = "强情绪共鸣型"
        al = raw["stats"].get("avg_likes", 0)
        ht = al * 3 if al > 0 else 1
        hit_rate = round(sum(1 for n in notes if n.get("likes", 0) >= ht) / max(raw["notes_count"], 1) * 100, 1)
        total_interact = tl + tc + raw["stats"].get("total_comments", 0)
        empty_pct = round(sum(1 for d in descs if not d or len(d) < 20) / max(len(descs), 1) * 100, 1)
        all_data.append({
            "name": raw["name"],
            "safe": raw["safe_name"],
            "stats": raw["stats"],
            "n": raw["notes_count"],
            "cats": raw["categories"],
            "freq": freq,
            "sentiment": sentiment,
            "heatmap": heatmap,
            "title_pats": title_pats,
            "track_dist": dict(track_dist),
            "hook_dist": dict(hook_dist),
            "td": {"图文": raw["stats"].get("normal_count", 0), "视频": raw["stats"].get("video_count", 0)},
            "sl": sl_ratio,
            "rl": rl,
            "hr": hit_rate,
            "al": al,
            "freq_label": freq.get("pattern", "?"),
            "cta": cta_info,
            "struct": struct_info,
            "emoji": emoji_info,
            "desc_empty_pct": empty_pct,
            "details_ok": raw["details_available"],
            "avg_interact": round(total_interact / max(raw["notes_count"], 1)),
            "top10": raw.get("top10", []),      # ★ v7 新增
            "tag_freq": raw.get("tag_freq", []),  # ★ v7 新增
        })
    return all_data


def build_dashboard_payload(all_data):
    """★ v7 新增：将内部数据结构转为标准化 Dashboard JSON payload。
    前端只需要处理这个 JSON，不再到处做 a?.b?.c?.d 防护。"""
    bloggers = []
    for d in all_data:
        s = d["stats"]
        sentiment = d.get("sentiment", {})
        score = sentiment.get("overall_score", 0) or 0

        if score > 0.3:
            sent_label = "偏正向"
        elif score > 0:
            sent_label = "中性偏正"
        elif score > -0.3:
            sent_label = "中性"
        else:
            sent_label = "偏负向"

        # 计算爆款阈值
        al = d["al"]
        ht = al * 3 if al > 0 else 1
        tl = s.get("total_likes") or 0
        tc = s.get("total_collects") or 0
        tm = s.get("total_comments") or 0
        total_interact = tl + tc + tm

        # 处理 top10 数据——前端直接渲染
        # ★ 所有数字保持原始数值，格式化交给 JS 的 fmt() 统一处理，避免双格式化产生 NaN
        top10 = []
        for i, note in enumerate(d.get("top10", [])[:10]):
            n_likes = note.get("likes", 0)
            n_collects = note.get("collects", 0)
            n_comments = note.get("comments_count", 0)
            n_interact = n_likes + n_collects + n_comments
            burst_level = (
                "🔥🔥🔥 超级爆款" if n_likes >= al * 10 else
                "🔥🔥 大爆款" if n_likes >= al * 5 else
                "🔥 小爆款" if n_likes >= al * 3 else
                "普通"
            )
            top10.append({
                "rank": i + 1,
                "title": note.get("title", ""),
                "likes": n_likes,
                "collects": n_collects,
                "comments": n_comments,
                "interact": n_interact,
                "burst_level": burst_level,
                "type": note.get("type", "normal"),
                "time": note.get("time", 0),
                "time_str": _ms_to_str(note.get("time", 0)),
            })

        # 赛道分布 (top 8)
        td = d.get("track_dist", {})
        tracks = sorted(td.items(), key=lambda x: x[1], reverse=True)[:8]

        # 钩子分布
        hd = d.get("hook_dist", {})

        # 标题模式
        tp = d.get("title_pats", {})
        pattern_names = ["数字型", "疑问型", "感叹型", "教程型", "列表型", "对比型", "故事型", "悬念型"]
        title_patterns = [
            {"name": pn, "pct": (tp.get(pn, {}) or {}).get("pct", 0)}
            for pn in pattern_names
        ]

        # CTA
        cta_labels = ["关注", "收藏", "点赞", "评论", "转发", "私信"]
        ci = d.get("cta", {})
        cta = [{"label": l, "pct": (ci.get(f"{l}引导", {}) or {}).get("pct", 0)} for l in cta_labels]

        # 热搜map
        hm = d.get("heatmap", {})
        heatmap = None
        mx = hm.get("hour_day_matrix")
        if mx and len(mx) == 7:
            maxv = max(max(r) for r in mx) if mx else 1
            heatmap = {
                "matrix": mx,
                "days": hm.get("day_names_cn", ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]),
                "slots": hm.get("time_slots", ["00-06", "06-08", "08-12", "12-14", "14-18", "18-21", "21-24"]),
                "maxv": maxv,
                "best_day": hm.get("best_day", "—"),
                "best_hour": hm.get("best_hour_block", "—"),
            }

        # 评论情感
        sr = d.get("sentiment", {})
        pn_list = sr.get("per_note", [])
        if pn_list:
            avg_pos = round(sum(p.get("positive_pct", 0) for p in pn_list) / len(pn_list), 1)
            avg_neu = round(sum(p.get("neutral_pct", 0) for p in pn_list) / len(pn_list), 1)
            avg_neg = round(sum(p.get("negative_pct", 0) for p in pn_list) / len(pn_list), 1)
        else:
            avg_pos = avg_neu = avg_neg = 0

        bloggers.append({
            "id": d["safe"],
            "name": d["name"],
            "stats": {
                "total_notes": d["n"],
                "video_count": s.get("video_count", 0),
                "normal_count": s.get("normal_count", 0),
                "total_likes": tl,
                "total_collects": tc,
                "total_comments": tm,
                "avg_likes": al,
                "avg_collects": s.get("avg_collects", 0) or 0,
                "avg_comments": s.get("avg_comments", 0) or 0,
                "avg_interact": d["avg_interact"],
                "hit_rate": d["hr"],
                "hit_threshold": ht,
                "sl_ratio": d["sl"],
                "ratio_label": d["rl"],
                "freq_label": d["freq_label"],
                "sentiment_score": round(score, 2),
                "sentiment_label": sent_label,
            },
            "content": {
                "tracks": [{"name": t[0], "count": t[1]} for t in tracks],
                "hooks": [{"name": k, "count": v} for k, v in sorted(hd.items(), key=lambda x: x[1], reverse=True)],
                "title_patterns": title_patterns,
                "cta": cta,
                "cta_all_zero": all(v["pct"] == 0 for v in cta),
                "format": {"video": d["td"].get("视频", 0), "normal": d["td"].get("图文", 0)},
                "desc_empty_pct": d["desc_empty_pct"],
                "details_ok": d["details_ok"],
            },
            "viral": {
                "top10": top10,
                "hit_rate": d["hr"],
                "sl_ratio": d["sl"],
                "interact": {
                    "likes_pct": round(tl / max(total_interact, 1) * 100, 1),
                    "collects_pct": round(tc / max(total_interact, 1) * 100, 1),
                    "comments_pct": round(tm / max(total_interact, 1) * 100, 1),
                },
            },
            "heatmap": heatmap,
            "sentiment": {
                "score": round(score, 2),
                "label": sent_label,
                "avg_positive_pct": avg_pos,
                "avg_neutral_pct": avg_neu,
                "avg_negative_pct": avg_neg,
                "total_comments_analyzed": sr.get("total_comments_analyzed", 0),
                "positive_examples": sr.get("positive_examples", [])[:3],
                "negative_examples": sr.get("negative_examples", [])[:3],
            },
            # 用于规则化 AI 总结的元数据
            "insights": {
                "top_track": tracks[0][0] if tracks else "未知",
                "top_hook": max(hd, key=hd.get) if hd else "未知",
                "top_pattern": _best_title_pattern(title_patterns),
                "dominant_format": "视频" if d["td"].get("视频", 0) >= d["td"].get("图文", 0) else "图文",
                "best_day": (hm.get("best_day") or "—") if hm else "—",
                "best_hour": (hm.get("best_hour_block") or "—") if hm else "—",
                "has_enough_data": d["n"] >= 5,
            },
        })

    return {
        "version": "7.0",
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "bloggerCount": len(bloggers),
        "bloggers": bloggers,
    }


def _best_title_pattern(title_patterns):
    """从标题模式列表中找到占比最高的那个名字。"""
    if not title_patterns:
        return "未知"
    best_name, best_pct = "未知", 0
    for p in title_patterns:
        if p["pct"] > best_pct:
            best_pct = p["pct"]
            best_name = p["name"]
    return best_name if best_pct > 0 else "未知"


def _fmt(n):
    """格式化数字为千分位字符串。"""
    if n is None or (isinstance(n, float) and n != n):
        return "—"
    return f"{int(n):,}" if isinstance(n, (int, float)) else str(n)


def _ms_to_str(ms):
    """毫秒时间戳 → 日期字符串。"""
    if not ms:
        return "—"
    try:
        from datetime import timezone
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def generate_dashboard(data_dir, output_dir, blogger_names=None):
    """主入口：加载数据 → 构建 payload → 注入模板 → 输出 HTML"""
    all_data = load_all_data(data_dir, blogger_names)
    if not all_data:
        print("No data found")
        return

    payload = build_dashboard_payload(all_data)
    html = make_html(payload)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "数据可视化面板.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated: {path} ({os.path.getsize(path) / 1024:.0f}KB)")
    return path


def make_html(payload):
    """将 payload 序列化为 JSON 并注入 HTML 模板。"""

    # ★ 安全：JSON 中不直接嵌入 </script>，防止 HTML 截断
    data_json = json.dumps(payload, ensure_ascii=False, default=str)
    data_json = data_json.replace("</", "<\\/")

    # 读取 Chart.js 本地文件（base64 内嵌，保证离线可用）
    chartjs_code = ""
    chartjs_path = os.path.join(os.path.dirname(__file__), "chart.umd.min.js")
    if os.path.exists(chartjs_path):
        with open(chartjs_path, "r", encoding="utf-8") as f:
            chartjs_code = f.read()

    # 读取 HTML 模板
    template_path = os.path.join(os.path.dirname(__file__), "dashboard_template_v7.html")
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("__DATA_JSON__", data_json)
    html = html.replace("__CHARTJS__", chartjs_code)
    return html


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="数据可视化面板 v7")
    p.add_argument("--data-dir", default="./data")
    p.add_argument("--output-dir", "-o", default="./output")
    p.add_argument("--bloggers")
    args = p.parse_args()
    bl = [n.strip() for n in args.bloggers.split(",") if n.strip()] if args.bloggers else None
    generate_dashboard(args.data_dir, args.output_dir, bl)
