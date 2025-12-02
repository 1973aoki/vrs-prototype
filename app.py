import streamlit as st
import pandas as pd
from streamlit_folium import st_folium
import main # main.py をライブラリとして読み込む

# ページの設定
st.set_page_config(page_title="送迎ルート自動作成システム", layout="wide")

st.title("🚌 放課後等デイサービス 送迎ルート作成")
st.markdown("Googleスプレッドシートの「Input」シートを読み込んで、最適なルートを計算します。")

# サイドバー
st.sidebar.header("操作パネル")

if st.sidebar.button("ルート計算を開始する", type="primary"):
    st.write("ルート最適化を開始します...")
    with st.spinner("AIがルートを計算中です... (最大180秒かかります)"):
        # main.py の関数を実行
        success, total_time, m, df = main.solve_vrp()
        
    if success:
        st.success(f"計算完了！ 総移動時間: {total_time}分")
        
        # 運行スケジュールはタブの下に表示するため、ここで重複描画をしない！
        # -----------------------------------------------------------
        # st.write("--- 地図表示を開始します ---") 
        # st_folium(m, width=700, height=500) # ← 削除！
        # st.write("--- 地図表示が完了しました ---") # ← 削除！
        # st.subheader("運行スケジュール")
        # st.dataframe(df) # ← 削除！
        # -----------------------------------------------------------

        # タブで表示切り替え (全ての表示コンテンツをこの中に入れる)
        tab1, tab2 = st.tabs(["🗺️ 地図確認", "📋 運行表"])
        
        with tab1:
            st.markdown(f"### 送迎ルート地図 (総移動時間: {total_time}分)")
            # st.write("地図表示完了") # ← デバッグ用なので削除
            # 💥 地図描画をtry-exceptで囲み、クラッシュを防ぐ 💥
            try:
              # 地図を一度だけ表示
                st_folium(m, width=1000, height=600, key='map_output')
                st.write("デバッグ: st_foliumの描画に成功しました。")
            except Exception as e:
                st.error(f"⚠️ 地図描画エラーによりクラッシュしました: {e}")
                st.info("ルートのデータ自体は生成されています。運行表を確認してください。")
            
        with tab2:
            st.markdown("### 運行スケジュール")

            try:
                # use_container_widthを削除し、代わりにwidth='stretch'を使用（推奨されている形式）
                # ただし、これでもエラーになる場合は、引数なしで表示します。
                # 表を一度だけ表示
                st.dataframe(df, use_container_width=True, key='schedule_df') # width='stretch' は非推奨なので修正
                st.write("デバッグ: DataFrameの描画に成功しました。")
            # スプレッドシート更新ボタン
            # if st.button("この結果をスプレッドシート(Output)に保存"):
                # with st.spinner("保存中..."):
                    # main.py の update_google_sheets 関数を実行
                    # msg = main.update_google_sheets(df)
                    # st.info(f"保存結果: {msg}")
                    
            except Exception as e:
                st.error(f"⚠️ 運行表描画エラーによりクラッシュしました: {e}")
                st.info("ルートのデータ自体は生成されています。")
                # エラーが出た場合、生データを見る
                st.code(df.to_json(orient='records'))

    else:
        st.error("解が見つかりませんでした。条件を見直してください。")
        
else:
    st.info("サイドバーの「ルート計算を開始する」ボタンを押してください。")

# ... else: st.info("サイドバーの「ルート計算を開始する」ボタンを押してください。")
# --------------------------------------------------------------------------
# 💥 デバッグ用マーカー: アプリが最後まで到達したか確認 💥
# --------------------------------------------------------------------------
st.sidebar.write("最終チェックポイント: アプリは最後まで実行されました。")