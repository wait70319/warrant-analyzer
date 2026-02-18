import streamlit as st
import pandas as pd
import numpy as np

# --- 核心邏輯 (股泰流分析器) ---
class GuTaiWarrantAnalyzer:
    def __init__(self, stock_price):
        self.stock_price = stock_price

    def analyze(self, df):
        # --- 1. 欄位名稱標準化 (Mapping) ---
        # 為了同時支援「券商匯出檔」與「權證達人寶典」，我們做一個對照表
        col_map = {
            # 權證達人寶典的欄位
            '權證買價': '買價', '權證賣價': '賣價', '權證成交量': '成交量',
            '流通在外估計張數': '流通張數', '最新流通在外張數': '流通張數',
            # 一般常見欄位
            '買張': '買張', '賣張': '賣張'
        }
        df = df.rename(columns=col_map)

        # 確保必要欄位存在，若無則補 0
        required_cols = ['買價', '賣價', '履約價', '剩餘天數']
        for col in required_cols:
            if col not in df.columns:
                return None, f"缺少必要欄位: {col}，請確認檔案格式。"
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # 處理流通張數 (若無此欄位則假設為安全值)
        if '流通張數' not in df.columns:
            df['流通張數'] = 0 

        # --- 2. 基礎計算 ---
        # 價差比: (賣價-買價)/買價
        # 若買價為0，設為無限大
        df['spread_pct'] = np.where(df['買價'] > 0, (df['賣價'] - df['買價']) / df['買價'] * 100, 999)
        
        # 價內外程度 (Moneyness)
        df['moneyness'] = (self.stock_price - df['履約價']) / df['履約價']
        
        # --- 3. 股泰流評分 (Score Model) ---
        df['score'] = 0
        df['tags'] = ''
        
        # A. 天數 (權重 25%)
        df.loc[df['剩餘天數'] >= 90, 'score'] += 25
        df.loc[(df['剩餘天數'] >= 60) & (df['剩餘天數'] < 90), 'score'] += 20
        df.loc[df['剩餘天數'] < 60, 'score'] -= 10
        df.loc[df['剩餘天數'] < 30, 'score'] -= 50
        df.loc[df['剩餘天數'] < 30, 'tags'] += '⚠️末日 '

        # B. 價內外區間 (權重 35%) -> 鎖定 Delta 0.4~0.6 (價外15%~價內5%)
        target_zone = (df['moneyness'] >= -0.15) & (df['moneyness'] <= 0.05)
        df.loc[target_zone, 'score'] += 35
        df.loc[target_zone, 'tags'] += '🔥黃金區間 '
        
        df.loc[df['moneyness'] < -0.20, 'score'] -= 20
        df.loc[df['moneyness'] < -0.20, 'tags'] += '深價外 '
        df.loc[df['moneyness'] > 0.15, 'score'] -= 10
        df.loc[df['moneyness'] > 0.15, 'tags'] += '深價內 '
        
        # C. 價差品質 (權重 40%)
        df.loc[df['spread_pct'] <= 1.5, 'score'] += 40
        df.loc[(df['spread_pct'] > 1.5) & (df['spread_pct'] <= 2.5), 'score'] += 30
        df.loc[df['spread_pct'] > 5.0, 'score'] -= 30
        
        # D. 地雷篩選
        # 賣價為 0 (無造市)
        df.loc[df['賣價'] == 0, 'score'] = -999
        df.loc[df['賣價'] == 0, 'tags'] += '🚫無賣單 '
        
        # 流通比過高 (籌碼亂) - 假設發行量通常是 5000 或 10000 張，若流通張數 > 4000 警示
        # 這裡用絕對張數做簡單判斷 (因為有的表沒有發行張數)
        if '流通張數' in df.columns:
            # 假設高於 8000 張在外流通，通常是散戶滿手
            df.loc[df['流通張數'] > 8000, 'score'] -= 50
            df.loc[df['流通張數'] > 8000, 'tags'] += '🤯籌碼亂 '

        # --- 4. 狀態判定 ---
        df['status'] = '觀察'
        df.loc[df['score'] >= 85, 'status'] = '✅ 股泰嚴選'
        df.loc[df['score'] <= 40, 'status'] = '❌ 剔除'
        df.loc[df['score'] < 0, 'status'] = '☠️ 危險'

        # 輸出欄位整理
        out_cols = ['權證名稱', '權證代碼', '履約價', '剩餘天數', '買價', '賣價', 'spread_pct', 'tags', 'score', 'status']
        if '流通張數' in df.columns:
            out_cols.insert(7, '流通張數')
            
        final_cols = [c for c in out_cols if c in df.columns]
        return df[final_cols].sort_values(by='score', ascending=False), None

# --- 輔助函式: 讀取並尋找 Header ---
def load_csv_smart(file):
    # 嘗試讀取前 10 行來判斷 header 在哪
    # 針對「權證達人寶典」，通常 header 在第 3 或 4 行 (index 2 or 3)
    try:
        # 先讀一點點來偵測
        preview = pd.read_csv(file, nrows=10, encoding='utf-8-sig') # 預設 utf-8
    except:
        file.seek(0)
        preview = pd.read_csv(file, nrows=10, encoding='big5') # 失敗就試 big5

    # 尋找包含 "權證代碼" 或 "權證名稱" 的那一行
    header_row = 0
    for i, row in preview.iterrows():
        row_str = str(row.values)
        if '權證名稱' in row_str or '權證代碼' in row_str:
            header_row = i + 1 # +1 因為 read_csv 的 header 參數是從 0 開始，但我們讀進來的 preview 已經把 header 當 data 了... 
            # 修正：直接用 read_csv 的 header 參數重讀
            header_row = i # 實際上 preview 的 index 就是 header 的位置 (如果是 header=None 讀入)
            # 但因為我們上面沒設 header=None，pandas 可能把第一行當 header。
            # 最保險的方法：直接重讀，指定 header
            if '日期' in str(preview.columns): # 權證達人寶典第一行通常是日期
                 header_row = i + 1
            break
            
    file.seek(0)
    try:
        df = pd.read_csv(file, header=header_row, encoding='big5') # 權證軟體多為 big5
    except:
        file.seek(0)
        df = pd.read_csv(file, header=header_row, encoding='utf-8-sig')
        
    return df

# --- 網頁介面 (Streamlit) ---
st.set_page_config(page_title="股泰流全市場權證篩選", layout="wide")
st.title("📊 股泰流-全市場權證分析工具")
st.markdown("支援單一股票 CSV 或 全市場權證 CSV (如權證達人寶典)")

# 1. 檔案上傳
uploaded_file = st.file_uploader("📂 上傳 CSV 檔", type=['csv'])

if uploaded_file is not None:
    try:
        df_raw = load_csv_smart(uploaded_file)
        
        # 2. 標的篩選邏輯
        # 檢查是否有「標的名稱」或「標的代碼」欄位
        target_col = None
        if '標的名稱' in df_raw.columns:
            target_col = '標的名稱'
        elif '標的代碼' in df_raw.columns:
            target_col = '標的代碼'
            
        selected_stock = None
        current_price_from_file = 0.0

        # 側邊欄：股票選擇器
        with st.sidebar:
            st.header("1️⃣ 選擇標的")
            if target_col:
                # 取出所有不重複的股票名稱
                stock_list = sorted(df_raw[target_col].astype(str).unique().tolist())
                # 增加一個搜尋框
                selected_stock = st.selectbox("請選擇或輸入股票 (支援搜尋)", stock_list, index=0)
                
                # 篩選資料
                df_filtered = df_raw[df_raw[target_col].astype(str) == selected_stock].copy()
                st.success(f"已選取：{selected_stock} ({len(df_filtered)} 檔權證)")
                
                # 嘗試自動抓取股價 (從檔案中)
                if '標的價格' in df_filtered.columns:
                    try:
                        price_val = df_filtered.iloc[0]['標的價格']
                        current_price_from_file = float(price_val)
                    except:
                        pass
            else:
                st.warning("檔案中找不到「標的名稱」欄位，將分析檔案中所有資料。")
                df_filtered = df_raw.copy()

            st.markdown("---")
            st.header("2️⃣ 參數設定")
            # 股價設定 (若有抓到就帶入預設值)
            stock_price = st.number_input(
                "目前母股股價", 
                value=current_price_from_file if current_price_from_file > 0 else 100.0, 
                step=0.5
            )
            
            st.markdown("---")
            st.markdown("**篩選標準：**")
            st.caption(" > 60天 / 價外15%~價內5% / 低價差")

        # 3. 執行分析
        if not df_filtered.empty:
            analyzer = GuTaiWarrantAnalyzer(stock_price)
            result_df, error = analyzer.analyze(df_filtered)
            
            if error:
                st.error(error)
            else:
                # 4. 顯示結果
                st.subheader(f"🏆 {selected_stock if selected_stock else '全體'} - 篩選結果")
                
                tab1, tab2, tab3 = st.tabs(["✅ 嚴選名單", "💣 地雷區", "📄 原始資料"])
                
                with tab1:
                    good_ones = result_df[result_df['status']=='✅ 股泰嚴選']
                    st.markdown(f"### 推薦：{len(good_ones)} 檔")
                    if not good_ones.empty:
                        st.dataframe(
                            good_ones.style.format({'spread_pct': '{:.2f}%', '買價': '{:.2f}', '賣價': '{:.2f}'})
                            .background_gradient(subset=['score'], cmap='Greens')
                        )
                    else:
                        st.info("此標的目前沒有符合「嚴選」標準的權證。")
                
                with tab2:
                    bad_ones = result_df[result_df['status'].isin(['☠️ 危險', '❌ 剔除'])]
                    st.dataframe(bad_ones.style.format({'spread_pct': '{:.2f}%'}))
                    
                with tab3:
                    st.dataframe(result_df)
        else:
            st.warning("篩選後無資料。")

    except Exception as e:
        st.error(f"檔案讀取發生錯誤: {e}")
        st.markdown("建議：請確認 CSV 檔案是否為「權證達人寶典」匯出格式，或標準券商格式。")

else:
    st.info("請從左側上傳 CSV 檔案開始分析。")
