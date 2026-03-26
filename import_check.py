import pandas as pd
import requests
import config
import re
import io

# ==============================================================================
# STAP 1: SNIPE-IT DATA OPHALEN
# ==============================================================================

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
    except Exception:
        pass

    for api_filter in api_filters:
        limit = 500
        offset = 0
        while True:
            try:
                url = f"{config.HARDWARE_URL}?limit={limit}&offset={offset}&sort=id&order=asc{api_filter}"
                response = requests.get(url, headers=config.headers, timeout=30)
                if response.status_code != 200:
                    break
                data = response.json()
                rows = data.get('rows', [])
                if not rows:
                    break
                for asset in rows:
                    if asset['id'] not in geziene_ids:
                        geziene_ids.add(asset['id'])
                        alle_assets.append(asset)
                offset += limit
                if offset >= data.get('total', 0):
                    break
            except Exception:
                break

    return alle_assets


# ==============================================================================
# STAP 2: HULPFUNCTIES
# ==============================================================================

def super_clean(val):
    """Stript alles behalve letters en cijfers, maakt lowercase."""
    if val is None:
        return ""
    if isinstance(val, float):
        if pd.isna(val):
            return ""
    return re.sub(r'[^a-z0-9]', '', str(val).lower().strip())


def herstel_serial(val):
    """
    Herstelt door Excel gecorrumpeerde serienummers:
      - Wetenschappelijke notatie: 2.44E+11 -> '244000000000'
      - Afgekapt .0 suffix: '12345.0' -> '12345'
    Noot: afgeknipte voorloopnullen (0487... -> 487...) kunnen NIET
    automatisch hersteld worden. Naam-first matching vangt die gevallen op.
    """
    if val is None:
        return ""
    s = str(val).strip()
    if not s or s.lower() == 'nan':
        return ""
    if re.match(r'^-?\d+(\.\d+)?[eE][+\-]?\d+$', s):
        try:
            return str(int(float(s)))
        except Exception:
            pass
    if re.match(r'^\d+\.0$', s):
        return s[:-2]
    return s


def is_actief_asset(asset):
    """
    Actief = niet verwijderd EN niet gearchiveerd/undeployable.
    Verwijderde assets worden NOOIT als primaire match gebruikt.
    """
    if asset.get('deleted_at'):
        return False
    status_label = asset.get('status_label')
    if isinstance(status_label, dict):
        meta = str(status_label.get('status_meta', '')).lower()
        if meta in ['archived', 'undeployable']:
            return False
    return True


def is_valid_serial(s):
    if not s or len(s) < 3:
        return False
    slechte_waarden = ['geen', 'nvt', 'na', 'tba', 'onbekend', 'niet', 'missing',
                       'tobefilled', 'defaultstring', 'unknown', 'none']
    return not any(bad in s for bad in slechte_waarden)


def is_valid_name(n):
    if not n or len(n) < 2:
        return False
    return n not in ['geennaam', 'onbekend', 'unknown']


def vind_kolom(headers, prioriteiten):
    for p in prioriteiten:
        for h in headers:
            if str(h).strip().lower() == p.lower():
                return h
    for p in prioriteiten:
        if len(p) <= 3:
            continue
        for h in headers:
            if p.lower() in str(h).strip().lower():
                return h
    return None


def extreme_clean_company(val):
    v = super_clean(val)
    for suffix in ['bv', 'nv', 'vof']:
        if v.endswith(suffix):
            v = v[:-len(suffix)]
    return v.strip()


def naam_varianten(naam_raw):
    """
    Genereert meerdere genormaliseerde varianten van een naam om
    notatie-verschillen op te vangen:
      'AF-01-Peter' -> {'af01peter', 'af-01-peter', 'af01-peter', ...}
      'TT-11'       -> {'tt11', 'tt-11'}
    """
    if not naam_raw:
        return set()
    naam = str(naam_raw).strip()
    varianten = set()
    varianten.add(super_clean(naam))                          # geen leestekens
    varianten.add(re.sub(r' +', '', naam.lower()))            # spaties weg
    varianten.add(naam.lower().replace(' ', '-'))             # spatie -> streepje
    varianten.add(super_clean(naam.replace('_', '-')))        # underscore als streepje
    varianten.discard('')
    return varianten


# ==============================================================================
# STAP 3: ZOEKINDEX BOUWEN
# Actieve en inactieve assets worden APART geindexeerd.
# Actief krijgt altijd voorrang; inactief is alleen een laatste redmiddel.
# ==============================================================================

def bouw_zoek_index(snipe_assets):
    by_name_actief   = {}
    by_name_alles    = {}
    by_tag_actief    = {}
    by_tag_alles     = {}
    by_serial_actief = {}
    by_serial_alles  = {}

    negeer_serials_clean = {super_clean(x) for x in config.NEGEER_SERIALS}

    def voeg_toe(index, sleutel, asset):
        if sleutel not in index:
            index[sleutel] = []
        if not any(a['id'] == asset['id'] for a in index[sleutel]):
            index[sleutel].append(asset)

    for asset in snipe_assets:
        actief = is_actief_asset(asset)

        for variant in naam_varianten(asset.get('name', '')):
            if is_valid_name(variant):
                voeg_toe(by_name_alles, variant, asset)
                if actief:
                    voeg_toe(by_name_actief, variant, asset)

        for variant in naam_varianten(asset.get('asset_tag', '')):
            if is_valid_name(variant):
                voeg_toe(by_tag_alles, variant, asset)
                if actief:
                    voeg_toe(by_tag_actief, variant, asset)

        serial_clean = super_clean(herstel_serial(asset.get('serial', '')))
        if is_valid_serial(serial_clean) and serial_clean not in negeer_serials_clean:
            voeg_toe(by_serial_alles, serial_clean, asset)
            if actief:
                voeg_toe(by_serial_actief, serial_clean, asset)

    return (by_name_actief, by_name_alles,
            by_tag_actief,  by_tag_alles,
            by_serial_actief, by_serial_alles)


# ==============================================================================
# STAP 4: MATCHING LOGICA
#
# NAAM IS KONING. Volgorde:
#
#   Ronde 1 (alleen ACTIEVE assets):
#     1a. Naam match    <- altijd eerst, ook als serial fout is
#     1b. Tag match
#     1c. Serial match
#
#   Ronde 2 (fallback naar INACTIEVE/VERWIJDERDE assets):
#     2a. Naam match
#     2b. Tag match
#     2c. Serial match
#
# Dit lost het TT-11 probleem op: actief TT-11 wordt gevonden op naam,
# ook al klopt het serienummer in Excel niet. De verwijderde TT-11 in de
# prullenbak wordt NOOIT als primaire match gekozen.
# ==============================================================================

def vind_beste_match(e_s_clean, e_n_varianten, gekoppelde_ids,
                     by_name_actief, by_name_alles,
                     by_tag_actief,  by_tag_alles,
                     by_serial_actief, by_serial_alles):

    valid_s     = is_valid_serial(e_s_clean)
    heeft_namen = bool(e_n_varianten)

    def zoek(index, sleutels):
        for sleutel in sleutels:
            if sleutel in index:
                for a in index[sleutel]:
                    if a['id'] not in gekoppelde_ids:
                        return a
        return None

    # -- Ronde 1: alleen actieve assets --
    if heeft_namen:
        match = zoek(by_name_actief, e_n_varianten)
        if match:
            return match
    if heeft_namen:
        match = zoek(by_tag_actief, e_n_varianten)
        if match:
            return match
    if valid_s:
        match = zoek(by_serial_actief, [e_s_clean])
        if match:
            return match

    # -- Ronde 2: fallback naar inactief/verwijderd --
    if heeft_namen:
        match = zoek(by_name_alles, e_n_varianten)
        if match:
            return match
    if heeft_namen:
        match = zoek(by_tag_alles, e_n_varianten)
        if match:
            return match
    if valid_s:
        match = zoek(by_serial_alles, [e_s_clean])
        if match:
            return match

    return None


# ==============================================================================
# STAP 5: TABBLAD 1 — INVENTARIS CONTROLE ('Lijst geavanceerd')
# ==============================================================================

def verwerk_inventaris(df, snipe_assets, indexen):
    df = df.fillna('')
    headers = list(df.columns)

    n_col  = vind_kolom(headers, ['pc-naam', 'pc naam', 'naam', 'hostname', 'endpoint', 'apparaat'])
    s_col  = vind_kolom(headers, ['serienummer', 'serial number', 'serial', 'serie', 'sn'])
    c_col  = vind_kolom(headers, ['company', 'bedrijf', 'klant', 'tenant', 'relatie'])
    m_col  = vind_kolom(headers, ['merk', 'manufacturer', 'fabrikant'])
    mo_col = vind_kolom(headers, ['modelnummer', 'model'])

    (by_name_actief, by_name_alles,
     by_tag_actief,  by_tag_alles,
     by_serial_actief, by_serial_alles) = indexen

    gekoppelde_ids = set()
    gevonden_lijst = []
    missend_lijst  = []

    for index, row in df.iterrows():
        if all(str(v).strip() == '' for v in row.values):
            continue

        excel_naam   = str(row[n_col]).strip() if n_col else ""
        excel_serial = herstel_serial(str(row[s_col]).strip() if s_col else "")

        e_n_varianten = naam_varianten(excel_naam)
        e_s_clean     = super_clean(excel_serial)

        match = vind_beste_match(
            e_s_clean, e_n_varianten, gekoppelde_ids,
            by_name_actief, by_name_alles,
            by_tag_actief,  by_tag_alles,
            by_serial_actief, by_serial_alles
        )

        item_info = {
            "rij":     index + 2,
            "naam":    excel_naam,
            "serial":  excel_serial,
            "bedrijf": str(row[c_col]).strip() if c_col else "",
            "merk":    str(row[m_col]).strip()  if m_col  else "",
            "model":   str(row[mo_col]).strip() if mo_col else "",
        }

        if match:
            gekoppelde_ids.add(match['id'])
            item_info['bedrijf'] = (match.get('company') or {}).get('name', '') or item_info['bedrijf']
            item_info['merk']    = (match.get('manufacturer') or {}).get('name', '') or item_info['merk']
            item_info['model']   = (match.get('model') or {}).get('name', '') or item_info['model']
            status_label         = match.get('status_label')
            item_info['status']  = status_label.get('name', 'Onbekend') if status_label else 'Geen Status'
            if match.get('deleted_at'):
                item_info['status'] = "Verwijderd"
            gevonden_lijst.append(item_info)
        else:
            missend_lijst.append(item_info)

    # Spookapparaten: actieve Snipe-IT assets NIET in Excel
    spook_lijst = []
    for asset in snipe_assets:
        if asset['id'] not in gekoppelde_ids and is_actief_asset(asset):
            status_label = asset.get('status_label')
            spook_lijst.append({
                "tag":     asset.get('asset_tag') or "",
                "naam":    asset.get('name') or "[Geen naam]",
                "serial":  asset.get('serial') or "[Geen serial]",
                "status":  status_label.get('name', 'Geen status') if status_label else 'Geen status',
                "bedrijf": (asset.get('company') or {}).get('name', ''),
                "merk":    (asset.get('manufacturer') or {}).get('name', ''),
                "model":   (asset.get('model') or {}).get('name', ''),
            })

    return {
        "totaal_excel": len(gevonden_lijst) + len(missend_lijst),
        "gevonden":     gevonden_lijst,
        "missend":      missend_lijst,
        "spook":        spook_lijst,
    }


# ==============================================================================
# STAP 6: TABBLAD 2 — UITGIFTE & FACTURATIE CONTROLE ('Uitgegeven')
# ==============================================================================

def verwerk_uitgegeven(df, snipe_assets, indexen):
    df = df.fillna('')
    headers = list(df.columns)

    n_col = vind_kolom(headers, ['naam', 'pc-naam', 'endpoint', 'asset', 'apparaat'])
    s_col = vind_kolom(headers, ['serienummer', 'serial number', 'serial', 'serie', 'sn'])
    k_col = vind_kolom(headers, ['klant', 'company', 'bedrijf', 'relatie', 'tenant'])
    f_col = vind_kolom(headers, ['gefactureerd?', 'gefactureerd', 'factuur', 'betaald'])

    (by_name_actief, by_name_alles,
     by_tag_actief,  by_tag_alles,
     by_serial_actief, by_serial_alles) = indexen

    perfect_lijst   = []
    afwijking_lijst = []
    missend_lijst   = []
    gekoppelde_ids  = set()

    for index, row in df.iterrows():
        if all(str(v).strip() == '' for v in row.values):
            continue

        val_naam   = str(row[n_col]).strip() if n_col else ""
        val_serial = herstel_serial(str(row[s_col]).strip() if s_col else "")
        val_klant  = str(row[k_col]).strip() if k_col else ""
        val_fact   = str(row[f_col]).strip().lower() if f_col else ""

        excel_fact_bool = val_fact in ['1', 'yes', 'ja', 'true', 'v', 'x', 'on', 'j', 'y', 'waar']
        str_fact_excel  = "Ja" if excel_fact_bool else "Nee"

        e_n_varianten = naam_varianten(val_naam)
        e_s_clean     = super_clean(val_serial)

        match = vind_beste_match(
            e_s_clean, e_n_varianten, gekoppelde_ids,
            by_name_actief, by_name_alles,
            by_tag_actief,  by_tag_alles,
            by_serial_actief, by_serial_alles
        )

        item_info = {
            "rij":         index + 2,
            "naam":        val_naam or "[Geen naam]",
            "serial":      val_serial,
            "klant_excel": val_klant,
            "fact_excel":  str_fact_excel,
        }

        if match:
            gekoppelde_ids.add(match['id'])

            snipe_klant  = (match.get('company') or {}).get('name', '')
            assigned_to  = match.get('assigned_to')
            status_label = match.get('status_label') or {}
            status_meta  = str(status_label.get('status_meta', '')).lower()
            status_naam  = str(status_label.get('name', '')).lower()

            is_uitgecheckt = False
            if assigned_to is not None:
                is_uitgecheckt = True
            elif status_meta == 'deployed':
                is_uitgecheckt = True
            elif any(w in status_naam for w in ['uitgegeven', 'in gebruik', 'klant']):
                is_uitgecheckt = True
            elif status_meta not in ['undeployable', 'archived'] and \
                 status_naam not in ['in magazijn', 'voorraad', 'besteld',
                                     'klaar voor levering', 'gerepareerd']:
                is_uitgecheckt = True

            # Gefactureerd-veld: zoek op HELE WOORDEN 'gefactureerd' of 'factuur'
            # zodat 'manufacturer' en 'form_factor' nooit per ongeluk matchen
            snipe_gefactureerd = False
            custom_fields = match.get('custom_fields')
            if isinstance(custom_fields, dict):
                for k, v in custom_fields.items():
                    if not isinstance(v, dict):
                        continue
                    veld_db   = str(v.get('field', '')).lower()
                    veld_naam = str(k).lower()
                    if (re.search(r'\bgefactureerd\b', veld_naam) or
                            re.search(r'\bgefactureerd\b', veld_db) or
                            re.search(r'\bfactuur\b', veld_naam) or
                            re.search(r'\bfactuur\b', veld_db)):
                        v_val = str(v.get('value', '')).lower().strip()
                        if v_val in ['1', 'yes', 'ja', 'true', 'v', 'x', 'on', 'j', 'y', 'waar']:
                            snipe_gefactureerd = True
                        break

            str_fact_snipe = "Ja" if snipe_gefactureerd else "Nee"

            afwijkingen = []
            klant_excel_clean = extreme_clean_company(val_klant)
            klant_snipe_clean = extreme_clean_company(snipe_klant)
            if klant_excel_clean and klant_snipe_clean:
                if (klant_excel_clean not in klant_snipe_clean and
                        klant_snipe_clean not in klant_excel_clean):
                    afwijkingen.append("Klant mismatch")
            if not is_uitgecheckt:
                afwijkingen.append("Niet uitgecheckt")
            if str_fact_excel != str_fact_snipe:
                afwijkingen.append("Factuur mismatch")

            item_info['snipe_klant'] = snipe_klant
            item_info['uitgecheckt'] = "Ja" if is_uitgecheckt else "Nee"
            item_info['fact_snipe']  = str_fact_snipe
            item_info['afwijkingen'] = afwijkingen

            if afwijkingen:
                afwijking_lijst.append(item_info)
            else:
                perfect_lijst.append(item_info)
        else:
            missend_lijst.append(item_info)

    return {
        "totaal_excel": len(perfect_lijst) + len(afwijking_lijst) + len(missend_lijst),
        "perfect":      perfect_lijst,
        "afwijking":    afwijking_lijst,
        "missend":      missend_lijst,
    }


# ==============================================================================
# STAP 7: HOOFDFUNCTIE
# ==============================================================================

def controleer_upload(file_stream, filename):
    snipe_assets = haal_snipe_assets_op()
    indexen      = bouw_zoek_index(snipe_assets)

    result = {
        "status":       "success",
        "totaal_snipe": len(snipe_assets),
        "inventaris":   None,
        "uitgegeven":   None,
    }

    try:
        file_bytes = file_stream if isinstance(file_stream, bytes) else file_stream.read()

        if filename.lower().endswith(('.xlsx', '.xls')):
            xls       = pd.ExcelFile(io.BytesIO(file_bytes))
            sheet_inv = 'Lijst geavanceerd' if 'Lijst geavanceerd' in xls.sheet_names else xls.sheet_names[0]
            df_inv    = pd.read_excel(xls, sheet_name=sheet_inv, dtype=str)
            result["inventaris"] = verwerk_inventaris(df_inv, snipe_assets, indexen)

            if 'Uitgegeven' in xls.sheet_names:
                df_uit = pd.read_excel(xls, sheet_name='Uitgegeven', dtype=str)
                result["uitgegeven"] = verwerk_uitgegeven(df_uit, snipe_assets, indexen)
        else:
            df_inv = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig', dtype=str)
            result["inventaris"] = verwerk_inventaris(df_inv, snipe_assets, indexen)

        return result

    except Exception as e:
        return {"status": "error", "message": f"Analyse fout: {str(e)}"}