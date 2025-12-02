import sys
import math
import requests
import json
import folium
import pandas as pd
import gspread
import tomllib
import streamlit as st
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

# ==========================================
# 1. ユーティリティ関数
# ==========================================

def get_distance_matrix_batched(locations, api_key):
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
                    row_minutes.extend([9999] * len(chunk_locs))
                    continue
                for element in data['rows'][0]['elements']:
                    if element['status'] == 'OK':
                        minutes = round(element['duration']['value'] / 60)
                        row_minutes.append(minutes)
                    else:
                        row_minutes.append(9999)
            except Exception:
                row_minutes.extend([9999] * len(chunk_locs))
        matrix.append(row_minutes)
        print(f"進捗: {i+1}/{num_locs} 地点完了")
    print("APIデータ取得完了！")
    return matrix

def calculate_haversine_matrix(locations):
    print("簡易計算モードで実行します...")
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
    print(f"シート '{sheet_name}' からデータを読み込んでいます...")
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet_id = "10DPMrEQZkOdYJFVIcjqVas7HCuu7xCBwyGD4ha7BqG0" # ★要書き換え★
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
    except Exception as e:
        print(f"スプレッドシート読み込みエラー: {e}")
        return [], [], []

    records = worksheet.get_all_records()
    names, location_names, locations = [], [], []
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

def update_google_sheets(df):
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file('credentials.json', scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet_id = "10DPMrEQZkOdYJFVIcjqVas7HCuu7xCBwyGD4ha7BqG0" # ★要書き換え★
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        try:
            worksheet = spreadsheet.worksheet("Output")
        except:
            worksheet = spreadsheet.add_worksheet(title="Output", rows=100, cols=20)
        
        worksheet.clear()
        if not df.empty:
            df = df.astype(str)
            payload = [df.columns.values.tolist()] + df.values.tolist()
            worksheet.update(values=payload, range_name='A1')
            return "成功しました！"
        return "データがありませんでした"
    except Exception as e:
        return f"エラー: {e}"

# ==========================================
# 2. データモデル構築 (★ここを改造★)
# ==========================================

def create_data_model(config): # 引数 config を受け取るように変更
    data = {}
    
    api_key = ""
    try:
        api_key = st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        try:
            with open(".streamlit/secrets.toml", "rb") as f:
                secrets = tomllib.load(f)
                api_key = secrets["GOOGLE_MAPS_API_KEY"]
        except:
            api_key = ""

    # 1. データ取得
    names, loc_names, locations = get_input_from_sheet("Input")
    if not names:
        return None # エラー時

    data['names'] = names
    data['location_names'] = loc_names
    data['locations'] = locations
    num_locations = len(locations)

    # 2. 行列計算
    if api_key:
        data['time_matrix'] = get_distance_matrix_batched(locations, api_key)
        if not data['time_matrix']:
            data['time_matrix'] = calculate_haversine_matrix(locations)
    else:
        data['time_matrix'] = calculate_haversine_matrix(locations)

    # 3. 車両・制約設定 (★configの値を使う★)
    real_vehicle_count = config['num_cars'] # 画面から来た値
    max_trips = config['max_trips']         # 画面から来た値
    
    data['num_vehicles'] = real_vehicle_count * max_trips
    data['real_vehicle_count'] = real_vehicle_count
    
    # 定員 (全員共通)
    data['vehicle_capacities'] = [config['capacity']] * data['num_vehicles']
    
    data['depot'] = 0
    data['service_time'] = config['service_time'] # 滞在時間
    data['demands'] = [0] + [1] * (num_locations - 1)
    
    # 時間窓 (画面から来た start_minutes, end_minutes を使う)
    start_min = config['start_minutes']
    end_min = config['end_minutes']
    
    # 全地点の時間窓
    data['time_windows'] = [[start_min, end_min]] * num_locations
    
    # ★修正: 施設の終了時間も、画面設定値(end_min)を厳守させる
    data['time_windows'][0] = [start_min, end_min]

    return data

# ==========================================
# 3. 出力用データ作成
# ==========================================

def create_map_object(data, manager, routing, solution):
    depot_loc = data['locations'][data['depot']]
    m = folium.Map(location=depot_loc, zoom_start=13)
    colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue', 'pink', 'darkgreen']

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
    return m

def create_schedule_df(data, manager, routing, solution):
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

    # ★追加修正: ここで全データを文字列型に強制変換する
    # これで数値と文字が混ざっていてもエラーになりません
    df = df.astype(str)

    return df

# ==========================================
# 4. メイン処理 (アプリ用)
# ==========================================

def solve_vrp(config): # configを受け取る
    data = create_data_model(config) # configを渡す
    if not data: return False, 0, None, None

    manager = pywrapcp.RoutingIndexManager(len(data['time_matrix']), data['num_vehicles'], data['depot'])
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return data['time_matrix'][from_node][to_node]
    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return data['demands'][from_node]
    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(demand_callback_index, 0, data['vehicle_capacities'], True, 'Capacity')

    def total_time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = data['time_matrix'][from_node][to_node]
        service = 0 if from_node == data['depot'] else data['service_time']
        return travel + service
    total_time_callback_index = routing.RegisterTransitCallback(total_time_callback)
    
    routing.AddDimension(total_time_callback_index, 10000, 10000, False, 'Time')
    time_dimension = routing.GetDimensionOrDie('Time')
    
    # 時間窓設定
    for i in range(len(data['time_matrix'])):
        index = manager.NodeToIndex(i)
        time_dimension.CumulVar(index).SetRange(data['time_windows'][i][0], data['time_windows'][i][1])

    # 車両出発時間の設定
    real_count = data['real_vehicle_count']
    depot_window = data['time_windows'][data['depot']]
    
    for i in range(data['num_vehicles']):
        start_index = routing.Start(i)
        end_index = routing.End(i)
        
        # 1便目は開始時間ジャストに出発
        if i < real_count:
            start_time = depot_window[0]
            time_dimension.CumulVar(start_index).SetRange(start_time, start_time)
        else:
            time_dimension.CumulVar(start_index).SetRange(depot_window[0], depot_window[1])
            
        time_dimension.CumulVar(end_index).SetRange(depot_window[0], depot_window[1])

        # 2便目以降にペナルティ(コスト)を与えて、1便目を優先させる
        trip_index = i // real_count
        if trip_index > 0:
            routing.SetFixedCostOfVehicle(1000, i)

    # 2便目制約
    solver = routing.solver()
    for v in range(real_count, data['num_vehicles']):
        prev_v = v - real_count
        prev_end_index = routing.End(prev_v)
        curr_start_index = routing.Start(v)
        turnover_time = 10 
        solver.Add(time_dimension.CumulVar(curr_start_index) >= time_dimension.CumulVar(prev_end_index) + turnover_time)

    # 実行
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_parameters.time_limit.seconds = 180

    print("最適化計算を実行中...")
    solution = routing.SolveWithParameters(search_parameters)

    if solution:
        total_time = solution.ObjectiveValue()
        m = create_map_object(data, manager, routing, solution)
        df = create_schedule_df(data, manager, routing, solution)
        return True, total_time, m, df
    else:
        return False, 0, None, None