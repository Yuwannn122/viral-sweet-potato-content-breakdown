"""通用工具函数"""

import re


def parse_count(s):
    """解析 '1.2万' / '1,234' / '12' 等格式为整数"""
    if not s:
        return 0
    s = str(s).strip().replace(",", "")
    if not s:
        return 0
    try:
        if "万" in s:
            return int(float(s.replace("万", "")) * 10000)
        return int(s)
    except (ValueError, TypeError):
        return 0


def safe_filename(name):
    """将字符串转为安全文件名"""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def ms_to_datetime(ts_ms):
    """13-digit毫秒时间戳 → datetime对象。失败返回None。"""
    if not ts_ms or ts_ms <= 0:
        return None
    try:
        from datetime import datetime
        return datetime.fromtimestamp(ts_ms / 1000.0)
    except (OSError, ValueError, OverflowError):
        return None
