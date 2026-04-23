"""
模拟盘账户 ID 生成工具

用稳定哈希把“策略 + 参数 + 标的”映射为唯一账户实例 ID。
"""
from __future__ import annotations

import hashlib
import json


def build_account_id(strategy_key: str, codes: list[str], params: dict) -> str:
    """
    生成稳定的模拟盘账户 ID。

    账户隔离维度：
    - 策略 key（如 overnight_long）
    - 标的列表（排序后）
    - 参数字典（按 key 排序）
    """
    payload = {
        "strategy": strategy_key,
        "codes": sorted(codes),
        "params": {k: params[k] for k in sorted(params)},
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{strategy_key}:{digest}"
