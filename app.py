import streamlit as st
import pandas as pd
import numpy as np

# --- 核心策略：股泰流 SOP 嚴格篩選器 (已移除掛單/無賣單檢查) ---
class GuTaiSOPAnalyzer:
    def __init__(self):
        pass

    def analyze(self, df):
        # 1. 欄位對應與資料清洗
        target_map = {
            '權證名稱': ['權證名稱'],
            '權證代碼': ['權證代碼'],
            '標的名稱': ['標的名稱', '標的證券'],
            '標的代碼': ['標的代碼'],
            '標的價格': ['標的價格', '標的股價', '標的收盤'],
            '買價': ['權證買價', '最佳買價', '買價'],
            '賣價': ['權證賣價', '最佳賣價', '賣價'],
            '買量': ['買進推計量', '買張', '最佳買量'],
            '賣量': ['賣出推計量', '賣張', '最佳賣量'],
            '履約價': ['履約價', '執行價'],
            '剩餘天數': ['剩餘天數', '距到期日', '天數'],
            '流通張數': ['流通在外估計張數', '流通在外張數', '最新流通在外張數', '外流張數'],
            '發行張數': ['發行量', '發行張數'],
            '隱含波動率': ['隱含波動率', 'BIV', '委買隱含波動率', '買進IV'],
            '歷史波動率': ['標的20日波動率', '歷史波動率', 'SV20', '20日波動率'],
            'Delta': ['DELTA', 'Delta', '對沖值'],
            'Gamma': ['GAMMA', 'Gamma'],
            'Theta': ['THETA', 'Theta']
        }

        df_clean = pd.DataFrame()
        
        # 鎖定欄位
        for target, keywords in target_map.items():
            best_match = None
            for kw in keywords:
                matches = [c for c in df.columns if kw in c]
                if matches:
                    best_match = matches[0]
                    break
            
            if best_match:
                df_clean[target] = df[best_match]
            else:
                if target in ['權證名稱', '權證代碼', '標的名稱']:
                    df_clean[target] = ''
                else:
                    df_clean[target] = 0

        # 轉數值
        numeric_cols = ['買價', '賣價', '買量', '賣量', '履約價', '剩餘天數', '標的價格', 
                        '流通張數', '發行張數', '隱含波動率', '歷史波動率', 'Delta', 'Gamma', 'Theta']
        
        for col in numeric_cols:
            if col in df_clean.columns:
                df_clean[col] = df_clean[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '', regex=False)
                df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0)

        # 2. 計算關鍵指標
        
        # A. 價差比 (Spread)
        df_clean['價差比'] = np.where(df_clean['買價'] > 0, 
                                     (df_clean['賣價'] - df_clean['買價']) / df_clean['買價'] * 100, 
                                     999)
        
        # B. 流通比
        df_clean['流通比'] = 0.0
        mask_issue = df_clean['發行張數'] > 0
        df_clean.loc[mask_issue, '流通比'] = (df_clean.loc[mask_issue, '流通張數'] / df_clean.loc[mask_issue, '發行張數']) * 100
        
        # C. 波動率校正
        mask_iv = df_clean['隱含波動率'] > 2
        df_clean.loc[mask_iv, '隱含波動率'] = df_clean.loc[mask_iv, '隱含波動率'] / 100
        mask_hv = df_clean['歷史波動率'] > 2
        df_clean.loc[mask_hv, '歷史波動率'] = df_clean.loc[mask_hv, '歷史波動率'] / 100

        # D. 價內外程度
        df_clean['價內外'] = (df_clean['標的價格'] - df_clean['履約價']) / df_clean['履約價']


        # 3. 股泰流 SOP 嚴格篩選邏輯
        df_clean['SOP狀態'] = '通過'
        df_clean['未通過原因'] = ''
        
        def add_fail_reason(mask, reason):
            df_clean.loc[mask, '未通過原因'] = np.where(
                df_clean.loc[mask, '未通過原因'] == '',
                reason,
                df_clean.loc[mask, '未通過原因'] + ', ' + reason
            )
            df_clean.loc[mask, 'SOP狀態'] = '剔除'

        # --- 規則 1: 剩餘天數 ---
        add_fail_reason(df_clean['剩餘天數'] < 60, '天數過短')
        
        # --- 規則 2: 價內外與 Delta ---
        has_delta = df_clean['Delta'].abs().sum() > 0
        if has_delta:
            abs_delta = df_clean['Delta'].abs()
            add_fail_reason((abs_delta < 0.35) | (abs_delta > 0.65), 'Delta不佳')
        else:
            sweet_zone = (df_clean['價內外'] >= -0.15) & (df_clean['價內外'] <= 0.05)
            add_fail_reason(~sweet_zone, '非黃金區間')

        # --- 規則 3: 流通比 ---
        add_fail_reason(df_clean['流通比'] > 80, '高流通地雷')
        
        # --- 規則 4: 價差與造市 (已移除 無賣單 & 掛單不足) ---
        # 僅保留價差比過大的檢查
        add_fail_reason(df_clean['價差比'] > 2.5, '價差過大')
        # [已移除] add_fail_reason(df_clean['賣價'] == 0, '無賣單')
        # [已移除] add_fail_reason((df_clean['買量']<5) | (df_clean['賣量']<5), '掛單不足')

        # --- 規則 5: 隱波陷阱 ---
        has_vol = (df_clean['歷史波動率'] > 0) & (df_clean['隱含波動率'] > 0)
        is_expensive = has_vol & (df_clean['隱含波動率'] > (df_clean['歷史波動率'] + 0.08)) 
        add_fail_reason(is_expensive, '隱波太貴')

        # 4. 排序
        df_clean['排序權重'] = df_clean['價差比']
        df_clean.loc[df_clean['SOP狀態'] == '剔除', '排序權重'] += 1000
        
        return df_clean.sort_values(by='排序權重'), None

# --- 檔案讀取 ---
def load_data_robust(file):
    filename = file.name.lower()
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

    # 找標題
    header_idx = -1
    for i, row in df_raw.head(20).iterrows():
        row_str = " ".join(row.astype(str).values)
        if '代碼' in row_str and '名稱' in row_str:
            header_idx = i
            break
    
    if header_idx == -1: return None, "找不到標題列"

    # 雙層標題合併
    new_columns = []
    if header_idx > 0:
        row_upper = df_raw.iloc[header_idx - 1].fillna('').astype(str)
        row_lower = df_raw.iloc[header_idx].fillna('').astype(str)
        if '標的' in row_upper.values or '權證' in row_upper.values:
            for up, low in zip(row_upper, row_lower):
                up, low = up.strip(), low.strip()
                new_columns.append(f"{up}{low}" if up and up!=low else low)
        else:
            new_columns = row_lower.tolist()
    else:
        new_columns = df_raw.iloc[header_idx].fillna('').astype(str).tolist()

    # 除重
    seen = {}
    deduped = []
    for col in new_columns:
        col = col.replace(' ', '').replace('\n', '')
        if col in seen: seen[col] += 1; deduped.append(f"{col}_{seen[col]}")
        else: seen[col] = 0; deduped.append(col)

    df = df_raw.iloc[header_idx + 1:].copy()
    df.columns = deduped
    return df, None

# --- 網頁介面 ---
st.set_page_config(page_title="股泰流權證SOP", layout="wide")

st.title("🛡️ 股泰流-權證 SOP 嚴格篩選器")
st.markdown("""
本工具依照 **「股泰流 SOP 表格」** 進行嚴格把關。
- **✅ 嚴選區**：符合 Delta 0.4~0.6、天數>60、低流通、低價差。
- **❌ 剔除區**：違反規則者直接剔除 (已放寬掛單量檢查)。
""")

uploaded_file = st.file_uploader("📂 上傳權證報表 (Excel/CSV)", type=['csv', 'xls', 'xlsx'])

if uploaded_file is not None:
    df, error = load_data_robust(uploaded_file)
    
    if error:
        st.error(error)
    else:
        # 標的選擇
        target_col = next((c for c in df.columns if '標的名稱' in c), None)
        if not target_col: target_col = next((c for c in df.columns if '標的代碼' in c), None)

        if not target_col:
            st.error("❌ 找不到標的名稱/代碼欄位")
        else:
            with st.sidebar:
                st.header("1️⃣ 標的篩選")
                df[target_col] = df[target_col].astype(str).str.strip()
                stock_list = sorted([x for x in df[target_col].unique() if x.lower() != 'nan' and x != ''])
                selected_stock = st.selectbox("搜尋標的:", stock_list)
                
                df_filtered = df[df[target_col] == selected_stock].copy()
                
                current_price = 0
                price_col = next((c for c in df_filtered.columns if '標的價格' in c), None)
                if price_col:
                    try:
                        current_price = pd.to_numeric(df_filtered[price_col], errors='coerce').iloc[0]
                        st.metric("母股價格", f"{current_price:.2f}")
                    except: pass
                
                st.markdown("---")
                st.header("💰 資金控管")
                total_capital = st.number_input("總資金 (萬)", value=100, step=10)
                st.info(f"權證建議上限 (15%)：**{total_capital * 0.15:.1f} 萬**")

            # 執行分析
            if not df_filtered.empty:
                analyzer = GuTaiSOPAnalyzer()
                result_df, err = analyzer.analyze(df_filtered)
                
                if err:
                    st.error(err)
                else:
                    cols = ['權證名稱', '未通過原因', 'Delta', '剩餘天數', '價差比', '流通比', 
                            '買價', '賣價', '隱含波動率', '歷史波動率', 'Gamma']
                    
                    fmt = {
                        'Delta': '{:.2f}', 'Gamma': '{:.3f}', 
                        '價差比': '{:.2f}%', '流通比': '{:.1f}%',
                        '隱含波動率': '{:.2f}', '歷史波動率': '{:.2f}', 
                        '買價': '{:.2f}', '賣價': '{:.2f}'
                    }

                    tab1, tab2 = st.tabs(["✅ 股泰嚴選", "❌ 剔除區"])
                    
                    with tab1:
                        good = result_df[result_df['SOP狀態'] == '通過']
                        st.markdown(f"### 符合標準：{len(good)} 檔")
                        if not good.empty:
                            clean_cols = [c for c in cols if c != '未通過原因']
                            st.dataframe(good[clean_cols].style.format(fmt))
                        else:
                            st.warning("⚠️ 無符合標準的權證 (請檢查 Delta 或 天數是否普遍不佳)")
                    
                    with tab2:
                        bad = result_df[result_df['SOP狀態'] == '剔除']
                        st.markdown(f"### 剔除：{len(bad)} 檔")
                        bad_cols = ['權證名稱', '未通過原因'] + [c for c in cols if c not in ['權證名稱', '未通過原因']]
                        
                        def highlight_fail(val):
                            return 'color: #ff4b4b; font-weight: bold;' 
                        
                        st.dataframe(bad[bad_cols].style.format(fmt).map(highlight_fail, subset=['未通過原因']))
