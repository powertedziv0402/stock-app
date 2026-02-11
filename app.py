import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="00631L 策略戰情室", layout="wide")
st.title("📈 00631L 雙重濾網．策略戰情室")

# --- 側邊欄說明 ---
st.sidebar.header("策略邏輯")
st.sidebar.info("""
**🟢 買進訊號 A (順勢):**
連續 3 日收盤 > 日 K 200 均線

**🔵 買進訊號 B (抄底):**
價格觸碰或跌破 週 K 200 均線 (最高原則)

**🔴 賣出訊號:**
連續 3 日收盤 < 日 K 200 均線

**表格說明:**
相同顏色的兩行為同一個交易循環
(買進 + 賣出)。
""")

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    # 下載數據
    df = yf.download(ticker, period="10y", progress=False, auto_adjust=False)
    
    if df.empty:
        return None, None, None

    # --- 資料格式修正 ---
    df.index = df.index.tz_localize(None) # 移除時區
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if 'Close' not in df.columns and 'Adj Close' in df.columns:
        df = df.rename(columns={'Adj Close': 'Close'})
    if 'Low' not in df.columns:
        df['Low'] = df['Close']

    # --- 計算指標 ---
    df['MA200_D'] = df['Close'].rolling(window=200).mean()
    
    weekly = df['Close'].resample('W').last()
    weekly_ma = weekly.rolling(window=200).mean()
    df['MA200_W'] = weekly_ma.reindex(df.index, method='ffill')

    # --- 策略回測邏輯 ---
    df['Action'] = None 
    holding = False
    history = [] 
    
    start_calc = 0
    for i in range(len(df)):
        if not pd.isna(df['MA200_D'].iloc[i]) and not pd.isna(df['MA200_W'].iloc[i]):
            start_calc = i
            break
            
    signals = [None] * len(df)
    
    for i in range(start_calc, len(df)):
        curr_idx = df.index[i]
        close = df['Close'].iloc[i]
        low = df['Low'].iloc[i]
        ma_d = df['MA200_D'].iloc[i]
        ma_w = df['MA200_W'].iloc[i]
        
        if i < 2: continue

        days_check = df['Close'].iloc[i-2:i+1]
        ma_check = df['MA200_D'].iloc[i-2:i+1]
        
        is_above_3days = all(days_check > ma_check)
        is_below_3days = all(days_check < ma_check)
        is_touch_weekly = low <= ma_w
        
        action = None
        date_str = curr_idx.strftime('%Y-%m-%d')
        
        if not holding:
            if is_touch_weekly:
                holding = True
                action = "Buy_B"
                history.append({'Date': date_str, 'Type': '🔵 買進 (抄底)', 'Price': close, 'RawType': 'Buy'})
            elif is_above_3days:
                holding = True
                action = "Buy_A"
                history.append({'Date': date_str, 'Type': '🟢 買進 (順勢)', 'Price': close, 'RawType': 'Buy'})
        else:
            if is_below_3days:
                holding = False
                action = "Sell"
                history.append({'Date': date_str, 'Type': '🔴 賣出', 'Price': close, 'RawType': 'Sell'})
        
        signals[i] = action

    df['Action'] = signals
    return df, history, holding

# --- 處理表格資料的函數 (14格邏輯) ---
def process_history_table(history, is_holding):
    # 我們需要顯示 14 格 (7 個循環)
    # 邏輯：最新的在最上面
    
    display_rows = []
    
    # 複製一份歷史紀錄並反轉 (最新的在前面)
    rev_history = history[::-1]
    
    # 1. 處理當前狀態 (第一格)
    if not is_holding:
        # 如果空手，第一格是空白的 "等待訊號"
        display_rows.append({
            '交易日期': '---', 
            '動作': '⚪ 等待買進訊號...', 
            '價格': '---', 
            'Group': 0 # Group 0 代表第一格空白
        })
        data_idx = 0
    else:
        # 如果持倉中，第一格是當前的買進單
        # 在 rev_history 中，最新的應該是 Buy
        if rev_history and rev_history[0]['RawType'] == 'Buy':
            latest = rev_history[0]
            display_rows.append({
                '交易日期': latest['Date'],
                '動作': latest['Type'],
                '價格': f"{latest['Price']:.2f}",
                'Group': 1 # Group 1 開始代表第一組循環
            })
            data_idx = 1 # 已經用掉一筆資料
        else:
            # 異常防呆
            data_idx = 0

    # 2. 填滿剩下的格子 (總共要湊滿 14 格)
    # 我們用 Group ID 來控制顏色，每兩筆資料(一買一賣)為一組
    
    current_group = 1 if is_holding else 1
    
    # 從 data_idx 開始遍歷歷史資料
    while len(display_rows) < 14:
        if data_idx < len(rev_history):
            item = rev_history[data_idx]
            
            # 決定 Group ID: 
            # 賣出單(Sell) 和 下一筆買進單(Buy) 應該是同一組
            # 因為 rev_history 是倒序，所以是先看到 Sell，再看到 Buy
            
            row_data = {
                '交易日期': item['Date'],
                '動作': item['Type'],
                '價格': f"{item['Price']:.2f}",
                'Group': current_group
            }
            display_rows.append(row_data)
            
            # 如果這筆是 Buy，代表這組循環結束(在倒序中)，換下一組顏色
            if item['RawType'] == 'Buy':
                current_group += 1
            
            data_idx += 1
        else:
            # 如果歷史資料不夠 14 筆，填空值
            display_rows.append({
                '交易日期': '', '動作': '', '價格': '', 'Group': -1
            })
            
    return pd.DataFrame(display_rows)

# --- 表格顏色設定 ---
def highlight_groups(row):
    group = row['Group']
    
    if group == 0: # 等待買進
        return ['background-color: #ffffff; color: #888888'] * len(row)
    elif group == -1: # 資料不足的空格
        return ['background-color: #f0f2f6'] * len(row)
    
    # 循環顏色 (深淺交替)
    if group % 2 != 0:
        # 奇數組 (例如 Group 1, 3, 5...) - 淺藍色背景
        return ['background-color: #e3f2fd; color: black'] * len(row)
    else:
        # 偶數組 (例如 Group 2, 4, 6...) - 淺灰色/白色背景
        return ['background-color: #ffffff; color: black'] * len(row)

# --- 主程式執行 ---
if st.button('🔄 點擊更新最新數據'):
    try:
        with st.spinner('正在連線 Yahoo Finance 抓取最新股價...'):
            df, history, is_holding = get_data_and_signal()
            
            if df is not None:
                # --- 頂部資訊 ---
                last_dt = df.index[-1].strftime('%Y-%m-%d')
                last_close = df['Close'].iloc[-1]
                last_ma_d = df['MA200_D'].iloc[-1]
                last_ma_w = df['MA200_W'].iloc[-1]
                
                st.header(f"📅 數據日期: {last_dt}")
                c1, c2, c3 = st.columns(3)
                c1.metric("目前股價", f"{last_close:.2f}")
                c2.metric("日 K 200", f"{last_ma_d:.2f}")
                c3.metric("週 K 200", f"{last_ma_w:.2f}")

                st.markdown("---")
                
                # --- 狀態警示 ---
                today_act = df['Action'].iloc[-1]
                if today_act == "Buy_B":
                    st.error("🚨 **觸發訊號**: 嚴重超跌，立即買進抄底！")
                elif today_act == "Buy_A":
                    st.success("✅ **觸發訊號**: 趨勢確認，進場買進！")
                elif today_act == "Sell":
                    st.warning("⚠️ **觸發訊號**: 趨勢反轉，獲利/停損出場！")

                # --- 版面分割: 左邊表格(14格)，右邊圖表 ---
                col_table, col_chart = st.columns([1, 2])
                
                with col_table:
                    st.subheader("📋 交易循環紀錄 (14格)")
                    # 處理表格資料
                    table_df = process_history_table(history, is_holding)
                    # 應用顏色樣式 (隱藏 Group 欄位)
                    styled_df = table_df.style.apply(highlight_groups, axis=1).hide(axis='index')
                    # 顯示表格
                    st.dataframe(styled_df, use_container_width=True, height=520, column_config={"Group": None})

                with col_chart:
                    st.subheader("📈 策略走勢圖")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='收盤價', line=dict(color='#2962FF', width=1.5)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_D'], mode='lines', name='日K200', line=dict(color='#FF6D00', width=1)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_W'], mode='lines', name='週K200', line=dict(color='#D50000', width=2, dash='dash')))
                    
                    buys = df[df['Action'].str.contains('Buy', na=False)]
                    sells = df[df['Action'] == 'Sell']
                    
                    fig.add_trace(go.Scatter(x=buys.index, y=buys['Close'], mode='markers', name='買進', marker=dict(color='green', size=12, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sells.index, y=sells['Close'], mode='markers', name='賣出', marker=dict(color='red', size=12, symbol='triangle-down')))
                    
                    fig.update_layout(height=500, margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1, x=0))
                    st.plotly_chart(fig, use_container_width=True)

            else:
                st.error("無法取得數據，請稍後再試。")
    except Exception as e:
        st.error(f"發生錯誤: {e}")
