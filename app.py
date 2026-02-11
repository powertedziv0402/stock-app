import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# --- 頁面設定 ---
st.set_page_config(page_title="00631L 策略訊號", layout="wide")
st.title("📊 00631L 雙重濾網策略監控")

# --- 側邊欄說明 ---
st.sidebar.header("策略說明")
st.sidebar.info("""
**買進訊號 A (右側):**
連續 3 日收盤價 > 日 K 200 均線

**買進訊號 B (最高原則):**
價格觸碰或跌破 週 K 200 均線 (抄底)

**賣出訊號:**
連續 3 日收盤價 < 日 K 200 均線
""")

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    # 使用 auto_adjust=False 確保抓到原始 Close
    df = yf.download(ticker, period="10y", progress=False, auto_adjust=False)
    
    if df.empty:
        return None, None, None

    # --- 🔧 絕對修正：處理 yfinance 資料格式問題 ---
    # 如果是多層索引 (MultiIndex)，強制把欄位扁平化
    if isinstance(df.columns, pd.MultiIndex):
        # 新版 yfinance 回傳格式通常是 (Price, Ticker)，我們要取第 0 層 (Price)
        df.columns = df.columns.get_level_values(0)
    
    # 再次確認：如果有 'Adj Close' 但沒有 'Close'，就改名
    if 'Close' not in df.columns and 'Adj Close' in df.columns:
        df = df.rename(columns={'Adj Close': 'Close'})
        
    # 如果還是沒有 Close，回報錯誤
    if 'Close' not in df.columns:
        st.error(f"資料欄位異常，抓到的欄位有：{df.columns.tolist()}")
        return None, None, None

    # 確保 Low 欄位也存在
    if 'Low' not in df.columns:
        # 如果只有 Close，就暫時用 Close 代替 Low (極端狀況)
        df['Low'] = df['Close']

    # --- 計算指標 ---
    df['MA200_D'] = df['Close'].rolling(window=200).mean()
    
    # 計算週均線並映射回日線
    df_weekly = df.resample('W').agg({'Low': 'min', 'Close': 'last'})
    df_weekly['MA200_W'] = df_weekly['Close'].rolling(window=200).mean()
    df['MA200_W'] = df_weekly['MA200_W'].reindex(df.index, method='ffill')

    # --- 策略回測邏輯 ---
    df['Action'] = None # 初始化
    
    holding = False
    history = []
    
    # 為了效能，只運算最後 2000 天
    calc_len = min(2000, len(df))
    start_calc = len(df) - calc_len
    if start_calc < 250: start_calc = 250 # 確保有足夠均線資料
    
    signals = [None] * start_calc # 前面的填空
    
    for i in range(start_calc, len(df)):
        curr_idx = df.index[i]
        close = df['Close'].iloc[i]
        low = df['Low'].iloc[i]
        ma_d = df['MA200_D'].iloc[i]
        ma_w = df['MA200_W'].iloc[i]
        
        # 安全檢查：如果有 NaN 就跳過
        if pd.isna(ma_d) or pd.isna(ma_w):
            signals.append(None)
            continue

        # 判斷變數
        is_above_3days = all(df['Close'].iloc[i-2:i+1] > df['MA200_D'].iloc[i-2:i+1])
        is_touch_weekly = low <= ma_w
        is_below_3days = all(df['Close'].iloc[i-2:i+1] < df['MA200_D'].iloc[i-2:i+1])
        
        action = None
        
        if not holding:
            if is_touch_weekly:
                holding = True
                action = "Buy_B"
                history.append({'Date': curr_idx, 'Type': '買進(抄底)', 'Price': close})
            elif is_above_3days:
                holding = True
                action = "Buy_A"
                history.append({'Date': curr_idx, 'Type': '買進(順勢)', 'Price': close})
        else:
            if is_below_3days:
                holding = False
                action = "Sell"
                history.append({'Date': curr_idx, 'Type': '賣出', 'Price': close})
        
        signals.append(action)

    df['Action'] = signals
    
    return df, history, holding

# --- 執行按鈕 ---
if st.button('🔄 更新最新數據與訊號'):
    try:
        with st.spinner('正在從 Yahoo Finance 抓取資料...'):
            df, history, is_holding = get_data_and_signal()
            
            if df is not None:
                last_date = df.index[-1].strftime('%Y-%m-%d')
                last_price = df['Close'].iloc[-1]
                last_ma_d = df['MA200_D'].iloc[-1]
                last_ma_w = df['MA200_W'].iloc[-1]
                
                st.header(f"📅 日期: {last_date}")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("目前股價", f"{last_price:.2f}")
                col2.metric("日 K 200", f"{last_ma_d:.2f}")
                col3.metric("週 K 200", f"{last_ma_w:.2f}")

                status_color = "green" if is_holding else "gray"
                status_text = "目前持倉中 (HOLD)" if is_holding else "目前空手 (EMPTY)"
                st.markdown(f"### 🚩 策略狀態: :{status_color}[{status_text}]")
                
                today_action = df['Action'].iloc[-1]
                if today_action == "Buy_B":
                    st.error("🚨 觸發買進訊號 B (嚴重超跌抄底)！")
                elif today_action == "Buy_A":
                    st.success("✅ 觸發買進訊號 A (趨勢確認)！")
                elif today_action == "Sell":
                    st.warning("⚠️ 觸發賣出訊號 (跌破支撐)！")
                else:
                    st.info("🍵 今日無動作，維持現狀。")

                st.subheader("📈 走勢圖與均線")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='收盤價', line=dict(color='blue', width=1)))
                fig.add_trace(go.Scatter(x=df.index, y=df['MA200_D'], mode='lines', name='日K200均', line=dict(color='orange', width=1)))
                fig.add_trace(go.Scatter(x=df.index, y=df['MA200_W'], mode='lines', name='週K200均', line=dict(color='red', width=2, dash='dash')))
                
                # 過濾出有動作的點
                buys = df[df['Action'].str.contains('Buy', na=False)]
                sells = df[df['Action'] == 'Sell']
                
                fig.add_trace(go.Scatter(x=buys.index, y=buys['Close'], mode='markers', name='買進點', marker=dict(color='green', size=10, symbol='triangle-up')))
                fig.add_trace(go.Scatter(x=sells.index, y=sells['Close'], mode='markers', name='賣出點', marker=dict(color='red', size=10, symbol='triangle-down')))

                st.plotly_chart(fig, use_container_width=True)

                st.subheader("📝 歷史交易訊號")
                hist_df = pd.DataFrame(history)
                if not hist_df.empty:
                    st.dataframe(hist_df.iloc[::-1].style.format({"Price": "{:.2f}"}), use_container_width=True)
                else:
                    st.write("尚無交易紀錄")
    except Exception as e:
        st.error(f"程式執行發生錯誤: {e}")
