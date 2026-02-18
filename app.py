import streamlit as st
import pandas as pd
import numpy as np

# --- 核心邏輯 (股泰流 - 旗艦版) ---
class GuTaiWarrantAnalyzer:
    def __init__(self):
        pass 

    def analyze(self, df):
        # 1. 欄位對應 (加入希臘字母與發行量)
        target_map = {
            '買價': ['權證買價', '最佳買價', '買價'],
            '賣價': ['權證賣價', '最佳賣價', '賣價'],
            '買量': ['買進推計量', '買張', '最佳買量'],
            '賣量': ['賣出推計量', '賣張', '最佳賣量'],
            '履約價': ['履約價', '執行價'],
            '剩餘天數': ['剩餘天數', '距到期日', '天數'],
            '標的價格': ['標的價格', '標的股價', '標的收盤'],
            '標的名稱': ['標的名稱', '標的證券'],
            '標的代碼': ['標的代碼', '標的代號'],
            '權證名稱': ['權證名稱'],
            '權證代碼': ['權證代碼'],
            '發行商': ['發行券商', '發行者', '券商'],
            
            # --- 股泰流關鍵數據 ---
            '流通張數': ['流通在外估計張數', '流通在外張數', '最新流通在外張數', '外流張數'],
            '發行張數': ['發行量', '發行張數'], # 用來算流通比
            '隱含波動率': ['隱含波動率', 'BIV', '委買隱含波動率', '買進IV'],
            '歷史波動率': ['標的20日波動率', '歷史波動率', 'SV20', '20日波動率'],
            'Delta': ['DELTA', 'Delta', '對沖值'],
            'Theta': ['THETA', 'Theta', '時間價值損失'],
            'Gamma': ['GAMMA', 'Gamma']
        }

        df_clean = pd.DataFrame()
        
        # 逐一尋找並鎖定欄位
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
                # 數值欄位補 0，文字欄位補空字串
                if target in ['標的名稱', '標的代碼', '權證名稱', '權證代碼', '發行商']:
                    df_clean[target] = ''
                else:
                    df_clean[target] = 0

        # 必要欄位檢查 (若無代碼或價格，無法分析)
        if df_clean['權證代碼'].iloc[0] == '' and df_clean['權證名稱'].iloc[0] == '':
             return None, "錯誤：無法讀取權證代碼或名稱，請確認檔案格式。"

        # 2. 數據清洗與轉型
        numeric_cols = ['買價', '賣價', '買量', '賣量', '履約價', '剩餘天數', '標的價格', 
                        '流通張數', '發行張數', '隱含波動率', '歷史波動率', 'Delta', 'Theta']
        
        for col in numeric_cols:
            if col in df_clean.columns:
                # 移除 % , 和非數字字元
                df_clean[col] = df_clean[col].astype(str).str.replace('%', '', regex=False).str.replace(',', '', regex=False)
                df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0)

        # 3. 進階計算
        # A. 價差比 (Spread)
        df_clean['spread_pct'] = np.where(df_clean['買價'] > 0, 
                                        (df_clean['賣價'] - df_clean['買價']) / df_clean['買價'] * 100, 
                                        999)
        
        # B. 流通比 (Circulation Ratio) = 流通張數 / 發行張數
        # 發行張數通常單位可能是「千股」或「張」，權證達人寶典通常是「千股」(例如 10000) 或「張」
        # 這裡假設若發行張數 < 100，可能是萬張單位，這比較少見，先直接除
        df_clean['流通比'] = np.where(df_clean['發行張數'] > 0, 
                                    (df_clean['流通張數'] / df_clean['發行張數']) * 100, 
                                    0)
        
        # C. 價內外程度 (Moneyness)
        # Call: (S-K)/K, Put: (K-S)/S (這裡簡化只算 Call 的邏輯，若要精確需判斷認購售)
        # 股泰流主要做認購 (Call)，若 Delta 為負則為 Put
        df_clean['moneyness'] = (df_clean['標的價格'] - df_clean['履約價']) / df_clean['履約價']
        
        # D. 波動率校正 (統一單位)
        # 若 HV < 1 (如 0.45) 且 IV > 1 (如 45)，將 IV 除以 100
        mask_scale = (df_clean['歷史波動率'] < 1) & (df_clean['隱含波動率'] > 1)
        df_clean.loc[mask_scale, '隱含波動率'] = df_clean.loc[mask_scale, '隱含波動率'] / 100

        # 4. 股泰流嚴格評分 (滿分 100，扣分無上限)
        df_clean['score'] = 0
        df_clean['tags'] = ''
        
        # --- 規則 1: 剩餘天數 (Time) ---
        # 股泰: > 60天是基本，> 90天更好，< 30天絕對不行
        df_clean.loc[df_clean['剩餘天數'] >= 100, 'score'] += 20
        df_clean.loc[(df_clean['剩餘天數'] >= 60) & (df_clean['剩餘天數'] < 100), 'score'] += 15
        df_clean.loc[df_clean['剩餘天數'] < 60, 'score'] -= 20
        df_clean.loc[df_clean['剩餘天數'] < 30, 'score'] -= 100 # 直接淘汰
        df_clean.loc[df_clean['剩餘天數'] < 30, 'tags'] += '⚠️末日 '

        # --- 規則 2: Delta 黃金區間 ---
        # 股泰: 0.4 ~ 0.6 最強 (價平附近)
        # 若無 Delta 數據，退而求其次用 Moneyness (-10% ~ +5%)
        has_delta = df_clean['Delta'].abs().sum() > 0 # 檢查是否有 Delta 數據
        
        if has_delta:
            # 取絕對值 (因為認售 Delta 是負的)
            abs_delta = df_clean['Delta'].abs()
            delta_sweet = (abs_delta >= 0.4) & (abs_delta <= 0.65)
            delta_ok = (abs_delta >= 0.3) & (abs_delta < 0.4)
            
            df_clean.loc[delta_sweet, 'score'] += 30
            df_clean.loc[delta_sweet, 'tags'] += '🎯黃金Delta '
            df_clean.loc[delta_ok, 'score'] += 10
            
            # Delta 太小 (<0.2) 漲不動
            df_clean.loc[abs_delta < 0.2, 'score'] -= 30
            df_clean.loc[abs_delta < 0.2, 'tags'] += '🐌漲不動 '
        else:
            # 備用方案: Moneyness
            # 價外 15% ~ 價內 5%
            zone_sweet = (df_clean['moneyness'] >= -0.15) & (df_clean['moneyness'] <= 0.05)
            df_clean.loc[zone_sweet, 'score'] += 30
            df_clean.loc[zone_sweet, 'tags'] += '🎯黃金區間 '
            df_clean.loc[df_clean['moneyness'] < -0.20, 'score'] -= 30
            df_clean.loc[df_clean['moneyness'] < -0.20, 'tags'] += '深價外 '

        # --- 規則 3: 流通比 (Chip) ---
        # 股泰: > 80% 絕對不碰 (籌碼亂/價格失真)
        # 理想: < 50%
        df_clean.loc[df_clean['流通比'] > 80, 'score'] = -999
        df_clean.loc[df_clean['流通比'] > 80, 'tags'] += '☠️高流通(地雷) '
        df_clean.loc[df_clean['流通比'] < 50, 'score'] += 10 # 籌碼安定

        # --- 規則 4: 波動率 (Volatility) ---
        # IV 不可過高於 HV (買貴了)
        # 容許 IV 比 HV 高 5% 左右 (券商利潤)，再高就是坑
        # 確保 HV 有值且大於 0
        valid_vol = (df_clean['歷史波動率'] > 0) & (df_clean['隱含波動率'] > 0)
        
        # IV - HV
        vol_diff = df_clean['隱含波動率'] - df_clean['歷史波動率']
        
        # IV 比 HV 低 (便宜)
        df_clean.loc[valid_vol & (vol_diff < 0), 'score'] += 20
        df_clean.loc[valid_vol & (vol_diff < 0), 'tags'] += '💎低估(俗) '
        
        # IV 比 HV 高出 0.1 (10%) -> 太貴
        df_clean.loc[valid_vol & (vol_diff > 0.10), 'score'] -= 30
        df_clean.loc[valid_vol & (vol_diff > 0.10), 'tags'] += '💸太貴 '

        # --- 規則 5: 價差與造市 (Liquidity) ---
        # 價差 < 2%
        df_clean.loc[df_clean['spread_pct'] <= 2.0, 'score'] += 20
        df_clean.loc[df_clean['spread_pct'] > 5.0, 'score'] -= 20
        
        # 檢查掛單量 (Size)
        # 若買量或賣量 < 10 張，扣分
        low_size = (df_clean['買量'] < 10) | (df_clean['賣量'] < 10)
        df_clean.loc[low_size, 'score'] -= 30
        df_clean.loc[low_size, 'tags'] += '💧掛單少 '
        
        # 無賣單 (券商縮手)
        df_clean.loc[df_clean['賣價'] == 0, 'score'] = -999
        df_clean.loc[df_clean['賣價'] == 0, 'tags'] += '🚫無賣單 '

        # 5. 狀態判定
        df_clean['status'] = '觀察'
        # 嚴選標準提高: 分數 > 80 且 不能是末日/高流通
        df_clean.loc[df_clean['score'] >= 80, 'status'] = '✅ 股泰嚴選'
        df_clean.loc[df_clean['score'] <= 30, 'status'] = '❌ 剔除'
        df_clean.loc[df_clean['score'] < 0, 'status'] = '☠️ 危險'

        return df_clean.sort_values(by='score', ascending=False), None

# --- 檔案讀取 (防錯 + 雙標題合併) ---
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

    # 合併雙層標題
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
st.set_page_config(page_title="股泰流權證旗艦版", layout="wide")
st.title("🔥 股泰流-權證分析工具 (旗艦版)")
st.markdown("### 核心策略：鎖定 Delta 0.4~0.6、避開高流通、抓出便宜隱波")

uploaded_file = st.file_uploader("📂 上傳權證達人寶典 (Excel/CSV)", type=['csv', 'xls', 'xlsx'])

if uploaded_file is not None:
    df, error = load_data_robust(uploaded_file)
    
    if error:
        st.error(error)
    else:
        # 標的搜尋
        target_col = next((c for c in df.columns if '標的名稱' in c), None)
        if not target_col: target_col = next((c for c in df.columns if '標的代碼' in c), None)

        if not target_col:
            st.error("❌ 找不到標的名稱/代碼欄位")
        else:
            with st.sidebar:
                st.header("1️⃣ 標的篩選")
                df[target_col] = df[target_col].astype(str).str.strip()
                stock_list = sorted([x for x in df[target_col].unique() if x.lower() != 'nan' and x != ''])
                selected_stock = st.selectbox("輸入代號或名稱:", stock_list)
                
                df_filtered = df[df[target_col] == selected_stock].copy()
                
                # 自動抓取股價
                current_price = 0
                price_col = next((c for c in df_filtered.columns if '標的價格' in c), None)
                if price_col:
                    try:
                        current_price = pd.to_numeric(df_filtered[price_col], errors='coerce').iloc[0]
                        st.metric("母股股價", f"{current_price:.2f}")
                    except: pass
                
                st.markdown("---")
                st.markdown("### 股泰流嚴格標準")
                st.info("""
                - **時間**: > 60天 (最好>90)
                - **Delta**: 0.4 ~ 0.6 (飆最快)
                - **籌碼**: 流通比 < 80% (避開地雷)
                - **價格**: IV < HV (買便宜)
                """)

            # 分析結果
            if not df_filtered.empty:
                analyzer = GuTaiWarrantAnalyzer()
                result_df, err = analyzer.analyze(df_filtered)
                
                if err:
                    st.error(err)
                else:
                    st.subheader(f"🏆 {selected_stock} - 股泰流分析報告")
                    
                    # 顯示欄位設定
                    display_cols = ['權證名稱', '權證代碼', 'Delta', '剩餘天數', '買價', '賣價', 
                                    'spread_pct', '流通比', '隱含波動率', '歷史波動率', 
                                    'tags', 'score', 'status']
                    final_cols = [c for c in display_cols if c in result_df.columns]
                    
                    # 格式化設定
                    fmt = {
                        'Delta': '{:.2f}', 'spread_pct': '{:.1f}%', '流通比': '{:.1f}%',
                        '隱含波動率': '{:.2f}', '歷史波動率': '{:.2f}', '買價': '{:.2f}', '賣價': '{:.2f}'
                    }

                    tab1, tab2, tab3 = st.tabs(["✅ 股泰嚴選 (Top Picks)", "💣 地雷/觀察區", "📊 原始數據"])
                    
                    with tab1:
                        good = result_df[result_df['status'] == '✅ 股泰嚴選']
                        st.markdown(f"**共找到 {len(good)} 檔符合嚴格標準的權證**")
                        if not good.empty:
                            st.dataframe(good[final_cols].style.format(fmt, na_rep="-"))
                        else:
                            st.warning("⚠️ 此標的目前沒有「完全符合」股泰流標準的權證。")
                            st.markdown("建議：\n1. 檢查是否 IV 普遍過高 (太貴)\n2. 檢查是否天數普遍不足\n3. 到「觀察區」找分數較高者勉強操作")

                    with tab2:
                        bad = result_df[result_df['status'] != '✅ 股泰嚴選']
                        st.dataframe(bad[final_cols].style.format(fmt, na_rep="-"))
                        
                    with tab3:
                        st.dataframe(df_filtered)
