# 迭代日志

## v0.5 (2026-06-26) — 批量拆解 + 赛道分类 + 可视化面板

### 新增
- 多博主批量拆解系统（`batch_run.py` + `cross_analyze.py`）
- 赛道竞争格局横向对比报告
- 29 赛道分类器（`classify_content_track`，`deep_analyze.py`）
- 数据可视化面板（`generate_dashboard.py`，Chart.js HTML 看板）
- 博主名预检确认机制（批量防错）
- 图文笔记图片序列分析（基于 MCP `imageList` 元数据）
- `--max-notes` 快速测试参数

### 优化
- 评论情感词库扩展（新增短正向表达）
- 笔记间隔 3s→5s，博主间隔 15s→30s（防风控）
- 4 份产出物结构对齐原版质量标杆（博主深度拆解 6→11章、结构化分析 4→8章、内容公式 5→9章、选题素材库 5→6章）
- `find_blogger` 搜索失败自动重试
- SKILL.md 重构（三大功能清晰、安全须知、准确参数）

---

## v0.4 (2026-03) — 五维+三镜 + 情感分析

### 新增
- 五维+三镜单条爆款拆解系统（`analyze_viral_post.py`）
- 评论区情感分析（关键词匹配法，~150词）
- 发布时间热力图（7时段×7天矩阵）
- 评论反向推断视频内容（`infer_content_from_comments`）
- ASL 句式分析 + 标签体检测
- 藏赞比语义判断 + CTA 自洽性检查
- BGM 诚实推断（有证据才推断）

### 优化
- MCP feed_id 模式改用 `call_raw` 手动解析
- 视觉心锚正则收紧（视觉词 AND 识别词）
- 产出格式统一（MD 双份存档）

---

## v0.3 — 环境自动准备

### 新增
- `check_env.py` — 自动检测 Python/dependency/MCP/登录
- 扫码登录分级降级策略
- MCP 二进制自动下载

---

## v0.2 — 基础分析流水线

### 新增
- `crawl_blogger.py` — 博主数据采集
- `analyze.py` — 数据分析（动态聚类）
- `generate_docs.py` — 4 份骨架文档生成
- `md_to_docx.py` — Markdown → Word 转换

---

## v0.1 — 初始版本

基于 [xhs-blogger-analyzer](https://github.com/arraycto/xhs-blogger-analyzer)（MIT License）fork。
