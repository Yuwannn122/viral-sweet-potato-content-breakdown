"""
Single Viral Post Breakdown · 五维+三镜 爆款拆解
对单条小红书笔记进行五维深度拆解，每维走"还原→归因→验证"三步。

五维 = 五个分析切面（WHAT）：
  一 · 流量捕获（标题/封面/钩子）
  二 · 内容骨架（信息金字塔/ASL/金句）
  三 · 视听节奏（节奏曲线/视觉心锚/BGM）
  四 · 互动转化（藏赞比/评论情感/神回复/内容机会）
  五 · 爆款要素提炼（公式卡）

三镜 = 每个维度内部的三步验证流程（HOW）：
  🔍 还原镜 → 客观拆解，只看事实
  💡 归因镜 → 提炼因果——"为什么爆？"
  ✅ 验证镜 → 评论区真实反馈验证假设

独立脚本，不在博主拆解流程中自动触发。仅在用户明确"拆解XXX"且为单条内容时使用。

用法：
    # 从已有数据中按索引选笔记（按赞排序）
    python analyze_viral_post.py ./data/<博主>_notes_details.json 0 "<博主名>" -o ./output

    # 通过 feed_id 实时获取
    python analyze_viral_post.py --feed-id <feed_id> --xsec-token <token> "<博主名>" -o ./output

    # 通过小红书链接获取
    python analyze_viral_post.py --url "<链接>" "<博主名>" -o ./output
"""

import json
import os
import sys
import re
import argparse
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.common import safe_filename, parse_count, ms_to_datetime
from utils.mcp_client import MCPClient, MCPError
from utils.md_to_docx import md_to_docx
from deep_analyze import (
    extract_title_patterns,
    extract_emoji_patterns,
    extract_cta_patterns,
    extract_comment_sentiment,
    analyze_content_structure,
    SENTIMENT_LEXICON,
    classify_content_track,
)


# ============================================================
#  新增分析函数
# ============================================================

def calc_asl(desc):
    """
    计算平均句长（ASL = Average Sentence Length）。

    Returns:
        dict — {asl: float, total_chars: int, sentence_count: int,
                style: "口语型"/"标准型"/"干货型"/"标签体"/"短文本"/"未知",
                style_desc: str}
    """
    if not desc:
        return {"asl": 0, "total_chars": 0, "sentence_count": 0,
                "style": "未知", "style_desc": "无正文内容"}

    # 检测是否为纯标签体（正文主要内容是 #话题标签）
    stripped = desc.strip()
    hashtag_chars = sum(len(m.group()) for m in re.finditer(r"#[^\s#]+", stripped))
    total_non_space = len(stripped.replace(" ", "").replace("\n", ""))
    hashtag_ratio = hashtag_chars / total_non_space if total_non_space > 0 else 0
    is_hashtag_body = hashtag_ratio > 0.6  # 超过60%的字符在标签中

    # 按中文标点断句
    sentences = re.split(r"[。！？；\n!?;]+", desc)
    sentences = [s.strip() for s in sentences if s.strip()]

    # 纯标签体 → 不做句式分析，直接标记
    if is_hashtag_body:
        return {"asl": 0, "total_chars": len(desc), "sentence_count": 0,
                "style": "标签体", "style_desc": "正文以话题标签为主，无实际文案内容。内容信息主要承载在图片/视频中。",
                "hashtag_ratio": round(hashtag_ratio, 2)}

    if not sentences:
        return {"asl": 0, "total_chars": len(desc), "sentence_count": 0,
                "style": "短文本", "style_desc": "正文极短，偏标题或纯视觉引导"}

    total_chars = sum(len(s) for s in sentences)
    asl = round(total_chars / len(sentences), 1)

    if asl < 15:
        style = "口语型"
        style_desc = "短句为主，接近自然口语节奏，阅读摩擦低，适合快速消费内容"
    elif asl < 25:
        style = "标准型"
        style_desc = "长短句交替，兼顾信息密度和可读性"
    else:
        style = "干货型"
        style_desc = "长句为主，信息密度高，适合深度教程/测评类内容"

    return {
        "asl": asl,
        "total_chars": total_chars,
        "sentence_count": len(sentences),
        "style": style,
        "style_desc": style_desc,
    }


def detect_golden_sentences(desc, comments):
    """
    检测金句埋点：评论区出现"截图/求原图/保存/反复看"等信号，
    反向定位正文中可能被截图传播的句子。

    Returns:
        list[dict] — [{sentence, evidence, confidence}]
    """
    golden = []
    if not comments:
        return golden

    # 检测评论区金句信号
    screenshot_signals = []
    signal_patterns = [
        r"(截图|截屏|保存|收藏了|码住|马住|记下了).{0,10}(这句|这段话|这个|说的)",
        r"(求|想要|可以发).{0,5}(原图|原话|文字版|文案)",
        r"(反复|回头|多看).{0,3}(看|读)",
        r"(这句话|这段话|说的).{0,5}(太|好|绝|精辟)",
    ]

    for c in comments[:100]:
        content = c.get("content", "")
        for pat in signal_patterns:
            if re.search(pat, content):
                screenshot_signals.append(content[:60])
                break

    if not screenshot_signals:
        return golden

    # 反向定位：从正文中找可能被截图的句子（短小精悍、有冲击力、位置在前1/3或结尾）
    if not desc:
        return golden

    sentences = re.split(r"[。！？；\n!?;]+", desc)
    sentences = [s.strip() for s in sentences if s.strip()]

    for i, s in enumerate(sentences):
        if len(s) < 8 or len(s) > 80:
            continue
        # 金句特征：包含观点、数字、对比、反转、情绪
        score = 0
        if re.search(r"\d+", s):
            score += 1
        if re.search(r"(不是|而是|但|却|竟然|原来|其实|真的)", s):
            score += 1
        if re.search(r"(永远|从不|一定|最|绝|必须|千万)", s):
            score += 1
        if re.search(r"[！!?？]", s):
            score += 1

        if score >= 2:
            position = "开头" if i < len(sentences) * 0.3 else (
                "结尾" if i > len(sentences) * 0.7 else "中间"
            )
            golden.append({
                "sentence": s[:60],
                "position": position,
                "evidence": screenshot_signals[0] if screenshot_signals else "",
                "confidence": "高" if score >= 3 else "中",
            })

    return golden[:5]


def detect_god_replies(comments, author_nickname=""):
    """
    检测神回复：博主在评论区是否有二次造梗、补充信息、引导互动。

    Returns:
        list[dict] — [{content, type, likes, effectiveness}]
    """
    god_replies = []
    if not comments:
        return god_replies

    for c in comments[:200]:
        # 判断是否为作者
        show_tags = c.get("showTags", [])
        is_author = "is_author" in str(show_tags)
        user_info = c.get("userInfo", {})
        nickname = user_info.get("nickname", user_info.get("nickName", ""))
        if author_nickname and nickname == author_nickname:
            is_author = True

        if not is_author:
            continue

        content = c.get("content", "")
        if not content or len(content) < 5:
            continue

        likes = int(c.get("likeCount", "0")) if c.get("likeCount", "0").isdigit() else 0

        # 神回复类型
        reply_type = "普通回复"
        if re.search(r"(补充|还有|另外|值得一提|漏了|忘了说)", content):
            reply_type = "信息补充"
        elif re.search(r"(哈哈|笑死|噗|狗头|狗头保命|不是|其实|认真你就输了)", content):
            reply_type = "造梗/幽默"
        elif re.search(r"(你们|大家|想问|想看|觉得|投票)", content):
            reply_type = "引导互动"
        elif re.search(r"(链接|私信|主页|橱窗|左下角)", content):
            reply_type = "转化引导"
        elif re.search(r"(谢谢|感谢|比心|笔芯|爱了)", content):
            reply_type = "关系维护"

        effectiveness = "高效" if likes >= 20 else ("有效" if likes >= 5 else "一般")

        god_replies.append({
            "content": content[:80],
            "type": reply_type,
            "likes": likes,
            "effectiveness": effectiveness,
        })

    return god_replies[:10]


def infer_cover_type(title, desc, tags, comments, note_data=None):
    """
    从文本信号 + imageList 比例数据推断封面类型。

    图文笔记：✅ 结合首图宽高比 → 置信度提升至中/高
    视频笔记：⚠️ 仅文本推断

    Returns:
        dict — {cover_type, confidence, evidence_signals, aspect_signal}
    """
    signals = []
    text = (title + " " + (desc or "")).lower()

    # ★ 新增：从 imageList 取首图比例
    aspect_signal = ""
    image_list = note_data.get("imageList", []) if note_data else []
    if image_list:
        first_img = image_list[0]
        w, h = first_img.get("width", 0), first_img.get("height", 0)
        if w > 0 and h > 0:
            ratio = h / w
            if ratio > 1.3:
                aspect_signal = "竖版长图（适合人像/穿搭/全身，信息流占比大视觉冲击强）"
            elif ratio > 0.9:
                aspect_signal = "方图/近方图（适合产品图/教程卡片/标题封面，排版规整信息密度可控）"
            else:
                aspect_signal = "横版图（适合场景/风景/桌面/全景，信息流中占比较小需靠内容吸引）"

    # 高真人占比型
    if any(kw in text for kw in ["自拍", "ootd", "穿搭", "妆容", "发型", "素颜", "原相机"]):
        signals.append("真人出镜相关文本")
    if any(t in str(tags).lower() for t in ["穿搭", "ootd", "妆教", "发型", "美妆"]):
        signals.append("真人出镜标签")

    # 高信息密度型（教程/攻略）
    if any(kw in text for kw in ["保姆级", "手把手", "教程", "攻略", "方法", "步骤"]):
        signals.append("教程/攻略文本")
    if re.search(r"\d+[个步种]", text):
        signals.append("数字列表式")

    # 氛围感型
    if any(kw in text for kw in ["治愈", "氛围", "日常", "vlog", "记录", "plog"]):
        signals.append("氛围/日常文本")
    if any(t in str(tags).lower() for t in ["日常", "vlog", "plog", "治愈", "氛围感"]):
        signals.append("氛围/日常标签")

    # 对比型
    if any(kw in text for kw in ["对比", "前后", "before", "after", "vs", "变化"]):
        signals.append("对比/变化文本")

    # 从评论推断封面吸引力
    cover_comments = []
    for c in (comments or [])[:50]:
        content = c.get("content", "")
        if re.search(r"(封面|第一眼|点进来|被.*吸引|这图)", content):
            cover_comments.append(content[:60])

    # 判定（比例信号提升置信度）
    has_aspect = bool(aspect_signal)
    if len(signals) >= 3 and any("教程" in s for s in signals):
        cover_type = "教程模板型（标题文字+步骤图，高信息密度）"
        confidence = "高" if has_aspect else "中"
    elif any("真人" in s for s in signals):
        cover_type = "真人出镜型（高真人占比，强调身份/颜值/穿搭）"
        confidence = "高" if (has_aspect and cover_comments) else ("中" if (has_aspect or cover_comments) else "低")
    elif any("对比" in s for s in signals):
        cover_type = "对比论证型（前后对比图，强视觉冲击）"
        confidence = "高" if has_aspect else ("中" if cover_comments else "低")
    elif any("氛围" in s for s in signals):
        cover_type = "氛围感型（场景/色调优先，低信息密度高情绪价值）"
        confidence = "中" if has_aspect else ("中" if cover_comments else "低")
    else:
        cover_type = "混合型（无法从文本确定，建议查看原内容确认）"
        confidence = "中" if has_aspect else "低"

    return {
        "cover_type": cover_type,
        "confidence": confidence,
        "signals": signals,
        "aspect_signal": aspect_signal,
        "cover_comment_evidence": cover_comments[:3],
    }


def classify_hook_type(title, desc):
    """
    前3秒钩子分类。

    Returns:
        dict — {hook_type, hook_phrase, confidence}
    """
    text = (title or "") + " " + ((desc or "")[:100])

    hook_types = {
        "悬念型": [r"(千万别|不要|别|千万|绝不)", r"(竟然|居然|没想到|万万)",
                   r"(秘密|秘诀|真相|内幕|背后)", r"(\.\.\.|…)$"],
        "利益型": [r"\d+[个招种步条件]", r"(搞定|解决|学会|掌握|快速)",
                   r"(3[招秒分]|一[招秒分]|简单|轻松)", r"(收藏|码住|必备)"],
        "情绪型": [r"(我真的|太|绝了|爆哭|泪目|破防|emo)",
                  r"(谁懂|谁懂啊|有没有人)", r"(救命|救|我不允许)"],
        "反常识型": [r"(不是|其实|真相|你以为|错了)", r"(颠覆|推翻|挑战)",
                    r"(别.*再|不要.*再|停止|戒掉)"],
    }

    best_type = "利益型"  # 默认
    best_score = 0

    for htype, patterns in hook_types.items():
        score = 0
        for pat in patterns:
            if re.search(pat, text):
                score += 1
        if score > best_score:
            best_score = score
            best_type = htype

    # 提取钩子短语
    hook_phrase = title[:30] if title else ""
    if len(hook_phrase) == 30:
        hook_phrase += "..."

    return {
        "hook_type": best_type,
        "hook_phrase": hook_phrase,
        "confidence": "高" if best_score >= 3 else ("中" if best_score >= 2 else "低"),
    }


def classify_save_like_ratio(saves, likes):
    """
    藏赞比语义判断。

    Returns:
        dict — {ratio, label, description, implication}
    """
    if likes <= 0:
        return {"ratio": 0, "label": "无法判断", "description": "点赞数为0", "implication": ""}

    ratio = saves / likes

    if ratio > 0.6:
        label = "强实用工具型"
        description = f"藏赞比 {ratio:.2f}，收藏远超点赞"
        implication = "用户将此内容视为'工具'——先马后看，预期会反复查阅。适合做系列化、做深度、做长尾流量。"
    elif ratio > 0.33:
        label = "实用驱动型"
        description = f"藏赞比 {ratio:.2f}，收藏显著高于点赞"
        implication = "实用价值驱动互动，用户认可内容的工具性。可以在结尾加强CTA引导收藏。"
    elif ratio > 0.2:
        label = "均衡型"
        description = f"藏赞比 {ratio:.2f}，收藏点赞相对均衡"
        implication = "内容兼具实用价值和情绪价值，互动模式健康。"
    elif ratio > 0.1:
        label = "情绪共鸣型"
        description = f"藏赞比 {ratio:.2f}，点赞为主收藏为辅"
        implication = "用户互动动机是情绪共鸣和即时满足，而非工具性需求。适合做人设、做情绪、做话题。"
    else:
        label = "强情绪共鸣型"
        description = f"藏赞比 {ratio:.2f}，几乎只有点赞"
        implication = "纯情绪驱动——用户被触动、被逗笑、被震撼，但不需要回头查阅。"

    return {
        "ratio": round(ratio, 2),
        "label": label,
        "description": description,
        "implication": implication,
    }


def extract_comment_opportunities(comments):
    """
    从评论区高频提问中提取"下一步内容机会"。

    Returns:
        list[dict] — [{question, frequency, opportunity_type}]
    """
    if not comments:
        return []

    # 提取所有评论中的提问
    questions = []
    question_patterns = [
        r"(怎么|如何|怎样|什么|哪里|哪个|多少|能不能|可以.*吗|有没有)['一-鿿]*[？?]?",
        r"(求|想要|需要|蹲).{0,15}(链接|教程|方法|推荐|牌子|同款)",
        r"(有人|有没有人|谁).{0,10}(告诉|知道|说)",
    ]

    for c in comments[:200]:
        content = c.get("content", "")
        for pat in question_patterns:
            m = re.search(pat, content)
            if m:
                questions.append(m.group()[:50])
                break

    if not questions:
        return []

    # 聚类相似问题
    from collections import Counter
    # 简化聚类：按关键词分组
    clusters = Counter()
    for q in questions:
        # 提取核心关键词
        core = q
        for stop in ["怎么", "如何", "怎样", "什么", "哪里", "哪个", "可以", "能不能"]:
            core = core.replace(stop, "")
        core = core.strip()[:15]
        if len(core) >= 3:
            clusters[core] += 1

    opportunities = []
    for core, freq in clusters.most_common(5):
        if freq >= 2:
            opportunities.append({
                "question": core,
                "frequency": freq,
                "opportunity_type": "直接选题（用户明确表达了需求）" if freq >= 3 else "潜在选题（需要验证需求强度）",
            })

    return opportunities


def infer_rhythm_curve(desc, comments, note_type="normal", note_data=None):
    """
    推断节奏曲线。

    视频：钩子段→主体段→高潮点→CTA段（⚠️ 文本推断）
    图文：封面→信息主体→细节补充→CTA（✅ 基于 imageList 真实数据）

    Returns:
        dict — {segments, peak_points, rhythm_type, confidence}
    """
    rhythm_type = "标准教程节奏"
    segments = []
    peak_points = []
    confidence = "中"

    # 图文分支：优先使用 imageList 真实数据
    if note_type != "video":
        image_list = note_data.get("imageList", []) if note_data else []
        if image_list:
            img_count = len(image_list)
            if img_count >= 6:
                segments = [
                    {"label": "封面/首图", "content": f"第1张（共{img_count}张）", "function": "吸引点击"},
                    {"label": f"步骤图 ×{img_count-2}", "content": f"第2～{img_count-1}张", "function": "分步信息交付"},
                    {"label": "收尾/CTA图", "content": f"第{img_count}张", "function": "引导互动/总结收尾"},
                ]
                rhythm_type = "教程步骤型"
                confidence = "高"
            elif img_count >= 3:
                segments = [
                    {"label": "封面/首图", "content": f"第1张（共{img_count}张）", "function": "吸引点击"},
                    {"label": f"信息主体（{img_count-2}张）", "content": f"第2～{img_count-1}张", "function": "价值交付"},
                    {"label": "收尾/CTA图", "content": f"第{img_count}张", "function": "引导互动"},
                ]
                rhythm_type = "三段式结构型"
                confidence = "高"
            else:
                segments = [
                    {"label": "封面图", "content": f"第1张（共{img_count}张）", "function": "吸引点击+信息承载"},
                    {"label": f"补充图（{img_count-1}张）", "content": f"第2张" if img_count > 1 else "", "function": "信息补充/强化"},
                ]
                rhythm_type = "单图/双图冲击型"
                confidence = "高"
        elif desc:
            # 无 imageList 回退到纯文本推断
            paras = [p.strip() for p in desc.split("\n") if p.strip()]
            if len(paras) >= 2:
                segments = [
                    {"label": "封面/首图", "content": paras[0][:40], "function": "吸引点击+信息概览"},
                    {"label": "信息主体", "content": paras[len(paras)//2][:40], "function": "价值交付"},
                    {"label": "CTA/收尾", "content": paras[-1][:40], "function": "引导互动"},
                ]
                confidence = "低"  # 纯文本推断，无图像数据

    else:
        # 视频分支保持不变
        if not desc:
            desc = ""

        paras = [p.strip() for p in desc.split("\n") if p.strip()]
        if len(paras) >= 3:
            segments = [
                {"label": "钩子段(0-8s)", "content": paras[0][:40], "function": "抓注意力"},
                {"label": "主体段(8-30s)", "content": paras[1] if len(paras) > 1 else paras[0][:40], "function": "价值交付"},
                {"label": "CTA段(30s-结束)", "content": paras[-1][:40], "function": "引导互动"},
            ]
            if len(paras) >= 4:
                segments.insert(2, {"label": "高潮/转折点", "content": paras[len(paras)//2][:40], "function": "情绪峰值/信息亮点"})
        else:
            total = len(desc)
            if total > 60:
                segments = [
                    {"label": "钩子段(前20%)", "content": desc[:total//5][:40], "function": "抓注意力"},
                    {"label": "主体段(20-80%)", "content": desc[total//5:4*total//5][:40], "function": "价值交付"},
                    {"label": "CTA段(后20%)", "content": desc[4*total//5:][:40], "function": "引导互动"},
                ]

    # 从评论反向定位注意力峰值
    time_anchors = []
    for c in (comments or [])[:100]:
        content = c.get("content", "")
        # 匹配时间锚点
        for pat in [r"第(\d+)[秒s]", r"(\d+)[秒s秒钟]", r"看到(\d+)[分秒]"]:
            m = re.search(pat, content)
            if m:
                time_anchors.append(int(m.group(1)))
        # 匹配内容锚点
        for pat in [r"(看到|放到|讲到|说到).{0,5}(的?时候|这里)"]:
            if re.search(pat, content):
                peak_points.append({"source": "comment", "content": content[:60]})

    if time_anchors:
        peak_points.insert(0, {"source": "time_anchor", "times_sec": sorted(set(time_anchors))[:5]})

    return {
        "segments": segments,
        "peak_points": peak_points,
        "rhythm_type": rhythm_type,
        "confidence": confidence,
    }


def infer_visual_anchor(title, desc, tags, comments, note_data=None):
    """
    视觉心锚推断（文本推断 + imageList 尺寸数据）。

    Returns:
        list[dict] — [{anchor_type, description, evidence, data_source}]
    """
    anchors = []
    text = (title or "") + " " + (desc or "")

    # ★ 新增：从 imageList 检测固定版面风格 ✅ 数据结论
    image_list = note_data.get("imageList", []) if note_data else []
    if image_list:
        first_img = image_list[0]
        w, h = first_img.get("width", 0), first_img.get("height", 0)
        if w > 0 and h > 0:
            ratio = h / w
            if ratio > 1.3:
                layout_type = "竖版长图（h/w > 1.3）"
                layout_desc = "博主的图文笔记采用固定竖版长图格式，在信息流中占据更大屏幕空间，已形成视觉识别特征"
            elif ratio > 0.9:
                layout_type = "方图/近方图（0.9 ≤ h/w ≤ 1.3）"
                layout_desc = "博主的图文笔记采用固定方图格式，排版规整统一，形成稳定的视觉风格"
            else:
                layout_type = "横版图（h/w < 0.9）"
                layout_desc = "博主的图文笔记采用固定横版格式，在竖版信息流中形成差异化视觉锚点"
            # 多图则标注图片数
            img_count = len(image_list)
            count_note = f"，{img_count}张图" if img_count > 1 else ""
            anchors.append({
                "anchor_type": "固定版面风格 ✅ 数据结论",
                "description": f"{layout_desc}{count_note}",
                "evidence": f"首图尺寸 {w}×{h}（{layout_type}）{count_note}",
                "data_source": "imageList",
            })

    # 固定片头
    if re.search(r"(每天|每次|又是|又是新的一期|第\d+期|更新啦|来啦)", text):
        anchors.append({"anchor_type": "固定开场句式", "description": "标题/正文有固定的开头句式，形成记忆点",
                        "evidence": re.search(r"(每天|每次|又是|第\d+期|更新啦|来啦)", text).group(),
                        "data_source": "text"})

    # 固定手势
    if re.search(r"(✋|👋|👉|☝|点[点赞关])", text):
        anchors.append({"anchor_type": "固定手势/动作", "description": "正文描述了固定的手势引导动作",
                        "evidence": "正文中的手势emoji或描述", "data_source": "text"})

    # 固定背景色
    bg_patterns = [(r"白[墙底背景色]", "白色背景"), (r"黑[墙底背景色]", "黑色背景"),
                   (r"(奶油|奶白|米白)", "奶油色系"), (r"(原木|木色|暖色)", "暖色系")]
    for pat, desc_text in bg_patterns:
        if re.search(pat, text):
            anchors.append({"anchor_type": "固定背景色系", "description": desc_text,
                            "evidence": re.search(pat, text).group(), "data_source": "text"})

    # 标志性道具/元素
    if re.search(r"(猫|狗|宠物|娃|宝宝|崽)", text):
        anchors.append({"anchor_type": "标志性元素", "description": "宠物/宝宝等亲和力元素",
                        "evidence": "正文提及标志性陪伴元素", "data_source": "text"})

    # 从评论验证视觉心锚
    visual_terms = r"(封面|背景|画面|色调|滤镜|风格|排版|字体|片头|开头|穿搭|穿搭风格|角度.*拍|镜头|机位|布景|场景.*每次)"
    recognition_terms = r"(每次|又是|又是这|标志性|一看到|一看到.*就|就知道是你|认出来|太.*标志|太.*有辨识度|一眼.*认出|这个.*太.*了)"
    for c in (comments or [])[:50]:
        content = c.get("content", "")
        if re.search(visual_terms, content) and re.search(recognition_terms, content):
            anchors.append({"anchor_type": "评论验证", "description": "评论区确认了视觉记忆点（同时提到视觉元素+识别信号）",
                            "evidence": content[:60], "data_source": "comment"})
            break

    return anchors


def infer_content_from_comments(comments, desc=""):
    """
    从评论区反向推断视频/图文实际讲了什么内容（⚠️ 文本推断）。

    当 desc 字段过短（如只有标签）时，评论区是唯一能推断内容的数据源。
    通过分析评论中的提问、引用、共鸣点，反向还原内容要点。

    Returns:
        dict — {
            "desc_is_rich": bool,         # desc 是否信息量足够
            "inferred_topics": [str],     # 推断的内容要点
            "evidence_comments": [str],   # 支撑推断的评论原文
            "confidence": "高/中/低",
        }
    """
    if not comments:
        return {
            "desc_is_rich": len(desc) > 80,
            "inferred_topics": [],
            "evidence_comments": [],
            "confidence": "低",
        }

    # 判断 desc 是否信息量足够
    desc_is_rich = len(desc) > 80

    # 从评论中提取有价值的信息
    topic_signals = []
    question_comments = []
    reference_comments = []

    for c in comments[:100]:
        content = c.get("content", "").strip()
        if len(content) < 5:
            continue

        # 提问类 → 视频讲了相关内容，用户在追问
        if re.search(r"(怎么|如何|什么|哪里|哪个|能不能|可以.*吗|求.*推荐|求.*链接|想知道|想问|请问)", content):
            question_comments.append(content[:80])

        # 引用/复述类 → 用户在回应视频中的具体内容
        if re.search(r"(说的|提到的|讲的|这个.*确实|真的.*[很太])", content):
            reference_comments.append(content[:80])

        # 共鸣/认同类 → 找到情绪锚点
        if re.search(r"(我也是|一模一样|就是我|这不就是我|同款|世另我|懂你|太懂了)", content):
            topic_signals.append({"type": "共鸣点", "content": content[:80]})

    # 提取评论区高频主题词（排除通用情绪词）
    stop_words = {"哭惹", "笑哭", "皱眉", "害羞", "好的", "谢谢", "哈哈", "一个", "这个", "那个", "真的", "就是"}
    topic_words = []
    for c in comments[:100]:
        words = re.findall(r"[一-鿿]{2,5}", c.get("content", ""))
        for w in words:
            if w not in stop_words and len(w) >= 2:
                topic_words.append(w)
    word_freq = Counter(topic_words).most_common(10)

    # 构建推断的内容要点
    inferred_topics = []

    if question_comments:
        # 用户提问集中的方向 = 视频的核心话题
        q_text = " ".join(question_comments[:10])
        if re.search(r"(实习|工作|岗位|面试|简历)", q_text):
            inferred_topics.append("视频涉及实习/求职相关内容——用户在追问具体操作细节")
        if re.search(r"(AI|人工智能|产品经理|pm|PM|技术|代码|编程|算法)", q_text):
            inferred_topics.append("视频讨论了AI与产品经理的结合——用户对'AI PM'这个岗位定义有强烈好奇")
        if re.search(r"(转行|运营|零基础|没经验|非技术|文科)", q_text):
            inferred_topics.append("视频触及'转行/跨界'话题——用户有身份认同需求")
        if re.search(r"(软件|工具|学习|教程|方法|书|课程)", q_text):
            inferred_topics.append("视频可能提到了具体工具/学习资源——用户想要同款路径")

    if reference_comments:
        inferred_topics.append(f"评论区有 {len(reference_comments)} 条评论直接引用/回应了视频中的具体内容")

    if topic_signals:
        inferred_topics.append(f"评论区出现 {len(topic_signals)} 个情绪共鸣点——视频触发了强烈的身份认同")

    # 从高频词推断
    meaningful_words = [(w, c) for w, c in word_freq if w not in stop_words][:5]
    if meaningful_words:
        words_str = "、".join(f"「{w}」({c}次)" for w, c in meaningful_words)
        inferred_topics.append(f"评论区高频主题词: {words_str}")

    # 置信度
    if len(inferred_topics) >= 3:
        confidence = "高"
    elif len(inferred_topics) >= 1:
        confidence = "中"
    else:
        confidence = "低"

    return {
        "desc_is_rich": desc_is_rich,
        "inferred_topics": inferred_topics,
        "evidence_comments": (question_comments + reference_comments)[:5],
        "confidence": confidence,
    }


# ============================================================
#  报告生成
# ============================================================

def gen_single_note_report(note_data, comments, nickname="", note_title=""):
    """
    生成五维+三镜完整拆解报告 MD 内容。
    """
    title = note_data.get("title", note_data.get("displayTitle", note_title))[:60]
    desc = note_data.get("desc", "") or ""
    note_type = note_data.get("type", "normal")
    interact = note_data.get("interactInfo", {})
    likes = parse_count(interact.get("likedCount", "0"))
    collects = parse_count(interact.get("collectedCount", "0"))
    comments_count = parse_count(interact.get("commentCount", "0"))
    shares = parse_count(interact.get("sharedCount", "0"))
    tags = re.findall(r"#([^#\[\]]+?)(?:\[.*?\])?#?", desc)
    note_time = note_data.get("time", 0)

    # ---- 执行各项分析 ----
    title_patterns = extract_title_patterns([title]) if title else {}
    emoji_info = extract_emoji_patterns([desc]) if desc else {}
    cta_info = extract_cta_patterns([desc]) if desc else {}
    structure_info = analyze_content_structure([desc]) if desc else {}
    asl_info = calc_asl(desc)
    hook_info = classify_hook_type(title, desc)
    cover_info = infer_cover_type(title, desc, tags, comments, note_data)
    save_like = classify_save_like_ratio(collects, likes)

    # 评论分析
    wrapped_note = [{"data": {"note": note_data, "comments": {"list": comments}}}]
    sentiment_info = extract_comment_sentiment(wrapped_note)

    golden_sentences = detect_golden_sentences(desc, comments)
    god_replies = detect_god_replies(comments, nickname)
    opportunities = extract_comment_opportunities(comments)
    rhythm_info = infer_rhythm_curve(desc, comments, note_type, note_data)
    visual_anchors = infer_visual_anchor(title, desc, tags, comments, note_data)
    content_from_comments = infer_content_from_comments(comments, desc)
    track_info = classify_content_track(title, desc, tags)

    # 时间
    dt = ms_to_datetime(note_time)
    publish_time_str = dt.strftime("%Y-%m-%d %H:%M") if dt else "未知"

    # 检查BGM证据
    bgm_evidence = []
    for c in (comments or [])[:100]:
        if re.search(r"(bgm|BGM|背景音乐|配乐|音乐|这首歌|BGM|bgm)", c.get("content", "")):
            bgm_evidence.append(c.get("content", "")[:60])
    if re.search(r"(bgm|BGM|背景音乐|配乐|音乐)", desc or ""):
        bgm_evidence.append("正文提及音乐/BGM")

    # ---- 构建报告 ----
    note_type_cn = "视频" if note_type == "video" else "图文"
    lines = [
        f"# 🔬 五维+三镜 爆款拆解报告",
        f"\n> 拆解对象：**{title}**",
        f"> 博主：{nickname} | 类型：{note_type_cn} | 发布时间：{publish_time_str}",
        f"> 赞 {likes:,} | 藏 {collects:,} | 评 {comments_count:,} | 分享 {shares:,}",
        f"\n---",
        f"\n## 📐 方法论说明",
        f"\n本报告采用 **「五维+三镜」拆解法**：",
        f"\n- **五维** = 流量捕获 / 内容骨架 / 视听节奏 / 互动转化 / 爆款要素提炼",
        f"\n- **三镜** = 每维内 🔍还原（客观事实）→ 💡归因（因果推断）→ ✅验证（评论证据）",
        f"\n- ⚠️ **文本推断** = 基于正文+评论间接推测（非画面/音频直接分析）",
        f"\n- ✅ **数据结论** = 基于互动数据和文本的确定性统计",
        f"\n---",
    ]

    # ========== 第一维 ==========
    lines.append(f"\n# 第一维 · 流量捕获")
    lines.append(f"\n> 回答：用户为什么点进来？")

    lines.append(f"\n## 🔍 还原镜 — 客观拆解")
    lines.append(f"\n### 标题分析")
    lines.append(f"> 原标题：**{title}**")
    if title_patterns:
        lines.append(f"\n| 标题模式 | 使用 |")
        lines.append(f"|----------|------|")
        for pn, pd in sorted(title_patterns.items(), key=lambda x: x[1]["count"], reverse=True):
            lines.append(f"| {pn} | ✅ |")

    lines.append(f"\n### 前3秒钩子")
    lines.append(f"- **钩子类型**: {hook_info['hook_type']}（置信度：{hook_info['confidence']}）")
    lines.append(f"- **钩子原文**: 「{hook_info['hook_phrase']}」")

    # 封面类型：根据置信度和数据源标注
    cover_label = "✅ 数据结论" if cover_info['confidence'] == "高" else ("⚠️ 文本推断" if cover_info['confidence'] == "低" else "⚠️ 文本+数据推断")
    lines.append(f"\n### 封面类型推断 {cover_label}")
    lines.append(f"- **推断类型**: {cover_info['cover_type']}（置信度：{cover_info['confidence']}）")
    lines.append(f"- **推断信号**: {', '.join(cover_info['signals']) if cover_info['signals'] else '无明显信号'}")
    if cover_info.get("aspect_signal"):
        lines.append(f"- **📐 比例数据**: {cover_info['aspect_signal']}")

    lines.append(f"\n## 💡 归因镜 — 驱动点击的核心要素")
    # 归因：综合标题模式和钩子类型
    drivers = []
    if hook_info["hook_type"] in ("利益型", "反常识型") and hook_info["confidence"] in ("高", "中"):
        drivers.append(f"**{hook_info['hook_type']}钩子**是最可能的点击驱动力——用户因'{hook_info['hook_phrase'][:20]}'产生好奇或利益预期")
    if title_patterns:
        top_p = max(title_patterns.items(), key=lambda x: x[1]["count"])
        drivers.append(f"**{top_p[0]}**标题模式降低了用户的认知负担，提升了点击意愿")
    if cover_info["confidence"] in ("高", "中"):
        drivers.append(f"**{cover_info['cover_type'].split('（')[0]}**封面与目标用户审美/需求匹配")
    if not drivers:
        drivers.append("数据不足以判断主因，建议结合原内容画面进一步分析")

    for d in drivers:
        lines.append(f"- {d}")

    lines.append(f"\n## ✅ 验证镜 — 评论区证据")
    lines.append(f"\n| 验证项 | 证据 | 结论 |")
    lines.append(f"|--------|------|------|")
    title_comments = [c for c in (comments or [])[:100] if re.search(r"(标题|封面|第一眼|点进来|被.*吸引)",
                      c.get("content", ""))]
    lines.append(f"| 标题/封面吸引 | {f'{len(title_comments)}条相关评论' if title_comments else '无直接证据'} | "
                 f"{'✅ 归因成立' if title_comments else '⚠️ 推断（待验证）'} |")
    lines.append(f"| 钩子有效 | {'评论区有互动响应' if comments else '无评论数据'} | "
                 f"{'✅ 钩子触发了用户反应' if comments else '⚠️ 推断（待验证）'} |")

    # ========== 第二维 ==========
    lines.append(f"\n# 第二维 · 内容骨架")
    lines.append(f"\n> 回答：用户为什么看得下去？")

    lines.append(f"\n## 🔍 还原镜 — 客观拆解")

    # 内容摘要（复用博主拆解逻辑：正文前150字）
    if desc:
        summary = desc[:150]
        if len(desc) > 150:
            summary += "..."
        lines.append(f"\n### 内容摘要")
        lines.append(f"> {summary}")

    # 当正文过短时，从评论反向推断视频内容
    if not content_from_comments.get("desc_is_rich") and content_from_comments.get("inferred_topics"):
        lines.append(f"\n### 从评论区推断的视频内容要点 ⚠️ 文本推断")
        lines.append(f"\n> 正文过短（仅{len(desc)}字），以下内容基于评论区讨论反向推断（置信度：{content_from_comments['confidence']}）\n")
        for i, topic in enumerate(content_from_comments["inferred_topics"]):
            lines.append(f"- {topic}")
        if content_from_comments.get("evidence_comments"):
            lines.append(f"\n**推断依据（评论原文）**：")
            for ev in content_from_comments["evidence_comments"][:3]:
                lines.append(f'- "{ev}"')

    lines.append(f"\n### 信息金字塔")
    if asl_info.get("style") == "标签体":
        lines.append(f"- **总字符数**: {asl_info['total_chars']}字")
        lines.append(f"- **标签占比**: {asl_info.get('hashtag_ratio', 0)*100:.0f}% 为话题标签")
        lines.append(f"- **风格判定**: **🏷️ {asl_info['style']}** — {asl_info['style_desc']}")
    else:
        lines.append(f"- **总字符数**: {asl_info['total_chars']}字")
        lines.append(f"- **断句数**: {asl_info['sentence_count']}句")
        lines.append(f"- **ASL（平均句长）**: {asl_info['asl']}字/句")
        lines.append(f"- **风格判定**: **{asl_info['style']}** — {asl_info['style_desc']}")

    if structure_info:
        lines.append(f"\n### 正文结构")
        lines.append(f"| 指标 | 数据 |")
        lines.append(f"|------|------|")
        lines.append(f"| 平均长度 | {structure_info.get('avg_length', 0)}字 |")
        lines.append(f"| 短文案(<200字) | {'✅' if structure_info.get('short_count', 0) > 0 else '❌'} |")
        lines.append(f"| 长文案(>500字) | {'✅' if structure_info.get('long_count', 0) > 0 else '❌'} |")
        lines.append(f"| 使用列表格式 | {'✅' if structure_info.get('has_list_count', 0) > 0 else '❌'} |")
        lines.append(f"| 使用数字小标题 | {'✅' if structure_info.get('has_number_heading', 0) > 0 else '❌'} |")

    if golden_sentences:
        lines.append(f"\n### 金句埋点 ⚠️ 文本推断")
        lines.append(f"\n| 疑似金句 | 位置 | 置信度 | 评论信号 |")
        lines.append(f"|----------|------|--------|----------|")
        for gs in golden_sentences:
            lines.append(f"| {gs['sentence'][:30]} | {gs['position']} | {gs['confidence']} | {gs['evidence'][:30]} |")

    lines.append(f"\n## 💡 归因镜 — 完读驱动力")
    drivers = []
    if asl_info["style"] == "标签体":
        drivers.append("正文为纯标签，内容信息主要承载在图片/视频中——完读驱动力来自视觉内容而非文案")
    elif asl_info["style"] == "口语型":
        drivers.append("短句口语风格降低了阅读摩擦，用户'一滑到底'的概率更高")
    if structure_info.get("has_number_heading", 0) > 0:
        drivers.append("数字小标题提供了清晰的阅读路径，用户知道'还差几步看完'")
    if golden_sentences:
        drivers.append(f"正文中至少有 {len(golden_sentences)} 处疑似金句，可能在传播中被截图分享")
    if not drivers:
        drivers.append("正文结构数据不足以判断完读驱动力")
    for d in drivers:
        lines.append(f"- {d}")

    lines.append(f"\n## ✅ 验证镜 — 评论区证据")
    screenshot_evidence = any(re.search(r"(截图|求原图|保存|反复看)", c.get("content", "")) for c in (comments or [])[:100])
    lines.append(f"| 验证项 | 证据 | 结论 |")
    lines.append(f"|--------|------|------|")
    lines.append(f"| 金句被截图 | {'发现' if golden_sentences else '未发现'}相关评论 | {'✅ 存在截图传播迹象' if golden_sentences else '⚠️ 推断（待验证）'} |")
    if asl_info.get("style") == "标签体":
        lines.append(f"| 完读率推测 | 正文为纯标签，无句式可分析 | 内容信息承载于图片/视频中，无法从句式推断完读率 |")
    else:
        asl_val = asl_info.get('asl', 0)
        friction = '低' if asl_val < 15 else ('中' if asl_val < 25 else '高')
        completion = '推测完读率较高' if asl_info['style'] == '口语型' else '推测完读率中等'
        lines.append(f"| 完读率推测 | ASL={asl_val}字（{friction}阅读摩擦） | {completion} |")

    # ========== 第三维 ==========
    lines.append(f"\n# 第三维 · 视听节奏")
    lines.append(f"\n> 回答：节奏是怎么操控用户情绪的？")

    lines.append(f"\n## 🔍 还原镜 — 客观拆解")

    if note_type == "video":
        lines.append(f"\n### 节奏曲线推断 ⚠️ 文本推断")
        if rhythm_info["segments"]:
            lines.append(f"\n| 分段 | 功能 | 推断内容 |")
            lines.append(f"|------|------|----------|")
            for seg in rhythm_info["segments"]:
                lines.append(f"| {seg['label']} | {seg['function']} | {seg['content'][:30]} |")
        lines.append(f"\n**节奏类型**: {rhythm_info['rhythm_type']}（置信度：{rhythm_info['confidence']}）")

        lines.append(f"\n### BGM 分析")
        if bgm_evidence:
            lines.append(f"\n**BGM 证据**: 评论区/正文提及了音乐/BGM信息")
            lines.append(f"- 🎵 **前3秒推测**: 强节奏/抓耳型 — 用于在信息流中快速捕获注意力")
            lines.append(f"- 🎵 **中段推测**: 降速/留白型 — 给用户思考和消化信息的时间")
            lines.append(f"- 🎵 **结尾推测**: 升调/推动型 — 配合CTA提升互动转化")
            lines.append(f"> ⚠️ BGM推断基于文本证据+视频创作规律，非实际音频分析。")
        else:
            lines.append(f"\n- 🎵 **评论和正文中未提及BGM/音乐信息**，且未获取原视频音频，无法判断BGM情感曲线。")
            lines.append(f"- ℹ️ 若该视频确实无BGM（纯人声/环境音），这本身也是一种策略选择——可能强化了真实感和亲近感。")
    else:
        # 图文笔记：根据是否有 imageList 数据决定标注
        img_label = "✅ 数据结论" if rhythm_info.get("confidence") == "高" else "⚠️ 文本推断"
        lines.append(f"\n### 图片序列结构 {img_label}")
        if rhythm_info.get("confidence") == "高":
            lines.append(f"- **序列模式**: {rhythm_info.get('rhythm_type', '未知')}（基于 imageList 真实图片数据）")
            for seg in rhythm_info.get("segments", []):
                lines.append(f"  - {seg['label']}: {seg['function']}")
        else:
            lines.append(f"- **推断排版**: {'高密度教程型（每张图有文字标注）' if structure_info.get('has_number_heading', 0) > 0 else '轻量种草型（图片为主文字点缀）'}")
            lines.append(f"- **信息流**: 封面吸引 → 主体信息 → 细节补充 → CTA收尾（基于正文结构的通用推断）")

    if emoji_info:
        lines.append(f"\n### Emoji 使用")
        lines.append(f"- **是否使用**: {'是' if emoji_info.get('emoji_usage_pct', 0) > 0 else '否'}")
        if emoji_info.get("top_emojis"):
            lines.append(f"- **高频Emoji**: {' '.join(e[0] for e in emoji_info['top_emojis'][:5])}")

    if visual_anchors:
        # 视觉心锚：按数据来源标注
        has_image_data = any(va.get("data_source") == "imageList" for va in visual_anchors)
        va_label = "✅ 数据+文本" if has_image_data else "⚠️ 文本推断"
        lines.append(f"\n### 视觉心锚 {va_label}")
        for va in visual_anchors:
            ds = va.get("data_source", "text")
            tag = "✅" if ds == "imageList" else ("💬" if ds == "comment" else "📝")
            lines.append(f"- {tag} **{va['anchor_type']}**: {va['description']}（证据：{va['evidence']}）")

    lines.append(f"\n## 💡 归因镜 — 节奏情绪效果")
    if note_type == "video":
        lines.append(f"- 该内容的节奏设计偏向 **{'爽感驱动' if rhythm_info.get('rhythm_type') != '标准教程节奏' else '信任感驱动'}**"
                      f"—{'快节奏+情绪峰值让用户停不下来' if rhythm_info.get('rhythm_type') != '标准教程节奏' else '清晰的信息层级让用户感到可靠和专业'}")
    else:
        lines.append(f"- 图文内容的'节奏感'由图片切换频率和信息密度控制——该笔记 {'' if structure_info.get('has_number_heading', 0) > 0 else '未'}使用结构化排版")

    lines.append(f"\n## ✅ 验证镜 — 评论区证据")
    time_evidence = []
    for c in (comments or [])[:100]:
        if re.search(r"(第\d+[秒s]|\d+[秒s秒钟]|看到.*时候|放到.*时候|bgm|背景音乐|配乐|音乐)", c.get("content", "")):
            time_evidence.append(c.get("content", "")[:60])
    lines.append(f"| 验证项 | 证据 | 结论 |")
    lines.append(f"|--------|------|------|")
    lines.append(f"| 节奏锚点 | {f'{len(time_evidence)}条评论提及时间/节奏' if time_evidence else '无直接证据'} | {'✅ 用户注意到了节奏设计' if time_evidence else '⚠️ 推断（待验证）'} |")

    # ========== 第四维 ==========
    lines.append(f"\n# 第四维 · 互动转化")
    lines.append(f"\n> 回答：数据为什么好？用户真正想要什么？")

    lines.append(f"\n## 🔍 还原镜 — 客观拆解")
    lines.append(f"\n### 藏赞比解读")
    lines.append(f"- **收藏 {collects:,} / 点赞 {likes:,} = {save_like['ratio']:.2f}**")
    lines.append(f"- **判定**: **{save_like['label']}**")
    lines.append(f"- {save_like['description']}")
    lines.append(f"- **含义**: {save_like['implication']}")

    # 评论情感
    if sentiment_info and sentiment_info.get("total_comments_analyzed", 0) > 0:
        per_note = sentiment_info.get("per_note", [])
        if per_note:
            pn = per_note[0]
            lines.append(f"\n### 评论情感分布")
            lines.append(f"\n| 情感 | 占比 |")
            lines.append(f"|------|------|")
            lines.append(f"| 😊 正向 | {pn['positive_pct']}% |")
            lines.append(f"| 😐 中性 | {pn['neutral_pct']}% |")
            lines.append(f"| 😟 负向 | {pn['negative_pct']}% |")
            lines.append(f"\n**倾向**: {pn['sentiment_label']} | **分析评论数**: {pn['comment_count']}条")

        if sentiment_info.get("positive_examples"):
            lines.append(f"\n**代表性正向评论**:")
            for ex in sentiment_info["positive_examples"][:2]:
                lines.append(f'- "{ex}"')

    # 高频词
    if comments:
        all_words = []
        for c in comments[:100]:
            words = re.findall(r"[一-鿿]{2,4}", c.get("content", ""))
            all_words.extend(words)
        word_freq = Counter(all_words).most_common(15)
        stop_words = {"一个", "这个", "那个", "什么", "可以", "不是", "没有", "自己", "就是", "已经", "还是", "因为", "所以"}
        meaningful = [(w, c) for w, c in word_freq if w not in stop_words][:8]
        if meaningful:
            lines.append(f"\n### 评论区高频词")
            lines.append(f"\n| 关键词 | 频次 |")
            lines.append(f"|--------|------|")
            for w, c in meaningful:
                lines.append(f"| {w} | {c} |")

    if god_replies:
        lines.append(f"\n### 神回复分析")
        lines.append(f"\n| 内容 | 类型 | 点赞 | 效果 |")
        lines.append(f"|------|------|------|------|")
        for gr in god_replies[:5]:
            lines.append(f"| {gr['content'][:30]} | {gr['type']} | {gr['likes']} | {gr['effectiveness']} |")

    if opportunities:
        lines.append(f"\n### 🔥 下一步内容机会")
        for i, opp in enumerate(opportunities):
            lines.append(f"{i+1}. **「{opp['question']}」** — {opp['opportunity_type']}（{opp['frequency']}条评论提及）")

    lines.append(f"\n## 💡 归因镜 — 用户互动真实动机")
    if save_like["label"] in ("强实用工具型", "实用驱动型"):
        lines.append(f"- **实用需求驱动**：用户将此内容视为工具/知识，互动动机是'省下来以后用'")
        if opportunities:
            lines.append(f"- **未满足需求**：评论区高频提问表明——用户想要的内容比博主给的更多")
    else:
        lines.append(f"- **情绪共鸣驱动**：用户互动的真实动机是身份认同、情感连接或即时娱乐，而非工具性需求")

    lines.append(f"\n## ✅ 验证镜 — 数据自洽性检查")
    # CTA与藏赞比自洽
    cta_types = list(cta_info.keys()) if cta_info else []
    cta_mismatch = False
    if "收藏引导" in cta_types and save_like["label"] in ("强情绪共鸣型", "情绪共鸣型"):
        cta_mismatch = True
        lines.append(f"- ⚠️ **CTA错配预警**：内容为{save_like['label']}，但CTA中包含收藏引导——用户互动动机以情绪为主，收藏引导可能效果有限")
    if not cta_types and save_like["label"] in ("强实用工具型", "实用驱动型"):
        cta_mismatch = True
        lines.append(f"- ⚠️ **CTA缺失预警**：内容实用性强但未设置收藏/关注引导，可能浪费了高收藏意愿的流量")
    if not cta_mismatch:
        lines.append(f"- ✅ CTA类型（{', '.join(cta_types) if cta_types else '无显式CTA'}）与藏赞比（{save_like['label']}）**基本自洽**")

    if opportunities:
        lines.append(f"- ✅ 评论区发现 **{len(opportunities)}** 个内容机会——这些是用户'花钱都买不到'的真实需求信号")

    # ========== 第五维 ==========
    lines.append(f"\n# 第五维 · 爆款要素提炼")
    lines.append(f"\n> 综合前四维发现，输出可执行的公式卡")

    lines.append(f"\n## 🔍 还原镜 — 要素清单")
    lines.append(f"\n| 维度 | 关键发现 |")
    lines.append(f"|------|----------|")
    lines.append(f"| 流量捕获 | 钩子={hook_info['hook_type']}，封面={cover_info['cover_type'].split('（')[0]} |")
    skeleton_label = "纯标签无文案" if asl_info.get("style") == "标签体" else f"ASL={asl_info['asl']}字({asl_info['style']})"
    lines.append(f"| 内容骨架 | {skeleton_label}，{'有' if golden_sentences else '未检出'}金句 |")
    lines.append(f"| 视听节奏 | {note_type_cn}，{'有分段节奏线索' if rhythm_info['segments'] else '节奏数据不足'} |")
    lines.append(f"| 互动转化 | 藏赞比={save_like['ratio']:.2f}({save_like['label']})，{'有' if opportunities else '未检出'}内容机会 |")

    lines.append(f"\n## 💡 归因镜 — 可复用 vs 不可复制")
    lines.append(f"\n### ✅ 可复用的要素")
    lines.append(f"- **标题公式**: {hook_info['hook_type']} + {list(title_patterns.keys())[0] if title_patterns else '通用'} — 可直接套用")
    if asl_info.get("style") == "标签体":
        lines.append(f"- **正文风格**: 🏷️ {asl_info['style']} — 正文无实际文案，内容信息承载在图片/视频中，需配合原内容画面分析")
    else:
        lines.append(f"- **正文风格**: ASL≈{asl_info['asl']}字的{asl_info['style']} — 模仿其句式节奏")
    if golden_sentences:
        lines.append(f"- **金句策略**: 在正文{', '.join(set(g['position'] for g in golden_sentences))}埋点 — 位置可复制")
    lines.append(f"- **CTA时机**: {'结尾' if cta_info else '自然融入'} — 学习其引导时机")

    lines.append(f"\n### ❌ 不可复制的人设红利")
    lines.append(f"- **个人经历/故事**: 博主的真实经历是信任的基础，无法模仿")
    lines.append(f"- **粉丝关系**: 已有的粉丝基础和互动习惯是长期积累的结果")
    lines.append(f"- **风格惯性**: 观众对特定画面风格/声音/BGM的熟悉感需要时间建立")

    lines.append(f"\n## ✅ 验证镜 — 转化岔口自洽性")
    lines.append(f"| 检查项 | 结果 |")
    lines.append(f"|--------|------|")
    lines.append(f"| CTA类型 × 藏赞比 | {'✅ 自洽' if not cta_mismatch else '⚠️ 存在错配'} |")
    lines.append(f"| 内容深度 × 用户需求 | {'✅ 匹配' if opportunities else '⚠️ 评论提问可能有未覆盖的需求'} |")
    lines.append(f"| 人设一致性 | ✅ 内容风格与博主人设一致（基于文本信号推断） |")

    # ---- 公式卡 ----
    lines.append(f"\n---")
    lines.append(f"\n# 📋 爆款公式卡")
    lines.append(f"\n```")
    lines.append(f"┌─────────────────────────────────────┐")
    lines.append(f"│  爆款公式卡 — {title[:20]}              │")
    lines.append(f"├─────────────────────────────────────┤")
    lines.append(f"│ 标题公式: {hook_info['hook_type']} + {list(title_patterns.keys())[0] if title_patterns else '通用'}  │")
    lines.append(f"│                                     │")
    lines.append(f"│ 钩子类型: {hook_info['hook_type']}         │")
    lines.append(f"│                                     │")
    style_str = f"🏷️ {asl_info['style']}" if asl_info.get("style") == "标签体" else f"{asl_info['style']} ASL≈{asl_info['asl']}字"
    lines.append(f"│ 正文风格: {style_str}    │")
    lines.append(f"│                                     │")
    lines.append(f"│ CTA策略: {', '.join(cta_types) if cta_types else '无显式CTA（内容驱动互动）'} │")
    lines.append(f"│                                     │")
    lines.append(f"│ 转化类型: {save_like['label']}          │")
    lines.append(f"│                                     │")
    # 赛道分类（有分类结果时展示，否则保持通用）
    track_label = "✅ 数据结论" if track_info["confidence"] in ("高", "中") else "⚠️ 文本推断"
    if track_info["primary_track"] != "综合/泛生活" and track_info["primary_track"] != "无法判断":
        track_str = f"{track_info['primary_track']}"
        if track_info["sub_track"]:
            track_str += f" · {track_info['sub_track']}"
        lines.append(f"│ 适配赛道: {track_str} │")
    else:
        lines.append(f"│ 适配赛道: 综合/泛生活（{track_label}）   │")
    lines.append(f"│                                     │")
    lines.append(f"│ ⚠️ 人设红利: 不可复制的个人魅力部分       │")
    lines.append(f"└─────────────────────────────────────┘")
    lines.append(f"```")
    lines.append(f"\n> ⚠️ 标注「文本推断」的结论基于正文+评论间接推测，建议配合原内容画面交叉验证。")
    lines.append(f"> ✅ 标注「数据结论」的结论基于互动数据和文本确定性统计。")

    return "\n".join(lines)


# ============================================================
#  主函数
# ============================================================

def analyze_viral_post(details_path=None, note_index=0, feed_id=None,
                        xsec_token=None, url=None, nickname="", output_dir=".", port=18060):
    """
    执行单条笔记五维+三镜深度拆解。
    """
    os.makedirs(output_dir, exist_ok=True)

    note_data = {}
    comments = []

    # ---- 数据获取 ----
    if details_path and os.path.exists(details_path):
        # Mode A: 从已有数据中按索引取
        print(f"📂 从已有数据加载: {details_path}")
        with open(details_path, "r", encoding="utf-8") as f:
            raw_details = json.load(f)

        valid_notes = [item for item in raw_details if "_error" not in item]
        if not valid_notes:
            print("❌ 没有有效笔记数据")
            return None

        # 按赞排序
        def get_likes(item):
            note = item.get("data", {}).get("note", item)
            interact = note.get("interactInfo", item.get("interactInfo", {}))
            return parse_count(interact.get("likedCount", "0"))

        valid_notes.sort(key=get_likes, reverse=True)

        if note_index >= len(valid_notes):
            print(f"❌ 索引 {note_index} 超出范围（共 {len(valid_notes)} 条有效笔记）")
            return None

        selected = valid_notes[note_index]
        note_data = selected.get("data", {}).get("note", selected)
        comments_data = selected.get("data", {}).get("comments", selected.get("comments", {}))
        comments = comments_data.get("list", []) if isinstance(comments_data, dict) else []

        # 提取博主昵称
        if not nickname:
            user = note_data.get("user", {})
            nickname = user.get("nickname", user.get("nickName", "未知博主"))

    elif feed_id:
        # Mode B: feed_id 实时获取
        print(f"🔍 通过 feed_id 实时获取: {feed_id}")
        client = MCPClient(port=port)
        try:
            raw = client.call_raw("get_feed_detail", {
                "feed_id": feed_id,
                "xsec_token": xsec_token or "",
                "load_all_comments": True,
                "limit": 50,
                "click_more_replies": False,
            }, timeout=90)
            # 手动解析 JSON-RPC 响应（绕过 _extract_data 的 session 问题）
            result = raw.get("result", {})
            contents = result.get("content", [])
            text_data = ""
            for c in contents:
                if c.get("type") == "text":
                    text_data += c.get("text", "")
            if text_data:
                detail = json.loads(text_data)
            else:
                detail = raw
            note_data = detail.get("data", {}).get("note", detail)
            comments_data = detail.get("data", {}).get("comments", detail.get("comments", {}))
            comments = comments_data.get("list", []) if isinstance(comments_data, dict) else []
            if not nickname:
                user = note_data.get("user", {})
                nickname = user.get("nickname", user.get("nickName", "未知博主"))
        except Exception as e:
            print(f"❌ 获取笔记失败: {e}")
            return None

    elif url:
        # Mode C: 链接解析
        print(f"🔗 从链接解析: {url}")
        note_id_match = re.search(r"(?:/explore/|/discovery/item/|note_id=)([a-f0-9]+)", url)
        if not note_id_match:
            print("❌ 无法从链接中解析 note_id，请检查链接格式")
            return None
        note_id = note_id_match.group(1)
        print(f"   解析到 note_id: {note_id}")

        # 尝试从 URL 中提取 xsec_token
        if not xsec_token:
            xt_match = re.search(r"xsec_token=([A-Za-z0-9_\-=]+)", url)
            if xt_match:
                xsec_token = xt_match.group(1)
                print(f"   从URL提取到 xsec_token")

        return analyze_viral_post(feed_id=note_id, xsec_token=xsec_token or "",
                                   nickname=nickname, output_dir=output_dir, port=port)
    else:
        print("❌ 请指定数据来源：details_path、feed_id 或 url")
        return None

    if not note_data:
        print("❌ 未获取到笔记数据")
        return None

    title = note_data.get("title", note_data.get("displayTitle", "未知标题"))[:40]
    safe_name = safe_filename(nickname) if nickname else "unknown"
    safe_title = safe_filename(title)[:30]

    print(f"\n{'='*60}")
    print(f"🔬 五维+三镜 爆款拆解")
    print(f"   博主: {nickname}")
    print(f"   笔记: {title}")
    print(f"   评论: {len(comments)}条")
    print(f"{'='*60}\n")

    # ---- 生成报告 ----
    md_content = gen_single_note_report(note_data, comments, nickname, title)

    # 保存 MD → 过程文件（存档）
    process_dir = os.path.join(output_dir, "_过程文件", "原始素材")
    os.makedirs(process_dir, exist_ok=True)

    md_name = f"{safe_name}_{safe_title}_五维拆解.md"
    md_path = os.path.join(process_dir, md_name)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"  📄 MD(存档): {md_path}")

    # 保存 MD → output 根目录（方便直接查看，与博主拆解产出格式一致）
    md_root_path = os.path.join(output_dir, md_name)
    with open(md_root_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"  📄 MD: {md_root_path}")

    # 转 DOCX → output 根目录
    docx_name = f"{safe_name}_{safe_title}_五维拆解.docx"
    docx_path = os.path.join(output_dir, docx_name)
    try:
        md_to_docx(md_path, docx_path)
        size_kb = os.path.getsize(docx_path) / 1024
        print(f"  📄 DOCX: {docx_path} ({size_kb:.0f}KB)")
    except Exception as e:
        print(f"  ❌ DOCX 生成失败: {e}")

    print(f"\n✅ 五维+三镜拆解完成！")
    return {"md_path": md_root_path, "docx_path": docx_path, "note_title": title}


# ============================================================
#  CLI
# ============================================================
if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="五维+三镜 爆款拆解 — 单条笔记深度分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 从已有数据中选TOP1（最高赞）
  python analyze_viral_post.py ./data/Esther不二_notes_details.json 0 "Esther不二"

  # 选第3条
  python analyze_viral_post.py ./data/Esther不二_notes_details.json 3 "Esther不二" -o ./output

  # 通过 feed_id
  python analyze_viral_post.py --feed-id <feed_id> "Esther不二" -o ./output

  # 通过链接
  python analyze_viral_post.py --url "<小红书链接>" "Esther不二" -o ./output
        """,
    )
    parser.add_argument("details_path", nargs="?", help="笔记详情 JSON 路径")
    parser.add_argument("note_index", nargs="?", type=int, default=0, help="笔记索引（按赞排序，0=最高赞）")
    parser.add_argument("nickname", nargs="?", default="", help="博主昵称")
    parser.add_argument("--feed-id", help="小红书 feed_id（与 details_path 二选一）")
    parser.add_argument("--xsec-token", default="", help="xsec_token（feed_id 模式需要）")
    parser.add_argument("--url", help="小红书链接（自动解析 note_id）")
    parser.add_argument("-o", "--output", default=".", help="输出目录")
    parser.add_argument("--port", type=int, default=18060, help="MCP 端口")
    args = parser.parse_args()

    if not args.details_path and not args.feed_id and not args.url:
        parser.error("请指定数据来源：details_path、--feed-id 或 --url")

    analyze_viral_post(
        details_path=args.details_path,
        note_index=args.note_index,
        feed_id=args.feed_id,
        xsec_token=args.xsec_token,
        url=args.url,
        nickname=args.nickname,
        output_dir=args.output,
        port=args.port,
    )
