"""Usage:  python make_pages.py <your_beat_plan_file.py> <your_tps_file.py>
Creates beat_plan.py and tps.py (the two pages) from your ORIGINAL files, applying every edit automatically."""
import re, sys

def need(cond, msg):
    print(("OK   " if cond else "MISS ") + msg)

def make_beat(src):
    s = src
    n = len(s)
    s = re.sub(r"st\.set_page_config\(.*?\)\n", "", s, count=1, flags=re.S)
    a = s.index("# ====================== SUPABASE CONFIG")
    b = s.index("# ====================== BUSINESS RULES")
    s = s[:a] + "# ====================== SUPABASE (shared) ======================\nfrom bridge import beat_db\nsupabase = beat_db()\n\n" + s[b:]
    a = s.index("# ====================== LOGIN PAGE")
    b = s.index("# ====================== ADMIN PANEL")
    s = s[:a] + s[b:]
    need("set_page_config" not in s, "beat: set_page_config removed")
    need("beat_db()" in s, "beat: shared Supabase client")
    need("LOGIN PAGE" not in s, "beat: login + logout blocks removed")
    return s

def hook(s, pattern, call, label):
    pat = re.compile(r"^([ \t]*)(" + pattern + r")[ \t]*$", re.M)
    def rep(m):
        i = m.group(1)
        return (f"{i}{m.group(2)}\n{i}try:\n{i}    import bridge\n{i}    {call}\n"
                f"{i}except Exception as _bridge_err:\n{i}    st.warning(f'Saved, but Beat Plan sync failed: {{_bridge_err}}')")
    s2, k = pat.subn(rep, s)
    need(k > 0, f"tps: {label} ({k} place(s))")
    return s2

def make_tps(src):
    s = src
    s = s.replace("from dotenv import load_dotenv\n", "")
    s = re.sub(r"st\.set_page_config\(.*?\)\n", "", s, count=1, flags=re.S)
    a = s.index("# Load environment variables")
    b = s.index("# ── UltraMsg WhatsApp API Credentials")
    s = s[:a] + "from bridge import tps_db\nsupabase = tps_db()\n\n" + s[b:]
    s = re.sub(r'ULTRAMSG_INSTANCE_ID\s*=\s*".*?"', 'ULTRAMSG_INSTANCE_ID = st.secrets.get("ULTRAMSG_INSTANCE_ID", "")', s, count=1)
    s = re.sub(r'ULTRAMSG_TOKEN\s*=\s*".*?"', 'ULTRAMSG_TOKEN       = st.secrets.get("ULTRAMSG_TOKEN", "")', s, count=1)
    a = s.index("# Initialize session state")
    b = s.index("# ---------------------------------------------------------------\n# Helpers")
    s = s[:a] + s[b:]
    a = s.index("def login():")
    b = s.index("# ------", a)
    s = s[:a] + s[b:]
    a = s.index("def main():")
    s = s[:a] + '''# ---------------------------------------------------------------
# Page entry (login + navigation are handled by app.py)
# ---------------------------------------------------------------
_ut = st.session_state.get("user_type")
if _ut == "employee":
    employee_dashboard()
elif _ut == "tl":
    tl_dashboard()
elif _ut == "admin":
    admin_dashboard()
'''
    s = hook(s, r'supabase\.table\("partners"\)\.insert\(partner_data\)\.execute\(\)',
             "bridge.sync_partner_to_store(partner_data)", "approve new counter -> create Beat Plan store")
    s = hook(s, r'supabase\.table\("partners"\)\.delete\(\)\.eq\("partner_id", req\[.partner_id.\]\)\.execute\(\)',
             "bridge.remove_store_by_gst(req['gst_number'], req['emp_id'])", "approve removal -> delete Beat Plan store")
    s = hook(s, r'supabase\.table\("partners"\)\.insert\(counter_data\)\.execute\(\)',
             "bridge.sync_partner_to_store(counter_data)", "Excel upload -> create Beat Plan stores")
    s = hook(s, r'supabase\.table\("partners"\)\.delete\(\)\.eq\("emp_id", emp_id_to_delete\)\.execute\(\)',
             "bridge.remove_stores_of_employee(emp_id_to_delete)", "delete employee -> delete their Beat Plan stores")
    need("set_page_config" not in s and "def login" not in s and "def main" not in s, "tps: config/login/main removed")
    return s

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    beat_src = open(sys.argv[1], encoding="utf-8").read()
    tps_src = open(sys.argv[2], encoding="utf-8").read()
    open("beat_plan.py", "w", encoding="utf-8").write(make_beat(beat_src))
    open("tps.py", "w", encoding="utf-8").write(make_tps(tps_src))
    print("\nCreated beat_plan.py and tps.py. Any MISS line above means that edit must be done by hand.")
