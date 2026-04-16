import requests
import json
import config

def analyseer_mismatches_met_ai(ontbrekende_action1, gearchiveerde_snipe_it):
    """
    Stuurt de onbekende apparaten uit Action1 en Snipe-IT naar de lokale AI 
    om te zoeken naar fuzzy matches (typo's, naamsvergelijkingen, etc).
    """
    
    # We beperken de data die we naar de AI sturen om overbelasting te voorkomen
    # Haal alleen de essentiële velden eruit.
    a1_data = []
    for app in ontbrekende_action1[:50]: # Max 50 tegelijk om context limieten te voorkomen
        a1_data.append({
            "naam": app.get('name', ''),
            "serial": app.get('berekend_serial', ''),
            "mac": app.get('hardware', {}).get('MAC', '')
        })

    snipe_data = []
    for app in gearchiveerde_snipe_it[:50]:
        snipe_data.append({
            "id": app.get('id'),
            "naam": app.get('naam', app.get('name', '')),
            "serial": app.get('serial', '')
        })

    # Controleer of we wel iets hebben om te vergelijken
    if not a1_data or not snipe_data:
        return {"status": "error", "message": "Niet genoeg data om te vergelijken."}

    ollama_url = "http://localhost:11434/api/generate"
    
    # De prompt waarin we de AI precies vertellen WAT we verwachten
    prompt = f"""
    Je bent een IT data-analist. Je krijgt twee lijsten met apparaten.
    Lijst 1: 'Action1 Apparaten' (gevonden in netwerk, missen in systeem).
    Lijst 2: 'Snipe-IT Apparaten' (staan in systeem, maar niet gekoppeld).
    
    Jouw taak: Zoek naar apparaten in Lijst 1 die sterk lijken op apparaten in Lijst 2. 
    Kijk naar:
    - Typfouten in serienummers (bijv. 'O' vs '0', of 1 letter verschil).
    - Namen die op elkaar lijken (bijv. 'LAPTOP-JAN' vs 'Jan-Laptop').
    - Overeenkomende stukken van het MAC-adres of andere patronen.
    
    Action1 Apparaten:
    {json.dumps(a1_data)}
    
    Snipe-IT Apparaten:
    {json.dumps(snipe_data)}
    
    Geef je antwoord ALTIJD als een geldige JSON array terug, precies in dit formaat:
    [
      {{
        "action1_naam": "naam uit lijst 1", 
        "snipe_naam": "naam uit lijst 2", 
        "reden": "Korte uitleg waarom je denkt dat dit een match is", 
        "zekerheid_procent": 95
      }}
    ]
    Als je geen matches kunt vinden, geef dan een lege array terug: []
    Geef GEEN andere tekst, begroetingen of uitleg. Alleen de pure JSON.
    """
    
    # We gebruiken de "format": "json" optie van Ollama zodat hij nooit tekst teruggeeft
    payload = {
        "model": "llama3", # Verander dit naar mistral of phi3 als je die lokaal hebt draaien
        "prompt": prompt,
        "stream": False,
        "format": "json" 
    }
    
    try:
        response = requests.post(ollama_url, json=payload, timeout=120)
        if response.status_code == 200:
            ai_antwoord = response.json().get("response", "[]")
            try:
                # Probeer de string van de AI om te zetten naar een Python Dictionary
                matches = json.loads(ai_antwoord)
                
                # Filter de matches waar de AI erg onzeker over is uit
                goede_matches = [m for m in matches if m.get("zekerheid_procent", 0) > 60]
                
                return {"status": "success", "matches": goede_matches}
            except json.JSONDecodeError:
                return {"status": "error", "message": "AI gaf geen geldige JSON terug."}
        else:
            return {"status": "error", "message": f"Fout van AI Server: {response.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "message": f"Kan de AI server (Ollama) niet bereiken. Draait deze wel? Fout: {e}"}