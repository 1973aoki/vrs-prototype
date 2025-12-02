import sys
import math
import requests
import json
import folium
import pandas as pd
import gspread
import tomllib  # <--- ★これを追加 (標準ライブラリ)
# main.py の冒頭に追加
import streamlit as st

from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp


# ==========================================
# 1. ユーティリティ関数
# ==========================================

def get_distance_matrix_batched(locations, api_key):
    """APIリクエスト分割関数"""
    num_locs = len(locations)
    print(f"Google Maps APIで {num_locs} 地点 ({num_locs*num_locs}要素) のルート情報を取得中...")
    matrix = []
    for i, origin in enumerate(locations):
        origin_str = f"{origin[0]},{origin[1]}"
        row_minutes = []
        chunk_size = 25
        for j in range(0, num_locs, chunk_size):
            chunk_locs = locations[j : j + chunk_size]
            destinations_str = "|".join([f"{loc[0]},{loc[1]}" for loc in chunk_locs])
            url = f"https://maps.googleapis.com/maps/api/distancematrix/json?units=metric&origins={origin_str}&destinations={destinations_str}&key={api_key}"
            try:
                response = requests.get(url)
                data = response.json()
                if data['status'] != 'OK':
                    print(f"APIエラー: {data.get('status')}")
                    row_minutes.extend([9999] * len(chunk_locs))
                    continue
                for element in data['rows'][0]['elements']:
                    if element['status'] == 'OK':
                        minutes = round(element['duration']['value'] / 60)
                        row_minutes.append(minutes)
                    else:
                        row_minutes.append(9999)
            except Exception as e:
                print(f"通信エラー: {e}")
                row_minutes.extend([9999] * len(chunk_locs))
        matrix.append(row_minutes)
        print(f"進捗: {i+1}/{num_locs} 地点完了")
    print("APIデータ取得完了！")
    return matrix

def calculate_haversine_matrix(locations):
    """簡易計算関数"""
    print("APIキーがないため、簡易計算モードで実行します...")
    matrix = []
    for i in range(len(locations)):
        row = []
        for j in range(len(locations)):
            if i == j:
                row.append(0)
            else:
                R = 6371.0
                lat1, lon1 = math.radians(locations[i][0]), math.radians(locations[i][1])
                lat2, lon2 = math.radians(locations[j][0]), math.radians(locations[j][1])
                dlat, dlon = lat2 - lat1, lon2 - lon1
                a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
                dist_km = R * c
                minutes = round((dist_km / 20.0) * 60)
                row.append(minutes)
        matrix.append(row)
    return matrix

def get_input_from_sheet(sheet_name="Input"):
    """スプレッドシート読み込み"""
    print(f"シート '{sheet_name}' からデータを読み込んでいます...")
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
    client = gspread.authorize(creds)
    
    # ★スプレッドシートID (各自書き換え)★
    spreadsheet_id = "10DPMrEQZkOdYJFVIcjqVas7HCuu7xCBwyGD4ha7BqG0" 
    spreadsheet = client.open_by_key(spreadsheet_id)
    
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        print(f"エラー: シート '{sheet_name}' が見つかりません。")
        sys.exit(1)

    records = worksheet.get_all_records()
    
    names = []
    location_names = []
    locations = []
    for row in records:
        names.append(str(row['名前']))
        location_names.append(str(row['場所名']))
        locations.append((float(row['緯度']), float(row['経度'])))
        
    print(f"{len(names)} 件のデータを読み込みました。")
    return names, location_names, locations

def get_osrm_route(start_coords, end_coords):
    url = f"http://router.project-osrm.org/route/v1/driving/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    try:
        response = requests.get(url)
        data = response.json()
        coords = data['routes'][0]['geometry']['coordinates']
        return [(lat, lon) for lon, lat in coords]
    except:
        return [start_coords, end_coords]

def format_minutes_to_time(minutes):
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    target_time = base_time + timedelta(minutes=int(minutes))
    return target_time.strftime("%H:%M")

def get_vehicle_display_name(vehicle_id, real_count):
    real_id = (vehicle_id % real_count) + 1
    trip_id = (vehicle_id // real_count) + 1
    return f"車両{real_id} (便{trip_id})", real_id

# ==========================================
# 2. データモデル構築 (多回転対応)
# ==========================================

def create_data_model():
    data = {}
    
    api_key = ""
    
    # --- APIキー読み込みロジック (修正版) ---
    try:
        # 1. アプリ実行時 (Streamlit経由)
        api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
        
    except Exception: 
        # 2. コマンド実行時 (python main.py)
        try:
            with open(".streamlit/secrets.toml", "rb") as f:
                secrets = tomllib.load(f)
                api_key = secrets["GOOGLE_MAPS_API_KEY"]
            print("確認: secrets.toml からAPIキーを読み込みました。")
        except Exception as e:
            print(f"注意: APIキーが見つかりません。簡易モードで実行します。")
            api_key = ""

    # 1. データ取得
    names, loc_names, locations = get_input_from_sheet("Input")
    data['names'] = names
    data['location_names'] = loc_names
    data['locations'] = locations
    num_locations = len(locations)

    # 2. 行列計算
    if api_key:
        data['time_matrix'] = get_distance_matrix_batched(locations, api_key)
        if data['time_matrix']:
             flat_list = [val for row in data['time_matrix'] for val in row]
             if 9999 in flat_list:
                 print("⚠️ 警告: 一部のルートが見つかりませんでした (9999分)")
        else:
            data['time_matrix'] = calculate_haversine_matrix(locations)
    else:
        data['time_matrix'] = calculate_haversine_matrix(locations)

    # 3. 車両・制約設定
    real_vehicle_count = 5
    max_trips = 2
    
    data['num_vehicles'] = real_vehicle_count * max_trips
    data['real_vehicle_count'] = real_vehicle_count
    data['vehicle_capacities'] = [10] * data['num_vehicles']
    
    data['depot'] = 0
    data['service_time'] = 5
    data['demands'] = [0] + [1] * (num_locations - 1)
    
    data['time_windows'] = [[1080, 1140]] * num_locations
    data['time_windows'][0] = [1080, 1140]

    return data
# ==========================================
# 3. 出力関数
# ==========================================

def save_map(data, manager, routing, solution):
    print("地図を生成しています...")
    depot_loc = data['locations'][data['depot']]
    m = folium.Map(location=depot_loc, zoom_start=13)
    colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue']

    vehicle_count = 0
    for vehicle_id in range(data['num_vehicles']):
        index = routing.Start(vehicle_id)
        if routing.IsEnd(solution.Value(routing.NextVar(index))):
            continue

        display_name, real_id = get_vehicle_display_name(vehicle_id, data['real_vehicle_count'])
        color = colors[(real_id - 1) % len(colors)]
        
        step = 1
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            loc = data['locations'][node_index]
            popup_text = f"{data['names'][node_index]} ({data['location_names'][node_index]})"

            if node_index == data['depot']:
                folium.Marker(loc, popup="拠点", icon=folium.Icon(color='red', icon='home')).add_to(m)
            else:
                folium.Marker(loc, popup=f"{display_name}-{step}: {popup_text}", icon=folium.Icon(color=color, icon='user')).add_to(m)
                step += 1

            index = solution.Value(routing.NextVar(index))
            next_node_index = manager.IndexToNode(index)
            next_loc = data['locations'][next_node_index]
            
            points = get_osrm_route(loc, next_loc)
            folium.PolyLine(points, color=color, weight=3, opacity=0.8, tooltip=display_name).add_to(m)
        
        vehicle_count += 1

    m.save("route_map_multi.html")
    print(f"地図を保存しました: route_map_multi.html (稼働: {vehicle_count}便)")

def save_google_sheets(data, manager, routing, solution):
    print("Googleスプレッドシート(Output)を更新しています...")
    rows = []
    time_dimension = routing.GetDimensionOrDie('Time')
    
    for vehicle_id in range(data['num_vehicles']):
        index = routing.Start(vehicle_id)
        if routing.IsEnd(solution.Value(routing.NextVar(index))):
            continue

        display_name, _ = get_vehicle_display_name(vehicle_id, data['real_vehicle_count'])
        step = 1
        while not routing.IsEnd(index):
            node_index = manager.IndexToNode(index)
            arrival_minutes = solution.Min(time_dimension.CumulVar(index))
            service = 0 if node_index == data['depot'] else data['service_time']
            
            rows.append({
                "車両名": display_name,
                "訪問順": step,
                "名前": data['names'][node_index],
                "場所名": data['location_names'][node_index],
                "到着予定時刻": format_minutes_to_time(arrival_minutes),
                "出発予定時刻": format_minutes_to_time(arrival_minutes + service),
                "滞在時間": service
            })
            step += 1
            index = solution.Value(routing.NextVar(index))
            
        node_index = manager.IndexToNode(index)
        arrival_minutes = solution.Min(time_dimension.CumulVar(index))
        rows.append({
            "車両名": display_name,
            "訪問順": step,
            "名前": data['names'][node_index] + " (到着)",
            "場所名": data['location_names'][node_index],
            "到着予定時刻": format_minutes_to_time(arrival_minutes),
            "出発予定時刻": "-",
            "滞在時間": "-"
        })

    df = pd.DataFrame(rows)
    df = df.astype(str)

    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet_id = "10DPMrEQZkOdYJFVIcjqVas7HCuu7xCBwyGD4ha7BqG0" # ★ID書き換え★
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        try:
            worksheet = spreadsheet.worksheet("Output")
        except:
            worksheet = spreadsheet.add_worksheet(title="Output", rows=100, cols=20)
        
        worksheet.clear()
        if not df.empty:
            payload = [df.columns.values.tolist()] + df.values.tolist()
            worksheet.update(values=payload, range_name='A1')
            print("スプレッドシートの更新が完了しました！")
        else:
            print("稼働した車両はありませんでした。")
        
    except Exception as e:
        print(f"シート更新エラー: {e}")

# ==========================================
# 4. メイン処理 (Solver)
# ==========================================

def solve():
    data = create_data_model()
    manager = pywrapcp.RoutingIndexManager(len(data['time_matrix']), data['num_vehicles'], data['depot'])
    routing = pywrapcp.RoutingModel(manager)

    # === ★追加: 若い番号の便（1便目）を優先して使う設定 ===
    # 2便目以降を使うと「ペナルティ（コスト）」がかかるようにします。
    # これにより、AIは「まずはペナルティのない1便目を使おう」と判断します。
    
    real_count = data['real_vehicle_count']
    for i in range(data['num_vehicles']):
        # 何便目かを計算 (0始まり: 0=1便目, 1=2便目...)
        trip_index = i // real_count
        
        # 2便目以降ならコストを追加 (例: 1000ポイント)
        if trip_index > 0:
            routing.SetFixedCostOfVehicle(1000, i)
    # ====================================================

    # コスト
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data['time_matrix'][from_node][to_node]
    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # 定員
    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return data['demands'][from_node]
    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(demand_callback_index, 0, data['vehicle_capacities'], True, 'Capacity')

    # 時間
    def total_time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = data['time_matrix'][from_node][to_node]
        service = 0 if from_node == data['depot'] else data['service_time']
        return travel + service
    total_time_callback_index = routing.RegisterTransitCallback(total_time_callback)
    
    routing.AddDimension(total_time_callback_index, 10000, 10000, False, 'Time')
    time_dimension = routing.GetDimensionOrDie('Time')
    
    # 時間窓 (Node)
    for i in range(len(data['time_matrix'])):
        index = manager.NodeToIndex(i)
        time_dimension.CumulVar(index).SetRange(data['time_windows'][i][0], data['time_windows'][i][1])

    # 時間窓 (Vehicle Start/End)
    # 車両ごとの時間窓設定 (修正版)
    real_count = data['real_vehicle_count']
    
    for i in range(data['num_vehicles']):
        start_index = routing.Start(i)
        end_index = routing.End(i)
        depot_window = data['time_windows'][data['depot']]
        
        # 1便目 (朝イチの便) かどうかチェック
        if i < real_count:
            # ★1便目は「開始時間ジャスト(18:00)」に出発させる
            # SetRange(1080, 1080) にすることで、18:00以外を許しません
            start_time = depot_window[0]
            time_dimension.CumulVar(start_index).SetRange(start_time, start_time)
        else:
            # 2便目以降は「18:00〜19:00」の範囲で自由 (前の便が帰ってきてから出る)
            time_dimension.CumulVar(start_index).SetRange(depot_window[0], depot_window[1])
            
        # 終了時間はいつでもOK
        time_dimension.CumulVar(end_index).SetRange(depot_window[0], depot_window[1])

    # 2便目制約 (安全版)
    solver = routing.solver()
    real_count = data['real_vehicle_count']
    for v in range(real_count, data['num_vehicles']):
        prev_v = v - real_count
        prev_end_index = routing.End(prev_v)
        curr_start_index = routing.Start(v)
        turnover_time = 10 
        solver.Add(time_dimension.CumulVar(curr_start_index) >= time_dimension.CumulVar(prev_end_index) + turnover_time)

    # 実行
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.time_limit.seconds = 180 # 180秒に設定

    print(f"最適化を開始します (実車{data['real_vehicle_count']}台 × 2回転)...")
    solution = routing.SolveWithParameters(search_parameters)

    if solution:
        print(f"総移動時間: {solution.ObjectiveValue()} 分")
        save_map(data, manager, routing, solution)
        save_google_sheets(data, manager, routing, solution)
    else:
        print("解が見つかりませんでした。条件を見直してください。")

if __name__ == '__main__':
    solve()