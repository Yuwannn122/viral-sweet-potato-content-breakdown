# 迭代日志

## v0.7 (2026-08-12) — 可视化面板 v7 重构

### 架构重构
- Python 层不再拼接 HTML/JS 字符串，改为 `build_dashboard_payload()` 生成标准化 JSON
- 新增独立 HTML 模板 `dashboard_template_v7.html`，JS 动态渲染所有图表
- Python → JSON → HTML Template → Chart.js 四层分离

### 新增
- 🔀 **账号切换器**：顶部下拉选择「全部博主」或单博主，纯前端切换
- 🏆 **爆款 TOP10 表格**：排名/标题/赞藏评/互动/爆款等级（超级/大/小）/发布时间
- 🔍 **爆款特征总结**：规则化提炼最常见标题模式/钩子/赛道/形式/时间
- 🧠 **AI 策略总结**（第 6 区）：规则化输出——为什么出爆款 / 内容优势 / 当前短板 / 模仿建议
- 🎯 **7 维雷达图**：赛道覆盖/标题/钩子/爆款/收藏/评论/情绪，归一化横向对比
- 📌 **跨赛道对比提示**：不同赛道博主自动标注差异说明
- 🌙 **暗色模式**：`prefers-color-scheme: dark` 自动切换
- 🔒 **HTML escape**：所有用户数据（标题/评论/博主名）统一转义
- 📦 **离线可用**：`chart.umd.min.js` 内嵌 + CDN fallback

### 修复
- 🐛 **NaN 显示**：Python `_fmt()` 千分位逗号导致 JS `Number("12,888")` = NaN，改为 Python 只传原始数字，JS 统一格式化
- 🐛 **图表空白**：`newChart()` 误调 `destroyCharts()` 销毁已创建的图表，改为仅清理同 ID 旧实例
- 🐛 **多博主支持**：彻底消除 `all_data[0]`，所有图表均支持 N 位博主并排展示
- 🐛 **滚动导航**：IntersectionObserver 自动高亮当前分区

### 容错增强
- `safeN()` 全局 NaN/Infinity 守卫 → 0
- `fmt()` / `esc()` NaN/Infinity → `—`
- `normDim()` 除零保护（雷达图）
- `newChart()` 注入前自动洗掉数据集中的 NaN/Infinity
- 任意字段缺失 → 「暂无数据」「样本不足」，不白屏

### 视觉升级
- 字体：Inter + Noto Sans SC + JetBrains Mono
- 配色：暖灰/米白/橙棕/低饱和绿，克制专业风
- 响应式：767px / 1199px 两断点，移动端 KPI 2 列、导航横向滚动

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
