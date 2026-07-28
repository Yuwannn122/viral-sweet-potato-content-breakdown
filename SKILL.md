---
name: viral-sweet-potato-content-breakdown
description: >
地瓜爆款拆解系统（Viral Sweet Potato Content Breakdown）。
三大功能体系：
  【Creator Profile Viral Breakdown · 博主全量拆解】
  输入博主昵称，自动爬取笔记 → 4 份深度报告（博主深度拆解 / 内容公式总结 / 选题素材库 / 结构化分析），支持与自己账号对比。日常对标首选，最安全。

  【Multi-Blogger Batch Mode · 多博主批量拆解】
  输入多位博主，依次爬取分析 → 每人独立报告 + 赛道竞争格局横向对比报告 + 数据可视化面板。建议间隔使用，勿频繁批量请求。

  【Single Viral Post Breakdown · 单条爆款拆解】
  输入笔记链接或已有数据，五维+三镜深度拆解 → 公式卡。独立功能，不依赖博主拆解流程。
  ★ 新功能：--ocr 模式可无需登录提取图片文字（原理见下文「OCR 图文提取」章节）

  适用任何领域：AI、美食、穿搭、旅行、母婴、健身、美妆、家居等。
  Skill 自动完成环境准备。用户唯一需要做的是扫码登录小红书（建议使用测试号/小号）。
  ★ OCR 模式无需登录，直接提取图片内容。

  触发词：
    博主拆解 → 「拆解博主」「分析博主」「对标账号」「博主数据」
    批量拆解 → 「依次拆解」「批量拆解」「拆解以下博主」「对比分析」
    单条拆解 → 「五维拆解」「爆款拆解」「拆解这条」「拆解这个视频/图文」
disable-model-invocation: false
argument-hint: "[博主昵称 / 笔记链接 / 博主列表]"
---

# 地瓜爆款拆解系统 · Viral Sweet Potato Content Breakdown

## 快速开始

三大功能，AI 根据你的输入自动路由：

| 你说 | AI 做什么 | 产出 | 推荐场景 |
|------|----------|------|---------|
| 「拆解博主 XX」 | 爬取全部笔记 → 4 份报告 | DOCX + MD + HTML 看板 | **日常对标**（最安全） |
| 「拆解博主 XX，对比我的账号」 | 上者 + 你的数据对比 | 4 份报告含对比章节 | 找差距 |
| 「依次拆解A、B、C…」 | 逐一爬取 → 横向对比 | N×4 报告 + 赛道竞争格局报告 + 可视化看板 | 竞品分析（建议低频使用） |
| 「拆解这条 <链接>」 | 五维+三镜拆解 | 单条公式卡 DOCX | 研究某条爆款 |

---

## 前置要求 & 安全须知

### 运行环境

| 要求 | 说明 |
|------|------|
| 本地桌面环境 | 需显示图片/打开文件（扫码登录必需） |
| Python 3.8+ | Skill 自动检测 |
| 网络 | 下载 MCP 二进制 + 爬取数据 |
| MCP 扫码登录 | 唯一手动步骤 |

### ⚠️ 安全须知

```text
1. 建议使用测试号/小号扫码 MCP，不要用主力号
2. xiaohongshu-mcp 是第三方逆向工具，非官方 API
3. 单次拆解 1 位博主（全量笔记）≈ 正常浏览行为，风险低
4. 批量拆解短时间内请求量大，建议间隔使用，不要连续跑多轮
5. 遇到 timed out → 停手等待 30 分钟以上冷却
6. 笔记间隔已设为 5 秒，博主间隔 30 秒，默认防风控
```

---

## 模式一：Creator Profile Viral Breakdown · 博主全量拆解

### 一键运行

```bash
# 基本
python run.py "A"

# 对比自己账号
python run.py "A" --self "我的账号名"

# 指定领域关键词（提升搜索覆盖率）
python run.py "A" --keywords "美妆,教程,测评…"

# 跳过环境检查（已确认 MCP 运行 + 已登录时）
python run.py "A" --skip-env
```

### 执行流程

```text
Phase 0: 环境准备（python 依赖 + MCP 二进制 + 扫码登录）
Phase 1: 数据采集（搜索博主 → 主页信息 → 笔记列表 → 逐条详情+评论）
Phase 2: 数据分析（分类/标签/TOP10/对比）
Phase 3: 文档骨架（4 份 DOCX 含数据表格）
Phase 3.5: AI 深度分析（数据底稿 → AI 写最终报告）
Phase 3.6: 数据可视化面板（HTML 看板）
```

### 产出物

| 文档 | 内容 | 格式 |
|------|------|------|
| 博主深度拆解 | 账号画像、人设拆解、TOP10 逐条分析、评论洞察 | DOCX + MD |
| 内容公式总结 | 标题公式/开头/结构/CTA/视觉/排版/发布时间 全维度模板 | DOCX + MD |
| 选题素材库 | 可借鉴选题、差异化赛道、优先级×难度矩阵、系列 IP 建议 | DOCX + MD |
| 全量笔记结构化分析 | 领域分布、藏赞比、发展趋势、爆款规律、发布热力图 | DOCX + MD |
| 数据可视化面板 | 账号总览 / 内容策略 / 爆款引擎 / 评论洞察 4 区看板 | HTML |

---

## 模式二：Multi-Blogger Batch Mode · 多博主批量拆解

### 一键运行

```bash
# 基本批量
python batch_run.py --bloggers "博主A,博主B,博主C"

# 含自己账号（差异化分析）
python batch_run.py --bloggers "博主A,博主B" --self "我的账号"

# 从文件读取博主列表
python batch_run.py --file bloggers.txt

# 快速测试（每位博主仅爬 10 条）
python batch_run.py --bloggers "A,B,C" --max-notes 10

# 跳过预检和环境检查
python batch_run.py --bloggers "A,B" --skip-precheck --skip-env
```

### 与单博主模式的区别

| 维度 | 单博主 | 批量 |
|------|--------|------|
| 请求量 | 1× 搜索 + N× 详情 | M× 搜索 + M×N× 详情 |
| 推荐频率 | 日常使用 | 偶尔竞品分析 |
| 额外产出 | — | 赛道竞争格局报告 + 横向对比看板 |
| 预检机制 | 无 | 跑前搜索确认博主名正确 |
| 断点恢复 | 无 | 每位博主完成后存档 |

### 额外产出

| 产出 | 内容 |
|------|------|
| 赛道竞争格局报告 | 横向对比表、标题/内容/情感/发布时间策略对比、领域重叠分析、赛道级用户诉求聚合 |
| [条件] 差异化机会分析 | 你的账号 vs 赛道均值、差距分析、未覆盖高需求话题、定位建议（需 `--self`） |
| 批量可视化看板 | 每位博主独立 KPI 行 + 雷达图 + 横向对比图表 |

### 输出结构

```text
output/
├── _batch_checkpoint.json
├── 赛道竞争格局_对比报告.docx
├── 数据可视化面板.html
├── 博主A/
│   ├── 博主A_博主深度拆解.docx
│   ├── 博主A_内容公式总结.docx
│   ├── 博主A_选题素材库.docx
│   └── 博主A_全量笔记结构化分析.docx
├── 博主B/
│   └── ...
└── _过程文件/
```

---

## 模式三：Single Viral Post Breakdown · 单条爆款拆解

> 独立功能，不依赖博主拆解流程。

### 运行

```bash
# 从已有数据按索引取笔记（0 = 最高赞）
python scripts/analyze_viral_post.py ./data/<博主>_notes_details.json 0 "<博主名>" -o ./output

# 通过小红书链接
python scripts/analyze_viral_post.py --url "<链接>" "<博主名>" -o ./output

# 通过 feed_id
python scripts/analyze_viral_post.py --feed-id <feed_id> "<博主名>" -o ./output

# ★ 通过链接 + OCR 提取图片文字（无需登录！）
python scripts/analyze_viral_post.py --url "<链接>" "<博主名>" --ocr -o ./output

# OCR 独立使用（仅提取图片文字，不拆解）
python scripts/extract_post_images_ocr.py --url "<链接>" -o ./ocr_output
```

### 方法论

**五维**（WHAT）= 流量捕获 / 内容骨架 / 视听节奏 / 互动转化 / 爆款要素提炼

**三镜**（HOW）= 每维内部 🔍还原（事实）→ 💡归因（因果）→ ✅验证（评论证据）

**数据可信度标注**：
- ✅ **数据结论** — 藏赞比、ASL、标题模式、评论情感、图片序列（基于 imageList）
- ⚠️ **文本推断** — BGM、封面类型（无 imageList 时）、节奏曲线（视频）
- 📐 **元数据** — 图文笔记封面比例/图片数量来自 MCP 返回的 `imageList`

**产出**：`{博主}_{标题}_五维拆解.docx`（含公式卡：标题公式 + 结构模板 + CTA 策略 + 适配赛道）

---

## 📸 OCR 图文提取（无需登录）

### 技术原理

小红书虽然是 SPA，但页面 HTML 中内嵌了包含图片 CDN 地址的 JSON 数据（用于 SEO 和首屏渲染）。图片 CDN（`sns-webpic-qc.xhscdn.com`）**没有鉴权限制**，只需设置 `Referer` 头即可直接下载。下载后用 `pytesseract` 做 OCR 识别，提取图片中的文字内容。

```
帖子URL → HTTPS请求HTML → 正则提取CDN图片URL → 下载图片 → pytesseract OCR → 结构化输出
```

**整个过程无需登录，无需 MCP。**

### 前置依赖

```bash
# Python 包
pip install requests Pillow pytesseract

# 系统依赖：Tesseract OCR + 中文语言包
# macOS:   brew install tesseract tesseract-lang
# Ubuntu:  apt install tesseract-ocr tesseract-ocr-chi-sim
# Windows: 下载 https://github.com/UB-Mannheim/tesseract/wiki
```

### 使用方式

**方式 1：集成到五维拆解（推荐）**

```bash
python scripts/analyze_viral_post.py --url "<链接>" "博主名" --ocr -o ./output
```

OCR 提取的图片文字会自动融入五维分析：
- **第二维 · 内容骨架**：用图片文字替代/补充空洞的正文，展示逐图信息分布和密度分析
- **第三维 · 视听节奏**：基于每张图的真实文字量构建信息流结构（封面吸引 → 密集信息交付 → 视觉缓冲 → ...）
- **附录**：完整 OCR 文字作为分析佐证

**方式 2：独立提取（不拆解）**

```bash
python scripts/extract_post_images_ocr.py --url "<链接>" -o ./ocr_output
```

产出物：
| 文件 | 内容 |
|------|------|
| `ocr_combined_text.txt` | 所有图片 OCR 文字的合并文本 |
| `ocr_results.json` | 逐图 OCR 结果（含置信度、文字量等） |

### 价值：把 ⚠️ 变成 ✅

当前五维拆解中大量结论挂着「⚠️ 文本推断」标注。对于**正文空洞的图文笔记**（只有标签、无实际文案），OCR 能从图片中提取真实内容，让分析从「盲猜」变成「实证」：

| 原状态 | OCR 增强后 |
|--------|-----------|
| ⚠️ 正文仅 #标签，无法分析内容骨架 | ✅ 从图片提取文字 → 真实的 ASL/结构分析 |
| ⚠️ 信息流纯文本推断 | ✅ 逐图文字量 → 真实的信息流结构 |
| ⚠️ 爆款要素只能猜 | ✅ 图片中的标题模式/步骤结构可被识别 |

### 局限

- OCR 有错字率（简体中文平均 70-85% 准确率），高质量图片可达到 90%+
- 手写体、艺术字、小字体识别效果差
- 纯图片（无文字）的 OCR 无意义
- 小红书 HTML 结构可能变化，URL 提取正则需维护

---

## 可视化面板

所有模式（单博主/批量）均自动生成 `数据可视化面板.html`。

**4 个分区**（对齐 4 份拆解报告）：

| 分区 | 对应报告 | 内容 |
|------|---------|------|
| 账号总览 | 博主深度拆解 | KPI 卡片、基础数据表、赛道饼图、横向对比表（批量）、雷达图（批量） |
| 内容策略 | 内容公式总结 | 钩子策略、标题模式、CTA 引导、内容形式分布 |
| 爆款引擎 | 结构化分析 | 藏赞比+爆款率、互动构成、发布时间热力图 |
| 评论洞察 | 情感分析 | 情感分布、正/负向评论样例 |

粘性导航点击平滑滚动，滚动时自动高亮当前分区。

---

## MCP 调用协议

```python
from scripts.utils.mcp_client import MCPClient
client = MCPClient(port=18060)
data = client.call("search_feeds", {"keyword": "<博主名>"})
```

### 可用工具

| 工具 | 作用 | 注意 |
|------|------|------|
| `check_login_status` | 检查登录 | — |
| `get_login_qrcode` | 获取二维码 | — |
| `search_feeds` | 搜索笔记 | 用于定位博主 |
| `user_profile` | 获取主页 | 需 `xsec_token` |
| `get_feed_detail` | 获取笔记详情 | 参数名是 `feed_id`，不是 `note_id` |

### 已知问题

- 每次调用链需重新 init → notify → call（session 不持久）
- 请求间隔 5 秒（笔记详情），30 秒（博主间）
- `timed out` = 风控触发，停止等待冷却

---

## 文件结构

```text
地瓜爆款拆解系统Skill/
├── SKILL.md                  # 本文件
├── run.py                    # 单博主入口
├── batch_run.py              # 批量入口
├── install.py                # 安装脚本
├── scripts/
│   ├── check_env.py          # Phase 0: 环境准备
│   ├── crawl_blogger.py      # Phase 1: 数据采集
│   ├── analyze.py            # Phase 2: 数据分析
│   ├── generate_docs.py      # Phase 3: 文档骨架
│   ├── deep_analyze.py       # Phase 3.5: AI 深度分析 + 情感分析 + 热力图 + 赛道分类
│   ├── generate_dashboard.py # Phase 3.6: 可视化面板
│   ├── analyze_viral_post.py       # Phase 4: 单条爆款拆解（支持 --ocr）
│   ├── extract_post_images_ocr.py  # ★ 新增：无需登录的图片OCR提取
│   ├── cross_analyze.py            # Phase 5: 跨博主对比
│   └── utils/
│       ├── common.py         # parse_count / safe_filename / ms_to_datetime
│       ├── mcp_client.py     # MCP HTTP 封装
│       └── md_to_docx.py     # MD → Word
└── references/
    └── 产出物质量标杆.md      # AI 分析质量标准
```

---

## 参考

- `references/产出物质量标杆.md` — ★ AI 分析时必读：4 份文档的结构模板 + 8 条写作准则 + 脚本 vs AI 分工
- `references/CHANGELOG.md` — 版本迭代日志（v0.1 → v0.5）
- `README.md` — 项目说明和快速开始
