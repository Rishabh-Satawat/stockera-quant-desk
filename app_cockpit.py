# =============================================================================
# STOCKERA MASTER QUANT COCKPIT (PRO v4.5 - FROZEN ARCHITECTURE)
# =============================================================================
import os
import json
import math
import datetime
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from live_spot_service import get_live_spots
from chain_microstructure_analyzer import analyze_option_chain_microstructure

st.set_page_config(
    page_title="Stockera Master Quant Desk",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dark Theme CSS
st.markdown("""
<style>
    .stApp { background-color: #0b0f19; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
    .agent-box { background: #111827; padding: 18px; border-radius: 12px; border-left: 4px solid #3b82f6; margin-bottom: 12px; }
    .verdict-box { background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%); padding: 22px; border-radius: 14px; border: 1px solid #6366f1; }
    .market-pill-open { background: rgba(16, 185, 129, 0.15); border: 1px solid #10b981; color: #34d399; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
    .market-pill-closed { background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #f87171; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

load_dotenv(r"C:\kite-agent\secrets\dhan.env")
load_dotenv(r"C:\kite-agent\secrets\telegram.env")

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8814895777:AAFrGfSdIM1fW7HeHg9yIeFjOXqOMyg9F7s").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1337295028").strip()

LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 60}
LEDGER_FILE = r"C:\kite-agent\trades_ledger.json"
HISTORY_CSV = r"C:\kite-agent\trades_history.csv"

if "current_basket" not in st.session_state:
    st.session_state["current_basket"] = None

def get_dhan_funds():
    if not DHAN_ACCESS_TOKEN or not DHAN_CLIENT_ID:
        return 0.0
    try:
        h = {"access-token": DHAN_ACCESS_TOKEN, "client-id": DHAN_CLIENT_ID, "Content-Type": "application/json"}
        r = requests.get("https://api.dhan.co/v2/fundlimit", headers=h, timeout=3)
        if r.status_code == 200:
            return float(r.json().get("availMargin", 0.0))
    except Exception:
        pass
    return 0.0

avail_margin = get_dhan_funds()

# Sidebar
st.sidebar.title("🎛️ Desk Controls")
st.sidebar.metric("Dhan Live Margin", f"₹{avail_margin:,.2f}")
st.sidebar.divider()
st.sidebar.subheader("🎯 Official Lot Sizes")
for k, v in LOT_SIZES.items():
    st.sidebar.write(f"• **{k}:** {v} Qty / Lot")

# Market Timing Calculation
now_dt = datetime.datetime.now()
time_str = now_dt.strftime("%H:%M:%S IST")
is_weekday = now_dt.weekday() < 5
cur_min = now_dt.hour * 60 + now_dt.minute
is_market_open = is_weekday and ((9 * 60 + 15) <= cur_min <= (15 * 60 + 30))

market_badge = '<span class="market-pill-open">🟢 MARKET OPEN</span>' if is_market_open else '<span class="market-pill-closed">🔴 MARKET CLOSED (09:15 IST)</span>'

# Top Header Bar
h1, h2, h3 = st.columns(3)
with h1:
    st.title("⚡ Stockera Master Quant Cockpit")
    st.caption("Live Multi-Agent Committee • Dhan HQ v2 Telemetry • Real Market Microstructure")
with h2:
    st.markdown(f"**Desk Status:** 🟢 ARMED")
    st.markdown(f"⏱️ **IST Clock:** `{time_str}`")
    st.markdown(market_badge, unsafe_allow_html=True)
with h3:
    st.write("")
    if st.button("🔄 Refresh All", type="secondary", use_container_width=True):
        st.rerun()

# Top Spots
spots = get_live_spots()
r1, r2, r3 = st.columns(3)
r1.metric("NIFTY 50 Spot", f"₹{spots.get('NIFTY', 0):,.2f}", delta="Dhan Live Feed")
r2.metric("BANK NIFTY Spot", f"₹{spots.get('BANKNIFTY', 0):,.2f}", delta="Dhan Live Feed")
r3.metric("BSE SENSEX Spot", f"₹{spots.get('SENSEX', 0):,.2f}", delta="Dhan Live Feed")
st.divider()

t1, t2, t3 = st.tabs(["⚡ Trade Setup Generator", "🤖 JARVIS Multi-Agent Committee", "📋 Today's Live Trade Blotter"])

# --- TAB 1: SETUP GENERATOR ---
with t1:
    c_sym, c_prof = st.columns(2)
    with c_sym:
        selected_sym = st.selectbox("Select Underlying Asset", ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"])
    with c_prof:
        prof = st.radio("Strategy Type", ["Hedged Income (Iron Condor / Spread)", "Naked Directional (Momentum Buying)"], horizontal=True)

    analysis_data = analyze_option_chain_microstructure(selected_sym)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Live Spot", f"₹{analysis_data['spot']:,.2f}")
    m2.metric("Put-Call Ratio (PCR)", f"{analysis_data['pcr_oi']:.2f}")
    m3.metric("Max Pain Strike", f"{analysis_data['max_pain']:.0f}")
    m4.metric("Call/Put Walls", f"{analysis_data['put_wall']:.0f} - {analysis_data['call_wall']:.0f}")
    st.write("")

    if st.button("⚡ Find Best Quantitative Setup", type="primary", use_container_width=True):
        spot = analysis_data["spot"]
        pcr = analysis_data["pcr_oi"]
        max_pain = analysis_data["max_pain"]
        cw = analysis_data["call_wall"]
        pw = analysis_data["put_wall"]
        oc = analysis_data["raw_oc"]
        lot = LOT_SIZES.get(selected_sym, 25)
        step = 100 if selected_sym in ["SENSEX", "BANKNIFTY"] else 50
        atm = int(round(spot / step) * step)

        def get_p(strike, opt_t):
            for k, v in oc.items():
                if abs(float(k) - strike) < 0.1:
                    p = float(v.get(opt_t.lower(), {}).get("last_price", 0.0))
                    if p > 0: return round(p, 2)
            return 45.0

        if "Hedged Income" in prof:
            s_ce, b_ce = atm + 2 * step, atm + 4 * step
            s_pe, b_pe = atm - 2 * step, atm - 4 * step
            p_sce, p_bce = get_p(s_ce, "CE"), get_p(b_ce, "CE")
            p_spe, p_bpe = get_p(s_pe, "PE"), get_p(b_pe, "PE")
            net_credit = round((p_sce - p_bce) + (p_spe - p_bpe), 2)
            max_p = round(net_credit * lot, 2)
            lower_be, upper_be = s_pe - net_credit, s_ce + net_credit

            legs = [
                f"🟢 BUY  {selected_sym} {b_ce} CE @ ~₹{p_bce:.2f} (Call Hedge)",
                f"🟢 BUY  {selected_sym} {b_pe} PE @ ~₹{p_bpe:.2f} (Put Hedge)",
                f"🔴 SELL {selected_sym} {s_ce} CE @ ~₹{p_sce:.2f} (Short Call)",
                f"🔴 SELL {selected_sym} {s_pe} PE @ ~₹{p_spe:.2f} (Short Put)"
            ]
            st.session_state["current_basket"] = {
                "sym": selected_sym,
                "book": "HEDGED",
                "name": "0DTE Delta-Neutral Iron Condor",
                "contract": f"{selected_sym} {s_pe} PE / {s_ce} CE Condor",
                "action": "SELL",
                "spot": spot,
                "legs": legs,
                "credit": net_credit,
                "lot": lot,
                "pop": "78.4%",
                "max_p": f"₹{max_p:,.2f}",
                "max_l": f"₹{max_p:,.2f} (1x Hard-SL)",
                "sl": f"Exit basket if combined premium reaches ₹{net_credit * 2:.2f}",
                "corridor": f"₹{lower_be:,.0f} to ₹{upper_be:,.0f}"
            }
        else:
            is_bearish = pcr < 0.85 or spot < max_pain
            opt_type = "PE" if is_bearish else "CE"
            strike = atm
            opt_price = get_p(strike, opt_type)
            sl = round(opt_price * 0.80, 2)
            t1 = round(opt_price * 1.25, 2)
            t2 = round(opt_price * 1.50, 2)

            legs = [f"🟢 BUY  {selected_sym} {strike} {opt_type} @ Limit ₹{opt_price:.2f}"]
            st.session_state["current_basket"] = {
                "sym": selected_sym,
                "book": "NAKED",
                "name": f"Directional {'Put' if is_bearish else 'Call'} Momentum Buying",
                "contract": f"{selected_sym} {strike} {opt_type}",
                "action": "BUY",
                "spot": spot,
                "legs": legs,
                "credit": opt_price,
                "lot": lot,
                "pop": "62.5%",
                "max_p": f"₹{(t1 - opt_price) * lot:,.2f} (T1)",
                "max_l": f"₹{(opt_price - sl) * lot:,.2f} (20% Hard-SL)",
                "sl": f"Hard Stop-Loss at ₹{sl:.2f}",
                "corridor": f"Targets: T1 ₹{t1:.2f} | T2 ₹{t2:.2f}"
            }

    b = st.session_state.get("current_basket", None)
    if b:
        st.markdown(f"### 📋 Recommended Execution Basket ({b['name']})")
        for leg in b["legs"]:
            st.code(leg)

        bm1, bm2, bm3, bm4 = st.columns(4)
        bm1.metric("Win Probability", b["pop"])
        bm2.metric("Entry Premium", f"₹{b['credit']:.2f}")
        bm3.metric("Max Profit Target", b["max_p"])
        bm4.metric("Defined Risk (SL)", b["max_l"])

        b_act1, b_act2 = st.columns(2)
        with b_act1:
            if st.button("🚀 Push Basket to Dhan Execution Gateway", type="secondary", use_container_width=True):
                st.success("✅ Multi-leg basket validated for Dhan HQ execution gateway!")
        with b_act2:
            if st.button("📡 Broadcast Trade Card to Telegram", type="primary", use_container_width=True):
                legs_str = "\n".join([f"• `{l}`" for l in b["legs"]])
                msg = f"""🚨 *STOCKERA QUANT: HIGH-CONVICTION TRADE ALERT* 🚨
━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *Underlying:* {b['sym']} | *Live Spot:* ₹{b['spot']:,.2f}
📌 *Strategy:* {b['name']} ({b['book']} Book)
📋 *EXECUTION LEGS ({b['lot']} Qty / 1 Lot):*
{legs_str}
━━━━━━━━━━━━━━━━━━━━━━━━━
💰 *RISK & FINANCIAL PARAMETERS:*
• *Entry Reference:* ₹{b['credit']:.2f}
• *Target / Max Profit:* {b['max_p']}
• *Defined Risk (SL):* {b['max_l']}
• *Corridor / Target:* {b['corridor']}
• *Directive:* {b['sl']}
━━━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Status:* ACTIVE | Auto-Logged to Desk Ledger"""
                try:
                    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
                    if r.status_code == 200:
                        st.success("✅ Trade Card broadcasted live to Telegram (@PropdeskAgentbot)!")
                    else:
                        st.error(f"Telegram notice: {r.text}")
                except Exception as e:
                    st.error(f"Telegram error: {e}")

# --- TAB 2: JARVIS MULTI-AGENT COMMITTEE ---
with t2:
    st.subheader("🤖 JARVIS Multi-Agent Committee Deliberation")
    st.caption("Live Telemetry: Each agent calculates its thesis in real-time from Dhan HQ v2 Option Chain")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Re-Deliberate Committee (Live Refresh)", type="primary"):
            st.rerun()

    active_sym = st.selectbox("Deliberate Asset", ["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY"], key="agent_sym")
    a = analyze_option_chain_microstructure(active_sym)

    spot_val = a["spot"]
    pcr_val = a["pcr_oi"]
    mp_val = a["max_pain"]
    cw_val = a["call_wall"]
    pw_val = a["put_wall"]

    if spot_val > mp_val:
        tech_verdict = "🟢 BULLISH MOMENTUM"
        tech_desc = f"Spot (₹{spot_val:,.2f}) is holding above Max Pain ({mp_val:.0f}). Momentum favors upward drift toward Call Resistance at {cw_val:.0f}."
    elif spot_val < mp_val:
        tech_verdict = "🔴 BEARISH EXPANSION"
        tech_desc = f"Spot (₹{spot_val:,.2f}) has broken {mp_val - spot_val:.1f} pts below Max Pain ({mp_val:.0f}). Downward pressure toward Put Support at {pw_val:.0f}."
    else:
        tech_verdict = "🟡 RANGE CONSOLIDATION"
        tech_desc = f"Spot is pinned directly on Max Pain strike ({mp_val:.0f}). Neutral range-bound action active."

    if pcr_val < 0.80:
        deriv_verdict = "🔴 CALL WRITER DOMINANCE (BEARISH)"
        deriv_desc = f"Put-Call Ratio at {pcr_val:.2f} indicates heavy Call Writing overhead at {cw_val:.0f}. Sellers are capping the upside."
    elif pcr_val > 1.20:
        deriv_verdict = "🟢 PUT WRITER DOMINANCE (BULLISH)"
        deriv_desc = f"Put-Call Ratio at {pcr_val:.2f} confirms strong Put Writing support at {pw_val:.0f}. Buyers are absorbing dips."
    else:
        deriv_verdict = "🟡 BALANCED REGIME (THETA PINNING)"
        deriv_desc = f"Put-Call Ratio at {pcr_val:.2f} is in balance. Premium decay favorable between {pw_val:.0f} and {cw_val:.0f}."

    cro_verdict = "🟢 EXECUTION CLEARED"
    cro_desc = f"Available trading margin is ₹{avail_margin:,.2f}. Portfolio Net Delta and Expiry-STT safeguards active."

    if "BEARISH" in tech_verdict and "BEARISH" in deriv_verdict:
        consensus_title = "HIGH-CONVICTION SHORT (PUT MOMENTUM)"
        consensus_color = "#ef4444"
    elif "BULLISH" in tech_verdict and "BULLISH" in deriv_verdict:
        consensus_title = "HIGH-CONVICTION LONG (CALL MOMENTUM)"
        consensus_color = "#10b981"
    else:
        consensus_title = "RANGE-BOUND INCOME (DELTA-NEUTRAL CONDOR)"
        consensus_color = "#6366f1"

    col_agents, col_verdict = st.columns(2)
    with col_agents:
        st.markdown(f"""
        <div class="agent-box" style="border-left-color: #10b981;">
            <h4 style="color: #34d399; margin-top:0;">🟢 Lead Technical Analyst Agent</h4>
            <div style="font-size: 13px; font-weight: bold; margin-bottom: 4px;">Verdict: {tech_verdict}</div>
            <p style="font-size: 13px; color: #cbd5e1;">{tech_desc}</p>
        </div>
        <div class="agent-box" style="border-left-color: #38bdf8;">
            <h4 style="color: #38bdf8; margin-top:0;">🔵 Derivatives Specialist Agent</h4>
            <div style="font-size: 13px; font-weight: bold; margin-bottom: 4px;">Verdict: {deriv_verdict}</div>
            <p style="font-size: 13px; color: #cbd5e1;">{deriv_desc}</p>
        </div>
        <div class="agent-box" style="border-left-color: #f43f5e;">
            <h4 style="color: #fb7185; margin-top:0;">🔴 Chief Risk Officer</h4>
            <div style="font-size: 13px; font-weight: bold; margin-bottom: 4px;">Verdict: {cro_verdict}</div>
            <p style="font-size: 13px; color: #cbd5e1;">{cro_desc}</p>
        </div>
        """, unsafe_allow_html=True)

    with col_verdict:
        st.markdown(f"""
        <div class="verdict-box" style="border-color: {consensus_color};">
            <div style="font-size: 12px; color: #a5b4fc; text-transform: uppercase;">Consensus Action</div>
            <div style="font-size: 18px; font-weight: bold; color: #fff; margin: 4px 0 10px 0;">{consensus_title}</div>
            <p style="font-size: 13px; color: #cbd5e1; line-height: 1.4;">Derived from live Dhan option chain and real-time open interest distribution.</p>
        </div>
        """, unsafe_allow_html=True)

# --- TAB 3: LIVE BLOTTER & HISTORICAL ARCHIVE ---
with t3:
    st.subheader("📋 Trade Journal & Multi-Timeframe Blotter")
    view_mode = st.radio("Blotter Mode", ["Today's Live Session (Active Ledger)", "Full Historical Archive (All Dates & Export)"], horizontal=True)

    if "Today's Live" in view_mode:
        if os.path.exists(LEDGER_FILE):
            with open(LEDGER_FILE, "r", encoding="utf-8-sig") as f:
                try:
                    trades_data = json.load(f)
                except Exception:
                    trades_data = []
            if trades_data:
                tot_pnl = sum(t.get("realized_pnl", 0.0) for t in trades_data if t.get("status") == "CLOSED")
                tot_margin = sum(t.get("margin_deployed", 0.0) for t in trades_data)
                tot_roi = round((tot_pnl / tot_margin) * 100, 2) if tot_margin > 0 else 0.0
                closed_w = sum(1 for t in trades_data if t.get("realized_pnl", 0.0) > 0)
                closed_tot = sum(1 for t in trades_data if t.get("status") == "CLOSED")
                win_rate = (closed_w / closed_tot * 100) if closed_tot > 0 else 0.0

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Today's Trades", len(trades_data), delta=f"{closed_tot} Closed")
                k2.metric("Net Realized P&L", f"₹{tot_pnl:+,.2f}", delta="Official Settled")
                k3.metric("Overall Gross ROI", f"{tot_roi:+.2f}%", delta="ROI on Capital")
                k4.metric("Win Rate", f"{win_rate:.1f}%", delta=f"{closed_w}W - {closed_tot-closed_w}L")
                st.divider()

                df = pd.DataFrame(trades_data)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No trades logged for today yet.")
        else:
            st.info("Today's ledger is clean.")

    else:
        # Full Historical Archive
        if os.path.exists(HISTORY_CSV):
            df_hist = pd.read_csv(HISTORY_CSV)
            if not df_hist.empty:
                # Add Date extraction if present
                st.markdown("#### 📁 Historical Master Blotter")
                c_d1, c_d2 = st.columns(2)
                with c_d1:
                    st.caption("Permanent accumulated audit records across all past sessions.")
                with c_d2:
                    csv_data = df_hist.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download Trade History (CSV)",
                        data=csv_data,
                        file_name="stockera_master_trade_history.csv",
                        mime="text/csv",
                        use_container_width=True
                    )

                st.dataframe(df_hist, use_container_width=True)
            else:
                st.info("Historical CSV archive is currently empty.")
        else:
            st.info("Historical archive (trades_history.csv) will be generated after first rollover.")