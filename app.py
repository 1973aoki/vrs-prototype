import streamlit as st
import pandas as pd
from streamlit_folium import st_folium
import main

# ページ設定
st.set_page_config(page_title="送迎ルート自動作成", layout="wide")

st.title("🚌 放課後等デイサービス 送迎ルート作成")
st.markdown("Googleスプレッドシートの「Input」データを読み込み、条件に合わせて最適なルートを作成します。")

# ==========================================
# セッションステートの初期化
# ==========================================
if 'calculated' not in st.session_state:
    st.session_state.calculated = False
    st.session_state.total_time = 0
    st.session_state.map_obj = None
    st.session_state.df_result = None

# ==========================================
# サイドバー: 設定パネル
# ==========================================
st.sidebar.header("⚙️ 運行条件の設定")

st.sidebar.subheader("1. 車両の設定")
num_cars = st.sidebar.number_input("稼働する車の台数", min_value=1, max_value=10, value=5)
capacity = st.sidebar.number_input("車の定員 (全員共通)", min_value=1, max_value=20, value=10)
max_trips = st.sidebar.selectbox("最大何回まで往復可能？", [1, 2, 3], index=1)

st.sidebar.subheader("2. 時間の設定")
start_time_obj = st.sidebar.time_input("出発時間 (拠点)", value=pd.to_datetime("18:00").time())
end_time_obj = st.sidebar.time_input("送迎完了リミット", value=pd.to_datetime("19:00").time())
service_time = st.sidebar.number_input("1人あたりの乗降時間(分)", min_value=1, max_value=10, value=5)

start_minutes = start_time_obj.hour * 60 + start_time_obj.minute
end_minutes = end_time_obj.hour * 60 + end_time_obj.minute

config = {
    'num_cars': num_cars,
    'capacity': capacity,
    'max_trips': max_trips,
    'start_minutes': start_minutes,
    'end_minutes': end_minutes,
    'service_time': service_time
}

# ==========================================
# メイン画面 (実行ロジック)
# ==========================================

if start_minutes >= end_minutes:
    st.error("⚠️ エラー: 終了時間は開始時間より後に設定してください。")
else:
    # --- 計算実行ボタン ---
    if st.sidebar.button("ルート計算を開始する", type="primary"):
        with st.spinner("AIがルートを計算中です... (最大180秒かかります)"):
            
            # 計算実行
            success, total_time, m, df = main.solve_vrp(config)
            
            if success:
                st.session_state.calculated = True
                st.session_state.total_time = total_time
                st.session_state.map_obj = m
                st.session_state.df_result = df
            else:
                st.session_state.calculated = False
                st.error("❌ 解が見つかりませんでした。条件（時間や台数）を緩めて再試行してください。")

    # --- 結果の表示 ---
    if st.session_state.calculated:
        st.success(f"✅ 計算完了！ (最適化スコア: {st.session_state.total_time})")
        
        m = st.session_state.map_obj
        df = st.session_state.df_result
        
        tab1, tab2 = st.tabs(["🗺️ 地図で確認", "📋 運行表で確認"])
        
        with tab1:
            # ★修正箇所: returned_objects=[] を追加して再描画ループを防ぐ
            st_folium(m, width=1000, height=600, returned_objects=[])
            
        with tab2:
            # 警告回避のために use_container_width=True を維持 (Streamlitのバージョンによっては width='stretch' 推奨)
            st.dataframe(df, use_container_width=True)
            
            csv = df.to_csv(index=False).encode('utf-8_sig')
            st.download_button(
                label="📥 結果をCSVでダウンロード",
                data=csv,
                file_name="route_result.csv",
                mime="text/csv",
            )
            
            if st.button("スプレッドシート(Output)に保存"):
                with st.spinner("保存中..."):
                    msg = main.update_google_sheets(df)
                    if "成功" in msg:
                        st.success(msg)
                    else:
                        st.error(msg)