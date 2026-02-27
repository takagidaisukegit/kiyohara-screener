"""
スクリーニング通過銘柄のカタリスト（株価変動要因）分析モジュール。

ルールベース（財務指標）+ ニュースキーワード + 四半期業績トレンドを組み合わせて、
今後1年程度で発生し得るカタリストを推定する。

呼び出し側: main.py の GET /api/catalyst/{code}
  - スクリーニング結果に含まれる銘柄コードに対してのみ呼ばれる
  - サーバー側キャッシュ (_cache) から既存の財務データを使い、
    追加では news + quarterly_income_stmt のみを取得する
"""

import yfinance as yf
import logging
from datetime import datetime, timedelta
from typing import Optional, List

logger = logging.getLogger(__name__)


# ── Balance sheet helper (screener.py と同一ロジック) ───────────────────

def _bs_val(bs, *keys) -> float:
    if bs is None or bs.empty:
        return 0.0
    col = bs.columns[0]
    idx = bs.index.tolist()
    for k in keys:
        if k in idx:
            try:
                v = bs.loc[k, col]
                if v is not None and v == v:
                    return float(v)
            except Exception:
                pass
    return 0.0


def _net_cash_ratio(bs, market_cap_jpy: float) -> Optional[float]:
    if bs is None or bs.empty:
        return None
    current_assets = _bs_val(
        bs, "Current Assets", "Total Current Assets",
        "Cash Cash Equivalents And Short Term Investments",
    )
    lt_investments = _bs_val(
        bs, "Investments And Advances", "Long Term Equity Investment",
        "Available For Sale Securities", "Other Investments",
    )
    total_liab = _bs_val(
        bs, "Total Liabilities Net Minority Interest", "Total Liabilities",
    )
    if current_assets == 0 and total_liab == 0:
        return None
    net_cash = current_assets + lt_investments * 0.7 - total_liab
    return net_cash / market_cap_jpy if market_cap_jpy > 0 else 0.0


# ── ニュースキーワード辞書 ───────────────────────────────────────────────

_NEWS_CATALYSTS: dict = {
    "自社株買い":   ["自社株", "自己株式取得", "buyback", "share repurchase", "repurchase program"],
    "増配":        ["増配", "dividend increase", "raised dividend", "higher dividend"],
    "特別配当":     ["特別配当", "special dividend", "extra dividend"],
    "TOB":        ["TOB", "tender offer", "公開買付", "takeover bid", "acquisition offer"],
    "MBO":        ["MBO", "management buyout"],
    "業績上方修正": ["上方修正", "upward revision", "beat earnings", "raised guidance", "earnings beat"],
    "M&A":        ["買収", "合併", "acquisition", "merger", "business combination"],
    "事業再編":    ["事業再編", "restructuring", "divestiture", "spin-off"],
    "株主還元強化": ["株主還元", "shareholder return", "capital return", "capital allocation"],
}


def _news_based(news_list: list) -> List[str]:
    """直近6ヶ月のニュースタイトルからカタリストキーワードを検出する。"""
    cutoff = datetime.now() - timedelta(days=180)
    found: List[str] = []
    for article in (news_list or [])[:15]:
        pub_time = article.get("providerPublishTime", 0)
        if pub_time:
            try:
                if datetime.fromtimestamp(pub_time) < cutoff:
                    continue
            except Exception:
                pass
        title = (article.get("title") or "").lower()
        for name, keywords in _NEWS_CATALYSTS.items():
            if name not in found and any(kw.lower() in title for kw in keywords):
                found.append(name)
    return found


# ── ルールベース分析 ────────────────────────────────────────────────────

def _rule_based(
    ncr: Optional[float],
    pbr: float,
    per: float,
    div_yield: float,
    cap_oku: float,
    sector_en: str,
) -> List[str]:
    """財務指標から発生確率の高いカタリストを推定する。sector_en は英語のまま渡す。"""
    results: List[str] = []

    # ① キャッシュリッチ系（最も期待度が高いカタリスト群）
    if ncr is not None:
        if ncr >= 2.5:
            results.append("大規模株主還元（増配・自社株買い）の可能性")
        elif ncr >= 1.5:
            if div_yield < 2.0:
                results.append("増配・自社株買い余地大（NCR≥1.5×低配当）")
            else:
                results.append("追加株主還元の余地あり（NCR≥1.5）")
        elif ncr >= 1.0 and div_yield < 0.5:
            results.append("無配/低配当 → 配当開始・増配の余地")
        elif ncr >= 0.8 and cap_oku < 200:
            results.append("小型キャッシュリッチ銘柄の再評価余地")

    # ② バリュー・買収防衛系
    if pbr and pbr <= 0.3:
        results.append("超低PBR（TOB/MBO候補水準）")
    elif pbr and pbr <= 0.5 and ncr is not None and ncr >= 0.9:
        results.append("キャッシュリッチ×割安：MBO候補")

    # ③ 業績割安系
    if per and per <= 8:
        results.append("PER一桁：収益力に対し著しく割安")

    # ④ セクター固有カタリスト（英語セクター名で判定）
    if sector_en == "Real Estate":
        results.append("不動産含み益の顕在化期待")
    elif sector_en in ("Technology", "Communication Services"):
        results.append("DX・AI需要拡大の恩恵期待")
    elif sector_en == "Industrials":
        results.append("設備投資回復局面での業績改善期待")
    elif sector_en == "Consumer Cyclical":
        results.append("消費回復・インバウンド需要の恩恵期待")
    elif sector_en == "Healthcare":
        results.append("高齢化需要・医療DXの追い風期待")

    return results


# ── 四半期業績トレンド ────────────────────────────────────────────────────

def _earnings_trend(ticker) -> Optional[str]:
    """直近2四半期の売上高を比較し、増収基調なら説明文を返す。"""
    try:
        qis = ticker.quarterly_income_stmt
        if qis is None or qis.empty:
            return None
        rev_key = next(
            (k for k in qis.index if "Total Revenue" in k or
             ("Revenue" in k and "Total" not in k and "Other" not in k)),
            None,
        )
        if not rev_key or len(qis.columns) < 2:
            return None
        latest = qis.loc[rev_key, qis.columns[0]]
        prev   = qis.loc[rev_key, qis.columns[1]]
        if latest and prev and float(prev) > 0:
            change = (float(latest) - float(prev)) / float(prev) * 100
            if change >= 15:
                return f"増収基調（前四半期比 +{change:.0f}%）"
    except Exception:
        pass
    return None


# ── 公開 API ─────────────────────────────────────────────────────────────

def analyze(code: str, base_data: Optional[dict] = None) -> str:
    """
    1銘柄のカタリストを分析して文字列で返す。

    base_data: _cache に保存済みのスクリーニング結果データ（省略時は yfinance から再取得）
               提供されると balance_sheet の再フェッチをスキップできる。
    """
    # ── Step 1: ticker オブジェクトを取得 ──
    ticker = None
    info: dict = {}
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
        return "データ取得失敗"

    # ── Step 2: NCR を決定（base_data があればそのまま使用） ──
    ncr: Optional[float] = base_data.get("net_cash_ratio") if base_data else None
    if ncr is None:
        try:
            bs = ticker.balance_sheet
            market_cap_jpy = info.get("marketCap", 0)
            ncr = _net_cash_ratio(bs, market_cap_jpy)
        except Exception:
            pass

    # ── Step 3: 財務指標（base_data 優先） ──
    if base_data:
        pbr       = base_data.get("pbr", 0)
        per       = base_data.get("per", 0)
        div_yield = base_data.get("dividend_yield", 0)
        cap_oku   = base_data.get("market_cap_oku", 0)
    else:
        pbr       = info.get("priceToBook") or 0
        per       = info.get("trailingPE") or info.get("forwardPE") or 0
        div_yield = (info.get("dividendYield") or 0) * 100
        cap_oku   = (info.get("marketCap") or 0) / 1e8

    sector_en = info.get("sector") or ""  # 英語のまま使用

    # ── Step 4: ルールベース分析 ──
    catalysts = _rule_based(ncr, pbr, per, div_yield, cap_oku, sector_en)

    # ── Step 5: 四半期業績トレンド（追加フェッチ） ──
    try:
        trend = _earnings_trend(ticker)
        if trend and trend not in catalysts:
            catalysts.insert(0, trend)
    except Exception:
        pass

    # ── Step 6: ニュースキーワード（追加フェッチ） ──
    try:
        news_cats = _news_based(ticker.news or [])
        for c in news_cats:
            if c not in catalysts:
                catalysts.append(c)
    except Exception:
        pass

    if not catalysts:
        return "明確なカタリストなし"

    return " / ".join(catalysts[:3])  # 最大3つ
