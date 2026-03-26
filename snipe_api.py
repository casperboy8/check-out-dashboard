import requests
import pandas as pd
import time
import config

def haal_factuur_statussen_op():
    statussen = {}
    gevonden_db_column = None
    offset = 0
    limit = 500

    while True:
        response = requests.get(f"{config.HARDWARE_URL}?limit={limit}&offset={offset}", headers=config.headers)
        if response.status_code != 200:
            break
            
        data = response.json().get('rows', [])
        for asset in data:
            asset_id = str(asset.get('id'))
            custom_fields = asset.get('custom_fields', {})
            
            is_gefactureerd = False
            if isinstance(custom_fields, dict):
                for veld_naam, veld_info in custom_fields.items():
                    if 'gefactureerd' in veld_naam.lower():
                        if not gevonden_db_column:
                            gevonden_db_column = veld_info.get('field')
                        waarde = veld_info.get('value')
                        if str(waarde).lower() in ['1', 'yes', 'ja', 'true']:
                            is_gefactureerd = True
                        break
            
            statussen[asset_id] = is_gefactureerd
            
        if len(data) < limit:
            break
        offset += limit
        
    return statussen, gevonden_db_column

def haal_checkouts_op(force_refresh=False):
    nu = time.time()
    if not force_refresh and "checkouts" in config.CACHE and (nu - config.CACHE["checkouts"]["tijd"]) < config.CACHE_TTL:
        return config.CACHE["checkouts"]["df"], config.CACHE["checkouts"]["db_column"]

    factuur_statussen, db_column_naam = haal_factuur_statussen_op()
    
    alle_acties = []
    offset = 0
    limit = 500
    grens_datum = pd.Timestamp.now().tz_localize(None) - pd.Timedelta(days=31)

    while True:
        response = requests.get(f"{config.ACTIVITY_URL}?action_type=checkout&limit={limit}&offset={offset}", headers=config.headers)
        if response.status_code != 200:
            if "checkouts" in config.CACHE:
                return config.CACHE["checkouts"]["df"], config.CACHE["checkouts"]["db_column"]
            return pd.DataFrame(), None
            
        data = response.json().get('rows', [])
        if not data:
            break

        alle_acties.extend(data)
        
        laatste_item = data[-1]
        created_at = laatste_item.get('created_at', {})
        datum_str = created_at.get('datetime') if isinstance(created_at, dict) else str(created_at)
        
        try:
            if pd.to_datetime(datum_str).tz_localize(None) < grens_datum:
                break
        except:
            pass
            
        if len(data) < limit:
            break
        offset += limit

    uitgecheckt = []
    for actie in alle_acties:
        item = actie.get('item', {})
        admin = actie.get('admin', {})
        target = actie.get('target', {})
        created_at = actie.get('created_at', {})
        
        item_id = str(item.get('id'))
        item_naam = item.get('name', 'Onbekend') if isinstance(item, dict) else str(item)
        item_type = item.get('type', 'Onbekend') if isinstance(item, dict) else ""
        
        beheerder_naam = admin.get('name', 'Systeem') if isinstance(admin, dict) else str(admin)
        doelwit_naam = target.get('name', 'Onbekend') if isinstance(target, dict) else str(target)
        doelwit_type = target.get('type', '') if isinstance(target, dict) else ""
        
        datum_str = created_at.get('datetime') if isinstance(created_at, dict) else str(created_at)

        try:
            if pd.to_datetime(datum_str).tz_localize(None) < grens_datum:
                continue
        except:
            pass

        is_asset = (item_type == 'asset')
        gefactureerd_status = False
        
        if is_asset:
            gefactureerd_status = factuur_statussen.get(item_id, False)

        volledige_item_naam = f"{item_naam} ({item_type})" if item_type else item_naam
        volledig_doelwit = f"{doelwit_naam} ({doelwit_type})" if doelwit_type else doelwit_naam

        uitgecheckt.append({
            "item_id": item_id,
            "is_asset": is_asset,
            "Gefactureerd": gefactureerd_status,
            "Item": volledige_item_naam,
            "Uitgevoerd_door": beheerder_naam,
            "Gegeven_aan": volledig_doelwit,
            "Tijdstip_raw": datum_str
        })

    df = pd.DataFrame(uitgecheckt)
    if not df.empty:
        df['Tijdstip_dt'] = pd.to_datetime(df['Tijdstip_raw']).dt.tz_localize(None)
        df = df.sort_values(by="Tijdstip_dt", ascending=False)
        df['Tijdstip'] = df['Tijdstip_dt'].dt.strftime('%d-%m-%Y %H:%M')
        df['timestamp_ms'] = df['Tijdstip_dt'].astype('int64') // 10**6 
        
    config.CACHE["checkouts"] = {
        "tijd": time.time(),
        "df": df,
        "db_column": db_column_naam
    }
        
    return df, db_column_naam

def haal_klanten_filters_op(force_refresh=False):
    nu = time.time()
    if not force_refresh and "klanten_filters" in config.CACHE and (nu - config.CACHE["klanten_filters"]["tijd"]) < config.CACHE_TTL:
        return config.CACHE["klanten_filters"]["data"]
        
    comp_resp = requests.get(f"{config.BASE_URL}/companies?limit=2000", headers=config.headers)
    bedrijven = comp_resp.json().get('rows', []) if comp_resp.status_code == 200 else []
    
    cat_resp = requests.get(f"{config.BASE_URL}/categories?limit=2000", headers=config.headers)
    categories = cat_resp.json().get('rows', []) if cat_resp.status_code == 200 else []

    bedrijven = sorted([{"id": c['id'], "name": c['name']} for c in bedrijven], key=lambda x: x['name'].lower())
    categories = sorted([{"id": c['id'], "name": c['name']} for c in categories], key=lambda x: x['name'].lower())

    data = {"companies": bedrijven, "categories": categories}
    
    config.CACHE["klanten_filters"] = {
        "tijd": time.time(),
        "data": data
    }
    return data