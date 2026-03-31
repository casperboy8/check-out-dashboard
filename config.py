import os

# ==========================================
# CONFIGURATIE SNIPE-IT
# ==========================================
BASE_URL = os.environ.get("SNIPEIT_BASE_URL", "http://192.168.99.10:8000/api/v1")
HARDWARE_URL = f"{BASE_URL}/hardware"
ACTIVITY_URL = f"{BASE_URL}/reports/activity"
API_KEY = os.environ.get("SNIPEIT_API_KEY", "")

SNIPE_STANDAARD_STATUS_ID = 1 
SNIPE_STANDAARD_MODEL_ID = 1  

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

# ==========================================
# CONFIGURATIE ACTION1 (Via .env)
# ==========================================
ACTION1_INSTANTIES = []

i = 1
while True:
    naam = os.environ.get(f"ACTION1_NAAM_{i}")
    if not naam:
        break 
        
    ACTION1_INSTANTIES.append({
        "naam": naam,
        "client_id": os.environ.get(f"ACTION1_CLIENT_ID_{i}", ""),
        "client_secret": os.environ.get(f"ACTION1_CLIENT_SECRET_{i}", ""),
        "org_id": os.environ.get(f"ACTION1_ORG_ID_{i}", ""),
        "region_url": os.environ.get(f"ACTION1_REGION_URL_{i}", "https://app.eu.action1.com")
    })
    i += 1

NEGEER_SERIALS = ['to be filled by o.e.m.', 'default string', 'unknown', 'onbekend', 'n/a', 'none', '0']

# ==========================================
# CACHING SYSTEEM
# ==========================================
CACHE = {}
CACHE_TTL = 300 # 5 minuten

def clear_cache():
    if "checkouts" in CACHE:
        del CACHE["checkouts"]

def clear_action1_cache():
    if "action1_sync" in CACHE:
        del CACHE["action1_sync"]

SNIPE_CUSTOM_FIELDS = {
    "CPU": "_snipeit_cpu_44",
    "RAM": "_snipeit_werkgeheugen_45",
    "MAC": "_snipeit_mac_adres_46"
}