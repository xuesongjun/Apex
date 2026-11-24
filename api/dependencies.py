"""
API dependencies and query parsing helpers
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query

from data.storage.repository import PaperRepository
from trading.account_id import build_account_id


def get_paper_repository() -> PaperRepository:
    return PaperRepository()


def _split_codes(raw_codes: str | None) -> list[str]:
    if not raw_codes:
        return []
    return [part.strip() for part in raw_codes.split(",") if part.strip()]


def _split_params(raw_params: str | None) -> dict:
    if not raw_params:
        return {}

    params: dict[str, int | float | str] = {}
    for item in raw_params.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        try:
            parsed: int | float | str = int(value)
        except ValueError:
            try:
                parsed = float(value)
            except ValueError:
                parsed = value
        params[key] = parsed
    return params


def resolve_account_id(
    account_id: Annotated[str | None, Query(description="稳定账户ID")] = None,
    strategy: Annotated[str | None, Query(description="策略 key，如 overnight_long")] = None,
    codes: Annotated[str | None, Query(description="代码列表，逗号分隔")] = None,
    params: Annotated[str | None, Query(description="参数列表，key=value 逗号分隔")] = None,
) -> str | None:
    if account_id:
        return account_id
    if strategy:
        parsed_codes = _split_codes(codes)
        if not parsed_codes:
            raise HTTPException(status_code=400, detail="提供 strategy 时必须同时提供 codes")
        parsed_params = _split_params(params)
        return build_account_id(strategy, parsed_codes, parsed_params)
    return None


PaperRepoDep = Annotated[PaperRepository, Depends(get_paper_repository)]
AccountIdDep = Annotated[str | None, Depends(resolve_account_id)]
