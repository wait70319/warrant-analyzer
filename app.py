import streamlit as st
import pandas as pd
import numpy as np
import io

# --- 核心策略：權證 SOP 雙模式分析器 ---
class GuTaiSOPAnalyzer:
    def __init__(self):
        pass

    def analyze(self, df, mode="目前 (嚴格實戰)"):
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
        
        # C. 單位校正 (統一單位為百分比)
        for col in ['隱含波動率', '歷史波動率', '溢價率']:
            mask_small = (df_clean[col] > -2) & (df_clean[col] < 2) & (df_clean[col] != 0)
            df_clean.loc[mask_small, col] = df_clean.loc[mask_small, col] * 100

        # D. 價內外程度
        df_clean['價內外'] = (df_clean['標的價格'] - df_clean['履約價']) / df_clean['履約價']


        # 3. SOP 嚴格篩選系統
        df_clean['SOP狀態'] = '通過'
        df_clean['未通過原因'] = ''
        
        def add_fail_reason(mask, reason):
            df_clean.loc[mask, '未通過原因'] = np.where(
                df_clean.loc[mask, '未通過原因'] == '',
                reason,
                df_clean.loc[mask, '未通過原因'] + ', ' + reason
            )
            df_clean.loc[mask, 'SOP狀態'] = '剔除'

        # --- 全域防雷底線 (不論哪種模式都必須遵守) ---
        add_fail_reason(df_clean['流通比'] > 80, '高流通地雷')
        add_fail_reason(df_clean['價差比'] > 2.5, '買賣價差過大')
        
        # 隱波檢查 (抓出莊家賣太貴的商品)
        has_vol = (df_clean['歷史波動率'] > 0) & (df_clean['隱含波動率'] > 0)
        is_expensive = has_vol & (df_clean['隱含波動率'] > (df_clean['歷史波動率'] + 8))
        add_fail_reason(is_expensive, '隱波太貴(降波風險)')


        # --- 模式分流 ---
        if mode == "目前 (嚴格實戰)":
            # === 🟢 目前模式：結合實質槓桿與券商防坑的 5 大濾網 ===
            
            # 1. 充足交易量 (確保能安全下車)
            add_fail_reason(df_clean['成交量'] < 500, '成交量不足(<500)')
            
            # 2. 合理的溢價率 (抓出甜蜜點，避開太貴的合約)
            add_fail_reason((df_clean['溢價率'] < 5) | (df_clean['溢價率'] > 15), '溢價率非甜蜜點(5~15%)')
            
            # 3. 剩餘天數 (抵禦時間價值流失)
            add_fail_reason(df_clean['剩餘天數'] < 60, '天數過短(<60天)')
            
            # 4. 合適的實質槓桿 (確保爆發力)
            add_fail_reason(df_clean['有效槓桿'] < 3.0, '實質槓桿過小(<3倍)')
            
            # 5. 券商優選 (避開不積極造市的莊家)
            target_issuers = ['元大', '凱基', '富邦', '統一', '群益']
            pattern = '|'.join(target_issuers)
            is_target_issuer = df_clean['發行商'].astype(str).str.contains(pattern, na=False)
            add_fail_reason(~is_target_issuer, '非大型優選券商')
            
        else:
            # === 🟡 原始模式：基礎 SOP ===
            # 只做最基本的安全防護，保留較多商品
            add_fail_reason(df_clean['剩餘天數'] < 30, '天數過短(<30天)')
            
            # 價內外/Delta 檢查
            has_delta = df_clean['Delta'].abs().sum() > 0
            if has_delta:
                abs_delta = df_clean['Delta'].abs()
                add_fail_reason((abs_delta < 0.35) | (abs_delta > 0.65), 'Delta不佳')
            else:
                sweet_zone = (df_clean['價內外'] >= -0.15) & (df_clean['價內外'] <= 0.05)
                add_fail_reason(~sweet_zone, '非黃金區間')


        # 4. 排序與最佳化
        df_clean['排序權重'] = df_clean['價差比']
        df_clean.loc[df_clean['SOP狀態'] == '剔除', '排序權重'] += 1000
        
        if mode == "目前 (嚴格實戰)":
            # 建立券商優先權分數: 元大/凱基(1) > 富邦/統一(2) > 群益(3) > 其他(9)
            conditions = [
                df_clean['發行商'].astype(str).str.contains('元大|凱基'),
                df_clean['發行商'].astype(str).str.contains('富邦|統一'),
                df_clean['發行商'].astype(str).str.contains('群益')
            ]
            choices = [1, 2, 3]
            df_clean['券商排序'] = np.select(conditions, choices, default=9)
            
            # 排序：狀態(通過在前) -> 券商優先 -> 價差小
            result_df = df_clean.sort_values(by=['SOP狀態', '券商排序', '價差比'], ascending=[False, True, True])
        else:
            result_df = df_clean.sort_values(by='排序權重')

        return result_df, None

# --- 檔案讀取 (維持原樣) ---
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

    header_idx = -1
    for i, row in df_raw.head(20).iterrows():
        row_str = " ".join(row.astype(str).values)
        if '代碼' in row_str and '名稱' in row_str:
            header_idx = i
            break
    
    if header_idx == -1: return None, "找不到標題列"

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

# --- 網頁介面 UI ---
st.set_page_config(page_title="實戰權證自動篩選器", layout="wide")

st.title("🛡️ 實戰權證自動篩選器")
st.markdown("將市場報價表上傳，系統將自動剔除高風險地雷，為您找出最具爆發力的優質權證。")

uploaded_file = st.file_uploader("📂 上傳權證報表 (Excel/CSV)", type=['csv', 'xls', 'xlsx'])

if uploaded_file is not None:
    df, error = load_data_robust(uploaded_file)
    
    if error:
        st.error(error)
    else:
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
                st.header("🚦 策略模式設定")
                
                # 切換兩種模式
                filter_mode = st.radio(
                    "選擇篩選強度：",
                    ["目前 (嚴格實戰)", "原始 (基礎防雷)"],
                    index=0
                )
                
                if filter_mode == "目前 (嚴格實戰)":
                    st.success("""
                    🟢 **嚴格實戰模式啟動：**
                    - 交易量 > 500 張 (確保流動性)
                    - 溢價率 5% ~ 15% (甜蜜點)
                    - 剩餘天數 > 60 天 (抵抗時間流失)
                    - 實質槓桿 > 3 倍 (確保爆發力)
                    - 鎖定優良造市商 (元大/凱基/富邦等)
                    """)
                else:
                    st.info("""
                    🟡 **原始基礎模式啟動：**
                    - 僅過濾高流通、大價差地雷
                    - 剩餘天數 > 30 天
                    - 基礎 Delta / 價內外區間檢查
                    """)

            # 執行分析
            if not df_filtered.empty:
                analyzer = GuTaiSOPAnalyzer()
                result_df, err = analyzer.analyze(df_filtered, mode=filter_mode)
                
                if err:
                    st.error(err)
                else:
                    base_cols = ['權證名稱', '發行商', '買價', '賣價', '價差比', '成交量', 
                                 '有效槓桿', '溢價率', '剩餘天數', 'Delta', '流通比', '未通過原因']
                    
                    fmt = {
                        'Delta': '{:.2f}', '價差比': '{:.2f}%', '流通比': '{:.1f}%',
                        '溢價率': '{:.2f}%', '有效槓桿': '{:.2f}',
                        '買價': '{:.2f}', '賣價': '{:.2f}', '成交量': '{:.0f}'
                    }

                    tab1, tab2 = st.tabs(["✅ 嚴選名單 (Pass)", "❌ 剔除區 (Fail)"])
                    
                    with tab1:
                        good = result_df[result_df['SOP狀態'] == '通過']
                        st.markdown(f"### 符合標準：{len(good)} 檔")
                        
                        if not good.empty:
                            excel_data = to_excel(good[base_cols[:-1]])
                            st.download_button(
                                label=f"📥 一鍵匯出 Excel ({filter_mode}名單)",
                                data=excel_data,
                                file_name=f'{selected_stock}_{filter_mode[:2]}嚴選.xlsx',
                                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                            )
                            st.dataframe(good[base_cols[:-1]].style.format(fmt))
                        else:
                            st.warning("⚠️ 查無符合標準的權證。")
                            if filter_mode == "目前 (嚴格實戰)":
                                st.info("💡 建議：嚴格模式條件較硬，您可以嘗試切換至「原始 (基礎防雷)」模式看看是否有其他選擇。")
                    
                    with tab2:
                        bad = result_df[result_df['SOP狀態'] == '剔除']
                        st.markdown(f"### 剔除：{len(bad)} 檔")
                        def highlight_fail(val): return 'color: #ff4b4b;' 
                        st.dataframe(bad[base_cols].style.format(fmt).map(highlight_fail, subset=['未通過原因']))
