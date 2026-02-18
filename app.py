import streamlit as st
import pandas as pd
import numpy as np

# --- 核心邏輯 (股泰流分析器) ---
class GuTaiWarrantAnalyzer:
    def __init__(self):
        pass # 不再需要初始化股價，改為動態讀取

    def analyze(self, df):
        # 1. 欄位對應與清洗
        # 將合併後的複雜欄位名稱簡化
        col_mapping = {}
        for c in df.columns:
            if '權證' in c and '買價' in c: col_mapping[c] = '買價'
            elif '權證' in c and '賣價' in c: col_mapping[c] = '賣價'
            elif '權證' in c and '履約' in c: col_mapping[c] = '履約價' # 防呆
            elif '履約價' in c: col_mapping[c] = '履約價'
            elif '剩餘' in c and '天' in c: col_mapping[c] = '剩餘天數'
            elif '標的' in c and '價格' in c: col_mapping[c] = '標的價格'
            elif '標的' in c and '名稱' in c: col_mapping[c] = '標的名稱'
            elif '標的' in c and '代碼' in c: col_mapping[c] = '標的代碼'
            elif '權證' in c and '名稱' in c: col_mapping[c] = '權證名稱'
            elif '權證' in c and '代碼' in c: col_mapping[c] = '權證代碼'
            elif '流通' in c and '張' in c: col_mapping[c] = '流通張數'
        
        df = df.rename(columns=col_mapping)

        # 檢查必要欄位
        required = ['買價', '賣價', '履約價', '剩餘天數', '標的價格']
        for r in required:
            if r not in df.columns:
                return None, f"缺少必要欄位: {r} (請確認檔案是否包含此資訊)"
            df[r] = pd.to_numeric(df[r], errors='coerce').fillna(0)
            
        if '流通張數' not in df.columns: df['流通張數'] = 0
        else: df['流通張數'] = pd.to_numeric(df['流通張數'], errors='coerce').fillna(0)

        # 2. 計算邏輯 (使用檔案中的標的價格)
        # 價差比
        df['spread_pct'] = np.where(df['買價'] > 0, (df['賣價'] - df['買價']) / df['買價'] * 100, 999)
        
        # 價內外程度 (Moneyness) = (標的價格 - 履約價) / 履約價
        # 這裡直接用每行資料自己的「標的價格」算，最準確
        df['moneyness'] = (df['標的價格'] - df['履約價']) / df['履約價']
        
        # 3. 評分系統
        df['score'] = 0
        df['tags'] = ''
        
        # A. 天數
        df.loc[df['剩餘天數'] >= 90, 'score'] += 25
        df.loc[(df['剩餘天數'] >= 60) & (df['剩餘天數'] < 90), 'score'] += 20
        df.loc[df['剩餘天數'] < 60, 'score'] -= 10
        df.loc[df['剩餘天數'] < 30, 'score'] -= 50
        df.loc[df['剩餘天數'] < 30, 'tags'] += '⚠️末日 '

        # B. 價內外 (Delta 0.4~0.6 區間)
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
        df.loc[df['流通張數'] > 8000, 'score'] -= 50
        df.loc[df['流通張數'] > 8000, 'tags'] += '🤯籌碼亂 '

        # 4. 狀態
        df['status'] = '觀察'
        df.loc[df['score'] >= 85, 'status'] = '✅ 股泰嚴選'
        df.loc[df['score'] <= 40, 'status'] = '❌ 剔除'
        df.loc[df['score'] < 0, 'status'] = '☠️ 危險'

        # 輸出欄位
        display_cols = ['權證名稱', '權證代碼', '標的價格', '履約價', '剩餘天數', '買價', '賣價', 'spread_pct', 'tags', 'score', 'status']
        if '流通張數' in df.columns: display_cols.insert(8, '流通張數')
        
        final_cols = [c for c in display_cols if c in df.columns]
        return df[final_cols].sort_values(by='score', ascending=False), None

# --- 讀取邏輯 (專門處理雙行標題) ---
def load_data_merged_header(file):
    filename = file.name.lower()
    
    # 1. 讀取原始資料 (不設 header)
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

    # 2. 尋找「標題列」的位置
    # 策略：找到含有 "代碼" 和 "名稱" 的那一行 (通常是下層標題)
    header_idx = -1
    for i, row in df_raw.head(20).iterrows():
        row_str = " ".join(row.astype(str).values)
        if '代碼' in row_str and '名稱' in row_str:
            header_idx = i
            break
    
    if header_idx == -1:
        return None, "找不到標題列 (需包含'代碼'與'名稱')"

    # 3. 處理「雙層標題」合併 (針對權證達人寶典)
    # 如果 header_idx 的上一行包含 "權證" 或 "標的"，代表是雙層標題
    new_columns = []
    
    if header_idx > 0:
        row_upper = df_raw.iloc[header_idx - 1].fillna('').astype(str) # 上層 (例如: 標的)
        row_lower = df_raw.iloc[header_idx].fillna('').astype(str)     # 下層 (例如: 名稱)
        
        is_double_header = False
        if '標的' in row_upper.values or '權證' in row_upper.values:
            is_double_header = True

        if is_double_header:
            # 合併上下兩行
            for up, low in zip(row_upper, row_lower):
                up = up.strip()
                low = low.strip()
                if up == low: # 如果上下重複
                    new_columns.append(low)
                elif up == '':
                    new_columns.append(low)
                else:
                    new_columns.append(f"{up}{low}") # 合併 (例如: 標的 + 名稱 -> 標的名稱)
        else:
            new_columns = row_lower.tolist()
    else:
        new_columns = df_raw.iloc[header_idx].fillna('').astype(str).tolist()

    # 4. 重建 DataFrame
    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = new_columns
    
    # 清洗欄位名稱 (移除空白)
    df.columns = df.columns.str.replace(' ', '').str.replace('\n', '')
    
    return df, None

# --- 網頁介面 ---
st.set_page_config(page_title="股泰流權證篩選", layout="wide")
st.title("📊 股泰流-全市場權證分析工具 (自動判讀版)")
st.caption("支援 CSV/XLS，自動合併雙層標題，自動讀取母股價格")

uploaded_file = st.file_uploader("📂 上傳檔案", type=['csv', 'xls', 'xlsx'])

if uploaded_file is not None:
    df, error = load_data_merged_header(uploaded_file)
    
    if error:
        st.error(error)
    else:
        # --- 尋找標的名稱欄位 ---
        target_col = None
        # 優先找 "標的名稱"
        if '標的名稱' in df.columns: target_col = '標的名稱'
        elif '標的代碼' in df.columns: target_col = '標的代碼'
        
        if target_col is None:
            st.error("❌ 找不到「標的名稱」欄位。以下是偵測到的欄位，請檢查檔案：")
            st.write(list(df.columns))
        else:
            # --- 側邊欄 ---
            with st.sidebar:
                st.header("1️⃣ 選擇標的")
                
                # 清洗資料: 移除標的名稱的空白
                df[target_col] = df[target_col].astype(str).str.strip()
                # 排除 nan
                stock_list = sorted([x for x in df[target_col].unique() if x.lower() != 'nan' and x != ''])
                
                selected_stock = st.selectbox("輸入代號或名稱搜尋:", stock_list)
                
                # 篩選資料
                df_filtered = df[df[target_col] == selected_stock].copy()
                
                st.success(f"已選取: {selected_stock}")
                st.info(f"權證數量: {len(df_filtered)} 檔")

                # 自動抓取價格顯示給使用者看 (不做修改)
                current_price = 0
                if '標的價格' in df_filtered.columns:
                    try:
                        current_price = pd.to_numeric(df_filtered['標的價格']).mean()
                        st.metric("目前標的價格 (自動讀取)", f"{current_price:.2f}")
                    except:
                        st.warning("無法讀取標的價格")
                
                st.markdown("---")
                st.caption("篩選標準：>60天 / 價外15%~價內5% / 低價差")

            # --- 主畫面 ---
            if not df_filtered.empty:
                analyzer = GuTaiWarrantAnalyzer() # 不需傳入價格
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
                                good.style.format({'spread_pct': '{:.2f}%', '買價': '{:.2f}', '賣價': '{:.2f}', '標的價格': '{:.2f}'})
                                .background_gradient(subset=['score'], cmap='Greens')
                            )
                        else:
                            st.warning("無符合「嚴選」標準的權證。")
                            
                    with tab2:
                        st.dataframe(result_df[result_df['status'] != '✅ 股泰嚴選'].style.format({'spread_pct': '{:.2f}%', '標的價格': '{:.2f}'}))
                        
                    with tab3:
                        st.dataframe(df_filtered)
            else:
                st.warning("篩選後無資料，請確認檔案內容。")
