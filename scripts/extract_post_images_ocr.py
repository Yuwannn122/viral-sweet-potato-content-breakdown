"""
Extract & OCR images from Xiaohongshu post — No login required.

Technical principle:
  小红书虽然是 SPA，但页面 HTML 中内嵌了包含图片 CDN 地址的 JSON 数据（用于 SEO 和首屏渲染）。
  图片 CDN（sns-webpic-qc.xhscdn.com 等）没有鉴权限制，只需设置 Referer 即可直接下载。
  下载后用 pytesseract 做 OCR 识别，提取图片中的文字内容。

Workflow:
  帖子URL → HTTPS请求HTML → 提取CDN图片URL → 下载图片 → pytesseract OCR → 结构化输出

Usage:
  # 从URL提取
  python extract_post_images_ocr.py --url "<小红书帖子链接>" -o ./ocr_output

  # 直接给HTML文本（调试）
  python extract_post_images_ocr.py --html "<html文件>" -o ./ocr_output

  # 只提取URL不下载不OCR（干跑）
  python extract_post_images_ocr.py --url "<链接>" --dry-run

  # 指定OCR语言（默认 chi_sim）
  python extract_post_images_ocr.py --url "<链接>" --lang chi_sim+eng

Dependencies:
  pip install requests Pillow pytesseract
  系统依赖: Tesseract OCR + 中文语言包
    macOS:   brew install tesseract tesseract-lang
    Ubuntu:  apt install tesseract-ocr tesseract-ocr-chi-sim
    Windows: 下载安装 https://github.com/UB-Mannheim/tesseract/wiki
"""

import json
import os
import re
import sys
import time
import hashlib
import argparse
import tempfile
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# ============================================================
#  CDN 图片 URL 匹配规则
# ============================================================

# 小红书图片 CDN 域名（按优先级）
XHS_IMAGE_CDN_DOMAINS = [
    "sns-webpic-qc.xhscdn.com",
    "ci.xiaohongshu.com",
    "sns-img-hw.xhscdn.com",
    "sns-img-qc.xhscdn.com",
    "sns-avatar-qc.xhscdn.com",  # 头像，低优先级
]

# 从HTML中提取图片URL的正则（匹配 CDN 域名 + 路径直到遇到引号/空格/换行）
_CDN_PATTERNS = [
    re.compile(rf'https?://{re.escape(domain)}/[^\'"\\s\]]+' )
    for domain in XHS_IMAGE_CDN_DOMAINS
]

# 需要跳过的非内容图片模式
_SKIP_PATTERNS = [
    r'avatar',           # 头像
    r'/icon/',           # 图标
    r'/emoji/',          # 表情
    r'/logo/',           # Logo
    r'favicon',
    r'/bg/',             # 背景
    r'watermark',        # 水印（可能有用的也保留）
]


def _is_content_image(url: str) -> bool:
    """判断是否为内容图片（非头像/图标等）"""
    url_lower = url.lower()
    for pat in _SKIP_PATTERNS:
        if re.search(pat, url_lower):
            return False
    return True


# ============================================================
#  HTML 获取
# ============================================================

def fetch_page_html(url: str, timeout: int = 30) -> str:
    """
    获取小红书帖子页面的 HTML。
    需要设置 UA 和 Referer 模拟正常浏览器访问。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
    }

    # 使用标准库 urllib（无外部依赖）或 requests
    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        return resp.text
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')


# ============================================================
#  图片 URL 提取
# ============================================================

def extract_image_urls_from_html(html: str) -> list[str]:
    """
    从 HTML 中提取图片 CDN URL。

    策略（按优先级）：
      1. 从 <script> 中的 JSON 数据提取 imageList
      2. 正则匹配所有 CDN 图片 URL（兜底）

    Returns:
        去重后的内容图片 URL 列表（保持原始顺序）
    """
    urls = []
    seen = set()

    # ---- Strategy 1: 从 JSON 数据中提取 imageList ----
    # 小红书在 HTML 中嵌入的 JSON 数据可能有多种格式：
    #   - window.__INITIAL_STATE__ = {...}
    #   - <script id="__NEXT_DATA__" type="application/json">...</script>
    #   - 其他内联 script 标签中的 JSON

    json_blobs = _extract_json_blobs(html)

    for blob in json_blobs:
        try:
            data = json.loads(blob)
        except (json.JSONDecodeError, ValueError):
            continue

        # 递归查找所有 imageList / url 字段
        for img_url in _walk_find_image_urls(data):
            if img_url not in seen and _is_content_image(img_url):
                urls.append(img_url)
                seen.add(img_url)

    # ---- Strategy 2: 正则全局匹配 CDN URL（兜底） ----
    for pattern in _CDN_PATTERNS:
        for match in pattern.finditer(html):
            url = match.group(0)
            # 清理 URL 末尾的无效字符
            url = _clean_url(url)
            if url not in seen and _is_content_image(url):
                urls.append(url)
                seen.add(url)

    # 按域名优先级排序（内容CDN在前，头像在后）
    def _domain_rank(url: str) -> int:
        for i, domain in enumerate(XHS_IMAGE_CDN_DOMAINS):
            if domain in url:
                return i
        return 99

    urls.sort(key=_domain_rank)

    return urls


def _extract_json_blobs(html: str) -> list[str]:
    """从 HTML 中提取所有可能的 JSON 数据块"""
    blobs = []

    # 模式1: window.__INITIAL_STATE__ = {...};
    for match in re.finditer(r'window\.__INITIAL_STATE__\s*=\s*', html):
        start = match.end()
        blob = _extract_balanced_json(html, start)
        if blob:
            blobs.append(blob)

    # 模式2: <script id="__NEXT_DATA__" type="application/json">...</script>
    for match in re.finditer(
        r'<script[^>]*?(?:id="__NEXT_DATA__"|type="application/json")[^>]*?>(.*?)</script>',
        html, re.DOTALL
    ):
        content = match.group(1).strip()
        if content:
            blobs.append(content)

    # 模式3: 任何包含 "imageList" 的 inline script
    for match in re.finditer(
        r'<script[^>]*?>\s*(.*?imageList.*?)\s*</script>',
        html, re.DOTALL | re.IGNORECASE
    ):
        content = match.group(1).strip()
        if content and len(content) > 50:
            # 尝试提取 JSON 部分
            json_start = content.find('{')
            if json_start >= 0:
                blob = _extract_balanced_json(content, json_start)
                if blob:
                    blobs.append(blob)

    return blobs


def _extract_balanced_json(text: str, start: int) -> Optional[str]:
    """从 text[start] 开始提取括号平衡的 JSON 字符串"""
    if start >= len(text) or text[start] != '{':
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape_next:
            escape_next = False
            continue

        if ch == '\\':
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def _walk_find_image_urls(obj, max_depth=10):
    """递归遍历 JSON 对象，提取所有图片 URL"""
    if max_depth <= 0:
        return

    if isinstance(obj, dict):
        # 检查是否是图片信息对象
        url = obj.get('url', '') or obj.get('traceId', '')
        # 更常见的字段名
        for key in ('url', 'traceId', 'original', 'fileUrl', 'coverUrl', 'imageUrl'):
            val = obj.get(key, '')
            if isinstance(val, str) and _is_cdn_url(val):
                yield val

        # 递归子对象
        for val in obj.values():
            yield from _walk_find_image_urls(val, max_depth - 1)

    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_find_image_urls(item, max_depth - 1)


def _is_cdn_url(url: str) -> bool:
    """判断是否为小红书 CDN 图片 URL"""
    return any(domain in url for domain in XHS_IMAGE_CDN_DOMAINS)


def _clean_url(url: str) -> str:
    """清理 URL 末尾的无效字符"""
    # 去掉尾部引号、括号、逗号等
    return re.sub(r'[)\'",;\]}]+$', '', url).strip()


# ============================================================
#  图片下载
# ============================================================

def download_image(url: str, output_dir: str, timeout: int = 30) -> Optional[str]:
    """
    下载单张图片。

    Args:
        url: 图片 CDN URL
        output_dir: 保存目录
        timeout: 超时秒数

    Returns:
        保存的文件路径，失败返回 None
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.xiaohongshu.com/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }

    try:
        import requests
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        content = resp.content
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()

    if not content or len(content) < 100:
        print(f"    ⚠️ 图片过小或为空: {url[:60]}...")
        return None

    # 根据 URL 生成唯一文件名
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    # 尝试从 URL 推断扩展名
    ext = ".jpg"
    for possible_ext in ['.png', '.webp', '.gif', '.jpeg', '.jpg']:
        if f'.{possible_ext.strip(".")}' in url.split('?')[0].lower():
            ext = possible_ext
            break

    filename = f"img_{url_hash}{ext}"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'wb') as f:
        f.write(content)

    return filepath


def download_images(urls: list[str], output_dir: str,
                    max_workers: int = 3,
                    timeout: int = 30) -> list[dict]:
    """
    并发下载多张图片。

    Returns:
        [{url, filepath, success, error}]
    """
    os.makedirs(output_dir, exist_ok=True)
    results = []

    def _download_one(idx_url):
        idx, url = idx_url
        filepath = download_image(url, output_dir, timeout)
        return {
            "index": idx,
            "url": url,
            "filepath": filepath,
            "success": filepath is not None,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_download_one, (i, url)): i
            for i, url in enumerate(urls)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                idx = futures[future]
                results.append({
                    "index": idx, "url": urls[idx] if idx < len(urls) else "",
                    "filepath": None, "success": False, "error": str(e),
                })

    # 按原始顺序排序
    results.sort(key=lambda r: r["index"])
    return results


# ============================================================
#  OCR 识别
# ============================================================

def _check_tesseract():
    """检查 Tesseract 是否可用"""
    import subprocess
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True, text=True, timeout=10
        )
        version_line = result.stdout.split('\n')[0] if result.stdout else "unknown"
        print(f"  🔍 Tesseract: {version_line}")
        return True
    except FileNotFoundError:
        print("  ❌ Tesseract 未安装或不在 PATH 中")
        print("     安装指南:")
        print("       macOS:   brew install tesseract tesseract-lang")
        print("       Ubuntu:  apt install tesseract-ocr tesseract-ocr-chi-sim")
        print("       Windows: 下载 https://github.com/UB-Mannheim/tesseract/wiki")
        return False
    except Exception as e:
        print(f"  ⚠️ Tesseract 检测异常: {e}")
        return True  # 继续尝试


def ocr_image(image_path: str, lang: str = "chi_sim") -> dict:
    """
    对单张图片执行 OCR。

    Args:
        image_path: 图片文件路径
        lang: Tesseract 语言（默认 chi_sim 简体中文）

    Returns:
        {text, confidence, image_path, word_count, line_count}
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        return {
            "text": "", "confidence": 0, "image_path": image_path,
            "error": f"缺少依赖: {e}. 请 pip install pytesseract Pillow",
        }

    try:
        img = Image.open(image_path)

        # 基本预处理：转为 RGB（处理 RGBA/P 等格式）
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')

        # OCR 识别
        text = pytesseract.image_to_string(img, lang=lang).strip()

        # 获取置信度数据
        try:
            data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
            confidences = [int(c) for c in data.get('conf', []) if c != '-1' and int(c) > 0]
            avg_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0
        except Exception:
            avg_confidence = 0

        lines = [l for l in text.split('\n') if l.strip()]
        words = text.split()

        return {
            "text": text,
            "confidence": avg_confidence,
            "image_path": image_path,
            "line_count": len(lines),
            "word_count": len(words),
        }

    except Exception as e:
        return {
            "text": "", "confidence": 0, "image_path": image_path,
            "error": str(e),
        }


def ocr_images(image_paths: list[str], lang: str = "chi_sim",
               max_workers: int = 2) -> list[dict]:
    """
    对多张图片并发执行 OCR。

    注意：Tesseract 本身是 CPU 密集型，并发过高可能反而变慢。
    推荐 max_workers=2。

    Returns:
        [{image_path, text, confidence, ...}] 按原始顺序
    """
    results = []

    def _ocr_one(idx_path):
        idx, path = idx_path
        result = ocr_image(path, lang)
        result["index"] = idx
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_ocr_one, (i, p)): i
            for i, p in enumerate(image_paths)
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                idx = futures[future]
                results.append({
                    "index": idx, "image_path": image_paths[idx] if idx < len(image_paths) else "",
                    "text": "", "confidence": 0, "error": str(e),
                })

    results.sort(key=lambda r: r.get("index", 0))
    return results


# ============================================================
#  元数据提取（从 HTML）
# ============================================================

def extract_note_meta_from_html(html: str) -> dict:
    """
    尝试从 HTML 中提取帖子元数据（标题、正文、互动数据等）。

    这是一个尽力而为的提取，不同帖子格式可能不同。
    如果提取失败，返回空 dict。
    """
    meta = {
        "title": "",
        "desc": "",
        "nickname": "",
        "likes": 0,
        "collects": 0,
        "comments_count": 0,
        "note_type": "normal",
        "publish_time": "",
    }

    # 尝试从页面标题提取
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()
        # 小红书标题格式: "xxx - 小红书"
        title = re.sub(r'\s*[-–—|]\s*小红书.*$', '', title)
        title = re.sub(r'\s*[-–—|]\s*小红书$', '', title)
        if title and title != "小红书":
            meta["title"] = title[:200]

    # 尝试从 meta 标签提取
    for meta_tag in re.finditer(r'<meta[^>]+>', html):
        tag = meta_tag.group(0)
        name = re.search(r'(?:name|property)=["\']([^"\']+)["\']', tag)
        content = re.search(r'content=["\']([^"\']+)["\']', tag)
        if name and content:
            meta[name.group(1)] = content.group(1)

    # 尝试从 JSON blob 中提取更多信息
    json_blobs = _extract_json_blobs(html)
    for blob in json_blobs:
        try:
            data = json.loads(blob)
            _extract_meta_from_json(data, meta)
        except (json.JSONDecodeError, ValueError):
            continue

    return meta


def _extract_meta_from_json(obj, meta: dict, depth: int = 0):
    """递归从 JSON 对象中提取帖子元数据"""
    if depth > 8:
        return

    if isinstance(obj, dict):
        # 标题
        for key in ('title', 'displayTitle', 'noteTitle', 'shareTitle'):
            if key in obj and isinstance(obj[key], str) and obj[key]:
                if not meta["title"] or len(obj[key]) > len(meta["title"]):
                    meta["title"] = obj[key][:200]
                break

        # 正文
        for key in ('desc', 'description', 'content', 'text'):
            if key in obj and isinstance(obj[key], str) and obj[key]:
                if not meta["desc"] or len(obj[key]) > len(meta["desc"]):
                    meta["desc"] = obj[key][:5000]
                break

        # 互动数据
        interact = obj.get('interactInfo', obj.get('interactionInfo', {}))
        if isinstance(interact, dict):
            for key, target in [
                ('likedCount', 'likes'), ('likedcount', 'likes'),
                ('collectedCount', 'collects'), ('collectedcount', 'collects'),
                ('commentCount', 'comments_count'), ('commentcount', 'comments_count'),
                ('sharedCount', 'shares'), ('sharedcount', 'shares'),
            ]:
                val = interact.get(key, '0')
                if isinstance(val, str):
                    from utils.common import parse_count
                    meta[target] = parse_count(val)
                elif isinstance(val, (int, float)):
                    meta[target] = int(val)

        # 作者昵称
        user = obj.get('user', {})
        if isinstance(user, dict):
            nick = user.get('nickname', user.get('nickName', ''))
            if nick:
                meta['nickname'] = str(nick)

        # 笔记类型
        ntype = obj.get('type', '')
        if ntype:
            meta['note_type'] = 'video' if ntype == 'video' else 'normal'

        # 发布时间
        ts = obj.get('time', obj.get('createTime', 0))
        if ts and ts > 0:
            try:
                from datetime import datetime
                meta['publish_time'] = datetime.fromtimestamp(ts / 1000.0).strftime('%Y-%m-%d %H:%M')
            except Exception:
                pass

        # 递归
        for val in obj.values():
            _extract_meta_from_json(val, meta, depth + 1)

    elif isinstance(obj, list):
        for item in obj[:50]:  # 限制遍历长度
            _extract_meta_from_json(item, meta, depth + 1)


# ============================================================
#  主流程
# ============================================================

def extract_and_ocr(
    url: str = None,
    html: str = None,
    output_dir: str = None,
    lang: str = "chi_sim",
    max_workers: int = 3,
    dry_run: bool = False,
    keep_images: bool = False,
) -> dict:
    """
    从帖子 URL 或 HTML 提取图片并 OCR。

    Args:
        url: 小红书帖子 URL
        html: 帖子 HTML 文本（与 url 二选一）
        output_dir: 输出目录（默认临时目录）
        lang: OCR 语言
        max_workers: 并发下载线程数
        dry_run: 仅提取 URL，不下载不 OCR
        keep_images: 保留下载的图片（默认 OCR 后删除）

    Returns:
        {
            "url": str,
            "image_urls": [str],
            "image_count": int,
            "images": [{index, url, filepath, ocr_text, confidence, ...}],
            "combined_text": str,      # 所有图片OCR文本合并
            "note_meta": dict,         # 帖子元数据
            "ocr_summary": dict,       # OCR 统计
        }
    """
    print("=" * 60)
    print("🖼️  Extract & OCR — 小红书图文内容提取")
    print("=" * 60)
    print()

    # ---- Step 1: 获取 HTML ----
    if html:
        print("📄 使用提供的 HTML 文本")
    elif url:
        print(f"🌐 获取页面: {url}")
        html = fetch_page_html(url)
        print(f"   ✅ HTML 获取成功 ({len(html):,} 字符)")
    else:
        raise ValueError("请提供 --url 或 --html")

    # ---- Step 2: 提取图片 URL ----
    print()
    print("🔍 提取图片 URL...")
    image_urls = extract_image_urls_from_html(html)
    print(f"   ✅ 找到 {len(image_urls)} 个图片 URL")

    if not image_urls:
        print("   ⚠️ 未找到任何图片 URL，尝试输出HTML片段供调试...")
        # 打印前500字符的HTML片段帮助调试
        snippet = html[:2000]
        print(f"   HTML 前 2000 字符:\n{snippet[:500]}...")
        return {
            "url": url,
            "image_urls": [],
            "image_count": 0,
            "images": [],
            "combined_text": "",
            "note_meta": extract_note_meta_from_html(html),
            "ocr_summary": {"error": "未找到图片URL"},
        }

    for i, img_url in enumerate(image_urls[:10]):
        print(f"   [{i+1}] {img_url[:80]}...")
    if len(image_urls) > 10:
        print(f"   ... 还有 {len(image_urls) - 10} 张")

    # ---- Step 2.5: 提取帖子元数据 ----
    note_meta = extract_note_meta_from_html(html)
    if note_meta.get("title"):
        print()
        print(f"📋 帖子元数据: 标题=\"{note_meta['title'][:50]}\", "
              f"作者={note_meta.get('nickname', '?')}, "
              f"赞={note_meta.get('likes', 0)}")

    # ---- Dry run ----
    if dry_run:
        print()
        print("🔍 Dry run — 仅提取 URL，不下载不 OCR")
        return {
            "url": url,
            "image_urls": image_urls,
            "image_count": len(image_urls),
            "images": [],
            "combined_text": "",
            "note_meta": note_meta,
            "ocr_summary": {"dry_run": True},
        }

    # ---- Step 3: 下载图片 ----
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="xhs_ocr_")
    img_dir = os.path.join(output_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

    print()
    print(f"📥 下载 {len(image_urls)} 张图片...")
    download_results = download_images(image_urls, img_dir, max_workers=max_workers)
    success_count = sum(1 for r in download_results if r["success"])
    print(f"   ✅ 成功 {success_count}/{len(image_urls)}")

    # ---- Step 4: OCR ----
    print()
    print("🔬 OCR 识别...")

    if not _check_tesseract():
        return {
            "url": url,
            "image_urls": image_urls,
            "image_count": len(image_urls),
            "images": download_results,
            "combined_text": "",
            "note_meta": note_meta,
            "ocr_summary": {"error": "Tesseract 不可用"},
        }

    success_paths = [r["filepath"] for r in download_results if r["success"]]
    ocr_results = ocr_images(success_paths, lang=lang, max_workers=2)

    # 合并结果
    images_output = []
    total_confidence = 0
    total_words = 0
    ocr_success = 0

    for dl in download_results:
        img_entry = {
            "index": dl["index"],
            "url": dl["url"],
            "filepath": dl["filepath"],
            "downloaded": dl["success"],
            "ocr_text": "",
            "ocr_confidence": 0,
            "ocr_line_count": 0,
            "ocr_word_count": 0,
        }

        if dl["success"]:
            # 找到对应的 OCR 结果
            for ocr in ocr_results:
                if ocr.get("image_path") == dl["filepath"]:
                    img_entry["ocr_text"] = ocr.get("text", "")
                    img_entry["ocr_confidence"] = ocr.get("confidence", 0)
                    img_entry["ocr_line_count"] = ocr.get("line_count", 0)
                    img_entry["ocr_word_count"] = ocr.get("word_count", 0)
                    if ocr.get("error"):
                        img_entry["ocr_error"] = ocr["error"]
                    else:
                        total_confidence += ocr.get("confidence", 0)
                        total_words += ocr.get("word_count", 0)
                        ocr_success += 1
                    break

        images_output.append(img_entry)

    # 合并所有 OCR 文本
    combined_text_parts = []
    for img in images_output:
        if img["ocr_text"]:
            combined_text_parts.append(
                f"--- 图片 {img['index'] + 1} ---\n{img['ocr_text']}"
            )
    combined_text = "\n\n".join(combined_text_parts)

    # OCR 统计
    ocr_summary = {
        "total_images": len(image_urls),
        "downloaded": success_count,
        "ocr_success": ocr_success,
        "avg_confidence": round(total_confidence / ocr_success, 1) if ocr_success > 0 else 0,
        "total_words": total_words,
        "combined_text_length": len(combined_text),
    }

    print(f"   ✅ OCR 完成: {ocr_success} 张识别成功")
    print(f"   📊 平均置信度: {ocr_summary['avg_confidence']}%")
    print(f"   📝 总字数: {total_words}")

    # ---- Step 5: 清理临时图片 ----
    if not keep_images:
        for img in images_output:
            if img["filepath"] and os.path.exists(img["filepath"]):
                try:
                    os.remove(img["filepath"])
                except OSError:
                    pass
        # 删除空的 images 目录
        try:
            if os.path.exists(img_dir) and not os.listdir(img_dir):
                os.rmdir(img_dir)
        except OSError:
            pass

    return {
        "url": url,
        "image_urls": image_urls,
        "image_count": len(image_urls),
        "images": images_output,
        "combined_text": combined_text,
        "note_meta": note_meta,
        "ocr_summary": ocr_summary,
        "output_dir": output_dir,
    }


# ============================================================
#  CLI
# ============================================================
if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Extract & OCR images from Xiaohongshu post (No login required)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从URL提取
  python extract_post_images_ocr.py --url "https://www.xiaohongshu.com/..." -o ./ocr_output

  # 仅预览URL（不下载不OCR）
  python extract_post_images_ocr.py --url "<链接>" --dry-run

  # 保留下载的图片
  python extract_post_images_ocr.py --url "<链接>" -o ./output --keep-images

  # 英文+中文OCR
  python extract_post_images_ocr.py --url "<链接>" --lang chi_sim+eng
        """,
    )
    parser.add_argument("--url", help="小红书帖子URL")
    parser.add_argument("--html", help="HTML文件路径（调试用）")
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument("--lang", default="chi_sim", help="OCR语言 (默认 chi_sim)")
    parser.add_argument("--max-workers", type=int, default=3, help="并发下载线程数")
    parser.add_argument("--dry-run", action="store_true", help="仅提取URL不下载不OCR")
    parser.add_argument("--keep-images", action="store_true", help="保留下载的图片")
    parser.add_argument("--json", dest="json_output", action="store_true", help="以JSON格式输出结果")
    args = parser.parse_args()

    if not args.url and not args.html:
        parser.error("请提供 --url 或 --html")

    # 读取 HTML 文件（如果指定）
    html_text = None
    if args.html:
        with open(args.html, "r", encoding="utf-8") as f:
            html_text = f.read()
        print(f"📄 读取 HTML 文件: {args.html} ({len(html_text):,} 字符)")

    start_time = time.time()
    result = extract_and_ocr(
        url=args.url,
        html=html_text,
        output_dir=args.output,
        lang=args.lang,
        max_workers=args.max_workers,
        dry_run=args.dry_run,
        keep_images=args.keep_images,
    )
    elapsed = time.time() - start_time

    # 输出结果
    if args.json_output:
        # 打印 JSON（不含过长的 text 字段）
        json_safe = {
            "url": result["url"],
            "image_count": result["image_count"],
            "image_urls": result["image_urls"],
            "note_meta": result["note_meta"],
            "ocr_summary": result["ocr_summary"],
            "images": [
                {
                    "index": img["index"],
                    "url": img["url"][:100],
                    "downloaded": img["downloaded"],
                    "ocr_confidence": img.get("ocr_confidence", 0),
                    "ocr_line_count": img.get("ocr_line_count", 0),
                    "ocr_word_count": img.get("ocr_word_count", 0),
                }
                for img in result["images"]
            ],
            "combined_text_preview": result["combined_text"][:500] + "..." if len(result["combined_text"]) > 500 else result["combined_text"],
        }
        print("\n" + "=" * 60)
        print("📋 JSON 输出:")
        print(json.dumps(json_safe, ensure_ascii=False, indent=2))

    # 保存完整结果
    if args.output and not args.dry_run and result.get("combined_text"):
        output_dir = args.output
        os.makedirs(output_dir, exist_ok=True)

        # 保存 OCR 文本
        txt_path = os.path.join(output_dir, "ocr_combined_text.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(result["combined_text"])
        print(f"\n💾 OCR 文本: {txt_path} ({len(result['combined_text']):,} 字符)")

        # 保存完整 JSON
        json_path = os.path.join(output_dir, "ocr_results.json")
        with open(json_path, "w", encoding="utf-8") as f:
            # 保存时压缩过长的 text
            serializable = {
                **result,
                "images": [
                    {**img, "ocr_text": img.get("ocr_text", "")[:300] + "..." if len(img.get("ocr_text", "")) > 300 else img.get("ocr_text", "")}
                    for img in result["images"]
                ],
                "combined_text": result["combined_text"][:1000] + "..." if len(result["combined_text"]) > 1000 else result["combined_text"],
            }
            json.dump(serializable, f, ensure_ascii=False, indent=2)
        print(f"💾 OCR JSON:  {json_path}")

    print()
    print("=" * 60)
    print(f"✅ 完成! 用时 {elapsed:.0f}秒")
    print(f"   {result['image_count']} 张图片, "
          f"{result['ocr_summary'].get('ocr_success', 0)} 张OCR成功, "
          f"总字数 {result['ocr_summary'].get('total_words', 0)}")
    print("=" * 60)
