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
    """Verwijder alles behalve letters en cijfers, lowercase."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return re.sub(r'[^a-z0-9]', '', str(val).lower().strip())


def herstel_serial_uit_float(val):
    """
    Excel slaat serienummers soms op als float (bijv. 2.07E+11).
    Dit converteert dat terug naar een heel getal string.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    # Detecteer wetenschappelijke notatie (bijv. 2.07E+11 of 2.07e+11)
    if re.match(r'^-?\d+(\.\d+)?[eE][+\-]?\d+$', s):
        try:
            return str(int(float(s)))
        except:
            pass
    # Verwijder .0 achtervoegsel dat Excel toevoegt bij nummers
    if re.match(r'^\d+\.0$', s):
        return s[:-2]
    return s


def extreme_clean_company(val):
    v = super_clean(val)
    for suffix in ['bv', 'nv', 'vof']:
        if v.endswith(suffix):
            v = v[:-len(suffix)]
    return v.strip()


def is_valid_serial(s_clean):
    if not s_clean: return False
    if len(s_clean) < 3: return False
    bad_words = ['geen', 'nvt', 'na', 'tba', 'onbekend', 'niet', 'missing']
    if any(b in s_clean for b in bad_words): return False
    return True


def is_valid_name(n_clean):
    if not n_clean: return False
    if len(n_clean) < 2: return False
    bad_words = ['geennaam', 'onbekend']
    if any(b in n_clean for b in bad_words): return False
    return True


def vind_kolom(headers, prioriteiten):
    for p in prioriteiten:
        for h in headers:
            if str(h).strip().lower() == p.lower():
                return h
    for p in prioriteiten:
        if len(p) <= 3: continue
        for h in headers:
            if p.lower() in str(h).strip().lower():
                return h
    return None


def is_actief_asset(a):
    if a.get('deleted_at'): return False
    status_label = a.get('status_label')
    if isinstance(status_label, dict):
        meta = str(status_label.get('status_meta', '')).lower()
        if meta in ['archived', 'undeployable']:
            return False
    return True


def genereer_naam_varianten(naam_raw):
    """
    Genereer meerdere 'schone' varianten van een naam om robuuster te matchen.
    Bijv: "AF-01-Peter" → ["af01peter", "af-01-peter", ...]
    
    Retourneert een set van cleaned strings om tegen te matchen.
    """
    if not naam_raw:
        return set()
    
    naam = str(naam_raw).strip()
    varianten = set()
    
    # Variant 1: alles weg behalve letters+cijfers (huidige super_clean)
    varianten.add(super_clean(naam))
    
    # Variant 2: lowercase, streepjes behouden maar spaties weg
    varianten.add(re.sub(r'\s+', '', naam.lower()))
    
    # Variant 3: lowercase, spaties vervangen door streepje
    varianten.add(naam.lower().replace(' ', '-'))
    
    # Variant 4: lowercase, alles vervangen door underscore → dan super_clean
    varianten.add(super_clean(naam.replace('_', '-')))
    
    # Verwijder lege strings
    varianten.discard('')
    return varianten


def vind_beste_match(e_s_clean, e_n_clean, naam_varianten, by_serial, by_name, by_tag, gekoppelde_ids):
    """
    Verbeterde matching met meerdere naam-varianten en serial-herstel.
    Prioriteit:
      1. Perfect match (naam + serial kloppen allebei)
      2. Naam match (elke variant)
      3. Asset tag match (elke variant)
      4. Serial match
      5. Fallbacks voor gearchiveerde/verwijderde items
    """
    valid_s = is_valid_serial(e_s_clean)
    valid_n = is_valid_name(e_n_clean)

    # --- STAP 1: PERFECTE MATCH (naam + serial) ---
    if valid_s and valid_n:
        for variant in naam_varianten:
            if variant in by_name:
                for a in by_name[variant]:
                    if a['id'] not in gekoppelde_ids and is_actief_asset(a):
                        a_serial = super_clean(a.get('serial', ''))
                        if a_serial == e_s_clean:
                            return a

    # --- STAP 2: NAAM MATCH (alle varianten, actieve assets eerst) ---
    if valid_n:
        for variant in naam_varianten:
            if variant in by_name:
                for a in by_name[variant]:
                    if a['id'] not in gekoppelde_ids and is_actief_asset(a):
                        return a

    # --- STAP 3: ASSET TAG MATCH (alle varianten) ---
    if valid_n:
        for variant in naam_varianten:
            if variant in by_tag:
                for a in by_tag[variant]:
                    if a['id'] not in gekoppelde_ids and is_actief_asset(a):
                        return a

    # --- STAP 4: SERIAL MATCH ---
    if valid_s and e_s_clean in by_serial:
        for a in by_serial[e_s_clean]:
            if a['id'] not in gekoppelde_ids and is_actief_asset(a):
                return a

    # --- FALLBACKS (gearchiveerde/verwijderde items) ---
    if valid_n:
        for variant in naam_varianten:
            if variant in by_name:
                for a in by_name[variant]:
                    if a['id'] not in gekoppelde_ids:
                        return a
        for variant in naam_varianten:
            if variant in by_tag:
                for a in by_tag[variant]:
                    if a['id'] not in gekoppelde_ids:
                        return a
    if valid_s and e_s_clean in by_serial:
        for a in by_serial[e_s_clean]:
            if a['id'] not in gekoppelde_ids:
                return a

    return None


def verwerk_inventaris(df, snipe_assets, by_serial, by_name, by_tag):
    df = df.fillna('')
    headers = list(df.columns)
    
    n_col = vind_kolom(headers, ['pc-naam', 'pc naam', 'naam', 'hostname', 'endpoint', 'apparaat'])
    s_col = vind_kolom(headers, ['serienummer', 'serial number', 'serial', 'serie', 'sn'])
    c_col = vind_kolom(headers, ['company', 'bedrijf', 'klant', 'tenant', 'relatie'])
    m_col = vind_kolom(headers, ['merk', 'manufacturer', 'fabrikant'])
    mod_col = vind_kolom(headers, ['modelnummer', 'model'])
    
    gekoppelde_ids = set()
    gevonden_lijst = []
    missend_lijst = []
    
    for index, row in df.iterrows():
        if all(str(val).strip() == '' for val in row.values): continue

        excel_naam = str(row[n_col]).strip() if n_col else ""
        excel_serial_raw = str(row[s_col]).strip() if s_col else ""
        
        # Herstel floats/wetenschappelijke notatie in serienummer
        excel_serial = herstel_serial_uit_float(excel_serial_raw)
        
        e_n_clean = super_clean(excel_naam)
        e_s_clean = super_clean(excel_serial)
        naam_varianten = genereer_naam_varianten(excel_naam)
        
        match_gevonden = vind_beste_match(
            e_s_clean, e_n_clean, naam_varianten,
            by_serial, by_name, by_tag, gekoppelde_ids
        )

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
        if asset['id'] not in gekoppelde_ids and is_actief_asset(asset):
            status_label = asset.get('status_label')
            status_naam = status_label.get('name', 'Geen status') if status_label else 'Geen status'
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
    
    n_col = vind_kolom(headers, ['naam', 'pc-naam', 'endpoint', 'asset'])
    s_col = vind_kolom(headers, ['serienummer', 'serial number', 'serial', 'serie', 'sn'])
    k_col = vind_kolom(headers, ['klant', 'company', 'bedrijf', 'relatie', 'tenant'])
    f_col = vind_kolom(headers, ['gefactureerd?', 'gefactureerd', 'factuur', 'betaald'])

    perfect_lijst = []
    afwijking_lijst = []
    missend_lijst = []
    gekoppelde_ids = set()

    for index, row in df.iterrows():
        if all(str(val).strip() == '' for val in row.values): continue
        
        val_naam = str(row[n_col]).strip() if n_col else ""
        val_serial_raw = str(row[s_col]).strip() if s_col else ""
        val_klant = str(row[k_col]).strip() if k_col else ""
        val_fact = str(row[f_col]).strip().lower() if f_col else ""
        
        # Herstel floats/wetenschappelijke notatie in serienummer
        val_serial = herstel_serial_uit_float(val_serial_raw)
        
        excel_fact_bool = val_fact in ['1', 'yes', 'ja', 'true', 'v', 'x', 'on', 'j', 'y', 'waar']
        str_fact_excel = "Ja" if excel_fact_bool else "Nee"
        
        e_n_clean = super_clean(val_naam)
        e_s_clean = super_clean(val_serial)
        naam_varianten = genereer_naam_varianten(val_naam)
        
        match_gevonden = vind_beste_match(
            e_s_clean, e_n_clean, naam_varianten,
            by_serial, by_name, by_tag, gekoppelde_ids
        )

        item_info = {
            "rij": index + 2,
            "naam": val_naam or "[Geen naam]",
            "serial": val_serial,
            "klant_excel": val_klant,
            "fact_excel": str_fact_excel
        }

        if match_gevonden:
            gekoppelde_ids.add(match_gevonden['id'])
            
            snipe_klant = match_gevonden.get('company', {}).get('name', '') if match_gevonden.get('company') else ""
            
            assigned_to = match_gevonden.get('assigned_to')
            status_label = match_gevonden.get('status_label', {})
            status_meta = str(status_label.get('status_meta', '')).lower()
            status_naam_str = str(status_label.get('name', '')).lower()
            
            is_uitgecheckt = False
            if assigned_to is not None:
                is_uitgecheckt = True
            elif status_meta == 'deployed':
                is_uitgecheckt = True
            elif any(woord in status_naam_str for woord in ['uitgegeven', 'in gebruik', 'klant']):
                is_uitgecheckt = True
            elif status_meta not in ['undeployable', 'archived'] and status_naam_str not in ['in magazijn', 'voorraad', 'besteld', 'klaar voor levering', 'gerepareerd']:
                is_uitgecheckt = True
            
            snipe_gefactureerd_bool = False
            custom_fields = match_gevonden.get('custom_fields')
            if isinstance(custom_fields, dict):
                for k, v in custom_fields.items():
                    if isinstance(v, dict):
                        field_name = str(v.get('field', '')).lower()
                        k_lower = str(k).lower()
                        if 'gefactureerd' in k_lower or 'factuur' in k_lower or 'gefactureerd' in field_name or 'factuur' in field_name:
                            v_val = str(v.get('value')).lower().strip()
                            if v_val in ['1', 'yes', 'ja', 'true', 'v', 'x', 'on', 'j', 'y', 'waar']:
                                snipe_gefactureerd_bool = True
                            break
            
            str_fact_snipe = "Ja" if snipe_gefactureerd_bool else "Nee"
            
            afwijkingen = []
            
            if extreme_clean_company(val_klant) not in extreme_clean_company(snipe_klant) and extreme_clean_company(snipe_klant) not in extreme_clean_company(val_klant):
                afwijkingen.append("Klant mismatch")
                
            if not is_uitgecheckt:
                afwijkingen.append("Niet uitgecheckt")
                
            if str_fact_excel != str_fact_snipe:
                afwijkingen.append("Factuur mismatch")
                
            item_info['snipe_klant'] = snipe_klant
            item_info['uitgecheckt'] = "Ja" if is_uitgecheckt else "Nee"
            item_info['fact_snipe'] = str_fact_snipe
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


def bouw_zoek_index(snipe_assets):
    """
    Bouw zoekindexen op met ALLE naam-varianten per asset,
    zodat we ook matchen als notaties licht verschillen.
    """
    by_serial = {}
    by_name = {}
    by_tag = {}

    for asset in snipe_assets:
        naam_raw = asset.get('name', '')
        serial_raw = asset.get('serial', '')
        tag_raw = asset.get('asset_tag', '')

        # --- Serienummer index ---
        # Herstel ook Snipe-IT serienummers die als float zijn opgeslagen
        serial_hersteld = herstel_serial_uit_float(serial_raw)
        s_clean = super_clean(serial_hersteld)
        if is_valid_serial(s_clean) and s_clean not in [super_clean(x) for x in config.NEGEER_SERIALS]:
            if s_clean not in by_serial:
                by_serial[s_clean] = []
            by_serial[s_clean].append(asset)

        # --- Naam index (alle varianten) ---
        for variant in genereer_naam_varianten(naam_raw):
            if is_valid_name(variant):
                if variant not in by_name:
                    by_name[variant] = []
                by_name[variant].append(asset)

        # --- Asset tag index (alle varianten) ---
        for variant in genereer_naam_varianten(tag_raw):
            if is_valid_name(variant):
                if variant not in by_tag:
                    by_tag[variant] = []
                by_tag[variant].append(asset)

    return by_serial, by_name, by_tag


def controleer_upload(file_stream, filename):
    snipe_assets = haal_snipe_assets_op()

    # Gebruik de nieuwe verbeterde index builder
    by_serial, by_name, by_tag = bouw_zoek_index(snipe_assets)

    result = {
        "status": "success",
        "totaal_snipe": len(snipe_assets),
        "inventaris": None,
        "uitgegeven": None
    }
    
    try:
        if isinstance(file_stream, bytes):
            file_bytes = file_stream
        else:
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