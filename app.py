import streamlit as st
import pandas as pd
import numpy as np

# --- 核心邏輯 (股泰流分析器) ---
class GuTaiWarrantAnalyzer:
    def __init__(self, stock_price):
        self.stock_price = stock_price

    def analyze(self, df):
        # 1. 欄位對應與資料清洗
        # 建立標準欄位對照表
        col_map = {
            '權證買價': '買價', '權證賣價': '賣價', 
            '權證成交量': '成交量', '最新流通在外張數': '流通張數',
            '流通在外估計張數': '流通張數'
        }
        df = df.rename(columns=col_map)

        # 確保數值欄位正確
        cols_to_fix = ['買價', '賣價', '履約價', '剩餘天數']
        for col in cols_to_fix:
            if col not in df.columns:
                # 若找不到欄位，嘗試模糊比對 (例如 "買 價")
                found = False
                for c in df.columns:
                    if col in c:
                        df = df.rename(columns={c: col})
                        found = True
                        break
                if not found:
                    return None, f"缺少必要欄位: {col}"
            
            # 轉為數字，非數字變成 NaN 後補 0
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        if '流通張數' not in df.columns:
            df['流通張數'] = 0 
        else:
            df['流通張數'] = pd.to_numeric(df['流通張數'], errors='coerce').fillna(0)

        # 2. 計算邏輯
        # 價差比 (若買價為0，設為 999)
        df['spread_pct'] = np.where(df['買價'] > 0, (df['賣價'] - df['買價']) / df['買價'] * 100, 999)
        
        # 價內外程度
        df['moneyness'] = (self.stock_price - df['履約價']) / df['履約價']
        
        # 3. 評分
        df['score'] = 0
        df['tags'] = ''
        
        # A. 天數
        df.loc[df['剩餘天數'] >= 90, 'score'] += 25
        df.loc[(df['剩餘天數'] >= 60) & (df['剩餘天數'] < 90), 'score'] += 20
        df.loc[df['剩餘天數'] < 60, 'score'] -= 10
        df.loc[df['剩餘天數'] < 30, 'score'] -= 50
        df.loc[df['剩餘天數'] < 30, 'tags'] += '⚠️末日 '

        # B. 價內外 (Delta 0.4~0.6)
        target_zone = (df['moneyness'] >= -0.15) & (df['moneyness'] <= 0.05)
        df.loc[target_zone, 'score'] += 35
        df.loc[target_zone, 'tags'] += '🔥黃金區間 '
        
        df.loc[df['moneyness'] < -0.20, 'score'] -= 20
        df.loc[df['moneyness'] < -0.20, 'tags'] += '深價外 '
        df.loc[df['moneyness'] > 0.15, 'score'] -= 10
        df.loc[df['moneyness'] > 0.15, 'tags'] += '深價內 '
        
        # C. 價差
        df.loc[df['spread_pct'] <= 1.5, 'score'] += 40
        df.loc[(df['spread_pct'] > 1.5) & (df['spread_pct'] <= 2.5), 'score'] += 30
        df.loc[df['spread_pct'] > 5.0, 'score'] -= 30
        
        # D. 地雷
        df.loc[df['賣價'] == 0, 'score'] = -999
        df.loc[df['賣價'] == 0, 'tags'] += '🚫無賣單 '
        
        if '流通張數' in df.columns:
            # 假設 > 8000 張可能籌碼亂
            df.loc[df['流通張數'] > 8000, 'score'] -= 50
            df.loc[df['流通張數'] > 8000, 'tags'] += '🤯籌碼亂 '

        # 4. 狀態
        df['status'] = '觀察'
        df.loc[df['score'] >= 85, 'status'] = '✅ 股泰嚴選'
        df.loc[df['score'] <= 40, 'status'] = '❌ 剔除'
        df.loc[df['score'] < 0, 'status'] = '☠️ 危險'

        # 輸出
        out_cols = ['權證名稱', '權證代碼', '履約價', '剩餘天數', '買價', '賣價', 'spread_pct', 'tags', 'score', 'status']
        if '流通張數' in df.columns:
            out_cols.insert(7, '流通張數')
            
        # 只選存在的欄位
        final_cols = [c for c in out_cols if c in df.columns]
        return df[final_cols].sort_values(by='score', ascending=False), None

# --- 輔助: 強力讀取與標題尋找 ---
def load_data_robust(file):
    filename = file.name.lower()
    df = None
    
    # 步驟 1: 嘗試多種編碼讀取
    try:
        if filename.endswith(('.xls', '.xlsx')):
            # Excel 讀取
            # 為了處理雙行標題，先讀多一點進來分析
            df_raw = pd.read_excel(file, header=None, nrows=20)
        else:
            # CSV 讀取 (優先 utf-8, 失敗轉 big5)
            try:
                df_raw = pd.read_csv(file, header=None, nrows=20, encoding='utf-8-sig')
            except:
                file.seek(0)
                df_raw = pd.read_csv(file, header=None, nrows=20, encoding='big5')
    except Exception as e:
        return None, f"檔案讀取失敗: {e}"

    # 步驟 2: 尋找真正的 Header
    # 策略: 找含有 '權證' 且含有 '買價' 或 '賣價' 的那一列
    header_row_idx = 0
    found_header = False
    
    for i, row in df_raw.iterrows():
        row_str = " ".join(row.astype(str).values)
        if '權證' in row_str and ('買價' in row_str or '賣價' in row_str or '名稱' in row_str):
            header_row_idx = i
            found_header = True
            break
    
    # 步驟 3: 正式讀取
    file.seek(0)
    try:
        if filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(file, header=header_row_idx)
        else:
            try:
                df = pd.read_csv(file, header=header_row_idx, encoding='big5')
            except:
                file.seek(0)
                df = pd.read_csv(file, header=header_row_idx, encoding='utf-8-sig')
    except:
        return None, "無法解析檔案內容"

    # 步驟 4: 強力清洗欄位名稱
    # 移除換行符號、空白
    df.columns = df.columns.astype(str).str.replace(r'\n', '', regex=True).str.replace(' ', '')
    
    # 步驟 5: 特殊處理「權證達人」的雙胞胎欄位 (例如兩個「名稱」，第二個通常是標的)
    # 如果有欄位叫 "名稱.1" 或 "代碼.1"，這通常是 pandas 處理重複欄位的結果 -> 重新命名為標的
    rename_dict = {}
    for col in df.columns:
        if '名稱.1' in col:
            rename_dict[col] = '標的名稱'
        elif '代碼.1' in col:
            rename_dict[col] = '標的代碼'
    
    if rename_dict:
        df = df.rename(columns=rename_dict)
        
    return df, None

# --- 網頁介面 ---
st.set_page_config(page_title="股泰流權證篩選", layout="wide")
st.title("📊 股泰流-全市場權證分析工具")

uploaded_file = st.file_uploader("📂 請上傳 CSV 或 Excel (xls/xlsx) 檔案", type=['csv', 'xls', 'xlsx'])

if uploaded_file is not None:
    df, error = load_data_robust(uploaded_file)
    
    if error:
        st.error(error)
    else:
        # --- 智慧欄位偵測 ---
        # 優先順序: 1. 標的名稱 2. 標的代碼 3. 第19欄(index 18) 4. 第18欄(index 17)
        target_col = None
        
        if '標的名稱' in df.columns:
            target_col = '標的名稱'
        elif '標的代碼' in df.columns:
            target_col = '標的代碼'
        else:
            # 備用方案: 嘗試用位置判斷
            if len(df.columns) > 18:
                # 權證達人寶典通常 index 18 是標的名稱
                possible_col = df.columns[18]
                st.toast(f"提示: 未找到「標的名稱」欄位，嘗試使用第 19 欄「{possible_col}」作為篩選依據。")
                target_col = possible_col
            elif len(df.columns) > 17:
                target_col = df.columns[17]

        # 若還是找不到，顯示除錯資訊
        if target_col is None:
            st.error("❌ 找不到「標的名稱」或「標的代碼」欄位。")
            with st.expander("點擊查看讀取到的所有欄位 (Debug)"):
                st.write(list(df.columns))
                st.write("前 5 筆資料預覽:", df.head())
        else:
            # --- 側邊欄與篩選 ---
            with st.sidebar:
                st.header("1️⃣ 選擇標的")
                
                # 排除空值
                df[target_col] = df[target_col].astype(str).str.strip()
                stock_list = sorted(df[df[target_col] != 'nan'][target_col].unique().tolist())
                
                # 搜尋框
                selected_stock = st.selectbox("輸入代號或名稱搜尋:", stock_list)
                
                # 執行篩選
                df_filtered = df[df[target_col] == selected_stock].copy()
                st.success(f"已選取: {selected_stock} ({len(df_filtered)} 檔)")

                # 嘗試抓取標的價格 (如果檔案有的話)
                # 權證達人可能有 '標的價格' 或 '標的股價'
                current_price = 100.0
                price_cols = [c for c in df_filtered.columns if '標的' in c and ('價' in c or 'Price' in c)]
                if price_cols:
                    try:
                        val = df_filtered.iloc[0][price_cols[0]]
                        current_price = float(val)
                    except:
                        pass
                
                st.markdown("---")
                st.header("2️⃣ 參數設定")
                stock_price = st.number_input("母股股價", value=current_price, step=0.5)

            # --- 主畫面結果 ---
            if not df_filtered.empty:
                analyzer = GuTaiWarrantAnalyzer(stock_price)
                result_df, err = analyzer.analyze(df_filtered)
                
                if err:
                    st.error(err)
                else:
                    st.subheader(f"🏆 {selected_stock} 分析結果")
                    
                    tab1, tab2 = st.tabs(["✅ 推薦名單", "💣 地雷/觀察"])
                    
                    with tab1:
                        good = result_df[result_df['status'] == '✅ 股泰嚴選']
                        if not good.empty:
                            st.dataframe(
                                good.style.format({'spread_pct': '{:.2f}%', '買價': '{:.2f}', '賣價': '{:.2f}'})
                                .background_gradient(subset=['score'], cmap='Greens')
                            )
                        else:
                            st.warning("無符合「嚴選」標準的權證。")
                            
                    with tab2:
                        st.dataframe(result_df[result_df['status'] != '✅ 股泰嚴選'])
