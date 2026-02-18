import streamlit as st
import pandas as pd
import numpy as np

# --- 核心策略：股泰流 SOP 嚴格篩選器 ---
class GuTaiSOPAnalyzer:
    def __init__(self):
        pass

    def analyze(self, df):
        # 1. 欄位對應與資料清洗 (保留強大的讀取能力)
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
                # 若缺欄位給預設值
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

        # ---------------------------------------------------------
        # 2. 計算關鍵指標 (對應表三：避雷指南)
        # ---------------------------------------------------------
        
        # A. 價差比 (Spread) -> 避免「價差過大」
        # 公式: (賣價 - 買價) / 買價
        df_clean['價差比'] = np.where(df_clean['買價'] > 0, 
                                     (df_clean['賣價'] - df_clean['買價']) / df_clean['買價'] * 100, 
                                     999)
        
        # B. 流通比 (Circulation) -> 避免「流通比過高」
        # 若發行張數異常小(可能單位不同)，做防呆處理
        df_clean['流通比'] = 0.0
        mask_issue = df_clean['發行張數'] > 0
        df_clean.loc[mask_issue, '流通比'] = (df_clean.loc[mask_issue, '流通張數'] / df_clean.loc[mask_issue, '發行張數']) * 100
        
        # C. 波動率校正 (統一單位為小數點，如 0.45)
        # 如果 IV > 1 (如 45)，除以 100
        mask_iv = df_clean['隱含波動率'] > 2
        df_clean.loc[mask_iv, '隱含波動率'] = df_clean.loc[mask_iv, '隱含波動率'] / 100
        mask_hv = df_clean['歷史波動率'] > 2
        df_clean.loc[mask_hv, '歷史波動率'] = df_clean.loc[mask_hv, '歷史波動率'] / 100

        # D. 價內外程度 (Moneyness)
        # 認購(Call): (股價 - 履約價) / 履約價
        df_clean['價內外'] = (df_clean['標的價格'] - df_clean['履約價']) / df_clean['履約價']


        # ---------------------------------------------------------
        # 3. 股泰流 SOP 嚴格篩選邏輯 (對應表一、表二)
        # ---------------------------------------------------------
        
        # 我們不打分了，直接給「通過」或「失敗原因」
        df_clean['SOP狀態'] = '通過'
        df_clean['未通過原因'] = ''
        
        def add_fail_reason(mask, reason):
            # 如果已經有原因了，就加逗號串接
            df_clean.loc[mask, '未通過原因'] = np.where(
                df_clean.loc[mask, '未通過原因'] == '',
                reason,
                df_clean.loc[mask, '未通過原因'] + ', ' + reason
            )
            df_clean.loc[mask, 'SOP狀態'] = '剔除'

        # --- 規則 1: 剩餘天數 (表一 Step 3) ---
        # 標準: > 60 天。 (<30天絕對不碰)
        add_fail_reason(df_clean['剩餘天數'] < 60, '天數過短')
        
        # --- 規則 2: 價內外與 Delta (表二 Key Metrics) ---
        # 標準: Delta 0.4 ~ 0.6 (最佳)，或 價外15%~價內5%
        # 優先看 Delta
        has_delta = df_clean['Delta'].abs().sum() > 0
        if has_delta:
            # 取絕對值(防認售)
            abs_delta = df_clean['Delta'].abs()
            # 放寬一點點容許值 (0.35~0.65) 以免篩太嚴，但在顯示時標註
            add_fail_reason((abs_delta < 0.35) | (abs_delta > 0.65), 'Delta不佳')
        else:
            # 沒 Delta 就看價內外
            sweet_zone = (df_clean['價內外'] >= -0.15) & (df_clean['價內外'] <= 0.05)
            add_fail_reason(~sweet_zone, '非黃金區間')

        # --- 規則 3: 流通比 (表三 避雷) ---
        # 標準: > 80% 絕對不碰 (這裡設 70% 預警)
        add_fail_reason(df_clean['流通比'] > 80, '高流通地雷')
        
        # --- 規則 4: 價差與造市 (表三 報價失靈) ---
        # 標準: 價差比 < 2.5% 且 必須有賣單
        add_fail_reason(df_clean['賣價'] == 0, '無賣單')
        add_fail_reason(df_clean['價差比'] > 2.5, '價差過大')
        add_fail_reason((df_clean['買量']<5) | (df_clean['賣量']<5), '掛單不足')

        # --- 規則 5: 隱波陷阱 (表三) ---
        # 標準: IV 不可遠大於 HV (買貴了)
        # 容許 IV <= HV + 5% (給券商賺一點)
        # 確保有數據才比
        has_vol = (df_clean['歷史波動率'] > 0) & (df_clean['隱含波動率'] > 0)
        # 判斷過貴: IV > HV + 0.05 (5%)
        is_expensive = has_vol & (df_clean['隱含波動率'] > (df_clean['歷史波動率'] + 0.08)) 
        add_fail_reason(is_expensive, '隱波太貴')

        # ---------------------------------------------------------
        # 4. 排序與分類
        # ---------------------------------------------------------
        # 排序邏輯：通過的放前面，然後依照 Spread 小 -> 大排序
        df_clean['排序權重'] = df_clean['價差比']
        # 沒通過的丟到後面
        df_clean.loc[df_clean['SOP狀態'] == '剔除', '排序權重'] += 1000
        
        return df_clean.sort_values(by='排序權重'), None

# --- 檔案讀取 (維持強大的雙標題處理) ---
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

    # 找標題列 (代碼 + 名稱)
    header_idx = -1
    for i, row in df_raw.head(20).iterrows():
        row_str = " ".join(row.astype(str).values)
        if '代碼' in row_str and '名稱' in row_str:
            header_idx = i
            break
    
    if header_idx == -1: return None, "找不到標題列"

    # 處理雙層標題
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

# --- Streamlit 網頁介面 ---
st.set_page_config(page_title="股泰流權證SOP", layout="wide")

st.title("🛡️ 股泰流-權證 SOP 嚴格篩選器")
st.markdown("""
本工具依照 **「股泰流 SOP 表格」** 進行嚴格把關。
- **✅ 嚴選區**：符合 Delta 0.4~0.6、天數>60、低流通、低價差的所有條件。
- **❌ 剔除區**：只要違反任何一項「避雷指南」，直接剔除並告知原因。
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
                
                # 顯示母股價格
                current_price = 0
                price_col = next((c for c in df_filtered.columns if '標的價格' in c), None)
                if price_col:
                    try:
                        current_price = pd.to_numeric(df_filtered[price_col], errors='coerce').iloc[0]
                        st.metric("母股價格", f"{current_price:.2f}")
                    except: pass
                
                st.markdown("---")
                st.header("💰 資金控管試算")
                total_capital = st.number_input("您的總資金 (萬)", value=100, step=10)
                warrant_allocation = total_capital * 0.15
                st.info(f"依據 SOP，權證部位建議上限：\n**{warrant_allocation:.1f} 萬** (15%)")
                st.caption("⚠️ 權證是耗材，絕不凹單，不做長期持有")

            # 執行分析
            if not df_filtered.empty:
                analyzer = GuTaiSOPAnalyzer()
                result_df, err = analyzer.analyze(df_filtered)
                
                if err:
                    st.error(err)
                else:
                    # 顯示欄位
                    cols = ['權證名稱', '未通過原因', 'Delta', '剩餘天數', '價差比', '流通比', 
                            '買價', '賣價', '隱含波動率', '歷史波動率', 'Gamma']
                    
                    # 格式
                    fmt = {
                        'Delta': '{:.2f}', 'Gamma': '{:.3f}', 
                        '價差比': '{:.2f}%', '流通比': '{:.1f}%',
                        '隱含波動率': '{:.2f}', '歷史波動率': '{:.2f}', 
                        '買價': '{:.2f}', '賣價': '{:.2f}'
                    }

                    # 分頁
                    tab1, tab2 = st.tabs(["✅ 股泰嚴選 (SOP Pass)", "❌ 剔除區 (Fail)"])
                    
                    with tab1:
                        good = result_df[result_df['SOP狀態'] == '通過']
                        st.markdown(f"### 符合標準：{len(good)} 檔")
                        if not good.empty:
                            # 針對嚴選名單，不顯示「未通過原因」欄位
                            clean_cols = [c for c in cols if c != '未通過原因']
                            st.dataframe(good[clean_cols].style.format(fmt))
                            st.success("🎉 這些權證通過了所有 SOP 檢核：\n- Delta 0.4~0.6 (黃金區間)\n- 天數 > 60天\n- 價差合理、籌碼安定")
                        else:
                            st.warning("⚠️ 此標的目前沒有權證通過「股泰流嚴格 SOP」。建議空手或換股操作。")
                    
                    with tab2:
                        bad = result_df[result_df['SOP狀態'] == '剔除']
                        st.markdown(f"### 剔除：{len(bad)} 檔")
                        # 剔除區要把「未通過原因」放在最前面
                        bad_cols = ['權證名稱', '未通過原因'] + [c for c in cols if c not in ['權證名稱', '未通過原因']]
                        
                        def highlight_fail(val):
                            return 'color: #ff4b4b; font-weight: bold;' 
                        
                        st.dataframe(bad[bad_cols].style.format(fmt).map(highlight_fail, subset=['未通過原因']))
