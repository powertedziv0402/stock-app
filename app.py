import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="00631L 策略戰情室", layout="wide")
st.title("📈 00631L 雙重濾網．全歷史績效戰情室")

# --- 側邊欄說明 ---
st.sidebar.header("策略邏輯 (實戰修正版)")
st.sidebar.info("""
**👑 優先級 1：週線抄底 (Buy B)**
* **基準**: 使用 **「上一週」** 結算的週 K 200 均線 (避免偷看未來)。
* **條件**: 本週任一天，盤中最低價 (Low) **碰到或跌破** 該均線。
* **動作**: **當日觸價即買進**。
* **價格**: 優先買在均線價 (若跳空開低則買開盤價)。

**🟢 優先級 2：日線順勢 (Buy A)**
* **條件**: 連續 3 日收盤 > 日 K 200 均線
* **動作**: 僅在無抄底訊號時執行。

**🔴 賣出訊號:**
* **條件**: 連續 3 日收盤 < 日 K 200 均線
""")

# --- 🔧 強化版資料抓取函數 ---
def fetch_data_robust(ticker):
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="max", auto_adjust=False)
        if not df.empty: return df
    except: pass
    
    try:
        df = yf.download(ticker, period="max", progress=False, auto_adjust=False)
        if not df.empty: return df
    except: pass
        
    return None

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    
    df = fetch_data_robust(ticker)
    
    if df is None or df.empty:
        return None, None, None

    # --- 1. 資料清洗 ---
    df.index = df.index.tz_localize(None).normalize()
    
    if isinstance(df.columns, pd.MultiIndex):
        try: df.columns = df.columns.get_level_values(0)
        except: pass
            
    if 'Close' not in df.columns and 'Adj Close' in df.columns:
        df = df.rename(columns={'Adj Close': 'Close'})
        
    for col in ['Close', 'Low', 'Open']:
        if col not in df.columns:
            if 'Close' in df.columns: df[col] = df['Close']
            else: return None, None, None

    # --- 2. 計算指標 (關鍵修正：移除未來函數) ---
    # 日 K 200
    df['MA200_D'] = df['Close'].rolling(window=200).mean()
    
    # 週 K 200 計算
    # 步驟 A: 算出每週五的 200 週均線
    weekly = df['Close'].resample('W-FRI').last()
    weekly_ma = weekly.rolling(window=200).mean()
    
    # ★★★ 關鍵修正：Shift(1) ★★★
    # 我們將週均線「往後移一格」。
    # 意義：本週(Week N) 的基準線，是來自 上一週(Week N-1) 的數值。
    # 這樣 4/8 (週二) 就會去對比 4/3 (上週五) 的均線，而不是 4/11 (本週五) 的。
    weekly_ma_shifted = weekly_ma.shift(1)
    
    # 步驟 B: 將「上週的均線」填滿到「本週的每一天」
    df['MA200_W'] = weekly_ma_shifted.reindex(df.index, method='ffill')

    # --- 3. 策略回測 ---
    df['Action'] = None 
    holding = False
    history = [] 
    
    # 寬容度 (稍微放寬一點點，避免數據誤差)
    tolerance = 1.01 
    
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
        ma_w = df['MA200_W'].iloc[i] # 這裡現在拿到的是"上週五"的數值，是已知數
        
        if i < 2: continue

        days_check = df['Close'].iloc[i-2:i+1]
        ma_check = df['MA200_D'].iloc[i-2:i+1]
        
        is_above_3days = all(days_check > ma_check)
        is_below_3days = all(days_check < ma_check)
        
        # --- 判斷觸價 ---
        # 邏輯：今天盤中最低價 <= 上週五決定的週均線
        is_touch_weekly = low <= (ma_w * tolerance)
        
        action = None
        date_str = curr_idx.strftime('%Y-%m-%d')
        
        if not holding:
            # === 優先級 1: 週線抄底 ===
            if is_touch_weekly:
                holding = True
                action = "Buy_B"
                
                # 價格模擬: 
                # 您的案例: 4/7收160, 4/8跌到142.3, 均線在152.82
                # 4/8 當天開盤可能在 158 (假設)，盤中殺到 142.3
                # 程式會在價格穿過 152.82 時成交。
                if open_p < ma_w:
                    buy_price = open_p
                    note_text = "跳空跌破 (買Open)"
                else:
                    buy_price = ma_w
                    note_text = "觸價掛單 (買MA)"

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
                        'Price': close,
                        'RawType': 'Buy',
                        'Note': "收盤確認"
                    })
        else:
            # 持倉中: 檢查賣出
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
if st.sidebar.button("🗑️ 清除快取 (數據異常請按我)"):
    st.cache_data.clear()
    st.rerun()

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
                # 這裡顯示的是「用來判斷本週是否買進」的週均線 (也就是上週的值)
                c3.metric("本週抄底價 (週 K 200)", f"{last_ma_w:.2f}")

                st.markdown("---")

                df_display = process_performance_table(history, is_holding)
                
                col_table, col_chart = st.columns([5, 4])
                
                with col_table:
                    st.subheader("📋 交易績效總覽 (實戰邏輯)")
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
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_W'], mode='lines', name='週K200 (基準)', line=dict(color='#D50000', width=2, dash='dash')))
                    
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
