"""数据可视化面板 v5 — 占位符替换式，零花括号问题"""
import json, os, sys, argparse
from datetime import datetime
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PAL = ["#D97757","#6B9080","#8B7E74","#B5838D","#7B9EA8","#C4956A","#9B8EC4","#6E8B7B"]
PN = ["数字型","疑问型","感叹型","教程型","列表型","对比型","故事型","悬念型"]

def load_all_data(data_dir, blogger_names=None):
    """加载所有博主数据"""
    from deep_analyze import (extract_comment_sentiment, extract_posting_heatmap,
                               detect_posting_frequency, extract_title_patterns, classify_content_track)
    from cross_analyze import discover_bloggers, load_blogger_data
    from analyze_viral_post import classify_hook_type
    if blogger_names: names = [n.strip() for n in blogger_names if n.strip()]
    else: names = discover_bloggers(data_dir)
    all_data = []
    for name in names:
        raw = load_blogger_data(data_dir, name)
        if not raw: continue
        notes = raw["notes"]
        freq = detect_posting_frequency(notes)
        sentiment = extract_comment_sentiment(raw["details"]) if raw["details_available"] else {}
        heatmap = extract_posting_heatmap(notes) if len(notes) >= 5 else {}
        titles = [n.get("title","") for n in notes if n.get("title")]
        title_pats = extract_title_patterns(titles) if titles else {}
        track_dist = Counter()
        for n in notes:
            t = classify_content_track(n.get("title",""), "", n.get("tags",[]))
            track_dist[t.get("primary_track","综合")] += 1
        hook_dist = Counter()
        for n in notes:
            hook_dist[classify_hook_type(n.get("title",""),"").get("hook_type","利益型")] += 1
        descs = []
        for item in raw["details"]:
            nd = item.get("data",{}).get("note",item)
            descs.append(nd.get("desc","") or "")
        from deep_analyze import extract_cta_patterns, analyze_content_structure, extract_emoji_patterns
        cta_info = extract_cta_patterns(descs) if descs else {}
        struct_info = analyze_content_structure(descs) if descs else {}
        emoji_info = extract_emoji_patterns(descs) if descs else {}
        tl = raw["stats"].get("total_likes",1) or 1; tc = raw["stats"].get("total_collects",0)
        sl_ratio = round(tc/tl,2)
        rl = "实用工具型" if sl_ratio>0.6 else ("实用驱动型" if sl_ratio>0.33 else ("均衡型" if sl_ratio>0.2 else ("情绪共鸣型" if sl_ratio>0.1 else "强情绪共鸣型")))
        al = raw["stats"].get("avg_likes",0); ht = al*3 if al>0 else 1
        hit_rate=round(sum(1 for n in notes if n.get("likes",0)>=ht)/max(raw["notes_count"],1)*100,1)
        total_interact=tl+tc+raw["stats"].get("total_comments",0)
        empty_pct=round(sum(1 for d in descs if not d or len(d)<20)/max(len(descs),1)*100,1)
        all_data.append({"name":raw["name"],"safe":raw["safe_name"],"stats":raw["stats"],
            "notes":notes,"n":raw["notes_count"],"cats":raw["categories"],"freq":freq,
            "sentiment":sentiment,"heatmap":heatmap,"title_pats":title_pats,
            "track_dist":dict(track_dist),"hook_dist":dict(hook_dist),
            "td":{"图文":raw["stats"].get("normal_count",0),"视频":raw["stats"].get("video_count",0)},
            "sl":sl_ratio,"rl":rl,"hr":hit_rate,"al":al,"freq_label":freq.get("pattern","?"),
            "cta":cta_info,"struct":struct_info,"emoji":emoji_info,"descs":descs,
            "desc_empty_pct":empty_pct,"details_ok":raw["details_available"],
            "avg_interact":round(total_interact/max(raw["notes_count"],1))})
    return all_data


def generate_dashboard(data_dir, output_dir, blogger_names=None):
    all_data = load_all_data(data_dir, blogger_names)
    if not all_data: print("No data found"); return
    html = make_html(all_data)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "数据可视化面板.html")
    with open(path, "w", encoding="utf-8") as f: f.write(html)
    print(f"Generated: {path} ({os.path.getsize(path)/1024:.0f}KB)")
    return path


def make_html(all_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    d = all_data[0]
    s = d["stats"]

    # ── Pre-compute all chart data ──
    score = d["sentiment"].get("overall_score", 0) or 0
    sent_label = "偏正向" if score > 0.3 else ("中性偏正" if score > 0 else "中性")

    td = d.get("track_dist", {})
    st = sorted(td.items(), key=lambda x: x[1], reverse=True)[:8]
    track_labels = json.dumps([t[0] for t in st], ensure_ascii=False)
    track_data = json.dumps([t[1] for t in st])
    track_colors = json.dumps(PAL[:len(st)])

    hd = d.get("hook_dist", {})
    hl = sorted(hd.keys(), key=lambda k: hd[k], reverse=True)
    hook_labels = json.dumps(hl, ensure_ascii=False)
    hook_data = json.dumps([hd[k] for k in hl])

    tp = d.get("title_pats", {})
    pattern_data = json.dumps([tp.get(pn,{}).get("pct",0) for pn in PN])

    cl = ["关注","收藏","点赞","评论","转发","私信"]
    ci = d.get("cta", {})
    cta_data = json.dumps([ci.get(f"{l}引导",{}).get("pct",0) for l in cl])

    format_data = json.dumps([d.get("td",{}).get("视频",0), d.get("td",{}).get("图文",0)])
    viral_data = json.dumps([d["sl"]*100, d["hr"]])

    tl = s.get("total_likes",1) or 1; tc = s.get("total_collects",0); tm = s.get("total_comments",0)
    tot = tl+tc+tm or 1
    interact_data = json.dumps([round(tl/tot*100,1), round(tc/tot*100,1), round(tm/tot*100,1)])

    sr = d.get("sentiment",{})
    pn_list = sr.get("per_note",[])
    if pn_list:
        avg_pos = round(sum(p.get("positive_pct",0) for p in pn_list)/len(pn_list),1)
        avg_neu = round(sum(p.get("neutral_pct",0) for p in pn_list)/len(pn_list),1)
        avg_neg = round(sum(p.get("negative_pct",0) for p in pn_list)/len(pn_list),1)
    else:
        avg_pos = avg_neu = avg_neg = 0
    sentiment_data = json.dumps([avg_pos, avg_neu, avg_neg])
    sentiment_total = sr.get("total_comments_analyzed", 0)
    pos_examples = sr.get("positive_examples", [])[:2]
    neg_examples = sr.get("negative_examples", [])[:2]

    # ── Heatmap ──
    heatmap_html = ""
    hm = d.get("heatmap", {})
    mx = hm.get("hour_day_matrix", [])
    if mx and len(mx) == 7:
        maxv = max(max(r) for r in mx) if mx else 1
        days = hm.get("day_names_cn", ["周一","周二","周三","周四","周五","周六","周日"])
        slots = hm.get("time_slots", ["00-06","06-08","08-12","12-14","14-18","18-21","21-24"])
        rows = ""
        for si, s_name in enumerate(slots):
            cells = ""
            for v in mx[si]:
                if v > 0:
                    alpha = v / maxv * 0.75
                    cells += '<td style="background:rgba(217,119,87,%.2f)">%d</td>' % (alpha, v)
                else:
                    cells += "<td></td>"
            rows += "<tr><th>%s</th>%s</tr>" % (s_name, cells)
        best_day = hm.get("best_day", "—")
        best_hour = hm.get("best_hour_block", "—")
        heatmap_html = '<div class="card full"><div class="ch">🔥 发布时间热力图 · %s</div><div class="cs">最佳: %s %s</div><table class="hm"><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table></div>' % (
            d["name"], best_day, best_hour, "".join("<th>%s</th>" % x for x in days), rows)

    # ── Notice ──
    notice = ""
    if d["desc_empty_pct"] > 40:
        notice = '<div class="notice"><strong>⚠️ 正文覆盖不足</strong> — %d% 笔记正文为空或极短（纯标签）。CTA/Emoji/内容结构等需正文数据的分析受限，标题驱动的钩子/模式分析不受影响。</div>' % d["desc_empty_pct"]

    # ── CTA special handling ──
    cta_all_zero = all(v == 0 for v in json.loads(cta_data))
    cta_card_html = """<div class="card"><div class="ch">📢 CTA 引导策略</div><div class="cs">行动号召类型分布</div><div class="notice"><strong>📝 正文不足</strong> — 该博主正文以标签/零文案为主，无法提取 CTA 策略。标题驱动的钩子和模式分析不受影响。</div></div>""" if cta_all_zero else """<div class="card"><div class="ch">📢 CTA 引导策略</div><div class="cs">行动号召类型分布</div><canvas id="ctaChart"></canvas></div>"""

    # ── Build JS — wrapped in DOMContentLoaded to ensure Canvas exists ──
    NAME = d["name"]
    js = "<script>\n"
    js += "document.addEventListener('DOMContentLoaded',function(){\n"
    js += "const co={responsive:true,maintainAspectRatio:true,plugins:{legend:{position:'bottom',labels:{font:{family:'Poppins',size:10},padding:12,usePointStyle:true}}}};\n"
    # Track donut
    js += "new Chart(document.getElementById('trackChart'),{type:'doughnut',data:{labels:" + track_labels + ",datasets:[{data:" + track_data + ",backgroundColor:" + track_colors + "}]},options:co});\n"
    # Hook
    js += "new Chart(document.getElementById('hookChart'),{type:'bar',data:{labels:" + hook_labels + ",datasets:[{label:'" + NAME + "',data:" + hook_data + ",backgroundColor:'#D97757'}]},options:{...co,scales:{y:{beginAtZero:true,title:{display:true,text:'次',font:{family:'Poppins'}}}}});\n"
    # Pattern
    js += "new Chart(document.getElementById('patternChart'),{type:'bar',data:{labels:" + json.dumps(PN, ensure_ascii=False) + ",datasets:[{label:'" + NAME + "',data:" + pattern_data + ",backgroundColor:'#D97757'}]},options:{...co,scales:{y:{beginAtZero:true,ticks:{callback:function(v){return v+'%'}}}}});\n"
    # CTA
    if not cta_all_zero:
        js += "new Chart(document.getElementById('ctaChart'),{type:'bar',data:{labels:" + json.dumps(cl, ensure_ascii=False) + ",datasets:[{label:'" + NAME + "',data:" + cta_data + ",backgroundColor:'#D97757'}]},options:{...co,scales:{y:{beginAtZero:true,ticks:{callback:function(v){return v+'%'}}}}});\n"
    # Format
    js += "new Chart(document.getElementById('formatChart'),{type:'bar',data:{labels:['视频','图文'],datasets:[{label:'" + NAME + "',data:" + format_data + ",backgroundColor:'#D97757'}]},options:{...co,scales:{y:{beginAtZero:true}}});\n"
    # Viral
    js += "new Chart(document.getElementById('viralBarChart'),{type:'bar',data:{labels:['藏赞比(x100)','爆款率(%)'],datasets:[{label:'" + NAME + "',data:" + viral_data + ",backgroundColor:['#D97757','rgba(217,119,87,0.4)']}]},options:{...co,scales:{y:{beginAtZero:true}}});\n"
    # Interact
    js += "new Chart(document.getElementById('interactChart'),{type:'bar',data:{labels:['点赞','收藏','评论'],datasets:[{label:'" + NAME + "',data:" + interact_data + ",backgroundColor:'#D97757'}]},options:{...co,scales:{y:{max:100,ticks:{callback:function(v){return v+'%'}}}}});\n"
    # Sentiment
    js += "new Chart(document.getElementById('sentimentChart'),{type:'bar',data:{labels:['正向','中性','负向'],datasets:[{label:'" + NAME + "',data:" + sentiment_data + ",backgroundColor:['#6B9080','#D4A853','#C0453A']}]},options:{...co,scales:{y:{max:100,ticks:{callback:function(v){return v+'%'}}}}});\n"
    # Scroll
    js += "const sections=document.querySelectorAll('section[id]');const navBtns=document.querySelectorAll('.tab-btn');const observer=new IntersectionObserver(function(entries){entries.forEach(function(e){if(e.isIntersecting){navBtns.forEach(function(b){b.classList.remove('active')});document.querySelector('.tab-btn[href=\"#'+e.target.id+'\"]').classList.add('active')}})},{rootMargin:'-30% 0px -60% 0px'});sections.forEach(function(s){observer.observe(s)});\n"
    js += "});\n"
    js += "</script>"

    # ── HTML template ──
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>小红书内容分析看板 | __NAME__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lora:wght@400;600&family=Poppins:wght@400;500;600&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
<style>
:root{--bg:#F7F5F0;--s:#FFF;--sa:#F0EDE6;--accent:#D97757;--t:#141413;--t2:#6B6860;--tm:#9C9890;--b:#E6E3DC;--r:12px;--sh:0 1px 3px rgba(0,0,0,0.04)}
*{margin:0;padding:0;box-sizing:border-box}html{scroll-behavior:smooth}
body{font-family:'Lora',serif;background:var(--bg);color:var(--t);-webkit-font-smoothing:antialiased;line-height:1.6}
.hdr{background:var(--s);border-bottom:1px solid var(--b);padding:24px 36px}
.hdr h1{font-family:'Poppins',sans-serif;font-size:22px;font-weight:600;letter-spacing:-0.3px}
.hdr .sub{font-family:'Poppins',sans-serif;font-size:12px;color:var(--t2);margin-top:4px}
.tab-nav{display:flex;gap:0;padding:0 36px;max-width:1500px;margin:0 auto;position:sticky;top:0;z-index:10;background:var(--bg);padding-top:8px}
.tab-btn{font-family:'Poppins',sans-serif;font-size:13px;font-weight:500;padding:10px 22px;border:none;background:transparent;color:var(--t2);cursor:pointer;text-decoration:none;border-bottom:2px solid transparent;transition:all .2s}
.tab-btn:hover{color:var(--t)}.tab-btn.active{color:var(--accent);border-bottom-color:var(--accent)}
section{scroll-margin-top:60px}
.kpi{display:flex;flex-direction:column;gap:10px;padding:18px 36px;max-width:1500px;margin:0 auto}
.kg{background:var(--s);border:1px solid var(--b);border-radius:var(--r);padding:12px 16px;box-shadow:var(--sh)}
.kgc{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}
.kc{background:var(--sa);border-radius:8px;padding:10px 12px}
.kl{font-family:'Poppins',sans-serif;font-size:9px;font-weight:500;color:var(--t2);text-transform:uppercase;letter-spacing:.5px}
.kl-n{font-weight:400;text-transform:none}
.kv{font-family:'Lora',serif;font-size:20px;font-weight:600;margin-top:2px;line-height:1.2}
.ku{font-family:'Poppins',sans-serif;font-size:10px;font-weight:400;color:var(--t2);margin-left:2px}
.ks{font-family:'Poppins',sans-serif;font-size:9px;color:var(--tm);margin-top:2px}
.main{max-width:1500px;margin:0 auto;padding:20px 36px}
.sec-title{font-family:'Poppins',sans-serif;font-size:17px;font-weight:600;margin:28px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--accent);display:inline-block}
.cg{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}.cg2{grid-template-columns:1fr 1fr}
.card{background:var(--s);border:1px solid var(--b);border-radius:var(--r);padding:20px;box-shadow:var(--sh)}.card.full{grid-column:1/-1}
.ch{font-family:'Lora',serif;font-size:15px;font-weight:600;margin-bottom:4px}
.cs{font-family:'Poppins',sans-serif;font-size:11px;color:var(--t2);margin-bottom:12px}
.dt{width:100%;border-collapse:collapse;font-family:'Poppins',sans-serif;font-size:12px}
.dt th{font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--t2);text-align:left;padding:8px 10px;border-bottom:2px solid var(--b)}
.dt td{padding:8px 10px;border-bottom:1px solid var(--b)}
.dt tr:nth-child(even) td{background:var(--sa)}.dt .n{font-family:'JetBrains Mono',monospace;font-size:11px;text-align:right}
.hm{width:100%;border-collapse:collapse;font-size:11px;font-family:'JetBrains Mono',monospace}
.hm th{font-family:'Poppins',sans-serif;font-size:10px;padding:4px 5px;text-align:center;color:var(--t2)}
.hm td{padding:4px 5px;text-align:center;border-radius:4px}
.cl{font-size:12px;padding:5px 0;border-bottom:1px solid var(--b)}
.notice{background:rgba(212,168,83,0.12);border:1px solid rgba(212,168,83,0.3);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-family:'Poppins',sans-serif;font-size:12px;color:var(--t2)}
.notice strong{color:#B8860B}
.footer{text-align:center;padding:28px;font-family:'Poppins',sans-serif;font-size:10px;color:var(--tm)}
@media(max-width:768px){.hdr,.kpi,.main{padding-left:14px;padding-right:14px}.cg,.cg2{grid-template-columns:1fr}.tab-nav{padding:0 14px}.tab-btn{padding:10px 14px;font-size:12px}}
</style>
</head>
<body>
<div class="hdr"><h1>📊 小红书内容分析看板</h1><p class="sub">__NAME__ &nbsp;|&nbsp; __NOW__ &nbsp;|&nbsp; 地瓜爆款拆解系统 v0.5</p></div>
<div class="kpi"><div class="kg"><div class="kgc">
<div class="kc"><div class="kl">篇均互动</div><div class="kv">__AVG_INTERACT__<span class="ku">次</span></div><div class="ks">均赞 __AVG_LIKES__</div></div>
<div class="kc"><div class="kl">爆款率</div><div class="kv">__HIT_RATE__<span class="ku">%</span></div><div class="ks">&gt;__HIT_THRESHOLD__赞为爆款</div></div>
<div class="kc"><div class="kl">内容类型<span class="kl-n"> (藏赞比判定)</span></div><div class="kv">__RATIO_LABEL__</div><div class="ks">藏赞比__SL_RATIO__ · __FREQ_LABEL__</div></div>
<div class="kc"><div class="kl">评论情感</div><div class="kv">__SENTIMENT_SCORE__</div><div class="ks">__SENT_LABEL__</div></div>
</div></div></div>

<nav class="tab-nav">
  <a href="#sec-overview" class="tab-btn active">账号总览</a>
  <a href="#sec-strategy" class="tab-btn">内容策略</a>
  <a href="#sec-viral" class="tab-btn">爆款引擎</a>
  <a href="#sec-comments" class="tab-btn">评论洞察</a>
</nav>

<div class="main">
  <section id="sec-overview"><div class="sec-title">一、账号总览</div><div class="cg">
    <div class="card"><div class="ch">📋 账号基础数据</div><div class="cs">来自小红书主页</div>
    <table class="dt"><tbody>
      <tr><td>笔记数</td><td class="n">__TOTAL_NOTES__</td><td>视频/图文</td><td class="n">__VIDEO_COUNT__/__NORMAL_COUNT__</td></tr>
      <tr><td>均赞</td><td class="n">__AVG_LIKES__</td><td>均收藏</td><td class="n">__AVG_COLLECTS__</td></tr>
      <tr><td>爆款率</td><td class="n">__HIT_RATE__%</td><td>藏赞比</td><td class="n">__SL_RATIO__ (__RATIO_LABEL__)</td></tr>
      <tr><td>更新频率</td><td>__FREQ_LABEL__</td><td>情感得分</td><td class="n">__SENTIMENT_SCORE__</td></tr>
    </tbody></table></div>
    <div class="card"><div class="ch">🏷️ 赛道分布</div><div class="cs">内容领域覆盖</div><canvas id="trackChart"></canvas></div>
  </div></section>

  <section id="sec-strategy"><div class="sec-title">二、内容策略</div>
    __NOTICE__
    <div class="cg">
      <div class="card"><div class="ch">🎣 前3秒钩子策略</div><div class="cs">吸引注意力的方式分布</div><canvas id="hookChart"></canvas></div>
      <div class="card"><div class="ch">📝 标题模式偏好</div><div class="cs">8种标题策略使用频率</div><canvas id="patternChart"></canvas></div>
      __CTA_CARD__
      <div class="card"><div class="ch">🎬 内容形式</div><div class="cs">视频/图文比</div><canvas id="formatChart"></canvas></div>
    </div>
  </section>

  <section id="sec-viral"><div class="sec-title">三、爆款引擎</div>
    <div class="cg">
      <div class="card"><div class="ch">📊 藏赞比 & 爆款率</div><div class="cs">收藏÷点赞 ×100 vs 爆款(>3倍均赞)占比(%)</div><canvas id="viralBarChart"></canvas></div>
      <div class="card"><div class="ch">❤️ 互动构成</div><div class="cs">点赞/收藏/评论占比</div><canvas id="interactChart"></canvas></div>
    </div>
    __HEATMAP__
    <div class="card full"><div class="ch">💡 藏赞比速查</div><div class="cs">{">0.6 实用工具型 · 0.33-0.6 实用驱动型 · 0.2-0.33 均衡型 · 0.1-0.2 情绪共鸣型 · <0.1 强情绪共鸣型"}</div></div>
  </section>

  <section id="sec-comments"><div class="sec-title">四、评论洞察</div>
    <div class="cg"><div class="card full"><div class="ch">💬 评论情感分布</div><div class="cs">正向/中性/负向占比</div><canvas id="sentimentChart"></canvas></div></div>
    <div class="cg cg2">
      <div class="card"><div class="ch">💚 正向 · __NAME__</div><div class="cs">__SENTIMENT_TOTAL__条评论</div>__POS_HTML__</div>
      <div class="card"><div class="ch">⚠️ 需关注 · __NAME__</div><div class="cs">负向评论</div>__NEG_HTML__</div>
    </div>
  </section>
</div>

<div class="footer"><p>Viral Sweet Potato Content Breakdown &nbsp;|&nbsp; 1 位博主 &nbsp;|&nbsp; __NOW__</p></div>
<script>__CHARTJS__</script>
__JS__
</body>
</html>"""

    # ── ChartJS ──
    chartjs_path = os.path.join(os.path.dirname(__file__), "chart.umd.min.js")
    chartjs_code = ""
    if os.path.exists(chartjs_path):
        with open(chartjs_path, "r", encoding="utf-8") as f:
            chartjs_code = f.read()

    # ── Fill template using .format() (NOT % operator, which conflicts with JS % signs) ──
    # Simple str.replace — no formatting operator conflicts
    html = html.replace("__NAME__", d["name"])
    html = html.replace("__NOW__", now)
    html = html.replace("__AVG_INTERACT__", f"{d['avg_interact']:,}")
    html = html.replace("__AVG_LIKES__", f"{d['al']:,}")
    html = html.replace("__HIT_RATE__", str(d["hr"]))
    html = html.replace("__HIT_THRESHOLD__", f"{d['al']*3:,}")
    html = html.replace("__RATIO_LABEL__", d["rl"])
    html = html.replace("__SL_RATIO__", str(d["sl"]))
    html = html.replace("__FREQ_LABEL__", d["freq_label"])
    html = html.replace("__SENTIMENT_SCORE__", f"{score:+.2f}")
    html = html.replace("__SENT_LABEL__", sent_label)
    html = html.replace("__TOTAL_NOTES__", str(d["n"]))
    html = html.replace("__VIDEO_COUNT__", str(s.get("video_count", 0)))
    html = html.replace("__NORMAL_COUNT__", str(s.get("normal_count", 0)))
    html = html.replace("__AVG_COLLECTS__", f"{s.get('avg_collects',0):,}")
    html = html.replace("__SENTIMENT_TOTAL__", str(sentiment_total))
    html = html.replace("__POS_HTML__", "".join("<p class='cl'>「%s」</p>" % e[:80] for e in pos_examples))
    neg = "".join("<p class='cl'>「%s」</p>" % e[:80] for e in neg_examples) if neg_examples else "<p style='font-size:12px;color:var(--tm)'>未检测到负向</p>"
    html = html.replace("__NEG_HTML__", neg)
    html = html.replace("__NOTICE__", notice)
    html = html.replace("__HEATMAP__", heatmap_html)
    html = html.replace("__CTA_CARD__", cta_card_html)
    html = html.replace("__JS__", js)
    html = html.replace("__CHARTJS__", chartjs_code)

    return html


if __name__ == "__main__":
    if sys.platform == "win32": sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="数据可视化面板 v5")
    p.add_argument("--data-dir", default="./data"); p.add_argument("--output-dir", "-o", default="./output")
    p.add_argument("--bloggers"); args = p.parse_args()
    bl = [n.strip() for n in args.bloggers.split(",") if n.strip()] if args.bloggers else None
    generate_dashboard(args.data_dir, args.output_dir, bl)
