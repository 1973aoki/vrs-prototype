# 1. ベースイメージ (軽量なPython)
FROM python:3.12-slim

# 2. 作業ディレクトリ
WORKDIR /app

# 3. 必要なパッケージをインストール (キャッシュ活用)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. ソースコードをコピー
# (.dockerignore で secrets.toml などを除外している前提)
COPY . .

# 5. ポート開放
EXPOSE 8501

# 6. アプリ起動コマンド
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]