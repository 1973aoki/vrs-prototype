# 1. ベースイメージの指定
# Python 3.12 の公式イメージ（軽量版）を使用します。
FROM python:3.12-slim

# 2. 作業ディレクトリの設定
# コンテナ内の /app フォルダを作業場所として指定します。
WORKDIR /app

# 3. 依存関係のコピーとインストール
# ホストPCの requirements.txt をコンテナにコピーします。
COPY requirements.txt .

# requirements.txt に書かれたすべてのライブラリをインストールします。
# ortools や requests などがインストールされます。
# --no-cache-dir はイメージサイズを小さく保つための推奨オプションです。
RUN pip install --no-cache-dir -r requirements.txt

# 4. アプリケーションコードのコピー
# プロジェクトのルートディレクトリにあるすべてのコードファイルをコンテナの /app にコピーします。
COPY . .

# 5. コンテナ起動時のデフォルトコマンド
# コンテナを実行したときに、メインの Python スクリプト main.py を実行するように設定します。
CMD ["python", "main.py"]