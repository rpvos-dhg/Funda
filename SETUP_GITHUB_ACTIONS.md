# Funda-rapport draaien op GitHub (zonder laptop)

Hiermee draait je dagelijkse Funda-run op GitHub in plaats van op je laptop. Je
laptop hoeft niet meer aan te staan. Je gevoelige gegevens komen uit GitHub
Secrets en worden nooit in de repo gezet. Alleen het versleutelde rapport wordt
gepubliceerd, net als nu.

## Eenmalig instellen (ca. 5 minuten)

### 1. Secrets aanmaken
Ga naar je repo op GitHub: **Settings -> Secrets and variables -> Actions ->
New repository secret**. Maak deze twee aan:

- **`FUNDA_PERSONAL_JSON`**
  Plak de volledige inhoud van je lokale `funda_personal.json` (open het bestand,
  selecteer alles, kopieer, plak in het secret-veld).

- **`FUNDA_PWA_PASSWORD`**
  Zet hier hetzelfde wachtwoord als in je lokale `funda_pwa_password.txt`. Dit is
  het wachtwoord waarmee het rapport versleuteld wordt en waarmee je het op je
  telefoon opent. Kies een sterk wachtwoord, want de pagina staat publiek (de
  inhoud is versleuteld, maar de beveiliging valt of staat met dit wachtwoord).

Optioneel:
- **`FUNDA_BLACKLIST_JSON`** — alleen nodig als je een vaste blacklist wilt
  meegeven. Plak de inhoud van `funda_blacklist.json`. Anders gewoon overslaan.

### 2. Controleren waar GitHub Pages vandaan komt
**Settings -> Pages.** Het moet staan op: **Deploy from a branch**, branch
`main`, map `/docs`. Dat is je huidige situatie, dus waarschijnlijk hoef je niks
te wijzigen. De workflow pusht het rapport naar `docs/`, Pages serveert het.

### 3. Actions aanzetten
**Settings -> Actions -> General.** Zorg dat Actions toegestaan zijn, en onder
"Workflow permissions" staat **Read and write permissions** aan (nodig om het
rapport terug te pushen).

### 4. Eerste run testen
**Tab Actions -> "Funda dagelijks rapport" -> Run workflow.** Dit draait hem
meteen, zodat je niet tot morgenochtend hoeft te wachten. Als alles groen is,
staat het verse rapport op je Pages-URL.

## Hoe het daarna werkt
- Elke ochtend om 05:00 UTC (07:00 NL zomertijd, 06:00 wintertijd) draait de run
  vanzelf. Je opent gewoon je bestaande webapp-URL en ziet het verse rapport.
- De tijd aanpassen? Wijzig de `cron`-regel in
  `.github/workflows/funda-daily.yml`. De waarde is in UTC.

## Wat waar staat (privacy)
- **Secrets (nooit publiek):** je `funda_personal.json` (inkomen, postcode,
  werkpostcodes) en het wachtwoord. Staan versleuteld in GitHub Secrets, worden
  tijdens de run als bestand neergezet en direct daarna gewist.
- **Cache (niet publiek):** seen-ids, prijs-tracking en je werk-coordinaten.
  Blijven bewaard tussen runs, maar staan niet in de repo.
- **Publiek (maar versleuteld):** alleen `docs/` met het AES-versleutelde rapport.
- De run stopt expres met een foutmelding als het wachtwoord-secret ontbreekt, om
  te voorkomen dat er ooit een leesbaar rapport publiek komt te staan.

## Aandachtspunten
- **Eerste paar dagen:** prijsdaling- en "lang op funda"-vlaggen vullen zich pas
  als de tracking een paar runs heeft gedraaid. De eerste run legt alleen de
  huidige stand vast.
- **Cache-verval:** als er meer dan ongeveer een week geen run draait, kan de
  cache verlopen. Dan begint de tracking opnieuw en lijkt alles even "nieuw". Met
  de dagelijkse run gebeurt dat niet.
- **Mocht Funda de GitHub-servers blokkeren** (datacenter-IP's worden soms
  geweerd) en je krijgt lege resultaten: dan is het alternatief een self-hosted
  runner op je laptop of een kleine VPS. Laat het weten, dan zet ik dat klaar.
- Je kunt nog steeds lokaal draaien met `python funda_zoek.py`; dat blijft werken.
