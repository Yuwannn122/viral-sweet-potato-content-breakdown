"""
Viral Sweet Potato Content Breakdown — 多博主批量编排器
串联 Phase 0（环境准备，一次）→ [Phase 1→2→3→3.5]（每位博主循环）→ Phase 5（跨博主对比）

特性：
  - 断点恢复：每位博主完成后写 checkpoint，崩溃后可续跑
  - 防风控：博主间 15s 间隔 + 博内保持现有 3s 延迟
  - 失败策略：单博主失败不中断批量，全部完成后统一重试 1 次
  - 输出结构：每位博主独立子目录 output/<博主>/

用法：
    python batch_run.py --bloggers "博主A,博主B,博主C"
    python batch_run.py --bloggers "博主A,博主B" --self "我自己"
    python batch_run.py --file bloggers.txt --keywords "AI,工具"
    python batch_run.py --bloggers "博主A,博主B" --skip-env
"""

import sys
import os
import json
import time
import argparse
import traceback
from datetime import datetime

# 脚本根目录
SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(SKILL_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

from utils.common import safe_filename


# ============================================================
#  Checkpoint 管理
# ============================================================

def generate_batch_id():
    """生成批次 ID。"""
    return "batch_" + datetime.now().strftime("%Y%m%d_%H%M%S")


def load_checkpoint(path):
    """
    加载断点文件。

    Returns:
        dict | None — checkpoint 数据，文件不存在或损坏返回 None
    """
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 基本校验
        required = ["batch_id", "bloggers", "completed", "failed"]
        if all(k in data for k in required):
            return data
    except (json.JSONDecodeError, IOError):
        pass
    return None


def save_checkpoint(path, data):
    """
    原子写入 checkpoint（写临时文件 → 重命名）。

    Args:
        path: checkpoint 文件路径
        data: checkpoint dict
    """
    data["updated_at"] = datetime.now().isoformat()
    tmp_path = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception as e:
        print(f"  ⚠️ checkpoint 写入失败: {e}")


def init_checkpoint(bloggers, self_blogger, keywords, data_dir, output_dir, port):
    """创建初始 checkpoint。"""
    return {
        "batch_id": generate_batch_id(),
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "bloggers": bloggers,
        "completed": [],
        "current": None,
        "failed": [],
        "failed_permanently": [],
        "self_blogger": self_blogger,
        "self_completed": False,
        "keywords": keywords,
        "data_dir": data_dir,
        "output_dir": output_dir,
        "port": port,
        "retry_round": 0,
    }


# ============================================================
#  博主列表解析
# ============================================================

def parse_blogger_list(arg_value, file_path):
    """
    解析博主列表。

    Args:
        arg_value: --bloggers 的 CSV 字符串
        file_path: --file 的文件路径

    Returns:
        list[str] — 去重保序的博主名列表
    """
    if arg_value and file_path:
        print("❌ --bloggers 和 --file 不能同时使用")
        sys.exit(1)
    if not arg_value and not file_path:
        print("❌ 请指定 --bloggers 或 --file")
        sys.exit(1)

    names = []
    if arg_value:
        names = [n.strip() for n in arg_value.split(",") if n.strip()]
    elif file_path:
        if not os.path.isfile(file_path):
            print(f"❌ 文件不存在: {file_path}")
            sys.exit(1)
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name and not name.startswith("#"):
                    names.append(name)

    # 去重保序
    seen = set()
    unique = []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    if not unique:
        print("❌ 博主列表为空")
        sys.exit(1)

    return unique


# ============================================================
#  Phase 0: 环境准备
# ============================================================

def run_phase_0(skip, port):
    """
    运行环境检查（只跑一次）。

    Args:
        skip: 是否跳过
        port: MCP 端口

    Returns:
        bool — 环境是否就绪
    """
    if skip:
        print("\n⏭️  跳过 Phase 0（--skip-env）")
        return True

    print()
    print("=" * 60)
    print("▶ Phase 0: 环境自动准备（仅执行一次）")
    print("=" * 60)

    try:
        from check_env import run_checks
        all_ok, results = run_checks(port=port, auto_fix=True)
        for r in results:
            status = "✅" if r["ok"] else "❌"
            print(f"  {status} {r['name']}: {r['detail']}")
        if not all_ok:
            print("\n❌ 环境检查未通过，请修复后重试。")
        return all_ok
    except ImportError as e:
        print(f"❌ 无法导入 check_env 模块: {e}")
        return False


# ============================================================
#  单博主处理
# ============================================================

def process_one_blogger(name, data_dir, output_dir, port, extra_keywords=None, is_self=False, max_notes=None):
    """
    对一位博主执行 Phase 1→2→3→3.5 全流程。

    使用函数导入（非 subprocess），每阶段独立 try/except，
    确保单阶段失败不影响后续博主。

    Args:
        name: 博主名
        data_dir: 数据目录（共享）
        output_dir: 输出目录（每位博主独立子目录）
        port: MCP 端口
        extra_keywords: 领域关键词列表
        is_self: 是否标记为自己账号

    Returns:
        dict — {
            "status": "ok" | "crawl_failed" | "analyze_failed" | ...,
            "nickname": str,
            "safe_name": str,
            "notes_count": int,
            "error": str (仅失败时),
        }
    """
    tag = "👤 自己" if is_self else "🎯 目标"
    print(f"\n{'='*60}")
    print(f"  {tag}: {name}")
    print(f"{'='*60}")

    result = {
        "status": "ok",
        "nickname": name,
        "safe_name": safe_filename(name),
        "notes_count": 0,
        "error": None,
    }

    # ----------------------------------------------------------
    # Phase 1: 数据采集
    # ----------------------------------------------------------
    print(f"\n📥 Phase 1: 数据采集...")
    try:
        from crawl_blogger import crawl_blogger

        crawl_result = crawl_blogger(
            keyword=name,
            output_dir=data_dir,
            port=port,
            is_self=is_self,
            extra_keywords=extra_keywords,
            max_notes=max_notes,
        )
        nickname = crawl_result.get("nickname", name)
        result["nickname"] = nickname
        result["safe_name"] = safe_filename(nickname)

        details = crawl_result.get("details", [])
        ok_count = len([d for d in details if "_error" not in d])
        err_count = len([d for d in details if "_error" in d])
        total = len(details)
        result["notes_count"] = ok_count

        # 错误率 > 80% 判定为爬取失败
        if total > 0 and err_count / total > 0.8:
            result["status"] = "crawl_failed"
            result["error"] = f"错误率过高（{err_count}/{total}）"
            print(f"  ❌ Phase 1 失败: {result['error']}")
            return result

        print(f"  ✅ Phase 1 完成: {ok_count}条有效" + (f"，{err_count}条失败" if err_count else ""))

    except Exception as e:
        result["status"] = "crawl_failed"
        result["error"] = str(e)[:200]
        print(f"  ❌ Phase 1 失败: {result['error']}")
        traceback.print_exc()
        return result

    # ----------------------------------------------------------
    # Phase 2: 数据分析
    # ----------------------------------------------------------
    print(f"\n📊 Phase 2: 数据分析...")
    safe = result["safe_name"]
    details_path = os.path.join(data_dir, f"{safe}_notes_details.json")
    analysis_path = os.path.join(data_dir, f"{safe}_analysis.json")

    if not os.path.isfile(details_path):
        result["status"] = "analyze_failed"
        result["error"] = f"笔记详情文件不存在: {details_path}"
        print(f"  ❌ Phase 2 失败: {result['error']}")
        return result

    try:
        from analyze import analyze_notes

        analysis = analyze_notes(details_path)
        if not analysis or not analysis.get("notes"):
            result["status"] = "analyze_failed"
            result["error"] = "分析结果为空"
            print(f"  ❌ Phase 2 失败: {result['error']}")
            return result

        # 保存分析结果（模拟 analyze.py CLI 的保存逻辑）
        save_notes = []
        for n in analysis["notes"]:
            save_notes.append({
                "id": n["id"],
                "title": n["title"],
                "type": n["type"],
                "likes": n["likes"],
                "likes_raw": n["likes_raw"],
                "collects": n["collects"],
                "collects_raw": n["collects_raw"],
                "comments_count": n["comments_count"],
                "comments_raw": n["comments_raw"],
                "shares": n["shares"],
                "tags": n["tags"],
                "category": n["category"],
                "time": n["time"],
            })
        save_data = {k: v for k, v in analysis.items() if k != "notes"}
        save_data["notes"] = save_notes
        save_data["notes_count"] = len(save_notes)
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        s = analysis.get("stats", {})
        print(f"  ✅ Phase 2 完成: {s.get('total', 0)}条, 均赞{s.get('avg_likes', 0):,}")

    except Exception as e:
        result["status"] = "analyze_failed"
        result["error"] = str(e)[:200]
        print(f"  ❌ Phase 2 失败: {result['error']}")
        traceback.print_exc()
        return result

    # ----------------------------------------------------------
    # Phase 3+3.5: 文档生成 + 深度分析
    # ----------------------------------------------------------
    # 每位博主的输出子目录
    blogger_output_dir = os.path.join(output_dir, safe)
    os.makedirs(blogger_output_dir, exist_ok=True)

    if not os.path.isfile(analysis_path):
        result["status"] = "docs_failed"
        result["error"] = f"分析文件不存在: {analysis_path}"
        print(f"  ❌ Phase 3 失败: {result['error']}")
        return result

    try:
        from generate_docs import generate_docs
        print(f"\n📝 Phase 3: 文档生成...")
        generate_docs(analysis_path, result["nickname"], blogger_output_dir, details_path)
        print(f"  ✅ Phase 3 完成")
    except Exception as e:
        result["status"] = "docs_failed"
        result["error"] = str(e)[:200]
        print(f"  ❌ Phase 3 失败: {result['error']}")
        traceback.print_exc()
        return result

    try:
        from deep_analyze import deep_analyze
        print(f"\n🔬 Phase 3.5: AI 深度分析（数据底稿）...")
        deep_analyze(analysis_path, result["nickname"], blogger_output_dir, details_path)
        print(f"  ✅ Phase 3.5 完成")
    except Exception as e:
        result["status"] = "deep_failed"
        result["error"] = str(e)[:200]
        print(f"  ❌ Phase 3.5 失败: {result['error']}")
        traceback.print_exc()
        # deep_failed 不算 fatal — 分析数据已保存
        result["status"] = "ok"
        print(f"  ⚠️ 分析数据已保存，深度分析可后续手动执行")
        return result

    return result


# ============================================================
#  批量主循环
# ============================================================

def precheck_bloggers(bloggers, port):
    """
    批量爬取前预检：搜索每位博主，对比搜索结果与输入名是否一致。
    复用 crawl_blogger.find_blogger() 的精确/模糊/兜底三级匹配逻辑。

    Returns:
        list[dict] — 匹配有差异的博主列表（空列表 = 全部精确匹配）
    """
    from scripts.utils.mcp_client import MCPClient
    from scripts.crawl_blogger import find_blogger

    client = MCPClient(port=port)

    print(f"\n{'='*60}")
    print(f"🔍 预检：搜索博主名确认匹配...")
    print(f"{'='*60}")

    mismatches = []
    for name in bloggers:
        try:
            uid, found_name, xsec = find_blogger(client, name)
        except Exception as e:
            print(f"  ❌ {name}: 搜索失败 ({e})")
            mismatches.append({"input": name, "found": "搜索失败", "exact": False})
            continue

        exact = (found_name == name)
        if exact:
            print(f"  ✅ {name} → 精确匹配: {found_name}")
        else:
            print(f"  ⚠️ {name} → 匹配到: {found_name} [名字不完全一致]")
            mismatches.append({"input": name, "found": found_name, "exact": False})

    return mismatches


def run_batch(bloggers, args):
    """
    执行完整的批量处理流程。

    Args:
        bloggers: 博主名列表
        args: 命令行参数

    Returns:
        dict — 批量结果摘要
    """
    data_dir = args.data_dir or "./data"
    output_dir = args.output_dir or "./output"
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # 解析领域关键词
    extra_keywords = None
    if args.keywords:
        extra_keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    # Checkpoint 路径
    checkpoint_path = os.path.join(output_dir, "_batch_checkpoint.json")

    # 尝试加载已有 checkpoint
    checkpoint = load_checkpoint(checkpoint_path)

    if checkpoint:
        # 检查 blogger 列表是否一致
        saved_bloggers = set(checkpoint.get("bloggers", []))
        current_bloggers = set(bloggers)
        if saved_bloggers == current_bloggers:
            print(f"\n📋 发现断点记录: {checkpoint['batch_id']}")
            print(f"   已完成: {len(checkpoint['completed'])}/{len(bloggers)}")
            if checkpoint.get("failed"):
                print(f"   失败: {len(checkpoint['failed'])}")
            print(f"   将从断点继续...")
        else:
            print(f"\n⚠️ 博主列表与断点记录不一致，创建新批次")
            checkpoint = None

    if not checkpoint:
        checkpoint = init_checkpoint(
            bloggers=bloggers,
            self_blogger=args.self_blogger,
            keywords=args.keywords,
            data_dir=data_dir,
            output_dir=output_dir,
            port=args.port,
        )

    # 确定需要处理的博主
    completed = set(checkpoint.get("completed", []))
    failed_permanently = set(checkpoint.get("failed_permanently", []))
    remaining = [b for b in bloggers if b not in completed and b not in failed_permanently]

    if not remaining and not checkpoint.get("failed"):
        print(f"\n✅ 所有博主已完成！")
        return checkpoint
    elif not remaining:
        print(f"\n📋 所有博主已处理（含失败），跳过主循环")
        return checkpoint

    # ------ 预检：搜索博主名，确认匹配结果 ------
    if remaining and not args.skip_precheck:
        mismatches = precheck_bloggers(remaining, args.port)
        if mismatches:
            print(f"\n{'='*60}")
            print(f"⚠️  以上 {len(mismatches)} 位博主搜索结果与输入名不完全一致！")
            for m in mismatches:
                print(f"   输入「{m['input']}」→ 找到「{m['found']}」")
            print(f"   如需修正：Ctrl+C 退出 → 修改名字 → 重新运行 batch_run.py")
            print(f"   如确认无误：不做任何操作，3 秒后自动继续...")
            print(f"{'='*60}")
            time.sleep(3)
        else:
            print(f"\n✅ 全部博主名与搜索结果一致，无需修正\n")
        # 预检后缓冲，避免后续搜索被 MCP 限流
        time.sleep(5)

    total = len(bloggers)
    for i, blogger in enumerate(remaining):
        checkpoint["current"] = blogger
        save_checkpoint(checkpoint_path, checkpoint)

        progress = f"[{len(completed) + i + 1}/{total}]"
        print(f"\n{'─'*60}")
        print(f"  {progress} 正在处理: {blogger}")
        print(f"{'─'*60}")

        result = process_one_blogger(
            name=blogger,
            data_dir=data_dir,
            output_dir=output_dir,
            port=args.port,
            extra_keywords=extra_keywords,
            is_self=False,
            max_notes=args.max_notes,
        )

        if result["status"] == "ok":
            checkpoint["completed"].append(blogger)
            print(f"\n  ✅ {progress} {blogger} 完成！")
        else:
            checkpoint["failed"].append(blogger)
            print(f"\n  ❌ {progress} {blogger} 失败: {result['error']}")

        checkpoint["current"] = None
        save_checkpoint(checkpoint_path, checkpoint)

        # 博主间延迟（防风控）
        is_last = (i == len(remaining) - 1) and not args.self_blogger
        if not is_last:
            delay = 30
            print(f"\n  ⏳ 防风控：等待 {delay} 秒后处理下一位博主...")
            time.sleep(delay)

    # ----------------------------------------------------------
    # 处理自己的账号
    # ----------------------------------------------------------
    if args.self_blogger and not checkpoint.get("self_completed"):
        self_name = args.self_blogger
        print(f"\n{'─'*60}")
        print(f"  👤 处理自己账号: {self_name}")
        print(f"{'─'*60}")

        self_result = process_one_blogger(
            name=self_name,
            data_dir=data_dir,
            output_dir=output_dir,
            port=args.port,
            extra_keywords=extra_keywords,
            is_self=True,
        )

        if self_result["status"] == "ok":
            checkpoint["self_completed"] = True
            print(f"\n  ✅ 自己账号处理完成！")
        else:
            print(f"\n  ❌ 自己账号处理失败: {self_result['error']}")

        save_checkpoint(checkpoint_path, checkpoint)

    # ----------------------------------------------------------
    # 重试失败博主
    # ----------------------------------------------------------
    failed = checkpoint.get("failed", [])
    if failed and checkpoint.get("retry_round", 0) == 0:
        print(f"\n{'='*60}")
        print(f"🔄 重试失败博主 ({len(failed)}位)...")
        print(f"{'='*60}")
        time.sleep(30)  # 重试前额外等待

        checkpoint["retry_round"] = 1
        still_failed = []

        for blogger in failed:
            print(f"\n  🔄 重试: {blogger}")
            time.sleep(5)

            result = process_one_blogger(
                name=blogger,
                data_dir=data_dir,
                output_dir=output_dir,
                port=args.port,
                extra_keywords=extra_keywords,
                is_self=False,
            )

            if result["status"] == "ok":
                checkpoint["completed"].append(blogger)
                print(f"  ✅ 重试成功: {blogger}")
            else:
                still_failed.append(blogger)
                print(f"  ❌ 重试仍失败: {blogger}")

            save_checkpoint(checkpoint_path, checkpoint)
            if len(failed) > 1:
                time.sleep(15)

        checkpoint["failed"] = still_failed
        checkpoint["failed_permanently"] = still_failed
        save_checkpoint(checkpoint_path, checkpoint)

    # ----------------------------------------------------------
    # 批量完成摘要
    # ----------------------------------------------------------
    final_completed = len(checkpoint.get("completed", []))
    final_failed = len(checkpoint.get("failed_permanently", checkpoint.get("failed", [])))

    print(f"\n{'='*60}")
    print(f"📊 批量处理摘要")
    print(f"{'='*60}")
    print(f"   成功: {final_completed}/{total}")
    if final_failed:
        print(f"   失败: {final_failed}/{total} — {', '.join(checkpoint.get('failed_permanently', checkpoint.get('failed', [])))}")
    print(f"{'='*60}")

    # ----------------------------------------------------------
    # Phase 5: 跨博主对比分析
    # ----------------------------------------------------------
    if final_completed >= 2:
        print(f"\n{'='*60}")
        print(f"📊 Phase 5: 赛道竞争格局分析")
        print(f"{'='*60}")

        try:
            from cross_analyze import cross_analyze
            cross_analyze(
                data_dir=data_dir,
                output_dir=output_dir,
                blogger_names=None,  # 自动发现
                self_name=args.self_blogger if checkpoint.get("self_completed") else None,
            )
            # 生成数据可视化面板
            from generate_dashboard import generate_dashboard
            generate_dashboard(data_dir, output_dir)
        except Exception as e:
            print(f"  ❌ 横向对比分析失败: {e}")
            traceback.print_exc()
    else:
        print(f"\n⚠️ 成功处理的博主不足 2 位，跳过横向对比分析")

    return checkpoint


# ============================================================
#  CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="Viral Sweet Potato Content Breakdown — 多博主批量编排器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 基本批量
  python batch_run.py --bloggers "博主A,博主B,博主C"

  # 含自己账号对比
  python batch_run.py --bloggers "博主A,博主B" --self "我自己"

  # 从文件读取博主列表
  python batch_run.py --file bloggers.txt --keywords "AI,工具"

  # 跳过环境检查（已确认 OK 时）
  python batch_run.py --bloggers "博主A,博主B" --skip-env
        """,
    )
    parser.add_argument(
        "--bloggers",
        help="博主名列表（逗号分隔），与 --file 二选一",
    )
    parser.add_argument(
        "--file",
        help="博主列表文件路径（每行一个博主名），与 --bloggers 二选一",
    )
    parser.add_argument(
        "--self",
        dest="self_blogger",
        help="自己的博主名（用于差异化对比分析）",
    )
    parser.add_argument(
        "--keywords",
        help="领域关键词（逗号分隔），用于扩展搜索。如：AI,工具,教程",
    )
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="跳过 Phase 0 环境检查",
    )
    parser.add_argument(
        "--skip-precheck",
        action="store_true",
        help="跳过博主名预检确认",
    )
    parser.add_argument(
        "--data-dir",
        default="./data",
        help="数据存放目录（默认 ./data）",
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="文档输出目录（默认 ./output）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=18060,
        help="MCP 服务端口（默认 18060）",
    )
    parser.add_argument(
        "--max-notes",
        type=int,
        default=None,
        help="每位博主最多爬取笔记数（默认全量），用于快速测试",
    )
    args = parser.parse_args()

    # 解析博主列表
    bloggers = parse_blogger_list(args.bloggers, args.file)

    print()
    print("🚀 Viral Sweet Potato Content Breakdown — 多博主批量模式")
    print(f"   博主列表: {', '.join(bloggers)}")
    print(f"   博主数量: {len(bloggers)}")
    if args.self_blogger:
        print(f"   对比账号: {args.self_blogger}")
    if args.keywords:
        print(f"   领域关键词: {args.keywords}")
    print(f"   数据目录: {args.data_dir}")
    print(f"   输出目录: {args.output_dir}")
    print(f"   MCP 端口: {args.port}")
    print()

    # Phase 0: 环境准备（一次）
    if not run_phase_0(args.skip_env, args.port):
        sys.exit(1)

    # 执行批量
    checkpoint = run_batch(bloggers, args)

    # 最终结果
    print(f"\n{'='*60}")
    print(f"🎉 批量处理完成！")
    print(f"   批次 ID: {checkpoint['batch_id']}")
    print(f"   成功: {len(checkpoint['completed'])}/{len(checkpoint['bloggers'])}")
    if checkpoint.get("completed"):
        print(f"   已完成: {', '.join(checkpoint['completed'])}")
    if checkpoint.get("failed_permanently") or checkpoint.get("failed"):
        final_failed = checkpoint.get("failed_permanently") or checkpoint.get("failed")
        print(f"   失败: {', '.join(final_failed)}")
    print(f"   输出目录: {os.path.abspath(args.output_dir)}")
    print(f"{'='*60}")

    # 列出产出物
    print(f"\n生成的文档：")
    output_dir = args.output_dir
    if os.path.isdir(output_dir):
        for root, dirs, files in os.walk(output_dir):
            for f in sorted(files):
                if f.endswith(".docx"):
                    rel = os.path.relpath(os.path.join(root, f), output_dir)
                    size_kb = os.path.getsize(os.path.join(root, f)) / 1024
                    print(f"  📄 {rel} ({size_kb:.0f}KB)")
    print()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    main()
