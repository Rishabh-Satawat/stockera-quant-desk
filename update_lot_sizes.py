import os
import re

files_to_update = [
    r"C:\kite-agent\dhan_option_engine.py",
    r"C:\kite-agent\auto_trade_hunter.py",
    r"C:\kite-agent\app_cockpit.py"
]

new_lot_dict = 'LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 60}'

for fpath in files_to_update:
    if os.path.exists(fpath):
        with open(fpath, "r", encoding="utf-8") as f:
            code = f.read()

        # Update LOT_SIZES dictionary
        code = re.sub(r'LOT_SIZES\s*=\s*\{.*?\}', new_lot_dict, code, flags=re.DOTALL)
        
        # Update inline ternary expressions
        code = code.replace('20 if sym == "SENSEX" else (25 if sym == "NIFTY" else 15)', 'LOT_SIZES.get(sym, 65)')
        code = code.replace('30 if sym == "SENSEX" else (25 if sym == "NIFTY" else 15)', 'LOT_SIZES.get(sym, 65)')

        with open(fpath, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"✅ Updated Lot Sizes in: {os.path.basename(fpath)}")

print("\n🚀 All files successfully synchronized with official 65 Qty for NIFTY and 30 Qty for BANKNIFTY!")
