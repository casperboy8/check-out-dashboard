import requests
import config

def get_pakbon_data(company_id):
    """Haalt zowel klant-assets als magazijn-assets op voor de pakbon."""
    alle_assets = []
    offset = 0
    
    # Haal alle assets op
    while True:
        url = f"{config.HARDWARE_URL}?limit=500&offset={offset}&sort=id&order=asc"
        resp = requests.get(url, headers=config.headers)
        if resp.status_code != 200: break
        rows = resp.json().get('rows', [])
        if not rows: break
        alle_assets.extend(rows)
        offset += 500
        if offset >= resp.json().get('total', 0): break

    magazijn_assets = []
    klant_assets = []

    for a in alle_assets:
        status_meta = str(a.get('status_label', {}).get('status_meta', '')).lower()
        asset_company = a.get('company', {})
        asset_company_id = str(asset_company.get('id', '')) if asset_company else ""

        # Alleen inzetbare items (niet gearchiveerd/defect)
        if status_meta not in ['archived', 'undeployable']:
            item = {
                "id": a['id'],
                "name": a.get('name') or 'Naamloos',
                "asset_tag": a.get('asset_tag') or '',
                "serial": a.get('serial') or 'Geen serial',
                "model": a.get('model', {}).get('name', 'Onbekend') if a.get('model') else 'Onbekend',
                "category": a.get('category', {}).get('name', 'Onbekend') if a.get('category') else 'Onbekend'
            }
            
            # Is het al van deze klant?
            if company_id and asset_company_id == str(company_id):
                klant_assets.append(item)
            # Of is het nog vrij in het magazijn?
            elif not asset_company_id or asset_company_id == "None":
                magazijn_assets.append(item)

    return {
        "status": "success", 
        "klant_assets": sorted(klant_assets, key=lambda x: (x['category'], x['name'])),
        "magazijn_assets": sorted(magazijn_assets, key=lambda x: (x['category'], x['name']))
    }

def verwerk_pakbon(company_id, asset_ids):
    """Koppelt de geselecteerde apparaten aan de gekozen klant in Snipe-IT."""
    if not company_id or not asset_ids:
        return {"status": "error", "message": "Geen klant of apparaten geselecteerd."}

    success_count = 0
    for aid in asset_ids:
        try:
            # We PATCHEN alleen de company_id, de status blijft hetzelfde!
            resp = requests.patch(
                f"{config.HARDWARE_URL}/{aid}", 
                json={"company_id": company_id}, 
                headers=config.headers
            )
            if resp.status_code == 200:
                success_count += 1
        except:
            pass

    config.clear_cache() # Vernieuw cache zodat wijziging direct zichtbaar is
    return {"status": "success", "message": f"{success_count} apparaten gekoppeld aan klant."}