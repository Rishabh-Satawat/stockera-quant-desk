import os
from datetime import datetime
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from kiteconnect import KiteConnect
from supabase import create_client

load_dotenv()

st.set_page_config(
    page_title="Tradetron Brain — Operator Console",
    page_icon="⚡",
    layout="wide"
)

st.title("⚡ Tradetron Brain — Systematic Desk Operator Console")
st.caption(f"Desk: Systematic Options | Live Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}")

# ==========================================
# 1. LIVE KERODHA KITE ACCOUNT STATUS
# ==========================================
st.subheader("🔑 Live Broker Connectivity (Zerodha Kite)")

KITE_API_KEY = os.getenv("KITE_API_KEY", "").strip()
token_file = "access_token.txt"

if os.path.exists(token_file) and KITE_API_KEY:
    try:
        with open(token_file) as f:
            kite_token = f.read().strip()
        
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(kite_token)
        
        # Fetch live profile and margins
        profile = kite.profile()
        margins = kite.margins()
        cash = margins.get("equity", {}).get("available", {}).get("cash", 0.0)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Kite Session", "🟢 CONNECTED", profile.get("user_id", "HP4636"))
        col2.metric("Account Holder", profile.get("user_name", "Rishabh Jain"))
        col3.metric("Available Cash", f"₹{cash:,.2f}")
        col4.metric("DhanHQ Data Bridge", "🟢 ACTIVE", "BFO/NFO Feed")

    except Exception as e:
        st.warning(f"⚠️ Kite session expired or invalid. Run 'python kite_auto_login.py' to refresh. Details: {e}")
else:
    st.info("ℹ️ access_token.txt not found. Run 'python kite_auto_login.py' to generate token.")

st.divider()

# ==========================================
# 2. LIVE 4-LEG TRADE & AUDIT DESK (SUPABASE)
# ==========================================
st.subheader("📊 Live 4-Leg Strategy & Audit Desk")

supabase_url = os.getenv("SUPABASE_URL", "").strip()
supabase_key = os.getenv("SUPABASE_KEY", "").strip()

if supabase_url and supabase_key:
    try:
        sp_client = create_client(supabase_url, supabase_key)
        today_str = str(datetime.now().date())

        res = sp_client.table("trade_legs").select("*").eq("trade_date", today_str).order("created_at", desc=True).execute()
        records = res.data or []

        if records:
            df = pd.DataFrame(records)

            # Active Open Positions
            df_open = df[df["status"] == "OPEN"]
            st.markdown(f"### 🟢 Active Open Positions ({len(df_open)} Legs)")
            if not df_open.empty:
                display_open = df_open[["cycle_id", "strategy_name", "leg_number", "leg_role", "symbol", "transaction_type", "quantity", "entry_price", "status"]]
                st.dataframe(display_open, use_container_width=True)
            else:
                st.caption("No open positions right now. Awaiting 09:15 AM entry trigger.")

            st.write("")

            # Closed / Realized Cycles
            df_closed = df[df["status"] == "CLOSED"]
            st.markdown(f"### 🏁 Realized Cycles Today ({len(df_closed)} Legs)")
            if not df_closed.empty:
                total_gross = df_closed["gross_pnl"].sum()
                friction = df_closed["brokerage_and_taxes"].sum() if "brokerage_and_taxes" in df_closed.columns else (len(df_closed) * 45.0)
                net = total_gross - friction
                pnl_color = "green" if net >= 0 else "red"

                m1, m2, m3 = st.columns(3)
                m1.metric("Total Gross P&L", f"₹{total_gross:,.2f}")
                m2.metric("Statutory Friction", f"-₹{friction:,.2f}")
                m3.metric("Net Realized P&L Today", f"₹{net:,.2f}")

                display_closed = df_closed[["cycle_id", "strategy_name", "leg_number", "leg_role", "symbol", "transaction_type", "quantity", "entry_price", "exit_price", "gross_pnl", "exit_trigger"]]
                st.dataframe(display_closed, use_container_width=True)
        else:
            st.info("No trades recorded yet for today in Supabase.")

    except Exception as e:
        st.error(f"Error querying Supabase: {e}")
else:
    st.warning("⚠️ SUPABASE_URL or SUPABASE_KEY missing in .env")

st.divider()
st.caption("Tradetron Brain Autonomous Execution Desk • Zerodha Kite Connect + Dhan Live Fills")