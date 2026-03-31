import requests
import concurrent.futures
import config

def get_pakbon_data(company_id):
    """Haalt pijlsnel klant-assets en magazijn-assets op via caching en multithreading."""
    alle_assets = []
    
    # 1. GEBRUIK HET GEHEUGEN (Razendsnel schakelen tussen klanten)
    if "alle_assets_cache" in config.CACHE:
        alle_assets = config.CACHE["alle_assets_cache"]
    else:
        # 2. GEEN CACHE? Haal alles razendsnel parallel op
        try:
            # Doe de eerste call om te kijken hoeveel apparaten er in totaal zijn
            eerste_url = f"{config.HARDWARE_URL}?limit=1000&offset=0"
            eerste_resp = requests.get(eerste_url, headers=config.headers, timeout=15)
            
            if eerste_resp.status_code == 200:
                data = eerste_resp.json()
                alle_assets.extend(data.get('rows', []))
                totaal_apparaten = data.get('total', 0)
                
                # Als er meer dan 1000 apparaten zijn, haal de rest tegelijkertijd (parallel) op
                if totaal_apparaten > 1000:
                    offsets = range(1000, totaal_apparaten, 1000)
                    
                    def haal_blok_op(offset):
                        u = f"{config.HARDWARE_URL}?limit=1000&offset={offset}"
                        return requests.get(u, headers=config.headers, timeout=15).json().get('rows', [])

                    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                        resultaten = executor.map(haal_blok_op, offsets)
                        for res in resultaten:
                            alle_assets.extend(res)
                            
            # Sla de complete lijst op in de cache voor de volgende klik
            config.CACHE["alle_assets_cache"] = alle_assets
        except Exception as e:
            return {"status": "error", "message": f"Fout bij verbinden met Snipe-IT: {str(e)}"}

    # 3. VERDEEL DE DATA (Dit gebeurt lokaal en duurt letterlijk milliseconden)
    magazijn_assets = []
    klant_assets = []

    for a in alle_assets:
        status_label = a.get('status_label') or {}
        status_meta = str(status_label.get('status_meta', '')).lower()
        
        asset_company = a.get('company') or {}
        asset_company_id = str(asset_company.get('id', '')) if asset_company else ""

        # Negeer alles wat in de prullenbak of in de reparatie ligt
        if status_meta not in ['archived', 'undeployable']:
            model_data = a.get('model') or {}
            category_data = a.get('category') or {}
            
            item = {
                "id": a['id'],
                "name": a.get('name') or 'Naamloos',
                "asset_tag": a.get('asset_tag') or '',
                "serial": a.get('serial') or 'Geen serial',
                "model": model_data.get('name', 'Onbekend'),
                "category": category_data.get('name', 'Onbekend')
            }
            
            # Is het al van deze klant?
            if company_id and asset_company_id == str(company_id):
                klant_assets.append(item)
            # Of ligt het nog in het magazijn (geen eigenaar)?
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

    # BELANGRIJK: Leeg het geheugen! 
    # De volgende keer dat iemand op een klant klikt, wordt de verse lijst gehaald.
    config.clear_cache() 
    return {"status": "success", "message": f"{success_count} apparaten gekoppeld aan klant."}