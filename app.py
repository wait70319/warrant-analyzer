import streamlit as st
import pandas as pd
import numpy as np
import io

# --- 核心策略：股泰流 SOP + 綠燈戰法 ---
class GuTaiSOPAnalyzer:
    def __init__(self):
        pass

    def analyze(self, df, green_light_mode=False):
        # 1. 欄位對應與資料清洗
        target_map = {
            '權證名稱': ['權證名稱'],
            '權證代碼': ['權證代碼'],
            '標的名稱': ['標的名稱', '標的證券'],
            '標的代碼': ['標的代碼'],
            '標的價格': ['標的價格', '標的股價', '標的收盤'],
            '發行商': ['發行券商', '發行者', '券商'],
            '買價': ['權證買價', '最佳買價', '買價'],
            '賣價': ['權證賣價', '最佳賣價', '賣價'],
            '成交量': ['權證成交量', '成交量', '總量'],
            '履約價': ['履約價', '執行價'],
            '剩餘天數': ['剩餘天數', '距到期日', '天數'],
            '流通張數': ['流通在外估計張數', '流通在外張數', '最新流通在外張數', '外流張數'],
            '發行張數': ['發行量', '發行張數'],
            '隱含波動率': ['隱含波動率', 'BIV', '委買隱含波動率', '買進IV'],
            '歷史波動率': ['標的20日波動率', '歷史波動率', 'SV20', '20日波動率'],
            '溢價率': ['溢價比率', '溢價率'],
            '有效槓桿': ['有效槓桿', '實質槓桿', '槓桿倍數'],
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
                if target in ['權證名稱', '權證代碼', '標的名稱', '發行商']:
                    df_clean[target] = ''
                else:
                    df_clean[target] = 0

        # 轉數值 (移除 %, 符號)
        numeric_cols = ['買價', '賣價', '成交量', '履約價', '剩餘天數', '標的價格', 
                        '流通張數', '發行張數', '隱含波動率', '歷史波動率', 
                        '溢價率', '有效槓桿', 'Delta', 'Gamma', 'Theta']
        
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
        
        # C. 單位校正 (統一單位)
        # 波動率 & 溢價率：若 > 5 (例如 15)，視為 %，除以 100 變回 0.15 (如果原本就是小數點則不動)
        # 但為了顯示好看，我們統一轉成 "百分比數值" (例如 15.5)
        # 假設資料混雜：有的 0.15 有的 15.0
        # 判斷邏輯：如果中位數 < 1，很可能是小數，乘 100
        for col in ['隱含波動率', '歷史波動率', '溢價率']:
            # 簡單判斷：如果該欄位大部分值小於 2 (且大於0)，視為小數，乘 100 轉為 %
            # 這裡用個別值判斷比較保險
            mask_small = (df_clean[col] > -2) & (df_clean[col] < 2) & (df_clean[col] != 0)
            df_clean.loc[mask_small, col] = df_clean.loc[mask_small, col] * 100

        # D. 價內外程度
        df_clean['價內外'] = (df_clean['標的價格'] - df_clean['履約價']) / df_clean['履約價']


        # 3. 股泰流 SOP 嚴格篩選
        df_clean['SOP狀態'] = '通過'
        df_clean['未通過原因'] = ''
        
        def add_fail_reason(mask, reason):
            df_clean.loc[mask, '未通過原因'] = np.where(
                df_clean.loc[mask, '未通過原因'] == '',
                reason,
                df_clean.loc[mask, '未通過原因'] + ', ' + reason
            )
            df_clean.loc[mask, 'SOP狀態'] = '剔除'

        # --- 基礎 SOP (任何模式都要遵守) ---
        add_fail_reason(df_clean['剩餘天數'] < 60, '天數過短')
        add_fail_reason(df_clean['流通比'] > 80, '高流通地雷')
        add_fail_reason(df_clean['價差比'] > 2.5, '價差過大')
        
        # 隱波檢查
        has_vol = (df_clean['歷史波動率'] > 0) & (df_clean['隱含波動率'] > 0)
        is_expensive = has_vol & (df_clean['隱含波動率'] > (df_clean['歷史波動率'] + 8)) # 容許 8% 差距
        add_fail_reason(is_expensive, '隱波太貴')

        # --- 模式分流：綠燈戰法 vs 一般篩選 ---
        if green_light_mode:
            # === 🟢 綠燈戰法 (嚴格條件) ===
            
            # 1. 成交量 > 800
            add_fail_reason(df_clean['成交量'] <= 800, '成交量不足')
            
            # 2. 溢價率 8% ~ 16%
            add_fail_reason((df_clean['溢價率'] < 8) | (df_clean['溢價率'] > 16), '溢價率不符')
            
            # 3. 剩餘天數 > 100天 (覆蓋原本的 60天)
            add_fail_reason(df_clean['剩餘天數'] <= 100, '天數<100')
            
            # 4. 有效槓桿 > 3.5
            add_fail_reason(df_clean['有效槓桿'] <= 3.5, '槓桿過小')
            
            # 5. 券商優先 (元大 > 統一 > 群益 > 國泰)
            # 模糊比對
            target_issuers = ['元大', '統一', '群益', '國泰']
            # 檢查發行商是否包含上述關鍵字
            pattern = '|'.join(target_issuers)
            is_target_issuer = df_clean['發行商'].astype(str).str.contains(pattern, na=False)
            add_fail_reason(~is_target_issuer, '非優選券商')
            
            # 綠燈模式下，Delta 暫時不強制 (因為天數與溢價率已卡很死)，但可作參考
            
        else:
            # === 一般 SOP 模式 ===
            # 價內外/Delta 檢查
            has_delta = df_clean['Delta'].abs().sum() > 0
            if has_delta:
                abs_delta = df_clean['Delta'].abs()
                add_fail_reason((abs_delta < 0.35) | (abs_delta > 0.65), 'Delta不佳')
            else:
                sweet_zone = (df_clean['價內外'] >= -0.15) & (df_clean['價內外'] <= 0.05)
                add_fail_reason(~sweet_zone, '非黃金區間')

        # 4. 排序
        df_clean['排序權重'] = df_clean['價差比']
        df_clean.loc[df_clean['SOP狀態'] == '剔除', '排序權重'] += 1000
        
        # 如果是綠燈模式，通過的依據「發行商優先順序」排序
        if green_light_mode:
            # 建立優先權分數: 元大(1) > 統一(2) > 群益(3) > 國泰(3) > 其他(9)
            conditions = [
                df_clean['發行商'].astype(str).str.contains('元大'),
                df_clean['發行商'].astype(str).str.contains('統一'),
                df_clean['發行商'].astype(str).str.contains('群益'),
                df_clean['發行商'].astype(str).str.contains('國泰')
            ]
            choices = [1, 2, 3, 3]
            df_clean['券商排序'] = np.select(conditions, choices, default=9)
            
            # 排序：狀態(通過在前) -> 券商優先 -> 價差小
            return df_clean.sort_values(by=['SOP狀態', '券商排序', '價差比'], ascending=[False, True, True]), None

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

# --- Excel 匯出函式 ---
def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    processed_data = output.getvalue()
    return processed_data

# --- 網頁介面 ---
st.set_page_config(page_title="股泰流權證SOP", layout="wide")

st.title("🛡️ 股泰流-權證 SOP 嚴格篩選器")
st.markdown("""
本工具依照 **「股泰流 SOP 表格」** 進行嚴格把關。
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
                st.header("🚦 策略設定")
                green_light = st.checkbox("啟用「好權證綠燈」篩選", value=False)
                if green_light:
                    st.success("""
                    **🟢 綠燈條件啟動：**
                    - 成交量 > 800 張
                    - 溢價率 8% ~ 16%
                    - 剩餘天數 > 100 天
                    - 有效槓桿 > 3.5 倍
                    - 券商：元大 > 統一 > 群益/國泰
                    """)

            # 執行分析
            if not df_filtered.empty:
                analyzer = GuTaiSOPAnalyzer()
                result_df, err = analyzer.analyze(df_filtered, green_light_mode=green_light)
                
                if err:
                    st.error(err)
                else:
                    # 顯示欄位
                    base_cols = ['權證名稱', '發行商', '買價', '賣價', '價差比', '成交量', 
                                 '有效槓桿', '溢價率', '剩餘天數', 'Delta', '流通比', '未通過原因']
                    
                    # 格式
                    fmt = {
                        'Delta': '{:.2f}', '價差比': '{:.2f}%', '流通比': '{:.1f}%',
                        '溢價率': '{:.2f}%', '有效槓桿': '{:.2f}',
                        '買價': '{:.2f}', '賣價': '{:.2f}', '成交量': '{:.0f}'
                    }

                    # 結果分頁
                    tab1, tab2 = st.tabs(["✅ 嚴選名單 (Pass)", "❌ 剔除區 (Fail)"])
                    
                    with tab1:
                        good = result_df[result_df['SOP狀態'] == '通過']
                        st.markdown(f"### 符合標準：{len(good)} 檔")
                        
                        # 下載按鈕 (放在結果上方)
                        if not good.empty:
                            excel_data = to_excel(good[base_cols[:-1]]) # 匯出時不包含「未通過原因」
                            st.download_button(
                                label="📥 一鍵匯出 Excel (嚴選名單)",
                                data=excel_data,
                                file_name=f'{selected_stock}_股泰嚴選.xlsx',
                                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            )
                            
                            st.dataframe(good[base_cols[:-1]].style.format(fmt))
                        else:
                            st.warning("⚠️ 無符合標準的權證。")
                            if green_light:
                                st.info("建議：綠燈條件較嚴格，可嘗試關閉綠燈模式，查看符合基礎 SOP 的權證。")
                    
                    with tab2:
                        bad = result_df[result_df['SOP狀態'] == '剔除']
                        st.markdown(f"### 剔除：{len(bad)} 檔")
                        def highlight_fail(val): return 'color: #ff4b4b;' 
                        st.dataframe(bad[base_cols].style.format(fmt).map(highlight_fail, subset=['未通過原因']))
