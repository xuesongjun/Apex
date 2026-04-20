"""
模拟盘辅助逻辑测试
"""
from scripts.run_paper_trade import build_account_id


def test_build_account_id_is_stable_and_order_insensitive():
    params = {"min_drop_pct": 3.0, "limit_pct": 0.15}

    a = build_account_id("overnight_long", ["513090", "159915"], params)
    b = build_account_id("overnight_long", ["159915", "513090"], {"limit_pct": 0.15, "min_drop_pct": 3.0})

    assert a == b


def test_build_account_id_changes_when_params_or_codes_change():
    base = build_account_id("overnight_long", ["513090"], {"min_drop_pct": 3.0})
    diff_params = build_account_id("overnight_long", ["513090"], {"min_drop_pct": 5.0})
    diff_codes = build_account_id("overnight_long", ["159915"], {"min_drop_pct": 3.0})

    assert base != diff_params
    assert base != diff_codes
