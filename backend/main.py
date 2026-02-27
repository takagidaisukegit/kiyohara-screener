"""
清原達郎式スクリーナー - FastAPI バックエンド
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
import threading
import os
import logging

from screener import run_screening, CRITERIA
from candidates import CANDIDATE_CODES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="清原達郎式スクリーナー API",
    description="ネットキャッシュ比率 × PBR × PER による日本小型株スクリーニング",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- キャッシュ ----------
_cache: dict = {"data": None, "lock": threading.Lock(), "running": False}


@app.get("/api/criteria")
def get_criteria():
    """デフォルトのスクリーニング基準を返す"""
    return CRITERIA


@app.get("/api/screen")
def screen(
    net_cash_ratio_min: Optional[float] = Query(default=None, description="ネットキャッシュ比率 最小値"),
    pbr_max:            Optional[float] = Query(default=None, description="PBR 上限"),
    per_max:            Optional[float] = Query(default=None, description="PER 上限"),
    market_cap_min_oku: Optional[float] = Query(default=None, description="時価総額 最小（億円）"),
    market_cap_max_oku: Optional[float] = Query(default=None, description="時価総額 最大（億円）"),
    top_n:              Optional[int]   = Query(default=None, description="表示件数"),
):
    """
    スクリーニングを実行して結果を返す。
    クエリパラメータで選定基準を上書き可能。同時実行防止のため、実行中は 429 を返す。
    """
    with _cache["lock"]:
        if _cache["running"]:
            raise HTTPException(status_code=429, detail="スクリーニング実行中です。しばらくお待ちください。")
        _cache["running"] = True

    # クエリパラメータで上書きされた基準のみ override に詰める
    override: dict = {}
    if net_cash_ratio_min is not None: override["net_cash_ratio_min"] = net_cash_ratio_min
    if pbr_max            is not None: override["pbr_max"]            = pbr_max
    if per_max            is not None: override["per_max"]            = per_max
    if market_cap_min_oku is not None: override["market_cap_min_oku"] = market_cap_min_oku
    if market_cap_max_oku is not None: override["market_cap_max_oku"] = market_cap_max_oku
    if top_n              is not None: override["top_n"]              = top_n

    try:
        logger.info(f"スクリーニング開始: {len(CANDIDATE_CODES)} 銘柄対象 override={override}")
        result = run_screening(CANDIDATE_CODES, override or None)
        with _cache["lock"]:
            _cache["data"] = result
        logger.info(f"スクリーニング完了: {result['total_passed']} 銘柄通過 → 上位 {len(result['stocks'])} 件")
        return result
    except Exception as e:
        logger.error(f"スクリーニングエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        with _cache["lock"]:
            _cache["running"] = False


@app.get("/api/cache")
def get_cache():
    """最後にスクリーニングした結果を返す（再実行なし）"""
    if _cache["data"] is None:
        raise HTTPException(status_code=404, detail="キャッシュがありません。先にスクリーニングを実行してください。")
    return _cache["data"]


@app.get("/api/status")
def status():
    return {
        "candidate_count": len(CANDIDATE_CODES),
        "is_running": _cache["running"],
        "has_cache": _cache["data"] is not None,
        "last_updated": _cache["data"]["updated_at"] if _cache["data"] else None,
    }


# ---------- 静的ファイル配信 ----------
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
frontend_dir = os.path.abspath(frontend_dir)

if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")
else:
    @app.get("/")
    def root():
        return {"message": "frontend ディレクトリが見つかりません"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
