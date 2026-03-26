import requests
import concurrent.futures
from datetime import datetime
import config

def zoek_serienummer(data):
    if isinstance(data, dict):
        voorkeuren = ['serial_number', 'serialnumber', 'system_serial', 'bios_serial', 'serial']
        for v in voorkeuren:
            waarde = data.get(v)
            if waarde and isinstance(waarde, str) and waarde.strip():
                return waarde.strip()
                
        for key, value in data.items():
            if 'serial' in key.lower() and 'volume' not in key.lower() and value:
                if isinstance(value, str):
                    return value.strip()
            gevonden = zoek_serienummer(value)
            if gevonden: return gevonden
            
    elif isinstance(data, list):
        for item in data:
            gevonden = zoek_serienummer(item)
            if gevonden: return gevonden
    return None

def zoek_bitlocker_sleutel(data):
    if isinstance(data, dict):
        custom = data.get('custom_attributes', data.get('customAttributes', {}))
        if isinstance(custom, dict):
            for key, value in custom.items():
                if 'bitlocker' in key.lower(): return str(value).strip()
        elif isinstance(custom, list):
            for item in custom:
                if isinstance(item, dict) and 'bitlocker' in item.get('name', '').lower():
                    return str(item.get('value', '')).strip()

        voorkeuren = ['bitlocker_key', 'recovery_key', 'bitlocker_recovery_key', 'recoverypassword']
        for v in voorkeuren:
            waarde = data.get(v)
            if isinstance(waarde, str) and len(waarde) > 20 and any(char.isdigit() for char in waarde):
                return waarde.strip()
                
        for key, value in data.items():
            if ('bitlocker' in key.lower() or 'recovery' in key.lower()) and value:
                if isinstance(value, str) and len(value) > 20 and any(char.isdigit() for char in value):
                    return value.strip()
            if isinstance(value, (dict, list)):
                gevonden = zoek_bitlocker_sleutel(value)
                if gevonden: return gevonden
                
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                gevonden = zoek_bitlocker_sleutel(item)
                if gevonden: return gevonden
    return None

def haal_snipe_assets_op():
    alle_assets = []
    limit = 200
    offset = 0
    while True:
        response = requests.get(f"{config.HARDWARE_URL}?limit={limit}&offset={offset}&sort=id&order=asc", headers=config.headers)
        if response.status_code != 200: break
        data = response.json()
        rows = data.get('rows', [])
        if not rows: break
        alle_assets.extend(rows)
        offset += limit
        if len(alle_assets) >= data.get('total', 0): break
    return alle_assets

def haal_action1_token_op(client_id, client_secret, region_url):
    response = requests.post(f"{region_url}/api/3.0/oauth2/token", data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret
    })
    if response.status_code == 200: return response.json().get("access_token")
    return None

def haal_action1_endpoints_op(token, org_id, region_url):
    alle_endpoints = []
    from_offset = 0
    limit = 100  
    req_headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    
    while True:
        response = requests.get(f"{region_url}/api/3.0/endpoints/managed/{org_id}?from={from_offset}&limit={limit}", headers=req_headers)
        if response.status_code == 200:
            data = response.json()
            items = data if isinstance(data, list) else data.get('items', [])
            if not items: break
            alle_endpoints.extend(items)
            from_offset += limit
            if len(items) < limit: break
        else: break
    return alle_endpoints

def haal_action1_endpoint_details(token, org_id, region_url, endpoint_id):
    req_headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    response = requests.get(f"{region_url}/api/3.0/endpoints/managed/{org_id}/{endpoint_id}?fields=*", headers=req_headers)
    if response.status_code == 200: return response.json()
    return {}

def voer_sync_scan_uit():
    if not config.ACTION1_INSTANTIES:
        return {"status": "error", "message": "Geen Action1 configuratie gevonden. Controleer je .env bestand."}

    snipe_assets = haal_snipe_assets_op()
    if not snipe_assets: return {"status": "error", "message": "Kan Snipe-IT niet bereiken."}
        
    snipe_dict_naam = {}
    snipe_dict_serial = {}
    
    for asset in snipe_assets:
        naam = asset.get('name')
        serial = str(asset.get('serial', '') or '').strip()
        asset_id = asset.get('id')
        
        if naam:
            snipe_dict_naam[naam.strip().lower()] = {'id': asset_id, 'naam': naam.strip(), 'serial': serial}
        if serial and len(serial) > 3 and serial.lower() not in config.NEGEER_SERIALS:
            snipe_dict_serial[serial.lower()] = {'id': asset_id, 'naam': naam.strip(), 'serial': serial}

    alle_ontbrekende_endpoints = []
    alle_serienummer_mismatches = []
    alle_naam_mismatches = []
    
    for instantie in config.ACTION1_INSTANTIES:
        naam_inst = instantie['naam']
        token = haal_action1_token_op(instantie['client_id'], instantie['client_secret'], instantie['region_url'])
        if not token: continue
            
        action1_endpoints = haal_action1_endpoints_op(token, instantie['org_id'], instantie['region_url'])
        
        def verwerk_endpoint(endpoint):
            ep_id = endpoint.get('id')
            return endpoint, haal_action1_endpoint_details(token, instantie['org_id'], instantie['region_url'], ep_id) if ep_id else {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_ep = {executor.submit(verwerk_endpoint, ep): ep for ep in action1_endpoints}
            
            for future in concurrent.futures.as_completed(future_to_ep):
                endpoint, details = future.result()
                
                action1_naam = endpoint.get('name', endpoint.get('hostname', 'ONBEKEND'))
                naam_lower = action1_naam.strip().lower()
                
                a1_serial = zoek_serienummer(details) or ""
                a1_serial_lower = a1_serial.lower()
                bitlocker = "Geen BitLocker veld"
                
                if naam_lower not in snipe_dict_naam:
                    gev_bitlocker = zoek_bitlocker_sleutel(details)
                    if gev_bitlocker: bitlocker = gev_bitlocker

                endpoint['berekend_serial'] = a1_serial
                endpoint['bron_instantie'] = naam_inst

                if naam_lower in snipe_dict_naam:
                    snipe_data = snipe_dict_naam[naam_lower]
                    snipe_serial = snipe_data['serial']
                    
                    if a1_serial and a1_serial_lower != snipe_serial.lower():
                        alle_serienummer_mismatches.append({
                            'naam': action1_naam, 'snipe_id': snipe_data['id'],
                            'snipe_serial': snipe_serial if snipe_serial else "LEEG IN SNIPE-IT",
                            'a1_serial': a1_serial, 'bron_instantie': naam_inst
                        })
                else:
                    if a1_serial_lower and a1_serial_lower in snipe_dict_serial:
                        snipe_data = snipe_dict_serial[a1_serial_lower]
                        alle_naam_mismatches.append({
                            'a1_naam': action1_naam, 'snipe_naam': snipe_data['naam'],
                            'serial': a1_serial, 'snipe_id': snipe_data['id'], 'bron_instantie': naam_inst
                        })
                    else:
                        alle_ontbrekende_endpoints.append({
                            'name': action1_naam, 'OS': endpoint.get('OS', 'Onbekend'),
                            'address': endpoint.get('address', ''), 'berekend_serial': a1_serial,
                            'berekend_bitlocker': bitlocker, 'bron_instantie': naam_inst
                        })

    result = {
        "status": "success",
        "naam_mismatches": alle_naam_mismatches,
        "serial_mismatches": alle_serienummer_mismatches,
        "ontbrekende_endpoints": alle_ontbrekende_endpoints
    }
    
    config.CACHE["action1_sync"] = {
        "tijd_str": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "data": result
    }
    
    return result