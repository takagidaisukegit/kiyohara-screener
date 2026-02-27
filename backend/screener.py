"""
清原達郎式スクリーニングロジック

修正ポイント:
  - totalCurrentAssets / totalLiab は info に入らないため balance_sheet から取得
  - 名証上場銘柄は .T が 404 になるため .N (Nagoya) にフォールバック
  - trailingPE が None の場合 forwardPE を使用
"""

import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)

CRITERIA = {
    "market_cap_min_oku": 50,
    "market_cap_max_oku": 1000,
    "pbr_max": 1.0,
    "per_max": 20.0,
    "net_cash_ratio_min": 0.5,
    "top_n": 20,
    "max_workers": 40,
}

CHART_LINKS = {
    "minkabu": "https://minkabu.jp/stock/{code}",
    "kabutan": "https://kabutan.jp/stock/chart?code={code}",
    "yahoo":   "https://finance.yahoo.co.jp/quote/{code}.T",
    "buffett": "https://www.buffett-code.com/company/{code}/",
    "irbank":  "https://irbank.net/{code}",
}


def _build_chart_links(code: str) -> dict:
    return {k: v.format(code=code) for k, v in CHART_LINKS.items()}


def _bs_val(bs, *keys) -> float:
    """balance_sheet DataFrame から最初に見つかったキーの値を返す。見つからなければ 0。"""
    if bs is None or bs.empty:
        return 0.0
    col = bs.columns[0]
    idx = bs.index.tolist()
    for k in keys:
        if k in idx:
            try:
                v = bs.loc[k, col]
                if v is not None and v == v:   # NaN チェック
                    return float(v)
            except Exception:
                pass
    return 0.0


def _net_cash_ratio(bs, market_cap_jpy: float) -> Optional[float]:
    """
    ネットキャッシュ比率 = (流動資産 + 投資有価証券×70% − 負債合計) / 時価総額
    balance_sheet が空の場合は None を返す。
    """
    if bs is None or bs.empty:
        return None

    current_assets = _bs_val(bs,
        "Current Assets", "Total Current Assets",
        "Cash Cash Equivalents And Short Term Investments",
    )
    lt_investments = _bs_val(bs,
        "Investments And Advances",
        "Long Term Equity Investment",
        "Available For Sale Securities",
        "Other Investments",
    )
    total_liab = _bs_val(bs,
        "Total Liabilities Net Minority Interest",
        "Total Liabilities",
    )

    if current_assets == 0 and total_liab == 0:
        return None  # データ未取得

    net_cash = current_assets + lt_investments * 0.7 - total_liab
    return net_cash / market_cap_jpy if market_cap_jpy > 0 else 0.0


def _fetch_single(code: str) -> Optional[dict]:
    """1銘柄を取得してスクリーニング基準を適用する。"""
    ticker = None
    info: dict = {}

    # 東証 (.T) → 名証 (.N) → 大証 (.OS) の順に試行
    for suffix in (".T", ".N", ".OS"):
        try:
            t = yf.Ticker(f"{code}{suffix}")
            i = t.info or {}
            if i.get("marketCap") and i["marketCap"] > 0:
                ticker, info = t, i
                break
        except Exception:
            continue

    if not ticker:
        return None

    # --- 時価総額 ---
    market_cap_jpy = info["marketCap"]
    market_cap_oku = market_cap_jpy / 1e8
    if not (CRITERIA["market_cap_min_oku"] <= market_cap_oku <= CRITERIA["market_cap_max_oku"]):
        return None

    # --- PBR ---
    pbr = info.get("priceToBook")
    if not pbr or pbr <= 0:
        price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        bvps  = info.get("bookValue") or 0
        if price and bvps > 0:
            pbr = price / bvps
    if not pbr or pbr <= 0 or pbr > CRITERIA["pbr_max"]:
        return None

    # --- PER (trailing → forward → price/EPS の順) ---
    per = info.get("trailingPE")
    if not per or per <= 0:
        per = info.get("forwardPE")
    if not per or per <= 0:
        price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        eps   = info.get("trailingEps") or 0
        if price and eps > 0:
            per = price / eps
    if not per or per <= 0 or per > CRITERIA["per_max"]:
        return None

    # --- ネットキャッシュ比率 (balance_sheet から算出) ---
    ncr: Optional[float] = None
    try:
        bs  = ticker.balance_sheet
        ncr = _net_cash_ratio(bs, market_cap_jpy)
    except Exception:
        pass

    # データが取れて基準未満なら除外。データ未取得は通過させてソート末尾に置く
    if ncr is not None and ncr < CRITERIA["net_cash_ratio_min"]:
        return None

    # --- 付加情報 ---
    div_yield = (info.get("dividendYield") or 0) * 100
    sector    = info.get("sector") or info.get("industry") or "不明"

    net_cash_oku = None
    if ncr is not None:
        net_cash_oku = round(ncr * market_cap_jpy / 1e8, 1)

    return {
        "code":           code,
        "name":           info.get("shortName") or info.get("longName") or code,
        "sector":         sector,
        "price":          info.get("currentPrice") or info.get("regularMarketPrice") or 0,
        "pbr":            round(pbr, 2),
        "per":            round(per, 2),
        "market_cap_oku": round(market_cap_oku, 1),
        "dividend_yield": round(div_yield, 2),
        "net_cash_ratio": round(ncr, 2) if ncr is not None else None,
        "net_cash_oku":   net_cash_oku,
        "chart_links":    _build_chart_links(code),
    }


def run_screening(candidate_codes: list) -> dict:
    passed = []
    with ThreadPoolExecutor(max_workers=CRITERIA["max_workers"]) as executor:
        futures = {executor.submit(_fetch_single, c): c for c in candidate_codes}
        for future in as_completed(futures):
            result = future.result()
            if result:
                passed.append(result)

    # ソート: ネットキャッシュ比率降順 (None は末尾) → PBR昇順
    passed.sort(key=lambda x: (
        -(x["net_cash_ratio"] if x["net_cash_ratio"] is not None else -999),
        x["pbr"]
    ))
    top = passed[:CRITERIA["top_n"]]

    return {
        "stocks":         top,
        "total_screened": len(candidate_codes),
        "total_passed":   len(passed),
        "criteria":       CRITERIA,
        "updated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
