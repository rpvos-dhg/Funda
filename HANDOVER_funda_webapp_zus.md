# Handover: Funda-webapp voor mijn zus

Doel van de nieuwe chat: een webapp bouwen die hetzelfde doet als het bestaande
Funda-zoekscript van Remco, maar voor zijn zus, en die **elke ochtend een vers
rapport in de webapp toont**. De inrichting (haar zoekcriteria, hosting, look)
wordt in de nieuwe chat bepaald. Dit document geeft de context en de geleerde
lessen mee.

---

## 1. Wat er al bestaat (Remco's setup)

Map: `C:\Users\remco\OneDrive\Documents\Claude\Projects\Financien`

Twee Python-bestanden, gebouwd op de library `pyfunda` (`github.com/0xMH/pyfunda`):

- **`funda_zoek.py`** — zoekt dagelijks koopappartementen, filtert op buurt/stad/
  straat, doet een detailcheck (belegging, begane grond, blacklist), houdt bij wat
  nieuw is en schrijft een rapport. Draait dagelijks via Windows Task Scheduler.
- **`funda_rapport.py`** — bouwt uit de woningen een markdown + HTML rapport en
  een PWA (installeerbare webapp). Rekent maandlasten, hypotheekruimte (NHG,
  starter), reisafstand naar werk, erfpacht, energielabel, pros/cons.

Config- en datastanden (allemaal in `.gitignore`, bevatten PII of ruis):

- `funda_personal.json` — alle persoonlijke instellingen. Template:
  `funda_personal.example.json` (postcode, radius_km, prijs_min/max, m2_min,
  bruto_jaar, eigen_inleg, werk_postcodes, sinds dit traject ook `prijs_band_stap`
  en `lang_op_funda_dagen`).
- `funda_seen_ids.json` — welke woningen al eerder zijn gezien (nieuw-detectie).
- `funda_tracking.json` — prijs- en looptijdgeschiedenis (nieuw, zie hieronder).
- `funda_blacklist.json` — handmatig weggestreepte woningen.
- `funda_werk_coords.json` — gecachte geocoding van werkpostcodes.
- `funda_pwa_password.txt` — wachtwoord waarmee het rapport wordt versleuteld.

Publicatie: `funda_rapport.py` schrijft naar `docs/` (manifest, service-worker,
icon, `index.html`). `deploy.bat` (of de auto-push in `funda_zoek.py`) commit en
pusht `docs/` naar GitHub Pages. De PWA is AES-256-GCM versleuteld en vraagt om
het wachtwoord in de browser. Zo kan Remco het rapport op zijn telefoon openen.

---

## 2. Belangrijkste bevindingen uit dit traject

Dit zijn de lessen die de webapp-bouw moet meenemen.

### Funda kapt elke zoekopdracht af op ~140 resultaten
Het logboek liet elke run "totaal opgehaald: ~140" zien. Dat is een harde grens
op de **query**, niet op het aantal pagina's. Meer pagina's ophalen helpt dus
niet. Woningen die al lang te koop staan zakken achter die grens en kwamen nooit
in beeld.

**Oplossing (geïmplementeerd): prijsband-splitsing.** De prijsrange wordt in
banden van 20k geknipt (230-250k, 250-270k, ...). Elke band blijft onder de kap,
en samen dekken ze veel meer van de markt. Dedup op woning-id vangt overlap op de
bandgrenzen op. In de test verdubbelde dit de dekking (30 naar 60 woningen) en
juist de oudgedienden kwamen mee. Functie: `maak_prijs_banden()`. Bandgrootte
instelbaar via `prijs_band_stap` in de config.
> Voor de webapp: dezelfde truc is nodig. Eventueel ook splitsen op een tweede as
> (bijv. m2-banden of buurt) als zus een veel grotere markt heeft.

### Prijsdaling betrouwbaar detecteren: zelf bijhouden
De `pyfunda`-versie die hier draait geeft data terug via `.data` (dict). De
nieuwere library (master branch) is dataclass-gebaseerd en heeft wél
`publication_date` en een `PriceHistory`/`PriceChange`-model, maar daar kun je
niet op vertrouwen omdat de geïnstalleerde versie anders is.

**Oplossing (geïmplementeerd): eigen `funda_tracking.json`.** Per woning houden we
`first_seen`, `last_seen` en alle prijswijzigingen bij. Bij elke run vergelijken
we de huidige prijs met de hoogst geziene. Daalt hij, dan tonen we bedrag en
percentage. Werkt los van wat Funda teruggeeft, dus robuust. Functie:
`update_tracking()`. **Let op:** de eerste run legt alleen de huidige prijs vast.
Prijsdalingen verschijnen pas zodra een prijs daarna verandert. Voor zus betekent
dat: een paar dagen laten draaien voordat de daling-vlaggen nut hebben.

### "Lang op Funda" als onderhandelsignaal
Dagen-te-koop komt uit Funda's publicatiedatum als die er is (`_parse_pub_datum()`
probeert meerdere veldnamen), anders uit hoe lang wij de woning al volgen, met een
`+` om aan te geven dat het een ondergrens is. Boven 90 dagen (instelbaar via
`lang_op_funda_dagen`) krijgt de woning een vlag. Prijsdalers en langzitters
sorteren bovenaan en wegen mee in de rapportscore.

### Datamodel van pyfunda (handig voor de webapp)
Uit `listing.py` (master): een `Listing` heeft o.a. `price.amount`,
`areas.living`, `rooms.bedrooms`, `property_details.energy_label`,
`address.neighbourhood/city/postcode`, `location.latitude/longitude`,
`media.photo_urls`, `description`, `publication_date`, `sales_history`
(`time_on_market` = "Looptijd"), en `insights.views/saves`. Niet alles zit in de
zoekresultaten; vaak is een detail-call (`get_listing(id)`) nodig.

### Praktische valkuilen
- **pyfunda zit niet in de sandbox.** Installeren:
  `pip install git+https://github.com/0xMH/pyfunda.git`. Voor tests in de sandbox:
  stub de `funda`-module (zie `test_funda.py` in de outputs van dit traject, een
  `FakeFunda` met `search_listing` + `get_listing`). Daarmee kun je band-split,
  tracking, drop-detectie en rapport-rendering offline testen.
- **OneDrive-sync kapt bestanden af op de Linux-mount.** Tijdens verificatie bleek
  een net-geschreven `.py` op het mount-pad soms halverwege afgekapt, terwijl het
  echte Windows-bestand compleet was. Bij twijfel: kopieer naar `/tmp` en check de
  staart, of wacht een paar seconden.
- **`funda_rapport.py` doet netwerk-calls** (Nominatim geocoding, OSRM routing)
  tijdens rapportgeneratie. In tests die deur uitschakelen of mocken.

---

## 3. Aanbevolen architectuur voor de webapp van zus

De bestaande aanpak werkt al goed en is herbruikbaar: **Python-scraper genereert
een statische versleutelde PWA, een geplande taak draait elke ochtend, GitHub
Pages serveert het.** Zus opent elke ochtend dezelfde URL en ziet het verse
rapport.

Belangrijk: live scrapen kan niet vanuit de browser (Funda is geen connector en
pyfunda is Python). De webapp moet dus een **vooraf gegenereerd** rapport tonen,
ververst door een dagelijkse run. Een Cowork-artifact dat live data trekt is hier
dus niet de route; de statische-generatie-aanpak wel.

Logische opzet:
1. Eigen kopie van `funda_zoek.py` + `funda_rapport.py` met zus' criteria.
2. Eigen `funda_personal.json` (haar postcode, radius, prijs, m2, werkpostcodes,
   en of haar financiële profiel meegerekend moet worden).
3. Dagelijkse run (Task Scheduler op een machine die aan staat, of een andere
   scheduler/host) die het rapport bouwt en pusht.
4. GitHub Pages (of andere host) met wachtwoordbeveiliging zoals nu.

---

## 4. Openstaande keuzes voor de nieuwe chat (inrichting)

- **Zus' zoekprofiel:** postcode/woonplaats, straal, prijsrange, min m2, koop of
  ook huur, woningtype (alleen appartement of ook eengezinswoning), uitsluit- en
  twijfelbuurten.
- **Financiële module aan of uit:** Remco's rapport rekent NHG/starter/maandlasten
  op basis van zíjn inkomen. Voor zus: haar cijfers invullen, vereenvoudigen, of
  helemaal weglaten en puur de woningkaarten tonen.
- **Werk/reistijd:** wil zus reisafstand naar werk in het rapport? Zo ja, haar
  werkpostcode(s).
- **Hosting + ochtendlevering:** waar draait de dagelijkse run, en hoe opent zus
  hem (eigen GitHub Pages-URL, gedeeld met haar, wachtwoord). Wil ze ook een
  melding 's ochtends, of alleen de pagina openen?
- **Look en taal:** eigen kleur/titel/icon; rapport in dezelfde stijl of anders.
- **Schaal:** is haar markt veel groter? Dan mogelijk fijnere band-splitsing.

---

## 5. Snelle startpunten in de nieuwe chat

- Kopieer `funda_zoek.py`, `funda_rapport.py` en `funda_personal.example.json` als
  basis; maak een aparte map of repo voor zus zodat data gescheiden blijft.
- Zet meteen `funda_tracking.json`, `funda_seen_ids.json`, `funda_personal.json` en
  `funda_pwa_password.txt` in `.gitignore`.
- Test offline met een gestubde `funda`-module voordat je live gaat.
- Laat de scraper een paar dagen draaien zodat prijsdaling- en looptijdvlaggen
  zich vullen.
