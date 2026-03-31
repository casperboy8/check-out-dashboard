from flask import Flask, render_template, request, jsonify, Response
import requests
import threading
import time
import json
import os

# Importeer onze eigen opgesplitste bestanden
import config
import snipe_api
import action1_sync
import import_check

app = Flask(__name__)

# ==========================================
# TARIEVEN OPSLAG (NU VEILIG IN /DATA MAP)
# ==========================================
# Zorg dat de data map bestaat als de app opstart
if not os.path.exists('data'):
    os.makedirs('data')

TARIEVEN_FILE = 'data/tarieven.json'

def laad_tarieven():
    if os.path.exists(TARIEVEN_FILE):
        try:
            with open(TARIEVEN_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def bewaar_tarieven(tarieven_dict):
    with open(TARIEVEN_FILE, 'w') as f:
        json.dump(tarieven_dict, f, indent=4)

# ==========================================
# ACHTERGROND WERKPROCESS
# ==========================================
def start_achtergrond_taken():
    def updater():
        time.sleep(5) 
        while True:
            try:
                snipe_api.haal_checkouts_op(force_refresh=True)
                snipe_api.haal_klanten_filters_op(force_refresh=True)
            except Exception as e:
                pass
            time.sleep(60)
            
    thread = threading.Thread(target=updater, daemon=True)
    thread.start()

start_achtergrond_taken()

# ==========================================
# FLASK ROUTES (WEB PAGINA'S)
# ==========================================
@app.route('/')
def index():
    df, db_column_naam = snipe_api.haal_checkouts_op()
    items = df.to_dict(orient='records') if not df.empty else []
    return render_template('index.html', items=items, db_column_naam=db_column_naam)

@app.route('/sync_dashboard')
def sync_dashboard():
    return render_template('sync.html')

@app.route('/klanten_dashboard')
def klanten_dashboard():
    return render_template('klanten.html')

@app.route('/import_dashboard')
def import_dashboard():
    return render_template('import.html')

@app.route('/instellingen_dashboard')
def instellingen_dashboard():
    return render_template('instellingen.html')

# ==========================================
# FLASK ROUTES (API / ACTION1)
# ==========================================
@app.route('/api/get_cached_sync', methods=['GET'])
def api_get_cached_sync():
    if "action1_sync" in config.CACHE:
        return jsonify({"status": "cached", "tijd": config.CACHE["action1_sync"]["tijd_str"], "data": config.CACHE["action1_sync"]["data"]})
    return jsonify({"status": "empty"})

@app.route('/api/run_sync_scan', methods=['GET'])
def api_run_sync_scan():
    return jsonify(action1_sync.voer_sync_scan_uit())

@app.route('/api/apply_sync_fixes', methods=['POST'])
def api_apply_sync_fixes():
    data = request.json
    actie_type = data.get('type')
    items = data.get('items', [])
    success_count = 0
    errors = []

    for item in items:
        try:
            if actie_type == 'rename':
                resp = requests.patch(f"{config.HARDWARE_URL}/{item['snipe_id']}", json={"name": item['a1_naam']}, headers=config.headers)
            elif actie_type == 'update_serial':
                resp = requests.patch(f"{config.HARDWARE_URL}/{item['snipe_id']}", json={"serial": item['a1_serial']}, headers=config.headers)
            elif actie_type == 'update_hardware':
                resp = requests.patch(f"{config.HARDWARE_URL}/{item['snipe_id']}", json=item['updates'], headers=config.headers)
            elif actie_type == 'create_new':
                notes = f"Geïmporteerd vanuit Action1 ({item['bron_instantie']}).\nIP: {item.get('address', '')}\nOS: {item.get('OS', '')}"
                bit = item.get('berekend_bitlocker', '')
                if bit and bit not in ["Geen BitLocker veld", "Niet gevonden / Geen BitLocker", "Geen BitLocker", "Niet Geëncrypt"]:
                    notes += f"\nBitLocker Key: {bit}"
                payload = {
                    "name": item['name'], "asset_tag": f"A1-{item['name']}", "model_id": config.SNIPE_STANDAARD_MODEL_ID,
                    "status_id": config.SNIPE_STANDAARD_STATUS_ID, "notes": notes
                }
                if item.get('berekend_serial') and item['berekend_serial'] != "Niet gevonden": payload["serial"] = item['berekend_serial']
                resp = requests.post(config.HARDWARE_URL, json=payload, headers=config.headers)
            
            if resp.status_code == 200 and resp.json().get('status') == 'success': success_count += 1
            else: errors.append(f"Fout bij {item.get('name', item.get('a1_naam', 'item'))}")
        except Exception as e:
            errors.append(str(e))

    config.clear_action1_cache()
    return jsonify({"status": "success" if success_count > 0 else "error", "success_count": success_count, "errors": errors})

# ==========================================
# FLASK ROUTES (API / SNIPE-IT CHECKOUTS)
# ==========================================
@app.route('/update_status', methods=['POST'])
def update_status():
    data = request.json
    item_id = data.get('item_id')
    if not data.get('db_column') or not data.get('is_asset'): return jsonify({"status": "error", "message": "Fout in request."}), 400
    try:
        resp = requests.patch(f"{config.HARDWARE_URL}/{item_id}", json={data.get('db_column'): "Ja" if data.get('status') else ""}, headers=config.headers)
        if resp.json().get("status") == "success": 
            config.clear_cache()
            return jsonify({"status": "success", "message": f"✅ Opgeslagen!"})
        return jsonify({"status": "error", "message": "Snipe-IT weigert het vinkje."}), 400
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/bulk_update_status', methods=['POST'])
def bulk_update_status():
    data = request.json
    success_count = 0
    waarde = "Ja" if data.get('status') else ""
    for item in data.get('items', []):
        if not item.get('is_asset'): continue
        try:
            if requests.patch(f"{config.HARDWARE_URL}/{item['item_id']}", json={data.get('db_column'): waarde}, headers=config.headers).json().get("status") == "success": success_count += 1
        except: pass
    if success_count > 0: config.clear_cache()
    return jsonify({"status": "success", "success_count": success_count, "errors": []})

# ==========================================
# FLASK ROUTES (PAKBONNEN)
# ==========================================
@app.route('/pakbon_dashboard')
def pakbon_dashboard():
    return render_template('pakbon.html')

# Voeg deze functies toe aan je app.py (vervang de oude pakbon routes)

@app.route('/pakbon_dashboard')
def pakbon_dashboard():
    return render_template('pakbon.html')

@app.route('/api/get_pakbon_data', methods=['POST'])
def api_get_pakbon_data():
    """Haalt zowel klant-assets als magazijn-assets op voor de pakbon."""
    data = request.json
    company_id = data.get('company_id')
    
    # 1. Haal alle assets op (we filteren ze zelf voor snelheid)
    alle_assets = []
    offset = 0
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

    return jsonify({
        "status": "success", 
        "klant_assets": sorted(klant_assets, key=lambda x: (x['category'], x['name'])),
        "magazijn_assets": sorted(magazijn_assets, key=lambda x: (x['category'], x['name']))
    })

@app.route('/api/verwerk_pakbon', methods=['POST'])
def api_verwerk_pakbon():
    """Koppelt de geselecteerde apparaten aan de gekozen klant in Snipe-IT."""
    data = request.json
    company_id = data.get('company_id')
    asset_ids = data.get('asset_ids', [])

    if not company_id or not asset_ids:
        return jsonify({"status": "error", "message": "Geen klant of apparaten geselecteerd."})

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
    return jsonify({"status": "success", "message": f"{success_count} apparaten gekoppeld aan klant."})

# ==========================================
# FLASK ROUTES (API / KLANTEN & INSTELLINGEN)
# ==========================================
@app.route('/api/get_klanten_filters', methods=['GET'])
def api_get_klanten_filters():
    return jsonify(snipe_api.haal_klanten_filters_op())

@app.route('/api/get_snipe_categories', methods=['GET'])
def api_get_snipe_categories():
    try:
        url = f"{config.BASE_URL}/categories"
        resp = requests.get(url, headers=config.headers)
        if resp.status_code == 200:
            categories = [c['name'] for c in resp.json().get('rows', [])]
            return jsonify({"status": "success", "categories": sorted(categories)})
        return jsonify({"status": "error", "message": "Kon categorieën niet laden."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route('/api/get_tarieven', methods=['GET'])
def api_get_tarieven():
    return jsonify(laad_tarieven())

@app.route('/api/save_tarieven', methods=['POST'])
def api_save_tarieven():
    data = request.json
    bewaar_tarieven(data)
    return jsonify({"status": "success"})

@app.route('/api/get_klant_inventaris', methods=['POST'])
def api_get_klant_inventaris():
    data = request.json
    company_id = data.get('company_id')
    category_id = data.get('category_id')

    if not company_id: return jsonify({"status": "error", "message": "Geen klant geselecteerd."})

    alle_assets = []
    offset = 0
    limit = 1000

    while True:
        url = f"{config.HARDWARE_URL}?company_id={company_id}&limit={limit}&offset={offset}"
        if category_id and category_id != 'all':
            url += f"&category_id={category_id}"

        resp = requests.get(url, headers=config.headers)
        if resp.status_code != 200: break
        rows = resp.json().get('rows', [])
        if not rows: break
        
        alle_assets.extend(rows)
        offset += limit

    inventaris = {}
    tarieven = laad_tarieven()

    for asset in alle_assets:
        cat_name = asset.get('category', {}).get('name', 'Onbekend') if asset.get('category') else 'Onbekend'
        model_name = asset.get('model', {}).get('name', 'Onbekend') if asset.get('model') else 'Onbekend'

        # FIX: Sla alles zonder facturatie-prijs direct over!
        if float(tarieven.get(cat_name, 0.0)) <= 0:
            continue

        if cat_name not in inventaris: inventaris[cat_name] = {}
        if model_name not in inventaris[cat_name]: inventaris[cat_name][model_name] = 0
        
        inventaris[cat_name][model_name] += 1

    totale_maandkosten = 0.0
    totaal_aantal = 0
    resultaat_lijst = []
    categorie_samenvatting = {}

    for cat, modellen in inventaris.items():
        prijs_per_stuk = float(tarieven.get(cat, 0.0))
        cat_totaal_aantal = 0
        
        for mod, count in modellen.items():
            regel_totaal = prijs_per_stuk * count
            totale_maandkosten += regel_totaal
            cat_totaal_aantal += count
            totaal_aantal += count
            resultaat_lijst.append({
                "categorie": cat, 
                "model": mod, 
                "aantal": count,
                "prijs_per_stuk": prijs_per_stuk,
                "totaal_prijs": regel_totaal
            })
            
        categorie_samenvatting[cat] = {
            "aantal": cat_totaal_aantal,
            "totaal_prijs": cat_totaal_aantal * prijs_per_stuk
        }

    resultaat_lijst = sorted(resultaat_lijst, key=lambda x: (x['categorie'], -x['aantal']))

    return jsonify({
        "status": "success",
        "data": resultaat_lijst,
        "totaal": totaal_aantal,
        "maandkosten": totale_maandkosten,
        "samenvatting": categorie_samenvatting
    })

@app.route('/api/get_alle_klanten_facturatie', methods=['GET'])
def api_get_alle_klanten_facturatie():
    alle_assets = []
    offset = 0
    limit = 1000
    
    while True:
        url = f"{config.HARDWARE_URL}?limit={limit}&offset={offset}"
        resp = requests.get(url, headers=config.headers)
        if resp.status_code != 200: break
        rows = resp.json().get('rows', [])
        if not rows: break
        alle_assets.extend(rows)
        offset += limit

    tarieven = laad_tarieven()
    klant_data = {}

    for asset in alle_assets:
        status_meta = str(asset.get('status_label', {}).get('status_meta', '')).lower()
        if status_meta in ['archived', 'undeployable']:
            continue

        cat = asset.get('category')
        cat_name = cat.get('name') if cat else "Onbekend"
        prijs_per_stuk = float(tarieven.get(cat_name, 0.0))

        # FIX: Sla alles zonder facturatie-prijs direct over!
        if prijs_per_stuk <= 0:
            continue

        comp = asset.get('company')
        comp_name = comp.get('name') if comp else "Zonder Klant / Intern"
        
        if comp_name not in klant_data:
            klant_data[comp_name] = {"totaal_apparaten": 0, "totale_kosten": 0.0, "categorieen": {}}
            
        if cat_name not in klant_data[comp_name]["categorieen"]:
            klant_data[comp_name]["categorieen"][cat_name] = 0
            
        klant_data[comp_name]["categorieen"][cat_name] += 1
        klant_data[comp_name]["totaal_apparaten"] += 1
        klant_data[comp_name]["totale_kosten"] += prijs_per_stuk

    resultaat = []
    for klant, data in klant_data.items():
        cat_str_list = []
        gesorteerde_cats = sorted(data["categorieen"].items(), key=lambda item: item[1], reverse=True)
        for c, count in gesorteerde_cats:
            cat_str_list.append(f"{count}x {c}")
        
        resultaat.append({
            "klantnaam": klant,
            "totaal_apparaten": data["totaal_apparaten"],
            "totale_kosten": data["totale_kosten"],
            "samenvatting": ", ".join(cat_str_list)
        })
        
    resultaat = sorted(resultaat, key=lambda x: x['totale_kosten'], reverse=True)
    return jsonify({"status": "success", "data": resultaat})

# ==========================================
# FLASK ROUTES (API / IMPORT EN DEBUG)
# ==========================================
@app.route('/api/upload_check', methods=['POST'])
def api_upload_check():
    if 'file' not in request.files: return jsonify({"status": "error", "message": "Geen bestand geüpload."}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"status": "error", "message": "Geen bestand geselecteerd."}), 400
    if not file.filename.lower().endswith(('.csv', '.xlsx', '.xls')): return jsonify({"status": "error", "message": "Alleen .xlsx, .xls of .csv bestanden zijn toegestaan."}), 400
        
    file_bytes = file.read()
    return jsonify(import_check.controleer_upload(file_bytes, file.filename))

@app.route('/api/download_snipe_raw', methods=['GET'])
def api_download_snipe_raw():
    try:
        assets = import_check.haal_snipe_assets_op()
        return Response(json.dumps(assets, indent=4), mimetype="application/json", headers={"Content-disposition": "attachment; filename=snipe_raw_export.json"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)