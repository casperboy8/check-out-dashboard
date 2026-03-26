import pandas as pd
import requests
import config
import re
import io

def haal_snipe_assets_op():
    alle_assets = []
    geziene_ids = set()
    api_filters = ["", "&deleted=true"]
    
    try:
        status_url = f"{config.BASE_URL}/statuslabels"
        s_resp = requests.get(status_url, headers=config.headers, timeout=10)
        if s_resp.status_code == 200:
            for label in s_resp.json().get('rows', []):
                if label.get('type') == 'archived':
                    api_filters.append(f"&status_id={label['id']}")
    except Exception as e:
        pass

    for api_filter in api_filters:
        limit = 500
        offset = 0
        while True:
            try:
                url = f"{config.HARDWARE_URL}?limit={limit}&offset={offset}&sort=id&order=asc{api_filter}"
                response = requests.get(url, headers=config.headers, timeout=30)
                if response.status_code != 200: break
                
                data = response.json()
                rows = data.get('rows', [])
                if not rows: break
                
                for asset in rows:
                    if asset['id'] not in geziene_ids:
                        geziene_ids.add(asset['id'])
                        alle_assets.append(asset)
                        
                offset += limit
                if offset >= data.get('total', 0): break
            except:
                break
                
    return alle_assets

def super_clean(val):
    """Verwijder alle niet-alphanumerieke tekens voor een zuivere match."""
    if val is None or pd.isna(val): return ""
    return re.sub(r'[^a-z0-9]', '', str(val).lower())

def verwerk_inventaris(df, snipe_assets, by_serial, by_name, by_tag):
    df = df.fillna('')
    headers = list(df.columns)
    
    n_col = next((c for c in headers if any(x in str(c).lower() for x in ['pc-naam', 'pc naam', 'naam', 'hostname', 'endpoint', 'apparaat', 'product'])), None)
    s_col = next((c for c in headers if any(x in str(c).lower() for x in ['serienummer', 'serial', 'serie', 'sn'])), None)
    c_col = next((c for c in headers if any(x in str(c).lower() for x in ['bedrijf', 'company', 'klant', 'tenant', 'relatie'])), None)
    m_col = next((c for c in headers if any(x in str(c).lower() for x in ['merk', 'manufacturer', 'fabrikant'])), None)
    mod_col = next((c for c in headers if any(x in str(c).lower() for x in ['model'])), None)
    
    gekoppelde_ids = set()
    gevonden_lijst = []
    missend_lijst = []
    
    for index, row in df.iterrows():
        if all(str(val).strip() == '' for val in row.values): continue

        excel_naam = str(row[n_col]).strip() if n_col else ""
        excel_serial = str(row[s_col]).strip() if s_col else ""
        
        e_n_clean = super_clean(excel_naam)
        e_s_clean = super_clean(excel_serial)
        
        match_gevonden = None

        if e_s_clean and e_s_clean in by_serial:
            for a in by_serial[e_s_clean]:
                if a['id'] not in gekoppelde_ids: match_gevonden = a; break
        if not match_gevonden and e_n_clean and e_n_clean in by_name:
            for a in by_name[e_n_clean]:
                if a['id'] not in gekoppelde_ids: match_gevonden = a; break
        if not match_gevonden and e_n_clean and e_n_clean in by_tag:
            for a in by_tag[e_n_clean]:
                if a['id'] not in gekoppelde_ids: match_gevonden = a; break

        item_info = {
            "rij": index + 2, 
            "naam": excel_naam, 
            "serial": excel_serial,
            "bedrijf": str(row[c_col]).strip() if c_col else "",
            "merk": str(row[m_col]).strip() if m_col else "",
            "model": str(row[mod_col]).strip() if mod_col else ""
        }
        
        if match_gevonden:
            gekoppelde_ids.add(match_gevonden['id'])
            s_company = match_gevonden.get('company', {})
            s_manufacturer = match_gevonden.get('manufacturer', {})
            s_model_data = match_gevonden.get('model', {})
            
            item_info['bedrijf'] = s_company.get('name', '') if s_company else item_info['bedrijf']
            item_info['merk'] = s_manufacturer.get('name', '') if s_manufacturer else item_info['merk']
            item_info['model'] = s_model_data.get('name', '') if s_model_data else item_info['model']

            status_label = match_gevonden.get('status_label')
            item_info['status'] = status_label.get('name', 'Onbekend') if status_label else 'Geen Status'
            if match_gevonden.get('deleted_at'): item_info['status'] = "Verwijderd"
                
            gevonden_lijst.append(item_info)
        else:
            missend_lijst.append(item_info)

    spook_lijst = []
    for asset in snipe_assets:
        if asset['id'] not in gekoppelde_ids:
            status_label = asset.get('status_label')
            status_naam = status_label.get('name', 'Geen status') if status_label else 'Geen status'
            if asset.get('deleted_at'): status_naam = "Verwijderd"
            s_company = asset.get('company', {})
            s_manufacturer = asset.get('manufacturer', {})
            s_model_data = asset.get('model', {})

            spook_lijst.append({
                "tag": asset.get('asset_tag'),
                "naam": asset.get('name') or "[Geen naam]",
                "serial": asset.get('serial') or "[Geen serial]",
                "status": status_naam,
                "bedrijf": s_company.get('name', '') if s_company else "",
                "merk": s_manufacturer.get('name', '') if s_manufacturer else "",
                "model": s_model_data.get('name', '') if s_model_data else ""
            })

    return {
        "totaal_excel": len(gevonden_lijst) + len(missend_lijst),
        "gevonden": gevonden_lijst,
        "missend": missend_lijst,
        "spook": spook_lijst
    }

def verwerk_uitgegeven(df, snipe_assets, by_serial, by_name, by_tag):
    df = df.fillna('')
    headers = list(df.columns)
    
    n_col = next((c for c in headers if any(x in str(c).lower() for x in ['naam', 'product', 'pc-naam', 'apparaat', 'asset'])), None)
    s_col = next((c for c in headers if any(x in str(c).lower() for x in ['serienummer', 'serial', 'serie', 'sn'])), None)
    k_col = next((c for c in headers if any(x in str(c).lower() for x in ['klant', 'company', 'bedrijf', 'relatie', 'tenant'])), None)
    f_col = next((c for c in headers if any(x in str(c).lower() for x in ['fact', 'gefactureerd', 'betaald'])), None)

    perfect_lijst = []
    afwijking_lijst = []
    missend_lijst = []
    gekoppelde_ids = set()

    for index, row in df.iterrows():
        if all(str(val).strip() == '' for val in row.values): continue
        
        val_naam = str(row[n_col]).strip() if n_col else ""
        val_serial = str(row[s_col]).strip() if s_col else ""
        val_klant = str(row[k_col]).strip() if k_col else ""
        val_fact = str(row[f_col]).strip().lower() if f_col else ""
        
        excel_fact_bool = val_fact in ['1', 'yes', 'ja', 'true', 'v', 'x', 'on', 'j', 'y', 'waar']
        
        e_n_clean = super_clean(val_naam)
        e_s_clean = super_clean(val_serial)
        
        match_gevonden = None
        if e_s_clean and e_s_clean in by_serial:
            for a in by_serial[e_s_clean]:
                if a['id'] not in gekoppelde_ids: match_gevonden = a; break
        if not match_gevonden and e_n_clean and e_n_clean in by_name:
            for a in by_name[e_n_clean]:
                if a['id'] not in gekoppelde_ids: match_gevonden = a; break
        if not match_gevonden and e_n_clean and e_n_clean in by_tag:
            for a in by_tag[e_n_clean]:
                if a['id'] not in gekoppelde_ids: match_gevonden = a; break

        item_info = {
            "rij": index + 2,
            "naam": val_naam or "[Geen naam]",
            "serial": val_serial,
            "klant_excel": val_klant,
            "fact_excel": "Ja" if excel_fact_bool else "Nee"
        }

        if match_gevonden:
            gekoppelde_ids.add(match_gevonden['id'])
            
            snipe_klant = match_gevonden.get('company', {}).get('name', '') if match_gevonden.get('company') else ""
            
            # --- VERNIEUWDE UITGECHECKT LOGICA ---
            assigned_to = match_gevonden.get('assigned_to')
            status_label = match_gevonden.get('status_label', {})
            status_meta = str(status_label.get('status_meta', '')).lower()
            status_naam_str = str(status_label.get('name', '')).lower()
            
            is_uitgecheckt = False
            # 1. Is hij hard aan een user/location gekoppeld?
            if assigned_to is not None: 
                is_uitgecheckt = True
            # 2. Is de API meta-status 'deployed'?
            elif status_meta == 'deployed':
                is_uitgecheckt = True
            # 3. Klinkt de statusnaam alsof hij is uitgegeven? (Jouw handmatige statussen)
            elif any(woord in status_naam_str for woord in ['uitgegeven', 'in gebruik', 'klant']):
                is_uitgecheckt = True
            
            # --- FACTURATIE LOGICA ---
            snipe_gefactureerd_bool = False
            custom_fields = match_gevonden.get('custom_fields')
            if isinstance(custom_fields, dict):
                for k, v in custom_fields.items():
                    if isinstance(v, dict):
                        field_name = str(v.get('field', '')).lower()
                        k_lower = str(k).lower()
                        if 'fact' in k_lower or 'gefactureerd' in k_lower or 'fact' in field_name or 'gefactureerd' in field_name:
                            v_val = str(v.get('value')).lower().strip()
                            if v_val in ['1', 'yes', 'ja', 'true', 'v', 'x', 'on', 'j', 'y', 'waar']:
                                snipe_gefactureerd_bool = True
                            break
            
            afwijkingen = []
            
            # Vergelijk bedrijf (met normale opschoning)
            if super_clean(val_klant) not in super_clean(snipe_klant) and super_clean(snipe_klant) not in super_clean(val_klant):
                afwijkingen.append("Klant mismatch")
                
            if not is_uitgecheckt:
                afwijkingen.append("Niet uitgecheckt")
                
            if excel_fact_bool != snipe_gefactureerd_bool:
                afwijkingen.append("Factuur mismatch")
                
            item_info['snipe_klant'] = snipe_klant
            item_info['uitgecheckt'] = "Ja" if is_uitgecheckt else "Nee"
            item_info['fact_snipe'] = "Ja" if snipe_gefactureerd_bool else "Nee"
            item_info['afwijkingen'] = afwijkingen
            
            if len(afwijkingen) > 0:
                afwijking_lijst.append(item_info)
            else:
                perfect_lijst.append(item_info)
        else:
            missend_lijst.append(item_info)

    return {
        "totaal_excel": len(perfect_lijst) + len(afwijking_lijst) + len(missend_lijst),
        "perfect": perfect_lijst,
        "afwijking": afwijking_lijst,
        "missend": missend_lijst
    }

def controleer_upload(file_stream, filename):
    snipe_assets = haal_snipe_assets_op()
    
    by_serial = {}
    by_name = {}
    by_tag = {}
    
    for asset in snipe_assets:
        n_clean = super_clean(asset.get('name'))
        s_clean = super_clean(asset.get('serial'))
        t_clean = super_clean(asset.get('asset_tag'))

        if s_clean and s_clean not in [super_clean(x) for x in config.NEGEER_SERIALS]:
            if s_clean not in by_serial: by_serial[s_clean] = []
            by_serial[s_clean].append(asset)
        if n_clean:
            if n_clean not in by_name: by_name[n_clean] = []
            by_name[n_clean].append(asset)
        if t_clean:
            if t_clean not in by_tag: by_tag[t_clean] = []
            by_tag[t_clean].append(asset)

    result = {
        "status": "success",
        "totaal_snipe": len(snipe_assets),
        "inventaris": None,
        "uitgegeven": None
    }
    
    try:
        file_bytes = file_stream.read()
        
        if filename.lower().endswith(('.xlsx', '.xls')):
            xls = pd.ExcelFile(io.BytesIO(file_bytes))
            
            if 'Lijst geavanceerd' in xls.sheet_names:
                df_inv = pd.read_excel(xls, sheet_name='Lijst geavanceerd', dtype=str)
            else:
                df_inv = pd.read_excel(xls, sheet_name=0, dtype=str)
            result["inventaris"] = verwerk_inventaris(df_inv, snipe_assets, by_serial, by_name, by_tag)
            
            if 'Uitgegeven' in xls.sheet_names:
                df_uit = pd.read_excel(xls, sheet_name='Uitgegeven', dtype=str)
                result["uitgegeven"] = verwerk_uitgegeven(df_uit, snipe_assets, by_serial, by_name, by_tag)
                
        else:
            df_inv = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig', dtype=str)
            result["inventaris"] = verwerk_inventaris(df_inv, snipe_assets, by_serial, by_name, by_tag)

        return result

    except Exception as e:
        return {"status": "error", "message": f"Analyse fout: {str(e)}"}