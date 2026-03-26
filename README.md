# 🚀 IT Dashboard (Snipe-IT & Action1 Integratie)

Een krachtige, in Python (Flask) gebouwde webapplicatie voor het automatiseren, synchroniseren en controleren van IT-hardware administraties. Dit dashboard fungeert als de ultieme brug tussen **Snipe-IT** (Asset Management), **Action1** (RMM) en complexe **Excel-administraties**.

## ✨ Belangrijkste Functies

* 📦 **Checkouts & Status Management (`/`)**
  * Snel overzicht van recente hardware checkouts.
  * Bulk-update functionaliteit om items direct in Snipe-IT af te vinken.
* 🔄 **Action1 vs Snipe-IT Synchronisatie (`/sync_dashboard`)**
  * Vergelijkt apparaten in Action1 met de Snipe-IT database.
  * Detecteert verschillen in PC-namen en Serienummers.
  * Met één druk op de knop namen updaten, serienummers corrigeren, of compleet nieuwe (ontbrekende) apparaten in Snipe-IT aanmaken inclusief BitLocker keys.
* 🏢 **Klanten Inventaris (`/klanten_dashboard`)**
  * Real-time inzicht in de opbouw van de hardware per klant (tenant).
  * Filter op hardware categorieën en groepeer op model.
* 📊 **Geavanceerde Excel Audit (`/import_dashboard`)**
  * Upload je Excel-administratie (met tabbladen `Lijst geavanceerd` en `Uitgegeven`).
  * **Inventaris Controle:** Zoekt via "Fuzzy Matching" (ongevoelig voor spaties, streepjes en hoofdletters) of Excel-apparaten in Snipe-IT staan, of dat het "Spookapparaten" zijn.
  * **Uitgifte & Facturatie Controle:** Controleert razendsnel of apparaten die in Excel als "Uitgegeven" staan, in Snipe-IT ook écht zijn *uitgecheckt*, aan de *juiste klant* hangen, én of de *facturatiestatus* exact overeenkomt.

## 🛠️ Tech Stack

* **Backend:** Python 3, Flask, Pandas (voor Excel/CSV verwerking), Requests.
* **Frontend:** HTML5, Bootstrap 5, Vanilla JavaScript.
* **Deployment:** Volledig gecontaineriseerd via Docker & Docker Compose.

## ⚙️ Installatie & Setup (Ubuntu / Linux)

### 1. Haal de code op
Zorg dat je `git` hebt geïnstalleerd en kloon de repository naar je server:
```bash
git clone [https://github.com/casperboy8/check-out-dashboard.git](https://github.com/casperboy8/check-out-dashboard.git) ~/Snipe-it-Dashboard
cd ~/Snipe-it-Dashboard