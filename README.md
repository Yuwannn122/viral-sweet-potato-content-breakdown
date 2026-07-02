<div align="center">

# 🔬 地瓜爆款拆解系统

**Viral Sweet Potato Content Breakdown · 小红书内容分析 Skill**

输入博主名 → 全量拆解报告 · 输入多位博主 → 赛道竞争格局 · 输入笔记链接 → 五维+三镜公式卡

[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green.svg)](#跨平台)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

> 基于 [xhs-blogger-analyzer](https://github.com/arraycto/xhs-blogger-analyzer)（MIT License）增删改。新增：多博主批量对比、赛道竞争格局报告、五维+三镜爆款拆解、评论区情感分析、发布时间热力图、29赛道分类、图片序列分析、数据可视化面板。

---

## 三大功能

| 功能 | 触发 | 产出 |
|------|------|------|
| **博主全量拆解** | `拆解博主 XX` / `拆解博主 XX，对比我的账号` | 4 份 DOCX + MD + HTML 看板 |
| **多博主批量拆解** | `依次拆解 A、B、C` / `批量拆解 AI 赛道：A、B、C` | N×4 报告 + 赛道竞争格局报告 + HTML 看板 |
| **单条爆款拆解** | `拆解这条 <笔记链接>` | 五维+三镜公式卡 DOCX |

适用于任何领域：AI、美食、穿搭、美妆、旅行、母婴、健身、职场等。

---

## 快速开始

```bash
# 单博主
python run.py "目标博主名"
python run.py "目标博主名" --self "我的账号"

# 批量
python batch_run.py --bloggers "博主A,博主B,博主C"
python batch_run.py --bloggers "A,B" --self "我的账号"

# 单条爆款
python scripts/analyze_viral_post.py --url "<链接>" "<博主名>" -o ./output

# 跳过环境检查（已确认 MCP + 已登录）
python run.py "目标博主名" --skip-env
```

环境自动准备（Python 依赖 + MCP 二进制 + 扫码登录），所有模式自动生成数据可视化面板。

---

## 产出物

### 博主全量拆解 & 批量拆解

| 文档 | 内容 |
|------|------|
| **博主深度拆解** | 11章：账号概览、人设拆解、TOP10逐条拆解、内容模式分类、评论深度洞察、选题逻辑、竞争优势、短板、对你的启示 |
| **内容公式总结** | 9章：11种标题公式、开头/结构/CTA/视觉/标签/排版/发布时间公式、一句话总结 |
| **选题素材库** | 6章：已验证爆款选题、对标高赞选题、差异化赛道、优先级×难度矩阵、系列IP建议、素材积累提醒 |
| **全量笔记结构化分析** | 8章：数据总览、内容领域全景图、发展趋势、爆款公式深度拆解、互动数据、标签生态、竞争格局、核心结论 |
| **赛道竞争格局报告**（批量） | 横向对比表、标题/内容/情感/发布时间策略对比、领域重叠、赛道级诉求聚合、差异化机会分析 |
| **数据可视化面板** | HTML：账号总览/内容策略/爆款引擎/评论洞察 4区可交互看板 |

### 单条爆款拆解

五维+三镜报告 + 公式卡（标题公式、结构模板、CTA策略、适配赛道），含数据结论 / 文本推断标注。

---

## 项目结构

```
地瓜爆款拆解系统/
├── SKILL.md                  # Skill 定义（核心）
├── run.py                    # 单博主入口
├── batch_run.py              # 批量入口
├── install.py                # 安装脚本
├── scripts/
│   ├── check_env.py          # Phase 0: 环境准备
│   ├── crawl_blogger.py      # Phase 1: 数据采集
│   ├── analyze.py            # Phase 2: 数据分析
│   ├── generate_docs.py      # Phase 3: 文档骨架
│   ├── deep_analyze.py       # Phase 3.5: AI深度分析 + 情感 + 热力图 + 赛道分类 + 图片序列
│   ├── generate_dashboard.py # Phase 3.6: 可视化面板
│   ├── analyze_viral_post.py # Phase 4: 单条爆款拆解
│   ├── cross_analyze.py      # Phase 5: 跨博主对比
│   └── utils/
│       ├── common.py         # parse_count / safe_filename / ms_to_datetime
│       ├── mcp_client.py     # MCP HTTP 封装
│       └── md_to_docx.py     # MD → Word
└── references/
    └── 产出物质量标杆.md      # AI 分析质量标准
```

---

## 批量拆解 vs 原版「多种玩法」

原版 xhs-blogger-analyzer 的 README 提到可"拆解博主 XX、YY、ZZ"，本质是**多次手动运行单博主模式**。本项目的 `batch_run.py` 是真正的批量编排系统：

| | 原版多次运行 | 本项目批量模式 |
|------|------------|-------------|
| 执行方式 | 手动逐个跑 `run.py` | 一次命令自动串联 |
| 断点恢复 | 无 | `_batch_checkpoint.json` |
| 博主名预检 | 无 | 跑前搜索确认匹配 |
| 横向对比报告 | 无 | 赛道竞争格局报告 |
| 上限 | 无限制（手动操作） | 无硬上限，受 MCP 请求频率和时间约束 |

**批量建议**：一次 3-5 位博主为宜。更多博主可以跑但耗时长且风控风险增加。

---

## Roadmap

- [x] 博主全量拆解（4 份报告）
- [x] 评论区情感分析 + 发布时间热力图
- [x] 五维+三镜 单条爆款拆解
- [x] 多博主批量拆解 + 赛道竞争格局报告
- [x] 数据可视化面板（Chart.js HTML 看板）
- [x] 图文笔记图片序列分析（imageList 元数据）
- [x] 29 赛道分类器（`classify_content_track`）
- [x] 博主名预检确认（批量防错）
- [ ] 数据可视化面板增强（交互导览）
- [ ] 多平台兼容测试（OpenClaw）

---

## 致谢 & License

基于 [xhs-blogger-analyzer](https://github.com/arraycto/xhs-blogger-analyzer)（MIT License）。

MIT License · 详见 [LICENSE](LICENSE)

---

<div align="center">

**让每一个小红书创作者，都能像专业 MCN 一样拆解内容。**

</div>
