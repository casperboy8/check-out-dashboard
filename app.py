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
import pakbon  # <--- Onze nieuwe module!

app = Flask(__name__)

# ==========================================
# TARIEVEN OPSLAG
# ==========================================
if not os.path.exists('data'):
    os.makedirs('data')

TARIEVEN_FILE = 'data/tarieven.json'

def laad_tarieven():
    if os.path.exists(TARIEVEN_FILE):
        try:
            with open(TARIEVEN_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def bewaar_tarieven(tarieven_dict):
    with open(TARIEVEN_FILE, 'w') as f: json.dump(tarieven_dict, f, indent=4)

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
            except: pass
            time.sleep(60)
    threading.Thread(target=updater, daemon=True).start()

start_achtergrond_taken()

# ==========================================
# FLASK ROUTES (WEB PAGINA'S)
# ==========================================
@app.route('/')
def index():
    df, db_column_naam = snipe_api.haal_checkouts_op()
    return render_template('index.html', items=df.to_dict(orient='records') if not df.empty else [], db_column_naam=db_column_naam)

@app.route('/sync_dashboard')
def sync_dashboard(): return render_template('sync.html')

@app.route('/klanten_dashboard')
def klanten_dashboard(): return render_template('klanten.html')

@app.route('/import_dashboard')
def import_dashboard(): return render_template('import.html')

@app.route('/instellingen_dashboard')
def instellingen_dashboard(): return render_template('instellingen.html')

@app.route('/pakbon_dashboard')
def pakbon_dashboard(): return render_template('pakbon.html')

# ==========================================
# FLASK ROUTES (API / PAKBONNEN)
# ==========================================
@app.route('/api/get_pakbon_data', methods=['POST'])
def api_get_pakbon_data():
    return jsonify(pakbon.get_pakbon_data(request.json.get('company_id')))

@app.route('/api/verwerk_pakbon', methods=['POST'])
def api_verwerk_pakbon():
    data = request.json
    return jsonify(pakbon.verwerk_pakbon(data.get('company_id'), data.get('asset_ids', [])))

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

    for item in items:
        try:
            if actie_type == 'rename':
                requests.patch(f"{config.HARDWARE_URL}/{item['snipe_id']}", json={"name": item['a1_naam']}, headers=config.headers)
                success_count += 1
            elif actie_type == 'update_serial':
                requests.patch(f"{config.HARDWARE_URL}/{item['snipe_id']}", json={"serial": item['a1_serial']}, headers=config.headers)
                success_count += 1
            elif actie_type == 'create_new':
                extra = item.get('extra_data', {})
                from datetime import datetime
                notes_text = (
                    f"🤖 ACTION1 IMPORT - {datetime.now().strftime('%d-%m-%Y')}\n"
                    f"------------------------------------------\n"
                    f"💻 Model: {extra.get('Model')}\n"
                    f"🏢 Fabrikant: {extra.get('Fabrikant')}\n"
                    f"💿 OS: {extra.get('OS_Naam')} (Versie: {extra.get('OS_Versie')})\n"
                    f"🧠 CPU: {extra.get('CPU')}\n"
                    f"📟 RAM: {extra.get('RAM')}\n"
                    f"🎮 GPU: {extra.get('GPU')}\n"
                    f"💽 Disk Totaal: {extra.get('Disk_Total_GB')} GB\n"
                    f"📂 Disk Vrij: {extra.get('Disk_Free_GB')} GB\n"
                    f"🔗 MAC: {extra.get('MAC')}\n"
                    f"🌐 IP: {item.get('address')}\n"
                    f"🕒 Laatst online: {extra.get('Last_Seen')}\n"
                )
                bit = item.get('berekend_bitlocker', '')
                if bit and bit != "Niet gevonden": notes_text += f"\n🔐 BitLocker Key: {bit}"

                payload = {
                    "name": item['name'], "asset_tag": f"A1-{item['name']}",
                    "model_id": config.SNIPE_STANDAARD_MODEL_ID, "status_id": config.SNIPE_STANDAARD_STATUS_ID,
                    "notes": notes_text, "serial": item.get('berekend_serial')
                }
                resp = requests.post(config.HARDWARE_URL, json=payload, headers=config.headers)
                if resp.status_code == 200: success_count += 1
        except: pass

    config.clear_action1_cache()
    return jsonify({"status": "success", "success_count": success_count})

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
            return jsonify({"status": "success"})
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
    return jsonify({"status": "success", "success_count": success_count})

# ==========================================
# FLASK ROUTES (API / KLANTEN & INSTELLINGEN)
# ==========================================
@app.route('/api/get_klanten_filters', methods=['GET'])
def api_get_klanten_filters(): return jsonify(snipe_api.haal_klanten_filters_op())

@app.route('/api/get_snipe_categories', methods=['GET'])
def api_get_snipe_categories():
    try:
        resp = requests.get(f"{config.BASE_URL}/categories", headers=config.headers)
        return jsonify({"status": "success", "categories": sorted([c['name'] for c in resp.json().get('rows', [])])}) if resp.status_code == 200 else jsonify({"status": "error"})
    except: return jsonify({"status": "error"})

@app.route('/api/get_tarieven', methods=['GET'])
def api_get_tarieven(): return jsonify(laad_tarieven())

@app.route('/api/save_tarieven', methods=['POST'])
def api_save_tarieven():
    bewaar_tarieven(request.json)
    return jsonify({"status": "success"})

@app.route('/api/get_klant_inventaris', methods=['POST'])
def api_get_klant_inventaris():
    data = request.json
    company_id = data.get('company_id')
    category_id = data.get('category_id')

    if not company_id: return jsonify({"status": "error", "message": "Geen klant geselecteerd."})

    alle_assets = []
    offset = 0
    while True:
        url = f"{config.HARDWARE_URL}?company_id={company_id}&limit=1000&offset={offset}"
        if category_id and category_id != 'all': url += f"&category_id={category_id}"
        resp = requests.get(url, headers=config.headers)
        if resp.status_code != 200: break
        rows = resp.json().get('rows', [])
        if not rows: break
        alle_assets.extend(rows)
        offset += 1000

    inventaris = {}
    tarieven = laad_tarieven()

    for asset in alle_assets:
        cat_name = asset.get('category', {}).get('name', 'Onbekend') if asset.get('category') else 'Onbekend'
        model_name = asset.get('model', {}).get('name', 'Onbekend') if asset.get('model') else 'Onbekend'
        if float(tarieven.get(cat_name, 0.0)) <= 0: continue
        if cat_name not in inventaris: inventaris[cat_name] = {}
        if model_name not in inventaris[cat_name]: inventaris[cat_name][model_name] = 0
        inventaris[cat_name][model_name] += 1

    totale_maandkosten, totaal_aantal, resultaat_lijst, categorie_samenvatting = 0.0, 0, [], {}

    for cat, modellen in inventaris.items():
        pps = float(tarieven.get(cat, 0.0))
        cat_totaal = 0
        for mod, count in modellen.items():
            totale_maandkosten += pps * count
            cat_totaal += count
            totaal_aantal += count
            resultaat_lijst.append({"categorie": cat, "model": mod, "aantal": count, "prijs_per_stuk": pps, "totaal_prijs": pps * count})
        categorie_samenvatting[cat] = {"aantal": cat_totaal, "totaal_prijs": cat_totaal * pps}

    return jsonify({"status": "success", "data": sorted(resultaat_lijst, key=lambda x: (x['categorie'], -x['aantal'])), "totaal": totaal_aantal, "maandkosten": totale_maandkosten, "samenvatting": categorie_samenvatting})

@app.route('/api/get_alle_klanten_facturatie', methods=['GET'])
def api_get_alle_klanten_facturatie():
    alle_assets = []
    offset = 0
    while True:
        resp = requests.get(f"{config.HARDWARE_URL}?limit=1000&offset={offset}", headers=config.headers)
        if resp.status_code != 200: break
        rows = resp.json().get('rows', [])
        if not rows: break
        alle_assets.extend(rows)
        offset += 1000

    tarieven = laad_tarieven()
    klant_data = {}

    for asset in alle_assets:
        if str(asset.get('status_label', {}).get('status_meta', '')).lower() in ['archived', 'undeployable']: continue
        cat_name = asset.get('category', {}).get('name', 'Onbekend') if asset.get('category') else "Onbekend"
        pps = float(tarieven.get(cat_name, 0.0))
        if pps <= 0: continue
        comp_name = asset.get('company', {}).get('name', "Zonder Klant / Intern") if asset.get('company') else "Zonder Klant / Intern"
        
        if comp_name not in klant_data: klant_data[comp_name] = {"totaal_apparaten": 0, "totale_kosten": 0.0, "categorieen": {}}
        if cat_name not in klant_data[comp_name]["categorieen"]: klant_data[comp_name]["categorieen"][cat_name] = 0
        klant_data[comp_name]["categorieen"][cat_name] += 1
        klant_data[comp_name]["totaal_apparaten"] += 1
        klant_data[comp_name]["totale_kosten"] += pps

    resultaat = [{"klantnaam": k, "totaal_apparaten": v["totaal_apparaten"], "totale_kosten": v["totale_kosten"], "samenvatting": ", ".join([f"{c}x {cat}" for cat, c in sorted(v["categorieen"].items(), key=lambda i: i[1], reverse=True)])} for k, v in klant_data.items()]
    return jsonify({"status": "success", "data": sorted(resultaat, key=lambda x: x['totale_kosten'], reverse=True)})

# ==========================================
# FLASK ROUTES (API / IMPORT EN DEBUG)
# ==========================================
@app.route('/api/upload_check', methods=['POST'])
def api_upload_check():
    if 'file' not in request.files or request.files['file'].filename == '': return jsonify({"status": "error", "message": "Geen bestand geüpload."}), 400
    file = request.files['file']
    return jsonify(import_check.controleer_upload(file.read(), file.filename))

@app.route('/api/download_snipe_raw', methods=['GET'])
def api_download_snipe_raw():
    try: return Response(json.dumps(import_check.haal_snipe_assets_op(), indent=4), mimetype="application/json", headers={"Content-disposition": "attachment; filename=snipe_raw_export.json"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)