# 清原達郎式スクリーナー

清原達郎氏の投資手法をベースにした日本小型株スクリーニング Web アプリケーション。

## スクリーニング基準

| 指標 | 条件 |
|------|------|
| **ネットキャッシュ比率** | ≥ 0.5（= (流動資産 + 投資有価証券×70% − 負債) ÷ 時価総額） |
| **時価総額** | 50億円 〜 1,000億円 |
| **PBR** | ≤ 1.0倍 |
| **PER** | ≤ 20倍 |
| **表示件数** | 上位20社（ネットキャッシュ比率降順） |

## 機能

- ボタン1クリックでリアルタイムスクリーニング実行
- 約300銘柄を並列取得してフィルタリング
- 各銘柄のチャートリンク（みんかぶ / 株探 / Yahoo Finance / バフェットコード / IRBank）
- カラム別ソート機能
- スクリーニング統計（対象数・通過数・通過率）

## 技術スタック

- **Backend**: Python 3.11+ / FastAPI / yfinance
- **Frontend**: Vanilla HTML / CSS / JavaScript（フレームワークなし）
- **データ**: Yahoo Finance（yfinance 経由）

## セットアップ & 起動

### 1. Python 環境構築

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. サーバー起動

```bash
cd backend
python main.py
```

ブラウザで `http://localhost:8000` を開く。

### 3. スクリーニング実行

「スクリーニング実行」ボタンを押す。
約300銘柄を並列取得するため **1〜2分** 程度かかります。

## ディレクトリ構成

```
kiyohara-screener/
├── backend/
│   ├── main.py          # FastAPI アプリ + 静的ファイル配信
│   ├── screener.py      # スクリーニングロジック
│   ├── candidates.py    # 候補銘柄コードリスト (~300)
│   └── requirements.txt
├── frontend/
│   ├── index.html       # メインページ
│   ├── style.css        # ダークモード UI
│   └── app.js           # フロントエンドロジック
└── README.md
```

## API エンドポイント

| Method | Path | 説明 |
|--------|------|------|
| GET | `/api/screen` | スクリーニング実行（1〜2分） |
| GET | `/api/cache` | 前回の実行結果を返す |
| GET | `/api/status` | サーバー状態確認 |

## 注意事項

- 本ツールは投資推奨ではありません
- データは Yahoo Finance (yfinance) 経由で取得しており、データの正確性は保証されません
- 実際の投資判断は最新の財務諸表を確認の上、ご自身の責任で行ってください
- yfinance の仕様変更により動作しなくなる場合があります

## ライセンス

MIT
