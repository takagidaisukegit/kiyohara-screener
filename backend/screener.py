"""
清原達郎式スクリーニングロジック
選定基準:
  - ネットキャッシュ比率 = (流動資産 + 投資有価証券×70% - 負債合計) / 時価総額 >= 0.5
  - 時価総額: 50億円 〜 1,000億円
  - PER: <= 20倍
  - PBR: <= 1.0倍
"""

import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# スクリーニング基準
CRITERIA = {
    "market_cap_min_oku": 50,       # 時価総額 下限（億円）
    "market_cap_max_oku": 1000,     # 時価総額 上限（億円）
    "pbr_max": 1.0,                 # PBR 上限
    "per_max": 20.0,                # PER 上限
    "net_cash_ratio_min": 0.5,      # ネットキャッシュ比率 下限
    "top_n": 20,                    # 表示件数
    "max_workers": 40,              # 並列フェッチ数
}

# チャートリンク生成
CHART_LINKS = {
    "minkabu":   "https://minkabu.jp/stock/{code}",
    "kabutan":   "https://kabutan.jp/stock/chart?code={code}",
    "yahoo":     "https://finance.yahoo.co.jp/quote/{code}.T",
    "buffett":   "https://www.buffett-code.com/company/{code}/",
    "irbank":    "https://irbank.net/{code}",
}


def _build_chart_links(code: str) -> dict:
    return {k: v.format(code=code) for k, v in CHART_LINKS.items()}


def _fetch_single(code: str) -> Optional[dict]:
    """1銘柄のデータを取得してスクリーニング基準を適用する"""
    try:
        ticker = yf.Ticker(f"{code}.T")
        info = ticker.info

        if not info or info.get("quoteType") not in ("EQUITY",):
            return None

        # --- 時価総額 ---
        market_cap_jpy = info.get("marketCap") or 0
        market_cap_oku = market_cap_jpy / 1_0000_0000
        if not (CRITERIA["market_cap_min_oku"] <= market_cap_oku <= CRITERIA["market_cap_max_oku"]):
            return None

        # --- PBR ---
        pbr = info.get("priceToBook")
        if pbr is None or pbr <= 0 or pbr > CRITERIA["pbr_max"]:
            return None

        # --- PER（trailing優先、なければforward）---
        per = info.get("trailingPE") or info.get("forwardPE")
        if per is None or per <= 0 or per > CRITERIA["per_max"]:
            return None

        # --- ネットキャッシュ比率 ---
        current_assets    = info.get("totalCurrentAssets") or 0
        total_liabilities = info.get("totalLiab") or 0
        lt_investments    = info.get("longTermInvestments") or 0
        net_cash = current_assets + lt_investments * 0.7 - total_liabilities
        net_cash_ratio = net_cash / market_cap_jpy if market_cap_jpy > 0 else 0

        if net_cash_ratio < CRITERIA["net_cash_ratio_min"]:
            return None

        # --- 配当利回り ---
        div_yield = (info.get("dividendYield") or 0) * 100

        # --- 業種 ---
        sector = info.get("sector") or info.get("industry") or "不明"

        return {
            "code":             code,
            "name":             info.get("shortName") or info.get("longName") or code,
            "sector":           sector,
            "price":            info.get("currentPrice") or info.get("regularMarketPrice") or 0,
            "pbr":              round(pbr, 2),
            "per":              round(per, 2),
            "market_cap_oku":   round(market_cap_oku, 1),
            "dividend_yield":   round(div_yield, 2),
            "net_cash_ratio":   round(net_cash_ratio, 2),
            "net_cash_oku":     round(net_cash / 1_0000_0000, 1),
            "chart_links":      _build_chart_links(code),
        }

    except Exception as e:
        logger.debug(f"[{code}] fetch error: {e}")
        return None


def run_screening(candidate_codes: list[str]) -> dict:
    """
    候補銘柄リストをスクリーニングして上位N件を返す
    """
    passed = []
    total = len(candidate_codes)

    with ThreadPoolExecutor(max_workers=CRITERIA["max_workers"]) as executor:
        futures = {executor.submit(_fetch_single, code): code for code in candidate_codes}
        for future in as_completed(futures):
            result = future.result()
            if result:
                passed.append(result)

    # ソート: ネットキャッシュ比率降順 → PBR昇順
    passed.sort(key=lambda x: (-x["net_cash_ratio"], x["pbr"]))
    top = passed[: CRITERIA["top_n"]]

    return {
        "stocks":        top,
        "total_screened": total,
        "total_passed":  len(passed),
        "criteria":      CRITERIA,
        "updated_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
