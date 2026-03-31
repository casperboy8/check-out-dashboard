import requests
import concurrent.futures
import config
import os
import json
from datetime import datetime

# Zorg dat de opslagmap bestaat (veilig in je Docker volume)
PAKBON_DIR = 'data/pakbonnen'
if not os.path.exists(PAKBON_DIR):
    os.makedirs(PAKBON_DIR)

def get_pakbon_data(company_id):
    """Haalt pijlsnel klant-assets en magazijn-assets op via caching."""
    alle_assets = []
    
    if "alle_assets_cache" in config.CACHE:
        alle_assets = config.CACHE["alle_assets_cache"]
    else:
        try:
            eerste_resp = requests.get(f"{config.HARDWARE_URL}?limit=1000&offset=0", headers=config.headers, timeout=15)
            if eerste_resp.status_code == 200:
                data = eerste_resp.json()
                alle_assets.extend(data.get('rows', []))
                totaal_apparaten = data.get('total', 0)
                
                if totaal_apparaten > 1000:
                    offsets = range(1000, totaal_apparaten, 1000)
                    def haal_blok_op(offset):
                        return requests.get(f"{config.HARDWARE_URL}?limit=1000&offset={offset}", headers=config.headers, timeout=15).json().get('rows', [])

                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        for res in executor.map(haal_blok_op, offsets):
                            alle_assets.extend(res)
                            
            config.CACHE["alle_assets_cache"] = alle_assets
        except Exception as e:
            return {"status": "error", "message": f"Fout: {str(e)}"}

    magazijn_assets, klant_assets = [], []

    for a in alle_assets:
        status_label = a.get('status_label') or {}
        status_meta = str(status_label.get('status_meta', '')).lower()
        asset_company = a.get('company') or {}
        asset_company_id = str(asset_company.get('id', '')) if asset_company else ""

        if status_meta not in ['archived', 'undeployable']:
            item = {
                "id": a['id'], "name": a.get('name') or 'Naamloos', "asset_tag": a.get('asset_tag') or '',
                "serial": a.get('serial') or 'Geen serial', "model": (a.get('model') or {}).get('name', 'Onbekend'),
                "category": (a.get('category') or {}).get('name', 'Onbekend')
            }
            if company_id and asset_company_id == str(company_id): klant_assets.append(item)
            elif not asset_company_id or asset_company_id == "None": magazijn_assets.append(item)

    return {
        "status": "success", 
        "klant_assets": sorted(klant_assets, key=lambda x: (x['category'], x['name'])),
        "magazijn_assets": sorted(magazijn_assets, key=lambda x: (x['category'], x['name']))
    }

def verwerk_pakbon(company_id, klantnaam, referentie, items):
    """Koppelt de apparaten én slaat een archiefkopie van de pakbon op."""
    if not company_id or not items:
        return {"status": "error", "message": "Geen klant of apparaten geselecteerd."}

    success_count = 0
    asset_ids = [item['id'] for item in items]
    
    # 1. Update Snipe-IT
    for aid in asset_ids:
        try:
            resp = requests.patch(f"{config.HARDWARE_URL}/{aid}", json={"company_id": company_id}, headers=config.headers)
            if resp.status_code == 200: success_count += 1
        except: pass

    # 2. Sla de Momentopname op
    timestamp = datetime.now()
    bestandsnaam = f"pakbon_{timestamp.strftime('%Y%m%d_%H%M%S')}_{klantnaam.replace(' ', '_')}.json"
    
    archief_data = {
        "bestandsnaam": bestandsnaam,
        "datum_weergave": timestamp.strftime('%d-%m-%Y %H:%M'),
        "klantnaam": klantnaam,
        "referentie": referentie,
        "items": items # Bewaar de complete lijst van apparaten inclusief serienummers
    }
    
    with open(os.path.join(PAKBON_DIR, bestandsnaam), 'w') as f:
        json.dump(archief_data, f, indent=4)

    config.clear_cache() 
    return {"status": "success", "message": f"{success_count} apparaten gekoppeld en pakbon gearchiveerd."}

def haal_geschiedenis_op():
    """Leest de data map uit om alle oude pakbonnen te tonen."""
    bestanden = []
    if os.path.exists(PAKBON_DIR):
        for f in os.listdir(PAKBON_DIR):
            if f.endswith('.json'):
                try:
                    with open(os.path.join(PAKBON_DIR, f), 'r') as file:
                        bestanden.append(json.load(file))
                except: pass
    
    # Sorteer nieuwste eerst
    bestanden.sort(key=lambda x: x.get('bestandsnaam', ''), reverse=True)
    return bestanden