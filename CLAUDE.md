# CLAUDE.md

Projectcontext voor Claude Code. Lees dit eerst.

## Wat dit project doet

Dagelijkse Funda-checker voor een koopappartement (regio Den Haag). Twee Python-
scripts zoeken nieuw aanbod, analyseren betaalbaarheid en bouwen een rapport
(markdown + HTML + een versleutelde PWA). Het draait automatisch op GitHub
Actions en publiceert het rapport op GitHub Pages.

- Live rapport: https://rpvos-dhg.github.io/Funda/ (wachtwoord-beveiligd)
- Repo: https://github.com/rpvos-dhg/Funda

## Belangrijkste bestanden

- `funda_zoek.py` - hoofdscript. Zoekt per prijsband, filtert op buurt/stad/
  straat, detailcheck (belegging, begane grond, blacklist), houdt nieuw-zijn en
  prijs/looptijd-tracking bij, roept het rapport aan.
- `funda_rapport.py` - bouwt markdown/HTML/PWA. Rekent maandlasten, hypotheek
  (NHG, starter), reisafstand naar werk, erfpacht, energielabel, pros/cons.
- `.github/workflows/funda-daily.yml` - draait 2x/dag (08:30 en 16:30 UTC =
  10:30 en 18:30 NL), genereert het rapport en pusht `docs/`.
- `funda_personal.example.json` - template voor de privé-config.

## Privébestanden (NIET op git, staan in .gitignore)

Deze leven alleen lokaal en mogen nooit gecommit worden:
`funda_personal.json` (inkomen, postcodes), `funda_pwa_password.txt`,
`funda_seen_ids.json`, `funda_tracking.json`, `funda_werk_coords.json`,
`funda_blacklist.json`, `funda_log.txt`.

Op GitHub komen dezelfde gegevens uit Secrets: `FUNDA_PERSONAL_JSON` en
`FUNDA_PWA_PASSWORD`. Optionele PWA push gebruikt `WEB_PUSH_PUBLIC_KEY`,
`WEB_PUSH_PRIVATE_KEY` en `WEB_PUSH_SUBSCRIPTION`. De state (seen-ids, tracking,
werk-coords en verrijkingscache) staat in de Actions-cache, niet in de repo.

## Belangrijke valkuilen (eerder tegengekomen)

- **Zoek-API zit sinds 18 aug 2026 achter auth (`401 no token provided`).**
  `listing-search-wonen.funda.io/_msearch/template` eist nu een token dat
  pyfunda niet meestuurt; ook v3.1.4 niet (upstream issue 0xMH/pyfunda#15, zelfde
  datum, nog steeds open en zonder commits sinds 17 juli). Daarom zoekt het
  script nu via de publieke zoekpagina, zie hieronder.
  Diagnose herhalen: workflow "Funda API debug" (draait ook automatisch zodra een
  dagelijkse run faalt).
- **Zoeken gaat via HTML, verrijken via de API.** `funda_html_zoek.py` haalt de
  woning-URL's van `www.funda.nl/zoeken/koop` (server-rendered Vue/Nuxt, geen
  bot-muur vanaf een Actions-runner) en laat het detail-endpoint - dat nog wél
  werkt - de rest invullen. Dat detail-antwoord bevat exact dezelfde velden als
  de oude zoek-API, inclusief `neighbourhood`, waar de buurtfilters op draaien.
  `HtmlZoeker` is een drop-in voor het `Funda`-object, dus `main()` en het
  rapport weten hier niets van.
  - Schakelen met `FUNDA_ZOEK_METHODE` of `zoek_methode` in de config:
    `auto` (standaard, probeert eerst de API en valt terug op HTML), `api`, `html`.
    Zodra Funda de API weer openzet, schakelt `auto` vanzelf terug.
  - De parser leunt op de klasse `@container` per woningkaart en op de tekst in
    die kaart. Verandert funda's markup, dan faalt `test_funda_html.py` niet
    (die draait op een fixture) maar `scripts/funda_html_validatie.py` wél.
    Structuur opnieuw afleiden: `scripts/funda_html_analyse.py`.
  - Detail-calls zijn het dure deel. Ze worden gecacht en overgeslagen voor
    woningen die op stad of straat-segment toch al afvallen.
  - **De straal moet een waarde zijn die funda kent** (1, 2, 5, 10, 15, 30, 50).
    Een andere waarde, zoals de 6 km uit de config, geeft géén foutmelding maar
    een lege resultatenpagina: status 200, nul kaarten. `snap_straal()` rondt
    daarom af op de dichtstbijzijnde ondersteunde waarde, net als de oude API.
    Zelfde valkuil bij het gebied: een postcode moet lowercase en zonder spatie.
- **"0 woningen" is niet hetzelfde als "zoeken stuk".** Een run stopt met exit
  code 2 - rapport en state onaangeroerd - in twee gevallen: geen enkele
  geslaagde zoek-call (API dicht), of wél geslaagde calls maar samen nul
  woningen. Dat tweede is de faalmodus van de HTML-route: gewijzigde markup geeft
  netjes 200 en nul kaarten, zonder exception. Zonder deze checks schrijft een
  kapotte zoekmethode een leeg rapport over het gevulde rapport heen terwijl de
  Action groen blijft.
- **pyfunda pin.** Het script gebruikt de v2.x API (`f.search_listing(...)` en
  `r.data` dicts). v3+ is een dataclass-rewrite zonder die methodes. Daarom is
  pyfunda vastgepind op `v2.9.0` in zowel `requirements.txt` als de workflow.
  Niet zomaar upgraden zonder de code mee te porten.
- **Niet in OneDrive zetten.** De repo stond eerst in een OneDrive-map. Dat gaf
  afgekapte bestanden bij opslaan en kapotte `.git`-locks. Daarom verplaatst naar
  `C:\dev\Funda`. Houd de repo buiten OneDrive.
- **Encryptie verplicht in CI.** `funda_rapport.py` weigert een onversleuteld
  rapport te schrijven als `FUNDA_REQUIRE_ENCRYPTION=1` (gezet in de workflow),
  zodat er nooit per ongeluk leesbare data publiek komt.
- **Bot pusht zelf.** De workflow commit `docs/` terug naar `main`. Doe lokaal
  altijd `git pull --rebase` voor je commit, anders wordt je push afgewezen.

## Lokaal draaien

```
pip install -r requirements.txt
python funda_zoek.py            # volledige run + rapport, opent HTML
python funda_zoek.py --no-open  # zonder browser
```

## Tests

- `python test_funda_zoek.py` - offline tests voor de veiligheidschecks in
  `main()`: een run stopt met exit 2 als álle zoek-calls falen én als ze allemaal
  slagen maar samen nul woningen opleveren.
- `python test_funda_html.py` - offline tests voor de HTML-zoekfallback
  (URL-opbouw, kaart-parser, drop-in-gedrag, dedup). Draait op een fixture die is
  nagebouwd op echte markup, dus geen netwerk nodig.
- `python scripts/funda_html_validatie.py` - controleert diezelfde parser tegen
  de échte funda.nl. Dit is de test die afgaat als funda hun HTML verandert.
- `test_funda.py` (indien aanwezig) stubt de funda-library en test
  band-splitsing, tracking, prijsdaling-detectie en rapport-rendering offline.

## Kernfeatures (waarom de code is zoals hij is)

- **Prijsband-splitsing.** Funda kapt een zoekopdracht af op ~140 resultaten.
  Door per prijsband (stap 20k) te zoeken en te dedupen pakken we meer van de
  markt, inclusief woningen die al lang te koop staan.
- **Eigen prijs-tracking** in `funda_tracking.json`: detecteert prijsdalingen
  los van wat Funda teruggeeft. Flags voor prijsdaling en "lang op funda".
- **Verversknop** in het rapport linkt naar de Actions "Run workflow"-pagina
  (geen token nodig, dus veilig op een publieke pagina).
- **iOS PWA push** werkt zonder vaste backend: de webapp toont een subscription
  JSON, die als GitHub Secret `WEB_PUSH_SUBSCRIPTION` wordt opgeslagen. Actions
  stuurt daarna met `scripts/send_web_push.cjs` een Web Push bij nieuwe woningen.
