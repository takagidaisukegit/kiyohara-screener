@echo off
chcp 65001 >nul
title 清原達郎式スクリーナー

echo ============================================
echo  清原達郎式スクリーナー 起動
echo ============================================
echo.

cd /d "%~dp0backend"

:: venv が無ければ作成
if not exist "venv\Scripts\activate.bat" (
    echo [1/3] 仮想環境を作成しています...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Python が見つかりません。Python 3.11以上をインストールしてください。
        pause
        exit /b 1
    )
)

:: 仮想環境を有効化
call venv\Scripts\activate.bat

:: 依存パッケージをインストール（初回 or 更新時）
echo [2/3] 依存パッケージを確認しています...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] パッケージのインストールに失敗しました。
    pause
    exit /b 1
)

:: ブラウザを少し遅れて開く（サーバー起動を待つ）
echo [3/3] サーバーを起動しています...
echo.
echo  アクセス先: http://localhost:8000
echo  停止するには Ctrl+C を押してください
echo.
start /b cmd /c "timeout /t 2 >nul && start http://localhost:8000"

:: サーバー起動
python main.py

pause
