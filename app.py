import streamlit as st
import pandas as pd
import numpy as np

# --- 核心邏輯 (股泰流) ---
class GuTaiWarrantAnalyzer:
    def __init__(self, stock_price):
        self.stock_price = stock_price

    def analyze(self, df):
        # 欄位名稱對應 (假設券商匯出的 CSV 欄位名稱可能不同，這裡做個簡單防呆)
        # 實際使用時，請確保 CSV 有：代號, 名稱, 履約價, 買價, 賣價, 剩餘天數, 流通比(選填)
        
        # 1. 基礎計算
        try:
            df['spread_pct'] = (df['賣價'] - df['買價']) / df['買價'] * 100
            df['moneyness'] = (self.stock_price - df['履約價']) / df['履約價']
        except KeyError as e:
            return None, f"欄位錯誤：您的 CSV 缺少 {e} 欄位"

        # 2. 評分
        df['score'] = 0
        df['tags'] = ''
        
        # A. 天數
        df.loc[df['剩餘天數'] >= 90, 'score'] += 25
        df.loc[(df['剩餘天數'] >= 60) & (df['剩餘天數'] < 90), 'score'] += 20
        df.loc[df['剩餘天數'] < 60, 'score'] -= 10
        df.loc[df['剩餘天數'] < 30, 'score'] -= 50
        df.loc[df['剩餘天數'] < 30, 'tags'] += '⚠️末日 '

        # B. 價內外 (Delta 區間)
        target_zone = (df['moneyness'] >= -0.15) & (df['moneyness'] <= 0.05)
        df.loc[target_zone, 'score'] += 35
        df.loc[target_zone, 'tags'] += '🔥黃金區間 '
        df.loc[df['moneyness'] < -0.15, 'score'] -= 10
        df.loc[df['moneyness'] < -0.20, 'tags'] += '深價外 '
        
        # C. 價差
        df.loc[df['spread_pct'] <= 1.0, 'score'] += 40
        df.loc[(df['spread_pct'] > 1.0) & (df['spread_pct'] <= 2.0), 'score'] += 30
        df.loc[df['spread_pct'] > 5.0, 'score'] -= 20
        
        # D. 流通比 (若有)
        if '流通比' in df.columns:
            df.loc[df['流通比'] > 80, 'score'] = -999
            df.loc[df['流通比'] > 80, 'tags'] += '☠️高流通 '

        # 3. 狀態判定
        df['status'] = '觀察'
        df.loc[df['score'] >= 85, 'status'] = '✅ 股泰嚴選'
        df.loc[df['score'] <= 40, 'status'] = '❌ 剔除'
        df.loc[df['score'] < 0, 'status'] = '☠️ 危險'

        # 整理顯示欄位
        display_cols = ['代號', '名稱', '履約價', '剩餘天數', '買價', '賣價', 'spread_pct', 'tags', 'score', 'status']
        if '流通比' in df.columns:
            display_cols.insert(4, '流通比')
            
        return df[display_cols].sort_values(by='score', ascending=False), None

# --- 網頁介面 (Streamlit) ---
st.set_page_config(page_title="股泰流權證篩選器", layout="wide")

st.title("📊 股泰流-個股權證分析工具")
st.markdown("""
**使用說明：**
1. 從券商軟體匯出權證 CSV (需包含：代號, 名稱, 履約價, 買價, 賣價, 剩餘天數)。
2. 輸入目前母股股價。
3. 上傳檔案，系統自動評分。
""")

# 側邊欄輸入
with st.sidebar:
    st.header("參數設定")
    stock_price = st.number_input("目前母股股價 (如南亞科輸入 278)", value=278.0, step=0.5)
    st.markdown("---")
    st.markdown("**篩選標準：**")
    st.markdown("- 天數 > 60天")
    st.markdown("- 價差 < 2%")
    st.markdown("- 價平 ~ 價外15%")

# 檔案上傳區
uploaded_file = st.file_uploader("📂 上傳權證 CSV 檔", type=['csv', 'xlsx'])

if uploaded_file is not None:
    try:
        # 讀取檔案
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, encoding='utf-8-sig') # 嘗試 utf-8-sig 或 big5
        else:
            df_raw = pd.read_excel(uploaded_file)
            
        st.write(f"已讀取 {len(df_raw)} 筆權證資料...")

        # 執行分析
        analyzer = GuTaiWarrantAnalyzer(stock_price)
        result_df, error = analyzer.analyze(df_raw)
        
        if error:
            st.error(error)
        else:
            # 顯示結果
            st.subheader("🏆 篩選結果")
            
            # 分頁顯示
            tab1, tab2, tab3 = st.tabs(["✅ 嚴選名單", "☠️ 地雷區", "📄 全部資料"])
            
            with tab1:
                st.success(f"找到 {len(result_df[result_df['status']=='✅ 股泰嚴選'])} 檔優質權證")
                st.dataframe(result_df[result_df['status']=='✅ 股泰嚴選'].style.format({'spread_pct': '{:.2f}%'}))
            
            with tab2:
                st.error("以下建議避開")
                st.dataframe(result_df[result_df['status'].isin(['☠️ 危險', '❌ 剔除'])])
                
            with tab3:
                st.dataframe(result_df)

    except Exception as e:
        st.error(f"檔案讀取失敗，請確認格式。錯誤訊息: {e}")

else:
    # 範例資料展示
    st.info("尚未上傳檔案，以下為南亞科模擬範例：")
    mock_data = pd.DataFrame([
        {'代號': '08A01', '名稱': '南亞科元大購01', '履約價': 285, '買價': 2.10, '賣價': 2.12, '剩餘天數': 120, '流通比': 10},
        {'代號': '08B02', '名稱': '南亞科凱基購02', '履約價': 350, '買價': 0.10, '賣價': 0.12, '剩餘天數': 90, '流通比': 5},
        {'代號': '08C03', '名稱': '南亞科富邦購03', '履約價': 278, '買價': 0.80, '賣價': 0.90, '剩餘天數': 20, '流通比': 30},
    ])
    analyzer = GuTaiWarrantAnalyzer(stock_price)
    res, _ = analyzer.analyze(mock_data)
    st.dataframe(res.style.format({'spread_pct': '{:.2f}%'}))