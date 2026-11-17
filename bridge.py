"""bridge.py - shared DB clients + sync logic between TPS (partners) and Beat Plan (gst_master).
TPS  partners.gst_number / emp_id   <->   Beat gst_master.GSTNumber / EmployeeCode
"""
import pandas as pd
import streamlit as st
from supabase import create_client

# Put these in .streamlit/secrets.toml (never hard-code keys in source):
# BEAT_SUPABASE_URL, BEAT_SUPABASE_KEY, TPS_SUPABASE_URL, TPS_SUPABASE_KEY
# ULTRAMSG_INSTANCE_ID, ULTRAMSG_TOKEN


@st.cache_resource
def beat_db():
    return create_client(st.secrets["BEAT_SUPABASE_URL"], st.secrets["BEAT_SUPABASE_KEY"])


@st.cache_resource
def tps_db():
    return create_client(st.secrets["TPS_SUPABASE_URL"], st.secrets["TPS_SUPABASE_KEY"])


GST_MAP = {"storeid": "StoreID", "storename": "StoreName", "gstnumber": "GSTNumber",
           "city": "City", "employeecode": "EmployeeCode"}


def fetch_all(db, table):
    rows, start = [], 0
    while True:
        chunk = db.table(table).select("*").range(start, start + 999).execute().data or []
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        start += 1000
    return pd.DataFrame(rows)


def _stores():
    df = fetch_all(beat_db(), "gst_master")
    if df.empty:
        return pd.DataFrame(columns=list(GST_MAP.values()))
    df = df.rename(columns={c: GST_MAP[c.lower()] for c in df.columns if c.lower() in GST_MAP})
    df["GSTNumber"] = df["GSTNumber"].astype(str).str.strip().str.upper()
    df["EmployeeCode"] = df["EmployeeCode"].astype(str).str.strip()
    return df


def _counters():
    df = fetch_all(tps_db(), "partners")
    if df.empty:
        return pd.DataFrame(columns=["partner_name", "gst_number", "city", "emp_id"])
    df["gst_number"] = df["gst_number"].astype(str).str.strip().str.upper()
    df["emp_id"] = df["emp_id"].astype(str).str.strip()
    return df


def _insert_flex(table, rec):
    """Insert trying CamelCase, then lowercase column names (Postgres casing issue)."""
    try:
        return beat_db().table(table).insert(rec).execute()
    except Exception as e:
        if "PGRST204" in str(e) or "schema cache" in str(e):
            return beat_db().table(table).insert({k.lower(): v for k, v in rec.items()}).execute()
        raise


def _next_store_id(stores):
    nums = pd.to_numeric(stores["StoreID"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    return f"S{int(nums.max() if nums.notna().any() else 0) + 1:05d}"


def sync_partner_to_store(partner: dict, stores=None):
    """Called when a TL approves a counter (or by the admin sync). Returns True if a store was created."""
    stores = _stores() if stores is None else stores
    gst = str(partner["gst_number"]).strip().upper()
    emp = str(partner["emp_id"]).strip()
    if ((stores["GSTNumber"] == gst) & (stores["EmployeeCode"] == emp)).any():
        return False
    _insert_flex("gst_master", {
        "StoreID": _next_store_id(stores),
        "StoreName": str(partner.get("partner_name", "")).strip().title(),
        "GSTNumber": gst,
        "City": str(partner.get("city") or "").strip().title(),
        "EmployeeCode": emp,
    })
    return True


def remove_store_by_gst(gst, emp_id):
    """Called when a TL approves a counter removal."""
    gst, emp_id = str(gst).strip().upper(), str(emp_id).strip()
    for g, e in (("GSTNumber", "EmployeeCode"), ("gstnumber", "employeecode")):
        try:
            beat_db().table("gst_master").delete().eq(g, gst).eq(e, emp_id).execute()
            return True
        except Exception as ex:
            if "42703" not in str(ex) and "does not exist" not in str(ex):
                raise
    return False


def compare():
    """(counters_not_in_beat, stores_not_in_tps, stores_df, counters_df)"""
    s, c = _stores(), _counters()
    s_key = set(zip(s["GSTNumber"], s["EmployeeCode"]))
    c_key = set(zip(c["gst_number"], c["emp_id"]))
    miss_store = c[[k not in s_key for k in zip(c["gst_number"], c["emp_id"])]]
    miss_counter = s[[k not in c_key for k in zip(s["GSTNumber"], s["EmployeeCode"])]]
    return miss_store, miss_counter, s, c


def sync_all_missing():
    """Create Beat stores for every TPS counter that has none."""
    miss, _, s, _ = compare()
    n = 0
    for p in miss.to_dict("records"):
        if sync_partner_to_store(p, s):
            n += 1
            s = _stores()
    return n
