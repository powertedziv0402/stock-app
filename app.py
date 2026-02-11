import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="00631L 策略戰情室", layout="wide")
st.title("📈 00631L 雙重濾網．全歷史績效戰情室")

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
* **第一行(黃色)**: 目前最新狀態 (等待中或持倉中)
* **下方列表**: 2016 至今已完成的歷史交易
* **損益**: 紅色代表獲利，綠色代表虧損
""")

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    # 下載數據 (確保包含 2016 至今)
    df = yf.download(ticker, start="2015-01-01", progress=False, auto_adjust=False)
    
    if df.empty:
        return None, None, None

    # --- 資料清洗 ---
    df.index = df.index.tz_localize(None) 
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
    
    # 找出開始計算的點 (確保 MA 有值)
    start_calc = 0
    for i in range(len(df)):
        if not pd.isna(df['MA200_D'].iloc[i]) and not pd.isna(df['MA200_W'].iloc[i]):
            start_calc = i
            break
            
    signals = [None] * len(df)
    
    for i in range(start_calc, len(df)):
        curr_idx = df.index[i]
        
        # 只記錄 2016 年以後的訊號 (但計算需依賴前面數據)
        is_in_range = curr_idx.year >= 2016
        
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
                if is_in_range:
                    history.append({'Date': date_str, 'Type': '🔵 買進(抄底)', 'Price': close, 'RawType': 'Buy'})
            elif is_above_3days:
                holding = True
                action = "Buy_A"
                if is_in_range:
                    history.append({'Date': date_str, 'Type': '🟢 買進(順勢)', 'Price': close, 'RawType': 'Buy'})
        else:
            if is_below_3days:
                holding = False
                action = "Sell"
                if is_in_range:
                    history.append({'Date': date_str, 'Type': '🔴 賣出', 'Price': close, 'RawType': 'Sell'})
        
        signals[i] = action

    df['Action'] = signals
    return df, history, holding

# --- 處理績效表格的函數 ---
def process_performance_table(history, is_holding):
    trades = []
    
    # 用來暫存還沒賣出的買單
    temp_buy = None
    
    # 1. 遍歷歷史紀錄，將買賣配對
    for record in history:
        if record['RawType'] == 'Buy':
            temp_buy = record
        elif record['RawType'] == 'Sell' and temp_buy is not None:
            # 找到一組完整的交易 (買 + 賣)
            buy_price = temp_buy['Price']
            sell_price = record['Price']
            profit = sell_price - buy_price
            roi = (profit / buy_price) * 100
            
            trades.append({
                '狀態': '✅ 已實現',
                '買進日期': temp_buy['Date'],
                '買進價格': buy_price,
                '賣出日期': record['Date'],
                '賣出價格': sell_price,
                '損益點數': profit,
                '報酬率(%)': roi,
                'is_active': False
            })
            temp_buy = None # 清空，等待下一筆買進

    # 2. 轉換成 DataFrame 並反向排序 (新的在上面)
    df_trades = pd.DataFrame(trades)
    if not df_trades.empty:
        df_trades = df_trades[::-1] # 反轉，讓最近的賣出排在最上面

    # 3. 建立「第一格」狀態列 (新買進空格)
    current_status = {}
    
    if is_holding and temp_buy is not None:
        # 情況 A: 持倉中，但還沒賣出
        current_status = {
            '狀態': '🔥 持倉中',
            '買進日期': temp_buy['Date'],
            '買進價格': temp_buy['Price'],
            '賣出日期': '---',
            '賣出價格': None, # 用 None 方便後面格式化處理
            '損益點數': None,
            '報酬率(%)': None,
            'is_active': True # 標記為第一行
        }
    else:
        # 情況 B: 空手 (或剛賣出，等待新買點)
        current_status = {
            '狀態': '⏳ 等待時機',
            '買進日期': '---',
            '買進價格': None,
            '賣出日期': '---',
            '賣出價格': None,
            '損益點數': None,
            '報酬率(%)': None,
            'is_active': True
        }
    
    # 將狀態列轉為 DataFrame
    df_status = pd.DataFrame([current_status])
    
    # 合併: 狀態列在最上面 (Row 0) + 歷史交易在下面
    final_df = pd.concat([df_status, df_trades], ignore_index=True)
    
    return final_df

# --- 表格樣式設定 (色彩邏輯) ---
def style_dataframe(df):
    
    # 1. 定義顏色函式
    def highlight_status_row(row):
        # 如果是第一行 (is_active = True)，背景上鵝黃色
        if row.get('is_active') == True:
            return ['background-color: #FFF9C4; color: black; font-weight: bold'] * len(row)
        else:
            return [''] * len(row)

    def color_profit(val):
        # 損益欄位：台股紅賺綠賠
        if pd.isna(val): return ''
        color = '#D50000' if val > 0 else '#00C853' if val < 0 else 'black'
        return f'color: {color}; font-weight: bold'

    # 2. 應用樣式
    styler = df.style.apply(highlight_status_row, axis=1)
    
    # 針對特定欄位應用文字顏色
    styler = styler.map(color_profit, subset=['損益點數', '報酬率(%)'])
    
    # 格式化數字 (小數點後2位)
    styler = styler.format({
        '買進價格': '{:.2f}',
        '賣出價格': '{:.2f}',
        '損益點數': '{:+.2f}',
        '報酬率(%)': '{:+.2f}%'
    }, na_rep="---")
    
    return styler

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

                # --- 準備表格資料 ---
                df_display = process_performance_table(history, is_holding)
                
                # --- 版面配置 ---
                # 這次將表格放在左邊 (比較寬一點顯示詳細數據)，圖表在右邊
                col_table, col_chart = st.columns([5, 4])
                
                with col_table:
                    st.subheader("📋 交易績效總覽 (2016-2026)")
                    
                    # 應用樣式並隱藏輔助欄位 (關鍵修正: 指定 axis='columns')
                    styled_table = style_dataframe(df_display).hide(axis='index').hide(subset=['is_active'], axis="columns")
                    
                    # 顯示表格 (height 設定高一點讓它可捲動)
                    st.dataframe(
                        styled_table, 
                        use_container_width=True, 
                        height=600, # 高度夠高就會出現捲軸
                        column_config={
                            "狀態": st.column_config.TextColumn("狀態", width="medium"),
                            "買進日期": st.column_config.TextColumn("買進日期", width="small"),
                            "賣出日期": st.column_config.TextColumn("賣出日期", width="small"),
                        }
                    )

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
                    
                    fig.update_layout(height=600, margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1, x=0))
                    # 限制圖表縮放範圍從 2016 開始比較清楚
                    fig.update_xaxes(range=['2016-01-01', last_dt])
                    
                    st.plotly_chart(fig, use_container_width=True)

            else:
                st.error("無法取得數據，請稍後再試。")
    except Exception as e:
        st.error(f"發生錯誤: {e}")
