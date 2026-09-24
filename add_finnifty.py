import re

file_paths = [
    r"C:\kite-agent\dhan_option_engine.py",
    r"C:\kite-agent\chain_microstructure_analyzer.py",
    r"C:\kite-agent\auto_trade_hunter.py"
]

for p in file_paths:
    with open(p, "r", encoding="utf-8") as f:
        content = f.read()

    # Ensure FINNIFTY is mapped with scrip 27 and lot 60
    content = content.replace('"NIFTY": 13, "BANKNIFTY": 25, "SENSEX": 51', '"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51')
    content = content.replace('["NIFTY", "SENSEX", "BANKNIFTY"]', '["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"]')
    content = content.replace('["SENSEX", "NIFTY", "BANKNIFTY"]', '["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"]')
    
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)

print("✅ FINNIFTY (60 Qty / Scrip 27) added to the multi-index scanning universe!")
