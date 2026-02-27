"""
JPX（日本取引所グループ）の上場銘柄一覧 Excel から
コード → 日本語銘柄名 のマッピングを構築する。

初回起動時にダウンロードし、.cache/names_ja.json にキャッシュする（30日間有効）。
"""

import io
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict

logger = logging.getLogger(__name__)

_CACHE_DIR  = os.path.join(os.path.dirname(__file__), ".cache")
_CACHE_PATH = os.path.join(_CACHE_DIR, "names_ja.json")
_CACHE_TTL  = timedelta(days=30)

# JPX 公式: 上場銘柄一覧（全市場）
_JPX_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/misc/"
    "tvdivq0000001vg2-att/data_j.xls"
)

_names: Dict[str, str] = {}


# ── キャッシュ ───────────────────────────────────────────────────────────

def _load_cache() -> Dict[str, str]:
    try:
        if os.path.exists(_CACHE_PATH):
            mtime = datetime.fromtimestamp(os.path.getmtime(_CACHE_PATH))
            if datetime.now() - mtime < _CACHE_TTL:
                with open(_CACHE_PATH, encoding="utf-8") as f:
                    return json.load(f)
            logger.info("銘柄名キャッシュが期限切れ → 再ダウンロード")
    except Exception:
        pass
    return {}


def _save_cache(data: Dict[str, str]) -> None:
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"キャッシュ保存失敗: {e}")


# ── Excel 解析 ──────────────────────────────────────────────────────────

def _parse_excel(content: bytes) -> Dict[str, str]:
    """
    JPX の Excel ファイルを解析してコード→銘柄名辞書を返す。
    .xls → xlrd、.xlsx → openpyxl の順で試行する。
    """
    try:
        import pandas as pd

        df = None
        for engine in ("xlrd", "openpyxl", None):
            try:
                kwargs = {} if engine is None else {"engine": engine}
                df = pd.read_excel(io.BytesIO(content), dtype=str, **kwargs)
                break
            except Exception:
                continue

        if df is None:
            logger.warning("Excel 読み込み失敗 (xlrd または openpyxl が必要)")
            return {}

        # ヘッダー行を探す（先頭5行以内に "コード" を含む行があれば採用）
        for i in range(min(5, len(df))):
            row_vals = [str(v).strip() for v in df.iloc[i].values]
            if any("コード" in v for v in row_vals):
                df.columns = row_vals
                df = df.iloc[i + 1:].reset_index(drop=True)
                break

        cols = [str(c) for c in df.columns]
        code_col = next((c for c in cols if "コード" in c), None)
        name_col = next((c for c in cols if "銘柄名" in c), None)

        if not code_col or not name_col:
            # 列名で見つからない場合は先頭2列を使用
            if len(cols) >= 2:
                code_col, name_col = cols[0], cols[1]
            else:
                logger.warning("JPX ファイルの列構造を認識できませんでした")
                return {}

        result: Dict[str, str] = {}
        for _, row in df.iterrows():
            try:
                raw = str(row[code_col]).strip().split(".")[0]  # ".0" を除去
                code = raw.zfill(4)
                name = str(row[name_col]).strip()
                if len(code) == 4 and code.isdigit() and name and name != "nan":
                    result[code] = name
            except Exception:
                continue

        return result

    except Exception as e:
        logger.warning(f"JPX パース失敗: {e}")
        return {}


# ── ダウンロード ─────────────────────────────────────────────────────────

def _download() -> Dict[str, str]:
    try:
        import requests
        logger.info("JPX 銘柄一覧をダウンロード中...")
        r = requests.get(
            _JPX_URL, timeout=30,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        if r.status_code != 200:
            logger.warning(f"JPX ダウンロード失敗: HTTP {r.status_code}")
            return {}
        parsed = _parse_excel(r.content)
        logger.info(f"JPX から {len(parsed)} 銘柄名を取得")
        return parsed
    except Exception as e:
        logger.warning(f"JPX ダウンロードエラー: {e}")
        return {}


# ── 公開 API ─────────────────────────────────────────────────────────────

def initialize() -> None:
    """
    起動時に1回呼び出す。
    キャッシュが有効な場合はキャッシュを使用し、期限切れや未作成の場合は
    JPX からダウンロードする。
    """
    global _names
    cached = _load_cache()
    if cached:
        _names = cached
        logger.info(f"銘柄名キャッシュ読み込み完了 ({len(_names)} 件)")
        return
    _names = _download()
    if _names:
        _save_cache(_names)
    else:
        logger.warning("日本語銘柄名の取得に失敗。英語名にフォールバックします。")


def get(code: str, fallback: str = "") -> str:
    """
    4桁の銘柄コードに対応する日本語名を返す。
    見つからない場合は fallback を返す。
    """
    return _names.get(str(code).zfill(4), "") or fallback
