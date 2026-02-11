import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="00631L 策略戰情室", layout="wide")
st.title("📈 00631L 雙重濾網．全歷史績效戰情室")

# --- 側邊欄說明 ---
st.sidebar.header("策略邏輯 (優先級修正版)")
st.sidebar.info("""
**👑 最高優先級：買進訊號 B (抄底)**
* **條件**: 價格觸碰或跌破 **週 K 200 均線**
* **動作**: 無視日線趨勢，直接掛單在週均線價位買進。

**🟢 次要優先級：買進訊號 A (順勢)**
* **條件**: 連續 3 日收盤 > 日 K 200 均線
* **動作**: 若無抄底訊號，則依此訊號買進。

**🔴 賣出訊號:**
* **條件**: 連續 3 日收盤 < 日 K 200 均線
""")

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    
    # --- 🔧 強化版資料抓取邏輯 ---
    try:
        # 改用 Ticker 物件抓取，這在 Streamlit Cloud 上通常比較穩定
        stock = yf.Ticker(ticker)
        # 嘗試抓取 2015 至今
        df = stock.history(start="2015-01-01", auto_adjust=False)
        
        # 如果抓回來是空的 (Yahoo 偶爾會漏資料)，改抓 'max' 全部資料
        if df.empty:
            df = stock.history(period="max", auto_adjust=False)
            
    except Exception as e:
        return None, None, None
    
    if df.empty:
        return None, None, None

    # --- 資料清洗 ---
    df.index = df.index.tz_localize(None) 
    
    # 欄位名稱標準化 (history 抓下來的欄位通常很乾淨，但以防萬一)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # 確保關鍵欄位存在
    if 'Close' not in df.columns: return None, None, None
    if 'Low' not in df.columns: df['Low'] = df['Close']
    if 'Open' not in df.columns: df['Open'] = df['Close']

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
        is_in_range = curr_idx.year >= 2016
        
        close = df['Close'].iloc[i]
        open_p = df['Open'].iloc[i]
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
            # 優先級 1: 抄底
            if is_touch_weekly:
                holding = True
                action = "Buy_B"
                
                # 價格模擬
                if open_p < ma_w:
                    buy_price = open_p
                    note = "跳空跌破買進"
                else:
                    buy_price = ma_w
                    note = "觸價掛單買進"

                if is_in_range:
                    history.append({
                        'Date': date_str, 
                        'Type': '🔵 買進(抄底)', 
                        'Price': buy_price, 
                        'RawType': 'Buy',
                        'Note': note
                    })
            
            # 優先級 2: 順勢
            elif is_above_3days:
                holding = True
                action = "Buy_A"
                if is_in_range:
                    history.append({
                        'Date': date_str, 
                        'Type': '🟢 買進(順勢)', 
                        'Price': close,
                        'RawType': 'Buy',
                        'Note': "收盤確認"
                    })
        else:
            if is_below_3days:
                holding = False
                action = "Sell"
                if is_in_range:
                    history.append({
                        'Date': date_str, 
                        'Type': '🔴 賣出', 
                        'Price': close, 
                        'RawType': 'Sell',
                        'Note': "跌破日線3日"
                    })
        
        signals[i] = action

    df['Action'] = signals
    return df, history, holding

# --- 處理績效表格 ---
def process_performance_table(history, is_holding):
    trades = []
    temp_buy = None
    
    for record in history:
        if record['RawType'] == 'Buy':
            temp_buy = record
        elif record['RawType'] == 'Sell' and temp_buy is not None:
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
                '備註': temp_buy.get('Note', ''),
                'is_active': False
            })
            temp_buy = None

    df_trades = pd.DataFrame(trades)
    if not df_trades.empty:
        df_trades = df_trades[::-1]

    current_status = {}
    if is_holding and temp_buy is not None:
        current_status = {
            '狀態': '🔥 持倉中',
            '買進日期': temp_buy['Date'],
            '買進價格': temp_buy['Price'],
            '賣出日期': '---',
            '賣出價格': None,
            '損益點數': None,
            '報酬率(%)': None,
            '備註': temp_buy.get('Note', ''),
            'is_active': True
        }
    else:
        current_status = {
            '狀態': '⏳ 等待時機',
            '買進日期': '---',
            '買進價格': None,
            '賣出日期': '---',
            '賣出價格': None,
            '損益點數': None,
            '報酬率(%)': None,
            '備註': '',
            'is_active': True
        }
    
    df_status = pd.DataFrame([current_status])
    final_df = pd.concat([df_status, df_trades], ignore_index=True)
    return final_df

# --- 樣式設定 ---
def style_dataframe(df):
    def highlight_status_row(row):
        if row.get('is_active') == True:
            return ['background-color: #FFF9C4; color: black; font-weight: bold'] * len(row)
        return [''] * len(row)

    def color_profit(val):
        if pd.isna(val): return ''
        color = '#D50000' if val > 0 else '#00C853' if val < 0 else 'black'
        return f'color: {color}; font-weight: bold'

    styler = df.style.apply(highlight_status_row, axis=1)
    styler = styler.map(color_profit, subset=['損益點數', '報酬率(%)'])
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

                df_display = process_performance_table(history, is_holding)
                
                col_table, col_chart = st.columns([5, 4])
                
                with col_table:
                    st.subheader("📋 交易績效總覽 (含優先級修正)")
                    # 關鍵：隱藏 index 與 is_active 欄位
                    styled_table = style_dataframe(df_display).hide(axis='index').hide(subset=['is_active'], axis="columns")
                    st.dataframe(
                        styled_table, 
                        use_container_width=True, 
                        height=600, 
                        column_config={
                            "狀態": st.column_config.TextColumn("狀態", width="small"),
                            "備註": st.column_config.TextColumn("備註", width="small"),
                        }
                    )

                with col_chart:
                    st.subheader("📈 策略走勢圖")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='收盤價', line=dict(color='#2962FF', width=1.5)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_D'], mode='lines', name='日K200', line=dict(color='#FF6D00', width=1)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_W'], mode='lines', name='週K200', line=dict(color='#D50000', width=2, dash='dash')))
                    
                    # 繪製買賣點
                    buys_b = df[df['Action'] == 'Buy_B'] 
                    buys_a = df[df['Action'] == 'Buy_A'] 
                    sells = df[df['Action'] == 'Sell']
                    
                    fig.add_trace(go.Scatter(x=buys_b.index, y=buys_b['Low'], mode='markers', name='買進(抄底)', marker=dict(color='purple', size=15, symbol='star')))
                    fig.add_trace(go.Scatter(x=buys_a.index, y=buys_a['Close'], mode='markers', name='買進(順勢)', marker=dict(color='green', size=12, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sells.index, y=sells['Close'], mode='markers', name='賣出', marker=dict(color='red', size=12, symbol='triangle-down')))
                    
                    fig.update_layout(height=600, margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1, x=0))
                    fig.update_xaxes(range=['2016-01-01', last_dt])
                    st.plotly_chart(fig, use_container_width=True)

            else:
                st.error("Yahoo Finance 暫時無回應，請稍後再試 (或重新整理網頁)。")
    except Exception as e:
        st.error(f"發生錯誤: {e}")
