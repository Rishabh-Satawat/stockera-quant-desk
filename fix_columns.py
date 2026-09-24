import re

file_path = r"C:\kite-agent\app_cockpit.py"
with open(file_path, "r", encoding="utf-8") as f:
    code = f.read()

# Set the exact integer column counts for each line
code = re.sub(r'h1,\s*h2,\s*h3\s*=\s*st\.columns\([^\)]*\)', 'h1, h2, h3 = st.columns(3)', code)
code = re.sub(r'c_sym,\s*c_prof\s*=\s*st\.columns\([^\)]*\)', 'c_sym, c_prof = st.columns(2)', code)
code = re.sub(r'col_btn1,\s*col_btn2\s*=\s*st\.columns\([^\)]*\)', 'col_btn1, col_btn2 = st.columns(2)', code)
code = re.sub(r'col_agents,\s*col_verdict\s*=\s*st\.columns\([^\)]*\)', 'col_agents, col_verdict = st.columns(2)', code)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(code)

print("SUCCESS: Line 63 is now 'h1, h2, h3 = st.columns(3)'!")
