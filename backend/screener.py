"""
清原達郎式スクリーニングロジック

修正ポイント:
  - totalCurrentAssets / totalLiab は info に入らないため balance_sheet から取得
  - 名証上場銘柄は .T が 404 になるため .N (Nagoya) にフォールバック
  - trailingPE が None の場合 forwardPE を使用
  - 銘柄名は longName（日本語）優先
  - セクターを日本語に翻訳
  - 配当利回りを複数フィールドから算出・異常値補正
  - 選定基準を run_screening の引数で上書き可能
"""

import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import logging
from typing import Optional

import name_lookup

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

# yfinance セクター名 → 日本語
SECTOR_JA: dict = {
    "Basic Materials":        "素材・化学",
    "Communication Services": "情報・通信",
    "Consumer Cyclical":      "消費者サービス",
    "Consumer Defensive":     "生活必需品",
    "Energy":                 "エネルギー",
    "Financial Services":     "金融",
    "Healthcare":             "ヘルスケア",
    "Industrials":            "資本財・サービス",
    "Real Estate":            "不動産",
    "Technology":             "テクノロジー",
    "Utilities":              "公共事業",
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


def _translate_sector(sector: Optional[str], industry: Optional[str]) -> str:
    """セクター名を日本語に変換する。"""
    if sector and sector in SECTOR_JA:
        return SECTOR_JA[sector]
    if sector:
        return sector  # 未知のセクターはそのまま返す
    return industry or "不明"


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


def _div_yield_pct(info: dict) -> float:
    """
    配当利回り(%)を算出する。
    yfinance の dividendYield は小数形式 (0.025 = 2.5%)。
    異常値の場合は dividendRate / price で再計算し、0〜30% にクランプする。
    """
    raw = info.get("dividendYield") or info.get("trailingAnnualDividendYield") or 0
    pct = float(raw) * 100

    # 0% 以下または 30% 超は dividendRate / price で再計算を試みる
    if pct <= 0 or pct > 30:
        div_rate = float(info.get("dividendRate") or 0)
        price    = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)
        if div_rate > 0 and price > 0:
            pct = div_rate / price * 100
        else:
            pct = 0.0

    return round(max(0.0, min(pct, 30.0)), 2)


def _fetch_single(code: str, criteria: dict) -> Optional[dict]:
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
    if not (criteria["market_cap_min_oku"] <= market_cap_oku <= criteria["market_cap_max_oku"]):
        return None

    # --- PBR ---
    pbr = info.get("priceToBook")
    if not pbr or pbr <= 0:
        price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        bvps  = info.get("bookValue") or 0
        if price and bvps > 0:
            pbr = price / bvps
    if not pbr or pbr <= 0 or pbr > criteria["pbr_max"]:
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
    if not per or per <= 0 or per > criteria["per_max"]:
        return None

    # --- ネットキャッシュ比率 (balance_sheet から算出) ---
    ncr: Optional[float] = None
    try:
        bs  = ticker.balance_sheet
        ncr = _net_cash_ratio(bs, market_cap_jpy)
    except Exception:
        pass

    # データが取れて基準未満なら除外。データ未取得は通過させてソート末尾に置く
    if ncr is not None and ncr < criteria["net_cash_ratio_min"]:
        return None

    # --- 付加情報 ---
    sector    = _translate_sector(info.get("sector"), info.get("industry"))
    div_yield = _div_yield_pct(info)

    net_cash_oku = None
    if ncr is not None:
        net_cash_oku = round(ncr * market_cap_jpy / 1e8, 1)

    # 日本語銘柄名: JPX データ → longName → shortName の順で取得
    name = (
        name_lookup.get(code)
        or info.get("longName")
        or info.get("shortName")
        or code
    )

    return {
        "code":           code,
        "name":           name,
        "sector":         sector,
        "price":          info.get("currentPrice") or info.get("regularMarketPrice") or 0,
        "pbr":            round(pbr, 2),
        "per":            round(per, 2),
        "market_cap_oku": round(market_cap_oku, 1),
        "dividend_yield": div_yield,
        "net_cash_ratio": round(ncr, 2) if ncr is not None else None,
        "net_cash_oku":   net_cash_oku,
        "chart_links":    _build_chart_links(code),
    }


def run_screening(candidate_codes: list, criteria: Optional[dict] = None) -> dict:
    """
    スクリーニングを実行する。
    criteria に値を渡すとデフォルト (CRITERIA) を上書きできる。
    """
    c = {**CRITERIA, **(criteria or {})}
    passed = []
    with ThreadPoolExecutor(max_workers=c["max_workers"]) as executor:
        futures = {executor.submit(_fetch_single, code, c): code for code in candidate_codes}
        for future in as_completed(futures):
            result = future.result()
            if result:
                passed.append(result)

    # ソート: ネットキャッシュ比率降順 (None は末尾) → PBR昇順
    passed.sort(key=lambda x: (
        -(x["net_cash_ratio"] if x["net_cash_ratio"] is not None else -999),
        x["pbr"]
    ))
    top = passed[:c["top_n"]]

    return {
        "stocks":         top,
        "total_screened": len(candidate_codes),
        "total_passed":   len(passed),
        "criteria":       c,
        "updated_at":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
