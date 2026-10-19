"""
Universe configuration for Japan Day Trading Terminal
Categorized into Large-Cap (Prime leaders), Mid-Cap (High Beta & Momentum), and Small-Cap / Growth.

topix500: selects the finer TSE tick table. JPX rebalances TOPIX500 membership every
  October, so re-check membership at https://www.jpx.co.jp/ (wrong flag = wrong tick grid).
fx_beta: sensitivity to USD/JPY (1.0 = exporter that benefits from a weaker yen, 0 = domestic).
"""

STOCKS_UNIVERSE = [
    # --- LARGE CAP (TSE Prime Heavyweights) ---
    {"symbol": "7203.T", "code": "7203", "name": "Toyota Motor", "name_jp": "トヨタ自動車", "cap": "Large", "sector": "Automotive", "topix500": True, "fx_beta": 1.0},
    {"symbol": "6758.T", "code": "6758", "name": "Sony Group", "name_jp": "ソニーグループ", "cap": "Large", "sector": "Consumer Electronics & Media", "topix500": True, "fx_beta": 1.0},
    {"symbol": "9983.T", "code": "9983", "name": "Fast Retailing", "name_jp": "ファーストリテイリング", "cap": "Large", "sector": "Retail / Uniqlo", "topix500": True, "fx_beta": 0.0},
    {"symbol": "8035.T", "code": "8035", "name": "Tokyo Electron", "name_jp": "東京エレクトロン", "cap": "Large", "sector": "Semiconductors", "topix500": True, "fx_beta": 1.0},
    {"symbol": "9984.T", "code": "9984", "name": "SoftBank Group", "name_jp": "ソフトバンクグループ", "cap": "Large", "sector": "Tech Investment / Telecom", "topix500": True, "fx_beta": 0.0},
    {"symbol": "8306.T", "code": "8306", "name": "Mitsubishi UFJ Fin.", "name_jp": "三菱UFJフィナンシャルG", "cap": "Large", "sector": "Banking / Finance", "topix500": True, "fx_beta": 0.0},
    {"symbol": "6861.T", "code": "6861", "name": "Keyence", "name_jp": "キーエンス", "cap": "Large", "sector": "Industrial Automation", "topix500": True, "fx_beta": 1.0},
    {"symbol": "7974.T", "code": "7974", "name": "Nintendo", "name_jp": "任天堂", "cap": "Large", "sector": "Gaming / Entertainment", "topix500": True, "fx_beta": 1.0},
    {"symbol": "6501.T", "code": "6501", "name": "Hitachi", "name_jp": "日立製作所", "cap": "Large", "sector": "Industrial & Tech", "topix500": True, "fx_beta": 1.0},
    {"symbol": "4063.T", "code": "4063", "name": "Shin-Etsu Chemical", "name_jp": "信越化学工業", "cap": "Large", "sector": "Materials / Silicon Wafer", "topix500": True, "fx_beta": 1.0},
    {"symbol": "8058.T", "code": "8058", "name": "Mitsubishi Corp", "name_jp": "三菱商事", "cap": "Large", "sector": "General Trading (Sogo Shosha)", "topix500": True, "fx_beta": 0.0},
    {"symbol": "7267.T", "code": "7267", "name": "Honda Motor", "name_jp": "本田技研工業", "cap": "Large", "sector": "Automotive", "topix500": True, "fx_beta": 1.0},

    # --- MID CAP (High Liquidity, High Beta Day Trading Favorites) ---
    {"symbol": "6920.T", "code": "6920", "name": "Lasertec", "name_jp": "レーザーテック", "cap": "Mid", "sector": "Semiconductor EUV Inspection", "topix500": True, "fx_beta": 1.0},
    {"symbol": "6857.T", "code": "6857", "name": "Advantest", "name_jp": "アドバンテスト", "cap": "Mid", "sector": "Semiconductor Test Equipment", "topix500": True, "fx_beta": 1.0},
    {"symbol": "6526.T", "code": "6526", "name": "Socionext", "name_jp": "ソシオネクスト", "cap": "Mid", "sector": "Custom SoC / Chips", "topix500": True, "fx_beta": 1.0},
    {"symbol": "6146.T", "code": "6146", "name": "Disco Corp", "name_jp": "ディスコ", "cap": "Mid", "sector": "Semiconductor Dicing / Grinding", "topix500": True, "fx_beta": 1.0},
    {"symbol": "4385.T", "code": "4385", "name": "Mercari", "name_jp": "メルカリ", "cap": "Mid", "sector": "E-Commerce / C2C", "topix500": True, "fx_beta": 0.0},
    {"symbol": "4755.T", "code": "4755", "name": "Rakuten Group", "name_jp": "楽天グループ", "cap": "Mid", "sector": "E-Commerce / Mobile", "topix500": True, "fx_beta": 0.0},
    {"symbol": "6723.T", "code": "6723", "name": "Renesas Electronics", "name_jp": "ルネサスエレクトロニクス", "cap": "Mid", "sector": "Automotive Semiconductor", "topix500": True, "fx_beta": 1.0},
    {"symbol": "7012.T", "code": "7012", "name": "Kawasaki Heavy Ind.", "name_jp": "川崎重工業", "cap": "Mid", "sector": "Heavy Machinery / Defense", "topix500": True, "fx_beta": 1.0},
    {"symbol": "2413.T", "code": "2413", "name": "M3 Inc.", "name_jp": "エムスリー", "cap": "Mid", "sector": "Medical Platform", "topix500": True, "fx_beta": 0.0},
    {"symbol": "4689.T", "code": "4689", "name": "LY Corporation", "name_jp": "LINEヤフー", "cap": "Mid", "sector": "Internet / LINE / Yahoo", "topix500": True, "fx_beta": 0.0},
    {"symbol": "4062.T", "code": "4062", "name": "Ibiden", "name_jp": "イビデン", "cap": "Mid", "sector": "Electronics / IC Substrates", "topix500": True, "fx_beta": 1.0},

    # --- SMALL CAP & GROWTH (TSE Growth & Standard High Volatility Movers) ---
    {"symbol": "5032.T", "code": "5032", "name": "ANYCOLOR", "name_jp": "ANYCOLOR (にじさんじ)", "cap": "Small", "sector": "VTuber / Digital Entertainment", "topix500": False, "fx_beta": 0.0},
    {"symbol": "5253.T", "code": "5253", "name": "COVER Corp", "name_jp": "カバー (ホロライブ)", "cap": "Small", "sector": "VTuber / IP Production", "topix500": False, "fx_beta": 0.0},
    {"symbol": "4180.T", "code": "4180", "name": "Appier Group", "name_jp": "エイピアグループ", "cap": "Small", "sector": "AI Marketing SaaS", "topix500": False, "fx_beta": 0.0},
    {"symbol": "4443.T", "code": "4443", "name": "Sansan", "name_jp": "Sansan", "cap": "Small", "sector": "Cloud DX Platform", "topix500": False, "fx_beta": 0.0},
    {"symbol": "9166.T", "code": "9166", "name": "GENDA", "name_jp": "GENDA (GiGO)", "cap": "Small", "sector": "Entertainment & Amusement", "topix500": False, "fx_beta": 0.0},
    {"symbol": "4478.T", "code": "4478", "name": "freee K.K.", "name_jp": "フリー", "cap": "Small", "sector": "Cloud Accounting SaaS", "topix500": False, "fx_beta": 0.0},
    {"symbol": "4393.T", "code": "4393", "name": "Bank of Innovation", "name_jp": "バンク・オブ・イノベーション", "cap": "Small", "sector": "Mobile Gaming / IP", "topix500": False, "fx_beta": 0.0},
    {"symbol": "9348.T", "code": "9348", "name": "ispace", "name_jp": "アイスペース", "cap": "Small", "sector": "Lunar Exploration / Space", "topix500": False, "fx_beta": 0.0},
    {"symbol": "4477.T", "code": "4477", "name": "BASE Inc.", "name_jp": "BASE", "cap": "Small", "sector": "E-Commerce Platform", "topix500": False, "fx_beta": 0.0},
    {"symbol": "2158.T", "code": "2158", "name": "FRONTEO", "name_jp": "フロンテオ", "cap": "Small", "sector": "Data Science & Legal Tech AI", "topix500": False, "fx_beta": 0.0}
]

MACRO_ASSETS = {
    "nikkei": {"symbol": "^N225", "name": "Nikkei 225", "desc": "Tokyo Headline Index"},
    "usdjpy": {"symbol": "JPY=X", "name": "USD / JPY", "desc": "Dollar / Yen Exchange Rate"},
    "topix": {"symbol": "1306.T", "name": "TOPIX ETF (1306)", "desc": "Broad Market Index ETF"},
    "growth": {"symbol": "2516.T", "name": "TSE Growth ETF (2516)", "desc": "Growth 250 Index ETF"}
}
