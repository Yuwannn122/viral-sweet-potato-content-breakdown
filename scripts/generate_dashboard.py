"""
数据可视化面板生成器 v4
对齐 4 份拆解报告：账号总览 / 内容策略 / 爆款引擎 / 评论洞察
单页滚动布局，无 JS Tab 切换，全部内容直接可见。
"""
import json, os, sys, argparse
from datetime import datetime
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.common import safe_filename

def load_all_data(data_dir, blogger_names=None):
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
        notes = raw["notes"]; freq = detect_posting_frequency(notes)
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
        from deep_analyze import extract_cta_patterns, analyze_content_structure, extract_emoji_patterns
        descs = []
        for item in raw["details"]:
            nd = item.get("data",{}).get("note",item)
            d = nd.get("desc","") or ""
            descs.append(d)
        cta_info = extract_cta_patterns(descs) if descs else {}
        struct_info = analyze_content_structure(descs) if descs else {}
        emoji_info = extract_emoji_patterns(descs) if descs else {}
        tl = raw["stats"].get("total_likes",1) or 1; tc = raw["stats"].get("total_collects",0)
        sl_ratio = round(tc/tl,2)
        rl = "实用工具型" if sl_ratio>0.6 else ("实用驱动型" if sl_ratio>0.33 else ("均衡型" if sl_ratio>0.2 else ("情绪共鸣型" if sl_ratio>0.1 else "强情绪共鸣型")))
        al = raw["stats"].get("avg_likes",0); ht = al*3 if al>0 else 1
        hit_rate=round(sum(1 for n in notes if n.get("likes",0)>=ht)/max(raw["notes_count"],1)*100,1)
        all_data.append({"name":raw["name"],"safe":raw["safe_name"],"stats":raw["stats"],
            "notes":notes,"n":raw["notes_count"],"cats":raw["categories"],"freq":freq,
            "sentiment":sentiment,"heatmap":heatmap,"title_pats":title_pats,
            "track_dist":dict(track_dist),"hook_dist":dict(hook_dist),
            "td":{"图文":raw["stats"].get("normal_count",0),"视频":raw["stats"].get("video_count",0)},
            "sl":sl_ratio,"rl":rl,"hr":hit_rate,"al":al,"freq_label":freq.get("pattern","?"),
            "cta":cta_info,"struct":struct_info,"emoji":emoji_info,"descs":descs,
            "details_ok":raw["details_available"]})
    return all_data

def _js(obj): return json.dumps(obj,ensure_ascii=False,default=str).replace("</","<\\/")
PAL = ["#D97757","#6B9080","#8B7E74","#B5838D","#7B9EA8","#C4956A","#9B8EC4","#6E8B7B"]
PN = ["数字型","疑问型","感叹型","教程型","列表型","对比型","故事型","悬念型"]

def _card(h,sub,body): return f'<div class="card"><div class="ch">{h}</div><div class="cs">{sub}</div>{body}</div>'
def _full(h,sub,body): return f'<div class="card full"><div class="ch">{h}</div><div class="cs">{sub}</div>{body}</div>'

def generate_html(all_data, output_dir):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    names = [d["name"] for d in all_data]; N=len(all_data); is_batch=N>1

    # === KPI cards ===
    kpi_html = ""
    for i,d in enumerate(all_data):
        sl_label = "偏正向" if d["sentiment"].get("overall_score",0)>0.3 else ("中性偏正" if d["sentiment"].get("overall_score",0)>0 else "中性")
        score = d["sentiment"].get("overall_score",0) or 0
        ti = d["stats"].get("total_likes",1) or 1
        ai = round((ti+d["stats"].get("total_collects",0)+d["stats"].get("total_comments",0))/max(d["n"],1))
        name_html = f'<span class="dot" style="background:{PAL[i%len(PAL)]}"></span>{d["name"]}' if is_batch else ""
        kpi_html += f"""<div class="kpi-group"><div class="kgn">{name_html}</div><div class="kgc">
          <div class="kc"><div class="kl">篇均互动</div><div class="kv">{ai:,}<span class="ku">次</span></div><div class="ks">均赞 {d["al"]:,}</div></div>
          <div class="kc"><div class="kl">爆款率</div><div class="kv">{d["hr"]}<span class="ku">%</span></div><div class="ks">>{d["al"]*3:,}赞为爆款</div></div>
          <div class="kc"><div class="kl">内容类型<span class="kl-n"> (藏赞比判定)</span></div><div class="kv">{d["rl"]}</div><div class="ks">藏赞比{d["sl"]} · {d["freq_label"]}</div></div>
          <div class="kc"><div class="kl">评论情感</div><div class="kv">{'+' if score>=0 else ''}{score:.2f}</div><div class="ks">{sl_label}</div></div>
        </div></div>"""

    # === Section 1: 账号总览 ===
    s1 = ""
    if is_batch:
        rows = "".join(f'<tr><td><strong>{d["name"]}</strong></td><td class="n">{d["n"]}</td><td class="n">{d["al"]:,}</td><td class="n">{d["stats"].get("avg_collects",0):,}</td><td class="n">{d["hr"]}%</td><td class="n">{d["sl"]}</td><td>{d["freq_label"]}</td><td class="n">{d["sentiment"].get("overall_score",0) or 0:+.2f}</td></tr>' for d in all_data)
        s1 = _full("📋 横向对比总览","核心指标一览",f'<table class="dt"><thead><tr><th>博主</th><th>笔记</th><th>均赞</th><th>均收藏</th><th>爆款率</th><th>藏赞比</th><th>更新频率</th><th>情感</th></tr></thead><tbody>{rows}</tbody></table>')
        # Radar
        max_al = max(d["al"] for d in all_data) or 1
        rd = [{"label":d["name"],"data":[round(d["al"]/max_al*100),round(d["stats"].get("avg_collects",0)/max(max_al,1)*100),d["hr"],round(ai/max(d.get("avg_interact",1) for d in all_data)*100) if all_data else 0,50],"borderColor":PAL[i%len(PAL)],"backgroundColor":PAL[i%len(PAL)].replace(")","0.15)")[:6]+"0.15)","borderWidth":2} for i,d in enumerate(all_data)]
        # Fix ai reference
        rd2 = []
        max_ai = max((d["stats"].get("total_likes",1)+d["stats"].get("total_collects",0)+d["stats"].get("total_comments",0))/max(d["n"],1) for d in all_data) or 1
        for i,d in enumerate(all_data):
            ai2 = (d["stats"].get("total_likes",1)+d["stats"].get("total_collects",0)+d["stats"].get("total_comments",0))/max(d["n"],1)
            rd2.append({"label":d["name"],"data":[round(d["al"]/max_al*100),round(d["stats"].get("avg_collects",0)/max(max_al,1)*100),d["hr"],round(ai2/max_ai*100),50],"borderColor":PAL[i%len(PAL)],"backgroundColor":PAL[i%len(PAL)][:7]+"0.15)","borderWidth":2})
        s1 += _card("🎯 综合能力雷达","标准化相对值",'<canvas id="radarChart"></canvas>')
    else:
        d=all_data[0];s=d["stats"]
        s1 = _card("📋 账号基础数据","来自小红书主页",
            f'<table class="dt"><tbody><tr><td>笔记数</td><td class="n">{d["n"]}</td><td>视频/图文</td><td class="n">{s.get("video_count",0)}/{s.get("normal_count",0)}</td></tr>'
            f'<tr><td>均赞</td><td class="n">{s.get("avg_likes",0):,}</td><td>均收藏</td><td class="n">{s.get("avg_collects",0):,}</td></tr>'
            f'<tr><td>爆款率</td><td class="n">{d["hr"]}%</td><td>藏赞比</td><td class="n">{d["sl"]} ({d["rl"]})</td></tr>'
            f'<tr><td>更新频率</td><td>{d["freq_label"]}</td><td>情感得分</td><td class="n">{d["sentiment"].get("overall_score",0) or 0:+.2f}</td></tr></tbody></table>')
        td=d.get("track_dist",{});st=sorted(td.items(),key=lambda x:x[1],reverse=True)[:8]
        if st: s1 += f'<div class="card"><div class="ch">🏷️ 赛道分布</div><div class="cs">内容领域覆盖</div><canvas id="trackChart"></canvas></div>'

    # === Section 2: 内容策略 ===
    hl = sorted(set().union(*(d.get("hook_dist",{}).keys() for d in all_data)))
    hd = [{"label":d["name"],"data":[d.get("hook_dist",{}).get(h,0) for h in hl],"backgroundColor":PAL[i%len(PAL)]} for i,d in enumerate(all_data)]
    pd = [{"label":d["name"],"data":[d.get("title_pats",{}).get(pn,{}).get("pct",0) for pn in PN],"backgroundColor":PAL[i%len(PAL)]} for i,d in enumerate(all_data)]
    cl = ["关注","收藏","点赞","评论","转发","私信"]
    cd = [{"label":d["name"],"data":[d.get("cta",{}).get(f"{l}引导",{}).get("pct",0) for l in cl],"backgroundColor":PAL[i%len(PAL)]} for i,d in enumerate(all_data)]
    fd = [{"label":d["name"],"data":[d.get("td",{}).get("视频",0),d.get("td",{}).get("图文",0)],"backgroundColor":PAL[i%len(PAL)]} for i,d in enumerate(all_data)]
    s2 = f"""<div class="cg">
      {_card("🎣 前3秒钩子策略","吸引注意力的方式分布",'<canvas id="hookChart"></canvas>')}
      {_card("📝 标题模式偏好","8种标题策略使用频率",'<canvas id="patternChart"></canvas>')}
      {_card("📢 CTA 引导策略","行动号召类型分布",'<canvas id="ctaChart"></canvas>')}
      {_card("🎬 内容形式","视频/图文比",'<canvas id="formatChart"></canvas>')}
    </div>"""

    # === Section 3: 爆款引擎 ===
    vd = [{"label":d["name"],"data":[d["sl"]*100,d["hr"]],"backgroundColor":[PAL[i%len(PAL)],PAL[i%len(PAL)][:7]+"0.4)"]} for i,d in enumerate(all_data)]
    ids_data = []
    for i,d in enumerate(all_data):
        s=d["stats"];tl=s.get("total_likes",1) or 1;tc=s.get("total_collects",0);tm=s.get("total_comments",0);tot=tl+tc+tm or 1
        ids_data.append({"label":d["name"],"data":[round(tl/tot*100,1),round(tc/tot*100,1),round(tm/tot*100,1)],"backgroundColor":[PAL[i%len(PAL)]]*3})
    s3 = f"""<div class="cg">
      {_card("📊 藏赞比 & 爆款率","收藏÷点赞 vs 爆款占比",'<canvas id="viralBarChart"></canvas>')}
      {_card("❤️ 互动构成","点赞/收藏/评论占比",'<canvas id="interactChart"></canvas>')}
    </div>"""
    # Heatmaps
    for d in all_data:
        hm=d.get("heatmap",{});mx=hm.get("hour_day_matrix",[])
        if not mx or len(mx)!=7: continue
        maxv=max(max(r) for r in mx) if mx else 1
        days=hm.get("day_names_cn",["周一","周二","周三","周四","周五","周六","周日"])
        slots=hm.get("time_slots",["00-06","06-08","08-12","12-14","14-18","18-21","21-24"])
        rows=""
        for si,s in enumerate(slots):
            cells=""
            for v in mx[si]:
                if v>0: cells+=f'<td style="background:rgba(217,119,87,{v/maxv*0.75:.2f})">{v}</td>'
                else: cells+="<td></td>"
            rows+=f"<tr><th>{s}</th>{cells}</tr>"
        wins=" &nbsp;|&nbsp; ".join(f"{w['day']}{w['slot']}({w['count']}条)" for w in hm.get("optimalWindows",[])[:3])
        s3+=f"""<div class="card full"><div class="ch">🔥 发布时间热力图 · {d['name']}</div><div class="cs">最佳: {hm.get('best_day','')} {hm.get('best_hour_block','')}{' &nbsp;|&nbsp; '+wins if wins else ''}</div><table class="hm"><thead><tr><th></th>{"".join(f"<th>{x}</th>" for x in days)}</tr></thead><tbody>{rows}</tbody></table></div>"""

    # === Section 4: 评论洞察 ===
    sbs = []
    for i,d in enumerate(all_data):
        sr=d.get("sentiment",{});pn=sr.get("per_note",[])
        if pn: sbs.append({"name":d["name"],"pos":round(sum(p.get("positive_pct",0) for p in pn)/len(pn),1),"neu":round(sum(p.get("neutral_pct",0) for p in pn)/len(pn),1),"neg":round(sum(p.get("negative_pct",0) for p in pn)/len(pn),1),"tot":sr.get("total_comments_analyzed",0),"hp":sr.get("positive_examples",[])[:2],"hn":sr.get("negative_examples",[])[:2]})
        else: sbs.append({"name":d["name"],"pos":0,"neu":0,"neg":0,"tot":0,"hp":[],"hn":[]})
    sd = [{"label":s["name"],"data":[s["pos"],s["neu"],s["neg"]],"backgroundColor":PAL[i%len(PAL)]} for i,s in enumerate(sbs) if s["tot"]>0]
    s4 = f'<div class="cg">{_full("💬 评论情感分布","正向/中性/负向占比",'<canvas id="sentimentChart"></canvas>')}</div>'
    s4 += '<div class="cg cg2">'
    for i,s in enumerate(sbs):
        if not s["tot"]: continue
        s4 += _card(f'💚 正向 · {s["name"]}',f'{s["tot"]}条评论',"".join(f"<p class='cl'>「{e[:80]}」</p>" for e in s["hp"]))
        s4 += _card(f'⚠️ 需关注 · {s["name"]}','负向评论',"".join(f"<p class='cl'>「{e[:80]}」</p>" for e in s["hn"]) if s["hn"] else '<p style="font-size:12px;color:var(--color-text-muted)">未检测到负向</p>')
    s4 += '</div>'

    # === Full HTML ===
    blogger_tabs = ""
    if is_batch:
        tabs = "".join(f'<button class="bt{" active" if i==0 else ""}" data-bi="{i}">{d["name"]}</button>' for i,d in enumerate(all_data))
        blogger_tabs = f'<div class="bts" id="bloggerTabs"><button class="bt active" data-bi="all">全部</button>{tabs}</div>'

    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>小红书分析看板 — {_js(names)}</title>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,600;1,400&family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#F7F5F0;--s:#FFF;--sa:#F0EDE6;--accent:#D97757;--t:#141413;--t2:#6B6860;--tm:#9C9890;--b:#E6E3DC;--r:12px;--sh:0 1px 3px rgba(0,0,0,0.04)}}
*{{margin:0;padding:0;box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{font-family:'Lora',serif;background:var(--bg);color:var(--t);-webkit-font-smoothing:antialiased;line-height:1.6}}
.hdr{{background:var(--s);border-bottom:1px solid var(--b);padding:24px 36px}}
.hdr h1{{font-family:'Poppins',sans-serif;font-size:22px;font-weight:600;letter-spacing:-0.3px}}
.hdr .sub{{font-family:'Poppins',sans-serif;font-size:12px;color:var(--t2);margin-top:4px}}
.bts{{display:flex;gap:4px;padding:12px 36px 0;background:var(--s);border-bottom:1px solid var(--b)}}
.bt{{font-family:'Poppins',sans-serif;font-size:12px;font-weight:500;padding:7px 16px;border:none;background:transparent;color:var(--t2);cursor:pointer;border-radius:8px 8px 0 0;transition:all .2s;position:relative;top:1px}}
.bt:hover{{color:var(--t);background:var(--sa)}}
.bt.active{{color:var(--accent);background:var(--bg);border:1px solid var(--b);border-bottom-color:var(--bg)}}
.tab-nav{{display:flex;gap:0;padding:0 36px;max-width:1500px;margin:0 auto;position:sticky;top:0;z-index:10;background:var(--bg);padding-top:8px}}
.tab-btn{{font-family:'Poppins',sans-serif;font-size:13px;font-weight:500;padding:10px 22px;border:none;background:transparent;color:var(--t2);cursor:pointer;text-decoration:none;border-bottom:2px solid transparent;transition:all .2s}}
.tab-btn:hover{{color:var(--t)}}
.tab-btn.active{{color:var(--accent);border-bottom-color:var(--accent)}}
section{{scroll-margin-top:60px}}
.kpi{{display:flex;flex-direction:column;gap:10px;padding:18px 36px;max-width:1500px}}
.kg{{background:var(--s);border:1px solid var(--b);border-radius:var(--r);padding:12px 16px;box-shadow:var(--sh)}}
.kgn{{font-family:'Lora',serif;font-size:13px;font-weight:600;margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--b)}}
.kgn .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}}
.kgc{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:8px}}
.kc{{background:var(--sa);border-radius:8px;padding:10px 12px}}
.kl{{font-family:'Poppins',sans-serif;font-size:9px;font-weight:500;color:var(--t2);text-transform:uppercase;letter-spacing:.5px}}
.kl-n{{font-weight:400;text-transform:none}}
.kv{{font-family:'Lora',serif;font-size:20px;font-weight:600;margin-top:2px;line-height:1.2}}
.ku{{font-family:'Poppins',sans-serif;font-size:10px;font-weight:400;color:var(--t2);margin-left:2px}}
.ks{{font-family:'Poppins',sans-serif;font-size:9px;color:var(--tm);margin-top:2px}}
.main{{max-width:1500px;margin:0 auto;padding:20px 36px}}
.sec-title{{font-family:'Poppins',sans-serif;font-size:17px;font-weight:600;margin:28px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--accent);display:inline-block}}
.cg{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}}
.cg2{{grid-template-columns:1fr 1fr}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:var(--r);padding:20px;box-shadow:var(--sh)}}
.card.full{{grid-column:1/-1}}
.ch{{font-family:'Lora',serif;font-size:15px;font-weight:600;margin-bottom:4px}}
.cs{{font-family:'Poppins',sans-serif;font-size:11px;color:var(--t2);margin-bottom:12px}}
.dt{{width:100%;border-collapse:collapse;font-family:'Poppins',sans-serif;font-size:12px}}
.dt th{{font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:var(--t2);text-align:left;padding:8px 10px;border-bottom:2px solid var(--b)}}
.dt td{{padding:8px 10px;border-bottom:1px solid var(--b)}}
.dt tr:nth-child(even) td{{background:var(--sa)}}
.dt .n{{font-family:'JetBrains Mono',monospace;font-size:11px;text-align:right}}
.hm{{width:100%;border-collapse:collapse;font-size:11px;font-family:'JetBrains Mono',monospace}}
.hm th{{font-family:'Poppins',sans-serif;font-size:10px;padding:4px 5px;text-align:center;color:var(--t2)}}
.hm td{{padding:4px 5px;text-align:center;border-radius:4px}}
.cl{{font-size:12px;padding:5px 0;border-bottom:1px solid var(--b)}}
.footer{{text-align:center;padding:28px;font-family:'Poppins',sans-serif;font-size:10px;color:var(--tm)}}
@media(max-width:768px){{.hdr,.kpi,.main{{padding-left:14px;padding-right:14px}}.cg,.cg2{{grid-template-columns:1fr}}}}
</style></head><body>
<div class="hdr"><h1>📊 小红书内容分析看板</h1><p class="sub">{_js(names)} &nbsp;|&nbsp; {now} &nbsp;|&nbsp; Viral Sweet Potato Content Breakdown</p></div>
{blogger_tabs}
<div class="kpi" id="kpiBar">{kpi_html}</div>
<nav class="tab-nav">
  <a href="#sec-overview" class="tab-btn active">账号总览</a>
  <a href="#sec-strategy" class="tab-btn">内容策略</a>
  <a href="#sec-viral" class="tab-btn">爆款引擎</a>
  <a href="#sec-comments" class="tab-btn">评论洞察</a>
</nav>
<div class="main">
  <section id="sec-overview"><div class="sec-title">一、账号总览</div><div class="cg">{s1}</div></section>
  <section id="sec-strategy"><div class="sec-title">二、内容策略</div>{s2}</section>
  <section id="sec-viral"><div class="sec-title">三、爆款引擎</div>{s3}</section>
  <section id="sec-comments"><div class="sec-title">四、评论洞察</div>{s4}</section>
</div>
<div class="footer"><p>Viral Sweet Potato Content Breakdown &nbsp;|&nbsp; {N} 位博主 &nbsp;|&nbsp; {now}</p></div>
<script>
// All charts
const co={{responsive:true,maintainAspectRatio:true,plugins:{{legend:{{position:'bottom',labels:{{font:{{family:'Poppins',size:10}},padding:12,usePointStyle:true}}}}}}}};
// Radar
{"new Chart(document.getElementById('radarChart'),{type:'radar',data:{labels:"+_js(["均赞","均收藏","爆款率","篇均互动","正向情感"])+",datasets:"+_js(rd2)+"},options:{{...co,scales:{{r:{{beginAtZero:true,max:100,ticks:{{stepSize:20,font:{{size:10}}}}}}}}}});" if is_batch else ""}
// Track donut
{"new Chart(document.getElementById('trackChart'),{type:'doughnut',data:{labels:"+_js([t[0] for t in st] if not is_batch else [])+",datasets:[{{data:"+_js([t[1] for t in st] if not is_batch else [])+",backgroundColor:"+_js(PAL[:len(st)])+"}}]},options:{{plugins:{{legend:{{position:'bottom',labels:{{font:{{family:'Poppins',size:10}},padding:10,usePointStyle:true}}}}}}}}});" if not is_batch and st else ""}
// Hook
new Chart(document.getElementById('hookChart'),{{type:'bar',data:{{labels:{_js(hl)},datasets:{_js(hd)}}},options:{{...co,scales:{{y:{{beginAtZero:true,title:{{display:true,text:'次',font:{{family:'Poppins'}}}}}}}}}}}});
// Pattern
new Chart(document.getElementById('patternChart'),{{type:'bar',data:{{labels:{_js(PN)},datasets:{_js(pd)}}},options:{{...co,scales:{{y:{{beginAtZero:true,ticks:{{callback:v=>v+'%'}}}}}}}}}});
// CTA
new Chart(document.getElementById('ctaChart'),{{type:'bar',data:{{labels:{_js(cl)},datasets:{_js(cd)}}},options:{{...co,scales:{{y:{{beginAtZero:true,ticks:{{callback:v=>v+'%'}}}}}}}}}});
// Format
new Chart(document.getElementById('formatChart'),{{type:'bar',data:{{labels:['视频','图文'],datasets:{_js(fd)}}},options:{{...co,scales:{{y:{{beginAtZero:true}}}}}}}});
// Viral
new Chart(document.getElementById('viralBarChart'),{{type:'bar',data:{{labels:['藏赞比(x100)','爆款率(%)'],datasets:{_js(vd)}}},options:{{...co,scales:{{y:{{beginAtZero:true}}}}}}}});
// Interact
new Chart(document.getElementById('interactChart'),{{type:'bar',data:{{labels:['点赞','收藏','评论'],datasets:{_js(ids_data)}}},options:{{...co,scales:{{y:{{max:100,ticks:{{callback:v=>v+'%'}}}}}}}}}});
// Sentiment
{"new Chart(document.getElementById('sentimentChart'),{type:'bar',data:{labels:['正向','中性','负向'],datasets:"+_js(sd)+"},options:{...co,scales:{y:{max:100,ticks:{callback:v=>v+'%'}}}}});" if sd else ""}
// Sticky tab highlight on scroll
const sections=document.querySelectorAll('section[id]');
const navBtns=document.querySelectorAll('.tab-btn');
const observer=new IntersectionObserver(entries=>{{entries.forEach(e=>{{if(e.isIntersecting){{navBtns.forEach(b=>b.classList.remove('active'));document.querySelector('.tab-btn[href="#'+e.target.id+'"]').classList.add('active')}}}})}},{{rootMargin:'-30% 0px -60% 0px'}});
sections.forEach(s=>observer.observe(s));
</script>
</body></html>"""
    return html


def generate_dashboard(data_dir, output_dir, blogger_names=None):
    all_data = load_all_data(data_dir, blogger_names)
    if not all_data: print("❌ 未找到任何博主数据"); return None
    print(f"\n📊 生成运营级数据看板...")
    print(f"   博主: {len(all_data)} | 模式: {'批量对标' if len(all_data)>1 else '单博主诊断'}")
    html = generate_html(all_data, output_dir)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "数据可视化面板.html")
    with open(path, "w", encoding="utf-8") as f: f.write(html)
    print(f"  📄 {path} ({os.path.getsize(path)/1024:.0f}KB)")
    print(f"  📋 单页4区: 账号总览 / 内容策略 / 爆款引擎 / 评论洞察")
    return path

if __name__ == "__main__":
    if sys.platform == "win32": sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="数据可视化面板 v4")
    p.add_argument("--data-dir", default="./data"); p.add_argument("--output-dir", "-o", default="./output")
    p.add_argument("--bloggers"); args = p.parse_args()
    bl = [n.strip() for n in args.bloggers.split(",") if n.strip()] if args.bloggers else None
    generate_dashboard(args.data_dir, args.output_dir, bl)
