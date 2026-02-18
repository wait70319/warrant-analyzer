import streamlit as st
import pandas as pd
import numpy as np

# --- 核心邏輯 (股泰流分析器 - 唯一欄位版) ---
class GuTaiWarrantAnalyzer:
    def __init__(self):
        pass 

    def analyze(self, df):
        # 1. 精準鎖定欄位 (避免 rename 造成重複)
        # 定義我們要找的目標欄位，以及它們可能出現的關鍵字 (優先順序由左至右)
        target_map = {
            '買價': ['權證買價', '最佳買價', '買價'],
            '賣價': ['權證賣價', '最佳賣價', '賣價'],
            '履約價': ['履約價', '執行價', '標的履約價'],
            '剩餘天數': ['剩餘天數', '距到期日', '天數'],
            '標的價格': ['標的價格', '標的股價', '標的收盤'],
            '標的名稱': ['標的名稱', '標的證券'],
            '標的代碼': ['標的代碼', '標的代號'],
            '權證名稱': ['權證名稱'],
            '權證代碼': ['權證代碼'],
            '流通張數': ['流通在外張數', '流通張數', '外流張數', '最新流通在外張數']
        }

        df_clean = pd.DataFrame()
        
        # 逐一尋找最佳對應欄位
        found_cols = []
        for target, keywords in target_map.items():
            best_match = None
            # 策略：遍歷關鍵字，一旦找到對應欄位就鎖定，不再找下一個
            for kw in keywords:
                # 模糊比對：找 df 欄位中包含關鍵字的 (且未被使用過的)
                matches = [c for c in df.columns if kw in c]
                if matches:
                    # 優先選字數最短的 (通常最精確)，或者選第一個
                    best_match = matches[0]
                    break
            
            if best_match:
                df_clean[target] = df[best_match] # 複製數據
            else:
                # 若找不到非必要欄位，給預設值
                if target == '流通張數':
                    df_clean[target] = 0
                else:
                    # 找不到關鍵欄位，直接報錯
                    # 特例：若有標的名稱但無代碼，或反之，可容忍
                    if target not in ['標的代碼', '權證代碼']:
                         return None, f"找不到欄位：{target} (請檢查檔案標題)"

        # 2. 數據轉型與清洗
        numeric_cols = ['買價', '賣價', '履約價', '剩餘天數', '標的價格', '流通張數']
        for col in numeric_cols:
            if col in df_clean.columns:
                # 這裡使用 astype(str) 確保 clean，再轉 numeric
                df_clean[col] = pd.to_numeric(
                    df_clean[col].astype(str).str.replace(',', '', regex=False), 
                    errors='coerce'
                ).fillna(0)

        # 3. 計算邏輯
        # 價差比 (買價 > 0 才算，否則給 999)
        df_clean['spread_pct'] = np.where(df_clean['買價'] > 0, 
                                        (df_clean['賣價'] - df_clean['買價']) / df_clean['買價'] * 100, 
                                        999)
        
        # 價內外程度
        # 防呆：履約價不能為 0
        df_clean['moneyness'] = np.where(df_clean['履約價'] > 0,
                                       (df_clean['標的價格'] - df_clean['履約價']) / df_clean['履約價'],
                                       -0.99)

        # 4. 評分系統
        df_clean['score'] = 0
        df_clean['tags'] = ''
        
        # A. 天數
        df_clean.loc[df_clean['剩餘天數'] >= 90, 'score'] += 25
        df_clean.loc[(df_clean['剩餘天數'] >= 60) & (df_clean['剩餘天數'] < 90), 'score'] += 20
        df_clean.loc[df_clean['剩餘天數'] < 60, 'score'] -= 10
        df_clean.loc[df_clean['剩餘天數'] < 30, 'score'] -= 50
        df_clean.loc[df_clean['剩餘天數'] < 30, 'tags'] += '⚠️末日 '

        # B. 價內外 (Delta 0.4~0.6)
        target_zone = (df_clean['moneyness'] >= -0.15) & (df_clean['moneyness'] <= 0.05)
        df_clean.loc[target_zone, 'score'] += 35
        df_clean.loc[target_zone, 'tags'] += '🔥黃金區間 '
        
        df_clean.loc[df_clean['moneyness'] < -0.20, 'score'] -= 20
        df_clean.loc[df_clean['moneyness'] < -0.20, 'tags'] += '深價外 '
        df_clean.loc[df_clean['moneyness'] > 0.15, 'score'] -= 10
        df_clean.loc[df_clean['moneyness'] > 0.15, 'tags'] += '深價內 '
        
        # C. 價差
        df_clean.loc[df_clean['spread_pct'] <= 1.5, 'score'] += 40
        df_clean.loc[(df_clean['spread_pct'] > 1.5) & (df_clean['spread_pct'] <= 2.5), 'score'] += 30
        df_clean.loc[df_clean['spread_pct'] > 5.0, 'score'] -= 30
        
        # D. 地雷
        df_clean.loc[df_clean['賣價'] == 0, 'score'] = -999
        df_clean.loc[df_clean['賣價'] == 0, 'tags'] += '🚫無賣單 '
        
        # 流通張數檢測 (若有抓到值)
        df_clean.loc[df_clean['流通張數'] > 8000, 'score'] -= 50
        df_clean.loc[df_clean['流通張數'] > 8000, 'tags'] += '🤯籌碼亂 '

        # 5. 狀態判定
        df_clean['status'] = '觀察'
        df_clean.loc[df_clean['score'] >= 85, 'status'] = '✅ 股泰嚴選'
        df_clean.loc[df_clean['score'] <= 40, 'status'] = '❌ 剔除'
        df_clean.loc[df_clean['score'] < 0, 'status'] = '☠️ 危險'

        return df_clean.sort_values(by='score', ascending=False), None

# --- 檔案讀取 (解決雙層標題 + 欄位重複) ---
def load_data_robust(file):
    filename = file.name.lower()
    
    # 1. 讀取原始資料 (Header=None 先全讀進來)
    try:
        if filename.endswith(('.xls', '.xlsx')):
            df_raw = pd.read_excel(file, header=None)
        else:
            try:
                df_raw = pd.read_csv(file, header=None, encoding='utf-8-sig')
            except:
                file.seek(0)
                df_raw = pd.read_csv(file, header=None, encoding='big5')
    except Exception as e:
        return None, f"檔案讀取失敗: {e}"

    # 2. 尋找「標題列」
    # 策略：找含有 '代碼' 和 '名稱' 的那一行 (通常是下層標題)
    header_idx = -1
    for i, row in df_raw.head(20).iterrows():
        row_str = " ".join(row.astype(str).values)
        if '代碼' in row_str and '名稱' in row_str:
            header_idx = i
            break
    
    if header_idx == -1:
        return None, "找不到標題列 (需包含'代碼'與'名稱')"

    # 3. 處理「雙層標題」合併 (關鍵步驟)
    new_columns = []
    if header_idx > 0:
        row_upper = df_raw.iloc[header_idx - 1].fillna('').astype(str) # 上層
        row_lower = df_raw.iloc[header_idx].fillna('').astype(str)     # 下層
        
        is_double_header = False
        if '標的' in row_upper.values or '權證' in row_upper.values:
            is_double_header = True

        if is_double_header:
            for up, low in zip(row_upper, row_lower):
                up = up.strip()
                low = low.strip()
                # 簡單的合併邏輯
                if up and up != low:
                    col_name = f"{up}{low}"
                else:
                    col_name = low
                new_columns.append(col_name)
        else:
            new_columns = row_lower.tolist()
    else:
        new_columns = df_raw.iloc[header_idx].fillna('').astype(str).tolist()

    # 4. 欄位除重 (Deduplicate)
    # 如果有兩個欄位都叫 "買價"，Pandas 會報錯，所以我們要改名
    seen = {}
    deduped_columns = []
    for col in new_columns:
        # 清除空白
        col = col.replace(' ', '').replace('\n', '')
        if col in seen:
            seen[col] += 1
            deduped_columns.append(f"{col}_{seen[col]}") # 變成 買價_1
        else:
            seen[col] = 0
            deduped_columns.append(col)

    # 5. 重建 DataFrame
    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = deduped_columns
    
    return df, None

# --- 網頁介面 ---
st.set_page_config(page_title="股泰流權證篩選", layout="wide")
st.title("📊 股泰流-全市場權證分析工具 (防錯版)")

uploaded_file = st.file_uploader("📂 上傳檔案", type=['csv', 'xls', 'xlsx'])

if uploaded_file is not None:
    df, error = load_data_robust(uploaded_file)
    
    if error:
        st.error(error)
    else:
        # --- 尋找標的名稱 ---
        # 優先找 "標的名稱"
        target_col = None
        for c in df.columns:
            if '標的名稱' in c:
                target_col = c
                break
        
        if target_col is None:
            # 備用：找 '標的代碼'
            for c in df.columns:
                if '標的代碼' in c:
                    target_col = c
                    break

        if target_col is None:
            st.error("❌ 找不到「標的名稱」欄位。")
            with st.expander("查看所有欄位名稱"):
                st.write(list(df.columns))
        else:
            # --- 側邊欄 ---
            with st.sidebar:
                st.header("1️⃣ 選擇標的")
                
                # 清洗與排序
                df[target_col] = df[target_col].astype(str).str.strip()
                stock_list = sorted([x for x in df[target_col].unique() if x.lower() != 'nan' and x != ''])
                
                selected_stock = st.selectbox("搜尋標的:", stock_list)
                
                # 篩選資料
                df_filtered = df[df[target_col] == selected_stock].copy()
                
                st.success(f"已選取: {selected_stock}")
                st.info(f"權證數量: {len(df_filtered)} 檔")

                # 自動抓取價格
                current_price = 0
                price_col = None
                for c in df_filtered.columns:
                    if '標的價格' in c or '標的股價' in c:
                        price_col = c
                        break
                
                if price_col:
                    try:
                        # 取第一筆有效的價格
                        price_val = pd.to_numeric(df_filtered[price_col], errors='coerce').dropna().iloc[0]
                        st.metric("目前標的價格", f"{price_val:.2f}")
                    except:
                        st.warning("無法讀取標的價格")
                
                st.markdown("---")
                st.caption("股泰流標準：>60天 / 價外15%~價內5% / 低價差")

            # --- 主畫面 ---
            if not df_filtered.empty:
                analyzer = GuTaiWarrantAnalyzer()
                result_df, err = analyzer.analyze(df_filtered)
                
                if err:
                    st.error(err)
                else:
                    st.subheader(f"🏆 {selected_stock} 分析結果")
                    
                    tab1, tab2, tab3 = st.tabs(["✅ 推薦名單", "💣 地雷/觀察", "📄 原始資料"])
                    
                    with tab1:
                        good = result_df[result_df['status'] == '✅ 股泰嚴選']
                        if not good.empty:
                            st.dataframe(
                                good.style.format({
                                    'spread_pct': '{:.2f}%', 
                                    '買價': '{:.2f}', 
                                    '賣價': '{:.2f}', 
                                    '標的價格': '{:.2f}'
                                }, na_rep="-")
                                .background_gradient(subset=['score'], cmap='Greens')
                            )
                        else:
                            st.warning("無符合「嚴選」標準的權證。")
                            
                    with tab2:
                        st.dataframe(result_df[result_df['status'] != '✅ 股泰嚴選'].style.format({'spread_pct': '{:.2f}%'}))
                        
                    with tab3:
                        st.dataframe(df_filtered)
            else:
                st.warning("篩選後無資料。")
