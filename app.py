import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="00631L 策略戰情室", layout="wide")
st.title("📈 00631L 雙重濾網．全歷史績效戰情室")

# --- 側邊欄說明 ---
st.sidebar.header("策略邏輯 (盤中觸價即買)")
st.sidebar.info("""
**👑 優先級 1：週線抄底 (Buy B)**
* **條件**: 只要盤中最低價 (Low) **碰到或跌破** 週 K 200 均線。
* **動作**: **掛單買進**。
* **價格**: 以 **週 K 200 均線價格** 成交 (若跳空跌破則以開盤價成交)。

**🟢 優先級 2：日線順勢 (Buy A)**
* **條件**: 連續 3 日收盤 > 日 K 200 均線
* **動作**: 僅在無抄底訊號時執行。

**🔴 賣出訊號:**
* **條件**: 連續 3 日收盤 < 日 K 200 均線
""")

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    
    # 1. 抓取數據
    try:
        stock = yf.Ticker(ticker)
        # 抓取最大範圍以確保均線計算完整
        df = stock.history(period="max", auto_adjust=False)
    except:
        return None, None, None
    
    if df.empty: return None, None, None

    # 2. 資料清洗
    df.index = df.index.tz_localize(None) 
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # 欄位檢查
    for col in ['Close', 'Low', 'Open']:
        if col not in df.columns: return None, None, None

    # 3. 計算指標
    # 日 K 200
    df['MA200_D'] = df['Close'].rolling(window=200).mean()
    
    # 週 K 200 (計算修正)
    # 邏輯：週線均線是根據每週收盤算出來的，我們將其擴展回日線
    weekly = df['Close'].resample('W').last()
    weekly_ma = weekly.rolling(window=200).mean()
    
    # 使用 ffill 將上週的均線值延續到本週 (模擬支撐線概念)
    df['MA200_W'] = weekly_ma.reindex(df.index, method='ffill')

    # 4. 策略回測
    df['Action'] = None 
    holding = False
    history = [] 
    
    # 寬容度微調 (防止數據微小誤差)
    tolerance = 1.005 
    
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

        # 訊號判定
        days_check = df['Close'].iloc[i-2:i+1]
        ma_check = df['MA200_D'].iloc[i-2:i+1]
        
        is_above_3days = all(days_check > ma_check)
        is_below_3days = all(days_check < ma_check)
        
        # --- 核心修改：觸價判定 ---
        # 不看收盤，只看最低價是否摸到均線 (含寬容度)
        is_touch_weekly = low <= (ma_w * tolerance)
        
        action = None
        date_str = curr_idx.strftime('%Y-%m-%d')
        
        if not holding:
            # === 優先級 1: 週線抄底 (絕對優先) ===
            if is_touch_weekly:
                holding = True
                action = "Buy_B"
                
                # --- 價格邏輯修改 ---
                # 您的要求：買在週均線價格
                # 實戰防呆：如果開盤就跳空跌破均線 (Open < MA)，那只能買在 Open (會比 MA 更便宜)
                # 如果開盤在 MA 之上，盤中殺下來，那就買在 MA (掛單成交)
                if open_p < ma_w:
                    buy_price = open_p
                    note_text = "跳空跌破 (買Open)"
                else:
                    buy_price = ma_w
                    note_text = "觸價成交 (買MA)"

                if is_in_range:
                    history.append({
                        'Date': date_str, 
                        'Type': '👑 優先 1：週線抄底', 
                        'Price': buy_price, 
                        'RawType': 'Buy',
                        'Note': note_text
                    })
            
            # === 優先級 2: 日線順勢 ===
            elif is_above_3days:
                holding = True
                action = "Buy_A"
                if is_in_range:
                    history.append({
                        'Date': date_str, 
                        'Type': '🟢 優先 2：日線順勢', 
                        'Price': close, # 順勢單通常等收盤確認
                        'RawType': 'Buy',
                        'Note': "收盤確認"
                    })
        else:
            # 持倉中: 只能賣出
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

# --- 表格處理 ---
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
                '買進類型': temp_buy['Type'],
                '買進價格': buy_price,
                '賣出日期': record['Date'],
                '賣出價格': sell_price,
                '損益點數': profit,
                '報酬率(%)': roi,
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
            '買進類型': temp_buy['Type'],
            '買進價格': temp_buy['Price'],
            '賣出日期': '---',
            '賣出價格': None,
            '損益點數': None,
            '報酬率(%)': None,
            'is_active': True
        }
    else:
        current_status = {
            '狀態': '⏳ 等待時機',
            '買進日期': '---',
            '買進類型': '---',
            '買進價格': None,
            '賣出日期': '---',
            '賣出價格': None,
            '損益點數': None,
            '報酬率(%)': None,
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
    
    def color_type(val):
        if "優先 1" in str(val):
            return 'color: purple; font-weight: bold;'
        elif "優先 2" in str(val):
            return 'color: green;'
        return ''

    styler = df.style.apply(highlight_status_row, axis=1)
    styler = styler.map(color_profit, subset=['損益點數', '報酬率(%)'])
    styler = styler.map(color_type, subset=['買進類型'])
    
    styler = styler.format({
        '買進價格': '{:.2f}',
        '賣出價格': '{:.2f}',
        '損益點數': '{:+.2f}',
        '報酬率(%)': '{:+.2f}%'
    }, na_rep="---")
    return styler

# --- 主程式 ---
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
                    st.subheader("📋 交易績效總覽 (盤中觸價買入)")
                    styled_table = style_dataframe(df_display).hide(axis='index').hide(subset=['is_active'], axis="columns")
                    st.dataframe(
                        styled_table, 
                        use_container_width=True, 
                        height=600
                    )

                with col_chart:
                    st.subheader("📈 策略走勢圖")
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='收盤價', line=dict(color='#2962FF', width=1)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_D'], mode='lines', name='日K200', line=dict(color='#FF6D00', width=1)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_W'], mode='lines', name='週K200', line=dict(color='#D50000', width=2, dash='dash')))
                    
                    buys_b = df[df['Action'] == 'Buy_B'] 
                    buys_a = df[df['Action'] == 'Buy_A'] 
                    sells = df[df['Action'] == 'Sell']
                    
                    fig.add_trace(go.Scatter(x=buys_b.index, y=buys_b['Low'], mode='markers', name='👑 優先1:週線觸價', marker=dict(color='purple', size=15, symbol='star')))
                    fig.add_trace(go.Scatter(x=buys_a.index, y=buys_a['Close'], mode='markers', name='🟢 優先2:日線順勢', marker=dict(color='green', size=10, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sells.index, y=sells['Close'], mode='markers', name='賣出', marker=dict(color='red', size=10, symbol='triangle-down')))
                    
                    fig.update_layout(height=600, margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1, x=0))
                    fig.update_xaxes(range=['2016-01-01', last_dt])
                    st.plotly_chart(fig, use_container_width=True)

            else:
                st.error("Yahoo Finance 暫時無回應，請稍後再試。")
    except Exception as e:
        st.error(f"發生錯誤: {e}")
