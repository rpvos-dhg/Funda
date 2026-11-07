# Funda-rapport draaien op GitHub (zonder laptop)

Hiermee draait je Funda-run op GitHub in plaats van op je laptop. Je laptop hoeft
niet aan te staan. Je gevoelige gegevens komen uit GitHub Secrets en worden nooit
in de repo gezet. Alleen het versleutelde rapport wordt gepubliceerd. De regels
achter de opzet staan in `CLAUDE.md`.

## Eenmalig instellen (ca. 5 minuten)

### 1. Secrets aanmaken
Ga naar je repo op GitHub: **Settings -> Secrets and variables -> Actions ->
New repository secret**. Maak deze twee aan:

- **`FUNDA_PERSONAL_JSON`**
  Plak de volledige inhoud van je lokale `funda_personal.json`. Controleer het
  bestand eerst met `python -m json.tool funda_personal.json`: is de JSON
  ongeldig, dan stopt de run meteen. Een secret kun je niet aanvullen, alleen
  vervangen: plak dus altijd het hele bestand, ook als je één sleutel wijzigt.
  - De sleutels `beoordeling` (grens voor de woonlasten, gewichten, harde eisen,
    verrijking) en `financien` (scenario's, eigen geld, studieschuld, BKR,
    kosten koper, rente) zijn optioneel; zonder staat de standaard uit de code.
    Welke sleutels gelden staat in `CLAUDE.md` ("Config"), een voorbeeld met
    fictieve waarden in `funda_personal.example.json`. Een oude sleutel wordt
    niet meer gelezen; dan staat er een `::warning::` in de log.
  - Zet `thuis_coords` (`[lat, lon]` van je zoekpostcode) en `werk_coords`
    (`{postcode: [lat, lon]}`) er gerust in. Anders zoekt de run ze één keer op
    via PDOK; lukt dat niet, dan geen afstandsfilter of "reisafstand onbekend".
  - Wil je de knop "Nieuwe run" in het rapport (zie onderaan), zet er dan een
    veld `"actions_url"` in met de link naar je workflow.

- **`FUNDA_PWA_PASSWORD`**
  Zet hier hetzelfde wachtwoord als in je lokale `funda_pwa_password.txt`. Dit is
  het wachtwoord waarmee het rapport versleuteld wordt en waarmee je het op je
  telefoon opent. Kies een sterk wachtwoord, want de pagina staat publiek (de
  inhoud is versleuteld, maar de beveiliging valt of staat met dit wachtwoord).

Optioneel:
- **`FUNDA_BLACKLIST_JSON`**: alleen nodig als je een vaste blacklist wilt
  meegeven. Plak de inhoud van `funda_blacklist.json`. Wordt alleen gebruikt als
  de cache nog geen blacklist heeft.
- **`WEB_PUSH_PUBLIC_KEY`**, **`WEB_PUSH_PRIVATE_KEY`**,
  **`WEB_PUSH_SUBSCRIPTION`** en eventueel **`WEB_PUSH_SUBJECT`**: alleen nodig
  als je iOS-pushmeldingen wilt bij nieuwe woningen. Zie de sectie hieronder.

`FUNDA_MAIL_USER` en `FUNDA_MAIL_PASSWORD` gebruikt geen workflow meer (sinds
6 nov 2026); die secrets mogen weg.

### 2. Controleren waar GitHub Pages vandaan komt
**Settings -> Pages.** Het moet staan op: **Deploy from a branch**, branch
`main`, map `/docs`. De workflow pusht het rapport naar `docs/`, Pages serveert
het.

### 3. Actions aanzetten
**Settings -> Actions -> General.** Zorg dat Actions toegestaan zijn, en onder
"Workflow permissions" staat **Read and write permissions** aan (nodig om het
rapport terug te pushen).

### 4. Eerste run testen
**Tab Actions -> "Funda dagelijks rapport" -> Run workflow.** Dit draait hem
meteen. Als alles groen is, staat het verse rapport op je Pages-URL. Bij een lege
cache begint de run met een achterstand van het bestaande aanbod; die is na een
paar dagen weg. Sneller kan eenmalig met de input `sitemap_max_verkennen` = 600
(hoger gaat niet; zie `CLAUDE.md`).

## Hoe het daarna werkt
- De run draait vanzelf twee keer per dag, om 08:30 en 16:30 UTC: 10:30 en 18:30
  in de zomertijd, 09:30 en 17:30 in de wintertijd. GitHub kan een paar minuten
  later starten. Je opent gewoon je webapp-URL en ziet het verse rapport.
- De tijd aanpassen? Wijzig de `cron`-regels in
  `.github/workflows/funda-daily.yml`. De waarde is in UTC.
- Zoeken gaat op GitHub via funda's sitemaps: de zoek-API en de zoekpagina zijn
  dicht voor GitHub-servers. De details per woning komen van funda's
  detail-endpoint.

## Nieuwe run starten vanuit het rapport
In de topbalk van het rapport staat een knop met een vernieuwpijl (**Nieuwe
run**) als je in je config een `actions_url` hebt gezet, bijvoorbeeld:
`https://github.com/rpvos-dhg/Funda/actions/workflows/funda-daily.yml`.

De knop opent de Actions-pagina van de workflow. Daar klik je op **Run workflow**
om meteen een verse run te draaien. Bewust geen één-klik-trigger in de pagina
zelf: dat zou een GitHub-token met schrijfrechten vereisen, en dat hoort niet in
een publieke (zij het versleutelde) pagina thuis.

Zet `actions_url` zowel in je lokale `funda_personal.json` (voor lokale runs) als
in het secret `FUNDA_PERSONAL_JSON` (voor het rapport dat GitHub maakt).

## iOS-pushmeldingen via GitHub Actions

Dit gebruikt Web Push voor iOS-beginschermapps. Er is geen vaste backend nodig:
de PWA maakt een abonnement aan, jij slaat dat als GitHub Secret op, en GitHub
Actions verstuurt de push bij runs met nieuwe woningen. Een melding noemt per
woning adres, stad, het poortwoord (Past, Krap, Past niet of Prijs onbekend) en
de score, nooit een bedrag (een melding staat leesbaar op het vergrendelscherm).

1. Genereer VAPID-sleutels:

   ```bash
   npx web-push generate-vapid-keys
   ```

2. Maak GitHub Secrets:

   - `WEB_PUSH_PUBLIC_KEY`
   - `WEB_PUSH_PRIVATE_KEY`
   - optioneel `WEB_PUSH_SUBJECT`, bijvoorbeeld `mailto:jij@example.com`
     (zonder valt het terug op de URL van het rapport)

3. Draai de workflow een keer, zodat het rapport de publieke sleutel kent. Open
   daarna de PWA vanaf het iOS-beginscherm, ontgrendel het rapport, open het blok
   **Meldingen op deze iPhone** en tik op **Meldingen aanzetten**. Sta meldingen
   toe.

4. Tik op **Kopieer het abonnement** en sla de JSON op als GitHub Secret
   `WEB_PUSH_SUBSCRIPTION`.

Vanaf de volgende run met nieuwe woningen stuurt Actions een push (de stap
"Push-notificatie bij nieuwe woningen" in de log; zonder nieuwe woningen staat
daar "Geen nieuwe woningen, push overgeslagen"). Het blok verdwijnt zodra dit
toestel een abonnement heeft. Trekt iOS het abonnement later in of vervangt het
hem (de log meldt dan "Subscription is verlopen"), herhaal dan stap 3 en 4.

### Push testen zonder te wachten op nieuw aanbod
Er is geen aparte testworkflow meer. Test lokaal met het script dat de workflow
ook gebruikt, met een verzonnen woning (de bestanden hieronder staan in
`.gitignore`):

```bash
npm install --no-save --no-package-lock web-push@3
echo '{"nieuw_count": 1, "nieuw": [{"title": "Teststraat 1", "city": "Teststad", "status_push": "Past", "score": 8.0}]}' > funda_run_summary.json
read -rsp "Publieke sleutel: " WEB_PUSH_PUBLIC_KEY; echo
read -rsp "Privésleutel: " WEB_PUSH_PRIVATE_KEY; echo
read -rsp "Abonnement (de JSON uit stap 4, op één regel): " WEB_PUSH_SUBSCRIPTION; echo
export WEB_PUSH_PUBLIC_KEY WEB_PUSH_PRIVATE_KEY WEB_PUSH_SUBSCRIPTION
node scripts/send_web_push.cjs
unset WEB_PUSH_PUBLIC_KEY WEB_PUSH_PRIVATE_KEY WEB_PUSH_SUBSCRIPTION
rm funda_run_summary.json
```

Je krijgt dan de melding "1 nieuwe woning" met "Teststraat 1, Teststad · Past ·
8,0". Gebruik dezelfde sleutels als in de secrets. Plak ze na de vraag van
`read -s`, niet op de commandoregel zelf: wat je daar typt, komt in je
shellgeschiedenis (`~/.bash_history`), en de sleutels horen nergens op schijf
buiten GitHub Secrets. In PowerShell werkt hetzelfde met
`$env:WEB_PUSH_PRIVATE_KEY = Read-Host "Privésleutel"` (en zo voor de andere
twee); daarna `Remove-Item Env:WEB_PUSH_*`.

## Wat waar staat (privacy)
- **Secrets (nooit publiek):** je `funda_personal.json` (inkomen, postcodes,
  scenario's) en het wachtwoord. Staan versleuteld in GitHub Secrets, worden
  tijdens de run als bestand neergezet en direct daarna gewist.
- **Cache (niet publiek):** de state tussen runs, in de Actions-cache:
  `funda_seen_ids.json` (eerder geziene woningen), `funda_tracking.json`
  (prijs-tracking en de pool), `funda_blacklist.json`, `funda_werk_coords.json`
  en `funda_thuis_coords.json` (coördinaten van je postcodes),
  `funda_enrichment_cache.json` (verrijking, rente, robots.txt) en
  `funda_sitemap_cache.json` (de sitemaproute). Staat niet in de repo.
- **Publiek (maar versleuteld):** alleen `docs/` met het AES-versleutelde rapport.
- **Publieke log:** de Actions-log van een publieke repo is voor iedereen
  leesbaar. De run print daar alleen aantallen: geen woninglijst, geen postcode,
  geen bedragen.
- De run stopt expres met een foutmelding als het wachtwoord-secret ontbreekt, om
  te voorkomen dat er ooit een leesbaar rapport publiek komt te staan.

## Aandachtspunten
- **Eerste paar dagen:** prijsdaling- en "lang op funda"-vlaggen vullen zich pas
  als de tracking een paar runs heeft gedraaid. De eerste run legt alleen de
  huidige stand vast.
- **Cache-verval:** GitHub gooit een cache weg die een week niet gebruikt is. Dan
  begint de tracking opnieuw en lijkt alles even "nieuw". Met twee runs per dag
  gebeurt dat niet.
- **Rode run:** stopt de dagelijkse run met een fout, dan blijft het vorige
  rapport staan en wordt er niets gepubliceerd. De oorzaak staat in de
  `::error`-regel van de log; `CLAUDE.md` ("Wanneer stopt een run met exit 2")
  zegt wat elk geval betekent. De handmatige workflow **"Funda API debug"** laat
  zien of het aan de code ligt (job tests) of aan funda's kant (job funda-live).
- Je kunt nog steeds lokaal draaien met `python funda_zoek.py`. Let op: dat
  commit en pusht `docs/`; met `--no-push` niet.
