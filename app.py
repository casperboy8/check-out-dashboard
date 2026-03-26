from flask import Flask, render_template, request, jsonify, Response
import requests
import threading
import time
import json

# Importeer onze eigen opgesplitste bestanden
import config
import snipe_api
import action1_sync
import import_check

app = Flask(__name__)

# ==========================================
# ACHTERGROND WERKPROCESS (BACKGROUND WORKER)
# ==========================================
def start_achtergrond_taken():
    def updater():
        time.sleep(5) 
        while True:
            try:
                snipe_api.haal_checkouts_op(force_refresh=True)
                snipe_api.haal_klanten_filters_op(force_refresh=True)
            except Exception as e:
                print(f"Let op: Fout in achtergrondtaak: {e}")
            time.sleep(60)
            
    thread = threading.Thread(target=updater, daemon=True)
    thread.start()

start_achtergrond_taken()

# ==========================================
# FLASK ROUTES (WEB PAgINA'S)
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
    result = action1_sync.voer_sync_scan_uit()
    return jsonify(result)

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
# FLASK ROUTES (API / KLANTEN)
# ==========================================
@app.route('/api/get_klanten_filters', methods=['GET'])
def api_get_klanten_filters():
    return jsonify(snipe_api.haal_klanten_filters_op())

@app.route('/api/get_klant_inventaris', methods=['POST'])
def api_get_klant_inventaris():
    data = request.json
    company_id = data.get('company_id')
    category_id = data.get('category_id')

    if not company_id:
        return jsonify({"status": "error", "message": "Geen klant geselecteerd."})

    alle_assets = []
    offset = 0
    limit = 1000

    while True:
        url = f"{config.HARDWARE_URL}?company_id={company_id}&limit={limit}&offset={offset}"
        if category_id and category_id != 'all':
            url += f"&category_id={category_id}"

        resp = requests.get(url, headers=config.headers)
        if resp.status_code != 200:
            break
        
        rows = resp.json().get('rows', [])
        if not rows:
            break
        
        alle_assets.extend(rows)
        offset += limit

    inventaris = {}
    totaal_aantal = 0

    for asset in alle_assets:
        cat_name = asset.get('category', {}).get('name', 'Onbekend') if asset.get('category') else 'Onbekend'
        model_name = asset.get('model', {}).get('name', 'Onbekend') if asset.get('model') else 'Onbekend'

        if cat_name not in inventaris:
            inventaris[cat_name] = {}
        if model_name not in inventaris[cat_name]:
            inventaris[cat_name][model_name] = 0
        
        inventaris[cat_name][model_name] += 1
        totaal_aantal += 1

    resultaat_lijst = []
    for cat, modellen in inventaris.items():
        for mod, count in modellen.items():
            resultaat_lijst.append({"categorie": cat, "model": mod, "aantal": count})

    resultaat_lijst = sorted(resultaat_lijst, key=lambda x: (x['categorie'], -x['aantal']))

    return jsonify({
        "status": "success",
        "data": resultaat_lijst,
        "totaal": totaal_aantal
    })

# ==========================================
# FLASK ROUTES (API / IMPORT EN DEBUG)
# ==========================================
@app.route('/api/upload_check', methods=['POST'])
def api_upload_check():
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Geen bestand geüpload."}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "error", "message": "Geen bestand geselecteerd."}), 400
        
    if not file.filename.lower().endswith(('.csv', '.xlsx', '.xls')):
        return jsonify({"status": "error", "message": "Alleen .xlsx, .xls of .csv bestanden zijn toegestaan."}), 400
        
    resultaat = import_check.controleer_upload(file, file.filename)
    return jsonify(resultaat)

@app.route('/api/download_snipe_raw', methods=['GET'])
def api_download_snipe_raw():
    """Downloadt de exacte, ruwe JSON array die vanuit Snipe-IT wordt opgevangen."""
    try:
        assets = import_check.haal_snipe_assets_op()
        return Response(
            json.dumps(assets, indent=4),
            mimetype="application/json",
            headers={"Content-disposition": "attachment; filename=snipe_raw_export.json"}
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)