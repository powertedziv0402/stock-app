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
""")

# --- 核心邏輯函數 ---
@st.cache_data(ttl=3600)
def get_data_and_signal():
    ticker = "00631L.TW"
    # 下載數據
    df = yf.download(ticker, period="10y", progress=False, auto_adjust=False)
    
    if df.empty:
        return None, None, None

    # --- 關鍵修正 1: 強制移除時區 (解決 nan 問題) ---
    df.index = df.index.tz_localize(None)

    # --- 關鍵修正 2: 處理欄位格式 ---
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    if 'Close' not in df.columns and 'Adj Close' in df.columns:
        df = df.rename(columns={'Adj Close': 'Close'})
    
    # 確保有 Low，沒有就用 Close 代替
    if 'Low' not in df.columns:
        df['Low'] = df['Close']

    # --- 計算指標 ---
    # 1. 日 K 200 均
    df['MA200_D'] = df['Close'].rolling(window=200).mean()
    
    # 2. 週 K 200 均 (修正算法)
    # 先轉成週線，算完 MA，再填回日線
    weekly = df['Close'].resample('W').last()
    weekly_ma = weekly.rolling(window=200).mean()
    # 使用 ffill 將週線數值填入該週的每一天
    df['MA200_W'] = weekly_ma.reindex(df.index, method='ffill')

    # --- 策略回測邏輯 ---
    df['Action'] = None 
    holding = False
    history = [] # 紀錄所有交易
    
    # 從有均線數據後開始算
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
        
        # 確保有前兩天資料
        if i < 2: continue

        # 訊號判斷
        # 連續 3 天 (包含今天 i, 昨天 i-1, 前天 i-2)
        days_check = df['Close'].iloc[i-2:i+1]
        ma_check = df['MA200_D'].iloc[i-2:i+1]
        
        is_above_3days = all(days_check > ma_check)
        is_below_3days = all(days_check < ma_check)
        is_touch_weekly = low <= ma_w
        
        action = None
        
        if not holding:
            # 買進優先級：抄底 > 順勢
            if is_touch_weekly:
                holding = True
                action = "Buy_B"
                history.append({
                    'Date': curr_idx.strftime('%Y-%m-%d'), 
                    'Type': '🔵 買進 (抄底)', 
                    'Price': close,
                    'Note': f'跌破週均 {ma_w:.1f}'
                })
            elif is_above_3days:
                holding = True
                action = "Buy_A"
                history.append({
                    'Date': curr_idx.strftime('%Y-%m-%d'), 
                    'Type': '🟢 買進 (順勢)', 
                    'Price': close,
                    'Note': f'站上日均 {ma_d:.1f}'
                })
        else:
            if is_below_3days:
                holding = False
                action = "Sell"
                history.append({
                    'Date': curr_idx.strftime('%Y-%m-%d'), 
                    'Type': '🔴 賣出', 
                    'Price': close,
                    'Note': f'跌破日均 {ma_d:.1f}'
                })
        
        signals[i] = action

    df['Action'] = signals
    return df, history, holding

# --- 主程式執行 ---
if st.button('🔄 點擊更新最新數據'):
    try:
        with st.spinner('正在連線 Yahoo Finance 抓取最新股價...'):
            df, history, is_holding = get_data_and_signal()
            
            if df is not None:
                # --- 1. 頂部狀態卡片 ---
                last_dt = df.index[-1].strftime('%Y-%m-%d')
                last_close = df['Close'].iloc[-1]
                last_ma_d = df['MA200_D'].iloc[-1]
                last_ma_w = df['MA200_W'].iloc[-1]
                
                st.header(f"📅 數據日期: {last_dt}")
                
                # 顯示關鍵價格
                c1, c2, c3 = st.columns(3)
                c1.metric("目前股價", f"{last_close:.2f}")
                c2.metric("日 K 200 (多空線)", f"{last_ma_d:.2f}")
                c3.metric("週 K 200 (抄底線)", f"{last_ma_w:.2f}")

                # 顯示持倉狀態與今日訊號
                st.markdown("---")
                today_act = df['Action'].iloc[-1]
                
                # 狀態判斷
                if is_holding:
                    st.markdown(f"### 🚩 目前狀態: :green[持倉中 (HOLDING)]")
                    # 尋找這筆單的買入資訊
                    last_buy = None
                    for rec in reversed(history):
                        if "買進" in rec['Type']:
                            last_buy = rec
                            break
                    if last_buy:
                         st.info(f"💰 **本輪持倉成本**: {last_buy['Date']} 以 **{last_buy['Price']:.2f}** 元買進")
                else:
                    st.markdown(f"### 🚩 目前狀態: :gray[空手觀望 (EMPTY)]")
                
                # 警示訊號
                if today_act == "Buy_B":
                    st.error("🚨 **觸發訊號**: 嚴重超跌，立即買進抄底！")
                elif today_act == "Buy_A":
                    st.success("✅ **觸發訊號**: 趨勢確認，進場買進！")
                elif today_act == "Sell":
                    st.warning("⚠️ **觸發訊號**: 趨勢反轉，獲利/停損出場！")
                else:
                    st.caption("🍵 今日無交易訊號，維持現狀。")

                # --- 2. 交易紀錄表格 (您要求的功能) ---
                st.markdown("---")
                c_chart, c_hist = st.columns([2, 1])
                
                with c_hist:
                    st.subheader("📋 最近交易紀錄")
                    if history:
                        # 只取最後 5 筆，反轉順序讓最新的在上面
                        recent_hist = history[-5:][::-1]
                        hist_df = pd.DataFrame(recent_hist)
                        # 美化表格顯示
                        st.table(hist_df[['Date', 'Type', 'Price']])
                    else:
                        st.write("尚無交易紀錄 (可能是資料長度不足以產生訊號)")

                with c_chart:
                    st.subheader("📈 策略走勢圖")
                    fig = go.Figure()
                    # 股價與均線
                    fig.add_trace(go.Scatter(x=df.index, y=df['Close'], mode='lines', name='收盤價', line=dict(color='#2962FF', width=1.5)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_D'], mode='lines', name='日K200', line=dict(color='#FF6D00', width=1)))
                    fig.add_trace(go.Scatter(x=df.index, y=df['MA200_W'], mode='lines', name='週K200', line=dict(color='#D50000', width=2, dash='dash')))
                    
                    # 買賣點標記
                    buys = df[df['Action'].str.contains('Buy', na=False)]
                    sells = df[df['Action'] == 'Sell']
                    
                    fig.add_trace(go.Scatter(x=buys.index, y=buys['Close'], mode='markers', name='買進', marker=dict(color='green', size=12, symbol='triangle-up')))
                    fig.add_trace(go.Scatter(x=sells.index, y=sells['Close'], mode='markers', name='賣出', marker=dict(color='red', size=12, symbol='triangle-down')))
                    
                    # 設定圖表版面
                    fig.update_layout(height=450, margin=dict(l=20, r=20, t=30, b=20), legend=dict(orientation="h", y=1, x=0))
                    st.plotly_chart(fig, use_container_width=True)

            else:
                st.error("無法取得數據，請稍後再試。")
    except Exception as e:
        st.error(f"發生錯誤: {e}")
