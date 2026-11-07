# CLAUDE.md

Projectcontext voor Claude Code. Lees dit eerst. Hier staan de regels en
besluiten; de metingen en run-id's waarop ze rusten staan in
`notities/geschiedenis.md` (wordt niet automatisch geladen).

## Wat dit project doet

Dagelijkse Funda-checker voor een koopappartement (regio Den Haag). Twee Python-
scripts zoeken nieuw aanbod, analyseren betaalbaarheid en bouwen een rapport
(markdown + HTML + een versleutelde PWA). Het draait automatisch op GitHub
Actions en publiceert het rapport op GitHub Pages.

- Live rapport: https://rpvos-dhg.github.io/Funda/ (wachtwoord-beveiligd)
- Repo: https://github.com/rpvos-dhg/Funda
- Rooster: twee keer per dag, om 08:30 en 16:30 UTC. Dat is 10:30 en 18:30 in de
  zomertijd en 09:30 en 17:30 in de wintertijd (GitHub-cron is UTC).
- Instellen op GitHub (secrets, Pages, push): `SETUP_GITHUB_ACTIONS.md`.

## Belangrijkste bestanden

- `funda_zoek.py` - hoofdscript. Zoekt per prijsband, filtert op buurt/stad/
  straat, detailcheck (belegging, begane grond, blacklist), houdt nieuw-zijn en
  prijs/looptijd-tracking bij, roept het rapport aan.
- Zoekbronnen, elk een drop-in voor pyfunda's `Funda`-object: de zoek-API zelf,
  `funda_html_zoek.py` (zoekpagina), `funda_sitemap_zoek.py` (funda's sitemaps,
  op Actions de bron die werkt) en `funda_mail_bron.py` + `funda_mail_ophalen.py`
  (notificatiemails; sinds 6 nov 2026 alleen nog met `zoek_methode: mail`, niet
  in `auto`). `kies_zoeker()` kiest; zie "Zoekmethode kiezen".
- `funda_rapport.py` - bouwt het rapport: detail-call, reisafstand naar werk,
  beoordeling, verrijking en rente per woning, en schrijft markdown, HTML en de
  versleutelde PWA in `docs/`. Zie "Rapport, beoordeling en PWA" hieronder.
- `funda_beoordeling.py` - het beoordelingsmodel: poort (Past, Krap, Past niet,
  Prijs onbekend) met de leentoets 2026 (`data/trhk_2026_tabel1.json`) en de
  scenario's, score 0 tot 10 met uitleg, parsers voor funda's kenmerken. Pure
  functies, geen netwerk.
- `funda_verrijking.py` (open bronnen per woning, en de geocoding van postcodes
  via PDOK) en `funda_rente.py` (actuele hypotheekrente). Fail-soft, met budget,
  robots.txt en eerlijke user-agent.
- `funda_ui.py` met `ui/app.css`, `ui/app.js` en `ui/slot.html` - de UI (lijst,
  kaart, sheets) en het slotscherm. Geen import van `funda_rapport`. Tokens en
  regels van het palet: `.interface-design/system.md`.
- `.github/workflows/funda-daily.yml` - de dagelijkse run (rooster hierboven):
  genereert het rapport, publiceert `docs/` en stuurt de push.
  `.github/workflows/funda-debug.yml` ("Funda API debug", alleen handmatig):
  job **tests** (elk `test_*.py`) en job **funda-live**.
- `scripts/` - gereedschap buiten de dagelijkse run: `funda_api_debug.py` (job
  funda-live), `funda_html_validatie.py`, `funda_sitemap_validatie.py` en
  `funda_mail_validatie.py` (tegen de echte site of een echte mail),
  `funda_html_analyse.py`, `funda_sitemap_probe.py`, `funda_mail_imap_check.py`
  (alleen lokaal), `state_migratie.py` (cachemigratie) en `send_web_push.cjs`
  (de push, ook in de workflow).
- `data/trhk_2026_tabel1.json` - tabel 1 van de leentoets en de labelbedragen
  (zie "Jaarwissel").
- `testdata/` - fictieve fixtures: `woningen.json` (fixture-render),
  `beoordeling_v3.json` (UI), `beoordeling_verwacht.json` (golden file van het
  model), `verrijking/` en `rente/` (ingekorte echte antwoorden).
- `funda_personal.example.json` - template voor de privé-config.
- `notities/geschiedenis.md` - meetgeschiedenis en run-id's.

## Privébestanden (NIET op git, staan in .gitignore)

Deze leven alleen lokaal en mogen nooit gecommit worden; `.gitignore` is de
volledige lijst.

- Config en geheimen: `funda_personal.json` (inkomen, postcodes, de sleutels
  `beoordeling` en `financien`), `funda_pwa_password.txt`, `subscription.json`.
- State: `funda_seen_ids.json`, `funda_tracking.json`, `funda_blacklist.json`,
  `funda_werk_coords.json`, `funda_thuis_coords.json`,
  `funda_enrichment_cache.json`, `funda_sitemap_cache.json`.
- Uitvoer van een lokale run: `funda_log.txt`, `funda_run_summary.json`,
  `funda_rapport.md`, `funda_rapport.html`.
- `funda_seeds_lokaal.json` (eigen tiny_id's voor de sitemap-probe en
  -validatie).

Op GitHub komen dezelfde gegevens uit Secrets: `FUNDA_PERSONAL_JSON` en
`FUNDA_PWA_PASSWORD` (verplicht), `FUNDA_BLACKLIST_JSON` (optioneel; alleen
gebruikt als de cache nog geen blacklist heeft) en voor de push
`WEB_PUSH_PUBLIC_KEY`, `WEB_PUSH_PRIVATE_KEY`, `WEB_PUSH_SUBSCRIPTION` en
optioneel `WEB_PUSH_SUBJECT`. Een secret vul je niet aan, je vervangt hem: plak
de hele `funda_personal.json`, na een controle met
`python -m json.tool funda_personal.json`. `FUNDA_MAIL_USER` en
`FUNDA_MAIL_PASSWORD` gebruikt geen workflow meer (sinds 6 nov 2026); die
secrets mogen weg. De zeven state-bestanden staan in de Actions-cache, niet in
de repo (zie de valkuil over de padenlijst).

## Rapport, beoordeling en PWA (bouwronde nov 2026)

Ontwerp en besluiten: eigen palet (geen huisstijl van een merk), verrijking aan,
financiële scenario's, rentemodule, "Onthoud" zonder leesbaar wachtwoord.

- **Volgorde in `genereer_rapport()`.** Per woning: detail-call (in `funda_zoek`
  gecacht, dus geen extra funda-verkeer), pyfunda-verrijking (prijshistorie,
  buurtcijfer, makelaar), **eerst de routes** (de reisafstand telt mee in de
  score), dan een voorlopige beoordeling. Daarna de verrijking uit open bronnen
  (Past en Krap eerst, binnen het budget) en de definitieve beoordeling.
  Sorteren op `(geen vraagprijs, poort, twijfel, -score)`: zonder vraagprijs altijd
  achteraan, ook een veiling op PAST NIET (`funda_beoordeling.sorteer`, dezelfde
  sleutel als "Aanbevolen" in de UI). De beoordeling staat in `rij["beoordeling"]`
  en in `d["_beoordeling"]` (contract: docstring van `funda_beoordeling.py`).
- **Twijfel en push (`funda_zoek.py`).** `d["_twijfel"]` = korte zinnen
  (`twijfel_redenen`: twijfelbuurt van je lijst, gemeente Leidschendam-Voorburg);
  de woning blijft staan, onderaan in zijn groep. Leefbaarometer zwak komt uit de
  verrijking. Na het rapport zet `vul_summary_aan()` per nieuwe woning
  `status_push` (alleen het poortwoord: Past, Krap, Past niet of Prijs onbekend)
  en `score` in `funda_run_summary.json`; `scripts/send_web_push.cjs` toont dan
  "<adres>, <stad> · Past · 8,3", zonder beoordeling "<adres>, <stad> · 68 m2".
  De push toont de eerste drie, en `vul_summary_aan()` zet de nieuwe woningen
  daarvoor in de volgorde van "Aanbevolen" (`funda_beoordeling.sorteer`; zonder
  beoordeling achteraan), niet die van `sort_key` in `main()` (console en
  voorlopige samenvatting). Vastgepind in `test_funda_zoek.py::test_push_volgorde`.
  **Nooit een eurobedrag in de push** (eindreview PR #19): de statusregel (een
  bedrag onder de norm, of eigen geld te weinig) geeft met de publieke code en de
  publieke woningdata het bruto inkomen of het eigen geld terug, en een melding
  staat leesbaar op het vergrendelscherm. De bedragen staan alleen in het
  versleutelde rapport. Vangnet in het script: elk deel met een €-teken valt weg,
  ook bij een oude samenvatting met `status`.
- **Config.** `beoordeling` (grens `max_woonlasten_netto`, `krap_marge`,
  gewichten, harde eisen, `verrijking`) en `financien` (scenario's met
  toetsinkomen, eigen geld, studieschuld, BKR, kosten koper, rente) in
  `funda_personal.json` en de secret `FUNDA_PERSONAL_JSON`. Alles optioneel; de
  standaard staat in de code (`funda_beoordeling.STANDAARD`; die van
  `beoordeling.verrijking` alleen in `funda_verrijking.STANDAARD`). Voorbeeld met
  fictieve waarden in `funda_personal.example.json`. Zonder `financien` rekent
  het model met `bruto_jaar`, `eigen_inleg`, `duo_maandlast` en `leeftijd`,
  zonder scenario's. Inkomen komt nooit in het rapport, de log of de pushmelding.
  **Scenario's zonder eigen namen in de code** (opruimronde nov 2026). De echte
  id's en labels staan alleen in de secret; code, tests, fixtures en de
  voorbeeldconfig gebruiken fictieve (`nu`, `later`, `later_extra`; werk A en
  B). `test_funda_beoordeling.py::test_geen_scenarionamen` weigert de oude
  namen in elk bijgehouden bestand buiten `docs/`, ook als datum of
  uitgeschreven maand (met een eigen controle op die patronen). De logica kent geen id's
  behalve `nu`: scenario's staan op datum (`datum`, anders uit een id
  `JJJJ_MM`, anders vandaag), op dezelfde datum een voorwaardelijk scenario
  (`"voorwaardelijk": true`) na het gewone. De poort volgt `planning`; zonder
  geldige planning het eerste scenario na `nu` op datum (een voorwaardelijk
  alleen als er geen ander is), of het enige. Per woning: "Past " + label met
  een kleine eerste letter ("Past nu", "Past later"), bij een voorwaardelijk
  scenario "Past alleen " + label, anders "Past in geen scenario". Zonder label:
  "Nu", "Vanaf <maand jaar>" (plus wat er in het id na `JJJJ_MM` staat) of het
  id. Ontbreekt de vlag, dan is het voorwaardelijke scenario stil een gewoon
  scenario ("Past " + label); zet hem dus in de secret.
  **Welke sleutels gelden (sinds 7 nov 2026 alleen deze; de secret gebruikt ze
  ook):**
  - `beoordeling`: `score_basis`, `m2_wens`, `max_woonlaag_zonder_lift`,
    `fiets_kmu`, `lang_op_funda_dagen`, `max_woonlasten_netto`, `krap_marge`,
    `financiering` (`alleenstaand`, `overbod_pct`, `kk_onzekerheid`,
    `eigen_geld_tekort_past_niet`, `starter_tot`), `harde_eisen`, `werk`,
    `gewichten`, `drempels`, `verrijking`. `lang_op_funda_dagen` mag ook op het
    hoogste niveau (die leest `funda_zoek` ook).
  - `financien`: `alleenstaand`, `starter_tot`, `planning`, `scenarios` (per id
    `bruto_jaar`, `label`, optioneel `datum`, `eigen_geld` en `voorwaardelijk`;
    een kaal getal mag ook), `studieschuld.maandlast`, `bkr` (`[{limiet, opgezegd}]` of
    `[{maandlast}]`), `eigen_geld` (`nu`, `datum`, `per_maand`, `buffer`),
    `kosten_koper` (`vast`, `nhg_pct`) en `rente` (`pct`, `datum`,
    `rentevast_jaren`, `bron`, `nhg`, `ltv`, `max_dagen`).
  - **Weg** (G5 van de opruimronde): de oude aliassen, zoals
    `financien.toetsinkomen` en de rentesleutels in `beoordeling.financiering`;
    de lijst is `funda_beoordeling.OUDE_SLEUTELS`. Die worden niet meer gelezen.
    Staat er toch een in de config, dan rekent het rapport met de standaard en
    zet het een `::warning::` met alleen de vaste paden (`oude_sleutels()`),
    nooit de waarden en nooit een scenario-id (`<scenario>`: de log is publiek).
- **Rente (`funda_rente.py`).** Een handmatige rente gaat altijd voor
  (`financien.rente.pct` met `datum`; de enige plek). Rentevast staat ook daar
  (`financien.rente.rentevast_jaren`, standaard 10; korter dan 10 jaar = toetsrente
  5%). `funda_rente` leest `cfg["financien"]["rente"]` zelf; er is geen
  vertaallaag meer. Anders het nieuwste ASN-tariefblad (statische
  PDF's in het rentearchief op `www.asnbank.nl`; robots.txt verbiedt daar alleen
  `/web/contentViewCounter`), anders het DNB-cijfer "rente op nieuwe hypotheken"
  via het ECB Data Portal (`data-api.ecb.europa.eu`, `/service/data` toegestaan),
  anders 4,11% van 6 juli 2026 met een melding (`funda_beoordeling.STANDAARD_RENTE`,
  één bron voor model en `funda_rente`). Hooguit één poging per dag. Bron
  en peildatum staan in "Jouw budget"; ouder dan 30 dagen = melding bovenaan.
  **Bewust niet gebruikt:** de eigen API achter de rentepagina van ASN (vraagt een
  sleutel uit hun JavaScript-bundel) en de API van DNB (abonnementssleutel).
- **Verrijking (`funda_verrijking.py`).** Aan (`beoordeling.verrijking.aan`).
  **Eén bron per waarde:** de standaard van `beoordeling.verrijking` staat alleen
  in `funda_verrijking.STANDAARD` (`instellingen()` legt het blok uit de config
  eroverheen); `LBM_KLASSE`, `FUND_KLASSE` en de drempels die de verrijking
  gebruikt komen uit `funda_beoordeling` (die zelf geen projectmodule importeert,
  `test_import_zonder_personal`); `EERLIJKE_UA` staat in `funda_verrijking` en
  `funda_zoek` exporteert hem opnieuw (`test_ua`, `test_een_bron`).
  Bronnen en robots (gemeten 7 nov 2026): BAG en CBS-buurten via `api.pdok.nl`
  (robots verbiedt alleen de Locatieserver, die niet gebruikt wordt),
  Klimaateffectatlas (`cas.cloud.sogelink.com`, geen robots.txt), RIVM-
  geluidkaarten (`data.rivm.nl`, geen robots.txt), Leefbaarometer 3.0
  (`geo.leefbaarometer.nl`, lege robots.txt) en de RIVM-gezondheidsmonitor via
  CBS (`dataderden.cbs.nl`, geen robots.txt). robots.txt per host eerst, vers op
  de dag van ophalen (RFC 9309 par. 2.4: hooguit 24 uur; ook voor `funda_rente`);
  de laatste goede versie (hooguit 30 dagen) alleen als terugval bij een time-out
  of 5xx, nooit bij een weigering. `EERLIJKE_UA`, sequentieel met pauze, time-out 10 s, budget 60
  verzoeken per run (± 5 per nieuwe woning; daarna bijna alles uit de cache).
  Per host stoppen bij 401/403/429/5xx en die host een dag dicht laten; nooit
  omzeilen. Een fout geeft "onbekend" in het rapport, nooit exit 2 en nooit een
  woning minder. Allowlist van velden: herkomst, nationaliteit, inkomen en andere
  bevolkingskenmerken worden nooit gelezen, bewaard of getoond. Ook van funda's
  buurtcijfers wordt alleen de vraagprijs per m² bewaard; bij laden en opslaan
  gaat de hele cachesectie `market_insights` door die allowlist, ook buurten die
  deze run niet langskomen. Niet automatisch: het
  WOZ-waardeloket en KOOP (robots verbiedt het). De RIVM-laagnamen hebben een
  datum (`rivm_20250101_...`); verdwijnt een jaargang, dan wordt geluid
  "onbekend" tot `RIVM_LAGEN` is bijgewerkt.
- **Geocoding en routes.** Postcodes worden punten via de BAG-collectie `adres`
  op `api.pdok.nl` (`funda_verrijking.Geocoder`, filter op postcode, het punt
  van het eerste adres): de werkpostcodes (`funda_rapport.get_werk_coords`) en
  de zoekpostcode (`funda_zoek.thuis_coords`, alleen met het afstandsfilter
  aan). Per postcode gaat de config voor (`werk_coords` als
  `{postcode: [lat, lon]}`, `thuis_coords` als `[lat, lon]`), dan de caches
  `funda_werk_coords.json` en `funda_thuis_coords.json` (`{postcode: [lat, lon]}`),
  dan één poging via PDOK; een gevonden punt blijft voorgoed in die cache. Een
  eigen `Sessie` met de regels van de verrijking (robots.txt eerst,
  `EERLIJKE_UA`, nooit omzeilen) en **één stand voor `api.pdok.nl` per run**
  (`genereer_rapport` geeft hem door: `neem_cache_over`, `Sessie.neem_over`):
  een weigering (401/403/429) komt in `verrijking_weigering` van
  `funda_enrichment_cache.json` en houdt de host een dag dicht voor geocoding én
  verrijking, een serverfout sluit hem de rest van de run ook voor de
  verrijking, en robots.txt gaat één keer per run. Een time-out niet: dat ene
  zware verzoek zegt niets over de lichte van de verrijking. Traag (meting in de
  notities), dus `limit=1`, time-out 60 s, één poging per postcode per run, en
  na een time-out is de host die run dicht voor de geocoding. Lukt het niet, dan
  een `::warning::` met alleen aantallen en de reden (nooit de postcode): zonder
  thuispunt geen afstandsfilter (onbekend = doorlaten, en de sitemaproute haalt
  dan ook woningen buiten de straal vers op; zet daarom `thuis_coords` in de
  config), zonder werkpunt "reisafstand onbekend" (geen minpunt). **Bewust
  niet:** Nominatim (`nominatim.openstreetmap.org`, robots.txt verbiedt
  `/search`, `/reverse` en `/lookup`; gelezen 7 nov 2026) en de PDOK
  Locatieserver (robots.txt verbiedt `/bzk/locatieserver/*`). De route komt van
  OSRM (`router.project-osrm.org`, geen robots.txt), ook met `EERLIJKE_UA`,
  anders hemelsbreed x 1,3.
- **Cache.** Alles in het bestaande `funda_enrichment_cache.json`, als secties:
  `price_history`, `market_insights`, `broker` (pyfunda), `bag`, `fundering`,
  `geluid`, `buurtcode`, `leefbaarometer`, `tevredenheid`, `robots`,
  `verrijking_weigering` en `rente`. Adres- en puntsleutels zijn gehasht. Geen
  nieuw cachepad (zie de valkuil over de padenlijst). Van de makelaar alleen naam
  en reviews: zijn aanbod (`get_broker_listings`, een extra funda-verzoek met
  adressen van andere woningen) wordt sinds de opruimronde van nov 2026 niet meer
  opgehaald, en bij laden en opslaan uit oude cache-elementen gehaald.
- **Prijs op aanvraag.** Woningen zonder vraagprijs gaan standaard weg in de
  nafilter (`buiten_zoekcriteria`, reden "geen vraagprijs"), net als vroeger bij
  de zoek-API. Met `prijs_onbekend_tonen: true` komen ze terug, en dan: poort
  "Prijs onbekend", geen leentoets en geen woonlasten, score alleen uit
  onderdelen die niet van de prijs afhangen, altijd achteraan (ook bij
  client-side sorteren: prijs en woonlasten zijn leeg in `#woning-data`), "op
  aanvraag" en "onbekend" in de kerncijfers, "prijs op aanvraag" in markdown en
  pushmelding, en in de tracking geen prijs 0 (anders een "prijsdaling" van
  100%). Nooit rekenen met prijs 0: dat gaf budget "PAST", de laagste maandlast
  en de hoogste score. Vastgepind in `test_prijs_onbekend` (`main()`) en
  `test_prijs_onbekend_rapport` (het echte `bouw_rij` en `funda_ui`).
- **PWA.** De body wordt eerst met gzip ingepakt (niveau 9, mtime 0) en daarna
  versleuteld met AES-256-GCM (PBKDF2-SHA256, 100.000 iteraties, 16 byte zout,
  12 byte IV, ongewijzigd). Ciphertext comprimeert niet, dus zonder gzip vooraf
  kan Pages hem niet kleiner maken (fixture: 98 kB op schijf, 38 kB gzip). Het
  slotscherm is `ui/slot.html` (`funda_ui.vul_slot`); zonder
  `DecompressionStream` (iOS ouder dan 16.4) zegt het dat, in plaats van "fout
  wachtwoord". "Onthoud op dit apparaat" bewaart een niet-exporteerbare
  PBKDF2-sleutel in IndexedDB (30 dagen), nooit het wachtwoord; een oud bewaard
  wachtwoord wordt bij openen omgezet en gewist. Service worker cache
  `funda-shortlist-v5` (ophogen bij elke nieuwe wrapper, anders blijft een
  geïnstalleerde PWA de oude tonen). Manifest "Woningrapport" / "Woningen"
  (geen voornaam: het staat publiek), kleuren `funda_ui.THEME_COLOR` en
  `funda_ui.ACHTERGROND`, iconen in hetzelfde palet. "Nieuw" geldt per apparaat en
  telt pas als gezien als de kaart minstens half een seconde in beeld was, tussen
  de vaste top- en onderbalk.
- **Huisstijl: eigen palet "Inkt en blauw", bewust geen ANWB-huisstijl.** Kleuren,
  stylesheet, iconen en fonts van het ANWB-designsysteem zijn merkeigendom van de
  ANWB (merkrecht), en de CSS van het slotscherm staat buiten de versleuteling
  publiek op GitHub Pages. Daarom een eigen palet met dezelfde opbouw (tokens
  licht en donker, feedbackkleuren alleen voor feedback, WCAG AA gemeten).
  Tokens en regels: `.interface-design/system.md`. `test_funda_ui.py` weigert
  ANWB-blauw `#003d86`, geel `#ffcd00` en de merk- en fontnamen. Het eerdere
  paarse palet "Lavendel" is op 7 nov 2026 door de eigenaar afgewezen; de test
  weigert ook paarse tokens en pint topbalk `#0f172a`, knop `#2563eb`, link
  `#1d4ed8` en pagina `#f4f6f9` vast.
- **Log.** Alleen aantallen: labelnamen van funda's `characteristics` met hoe
  vaak ze voorkwamen (om de parsers te kalibreren), aantallen per poort,
  verrijking per bron en status, rente met bron. Nooit adressen, postcodes of
  bedragen van het profiel. De Actions-log van deze publieke repo is voor
  iedereen leesbaar; op Actions (`GITHUB_ACTIONS` gezet, `publieke_log()` in
  `funda_sitemap_zoek.py`) geldt daarom ook voor `main()`:
  - de startregel toont de postcode als "(verborgen)", en de zoek-URL van de
    HTML-route ook de prijs- en m2-grenzen;
  - geen woninglijst (`toon_lijsten()`: titel, postcode, wijk, prijs, URL; de
    lijsten "Eerder gezien" en "Afgewezen" met redenen, ook de blacklist), maar
    `toon_aantallen()`: nieuw, eerder gezien, afgewezen per reden (belegging,
    begane grond, blacklist) en met prijsdaling. De lijst staat in het
    versleutelde rapport. Lokaal blijft de volledige lijst, voor de diagnose.
  - geen regel per prijsband, alleen het totaal: de grenzen komen uit het
    profiel, het aantal banden maal de bandstap geeft de breedte van het budget
    en de aantallen per band waar het aanbod valt. Daarom ook geen aantallen
    zoek-calls (banden maal sorteringen) en elke zoekfout één keer
    ("Zoekfout: ..."). Een mislukte detail-call heet "een woning", zonder pad of
    nummer; `--debug-wijken` (buurten met aantallen) werkt alleen lokaal.
  - Vangnet: `log()` en de `::error::`-regels in `funda_zoek.py`, de foutregels
    van de zoekers en de detailfout in `funda_rapport.py` gaan door
    `log_tekst()`, dat detailpaden, detail-URL's en woningnummers (7 of meer
    cijfers) vervangt door "(woning)". Een foutmelding van de client noemt de
    woning ("status 403 voor https://www.funda.nl/detail/..."), en zo'n melding
    belandt in de `::error::`.
  Vastgepind in `test_funda_zoek.py::test_publieke_log` (`main()` met
  `GITHUB_ACTIONS` op de stubs). Verder zet `test_funda_zoek.py` `GITHUB_ACTIONS`
  bovenaan uit, zodat de job tests hetzelfde doet als lokaal.
- **Jaarwissel.** `test_funda_beoordeling.py` faalt op 1 januari zolang tabel 1
  niet van het lopende jaar is: dan `data/trhk_2026_tabel1.json` (tabel 1 en de
  labelbedragen), de NHG-grens en de startersgrens in `funda_beoordeling.py`
  bijwerken. Rente: zet je eigen rente in `financien.rente` als je een offerte
  hebt; anders volgt het rapport ASN.
- **Fixture-render.** De 13 fictieve woningen in `testdata/woningen.json` gaan in
  `test_funda_zoek.py::test_rapport_testdata` door het echte
  `genereer_rapport()` (stub-client, tijdelijke map, ontsleutelen in Python).
- **Fail-soft tegenover luid falen.** Rente, verrijking en geocoding mogen een
  run nooit laten falen (`haal_rente`, `verrijk_rijen`, de `::warning::` van de
  geocoding). De funda-checks die een run met exit 2 stoppen (zoekbron stuk,
  detail-endpoint dicht) blijven in `main()`; zie de lijst hieronder.

## Wanneer stopt een run met exit 2

Exit 2 betekent: de run stopt vóór het rapport. Rapport, `docs/`, seen-ids en
tracking blijven onaangeroerd (niets wordt nieuw, gezien of `weg`), er wordt
niets gepubliceerd en de dagelijkse workflow wordt rood. Wat de run al ophaalde,
mag wel in de caches blijven (`funda_sitemap_cache.json`, ook de verkenning uit
geval 4, en `funda_thuis_coords.json`): de stap "State bewaren (cache)" draait
met `if: always()`, dus de volgende run hoeft dat werk niet opnieuw te doen.
"0 woningen" is niet hetzelfde als "zoeken stuk": zonder deze checks schrijft een
kapotte zoekmethode een leeg of half rapport over het gevulde heen, terwijl de
Action groen blijft. De checks staan in `main()` (`funda_zoek.py`); de tests in
`test_funda_zoek.py`, tenzij anders vermeld.

1. **Geen enkele geslaagde zoek-call** ("Alle zoekopdrachten mislukt"), zoals bij
   een dichte zoek-API. Zo eindigt ook een kapotte sitemapbron: die gooit zijn
   fout bij elke zoekaanroep opnieuw, zonder nieuw verzoek. Fouten in de bron:
   een 401 of 403, HTML in plaats van XML, een robots.txt van `www.funda.nl` die
   `/detail/` uitsluit (`detail_verboden()`), nul kandidaten, een ingestelde stad
   met nul URL's (typfout of andere slug bij funda; viel eerst stil weg, terwijl
   getrackte woningen via de pool het rapport normaal lieten lijken), en de
   nieuwste lastmod onder de kandidaten ouder dan 3 dagen of geen lastmod
   (`MAX_LEEFTIJD_DAGEN`: een bevroren sitemap gaf anders een groene run zonder
   ooit nog nieuw aanbod). Tests: `test_alles_faalt`,
   `test_sitemapbron_faalt_luid`; `test_funda_sitemap.py::test_fouten`,
   `test_steden`, `test_leeftijd`.
2. **Alle zoek-calls geslaagd, samen nul woningen.** De faalmodus van de
   HTML-route: gewijzigde markup geeft netjes 200 en nul kaarten, zonder
   exception. Ook de mailroute komt hier uit als de mailbox niet te lezen is.
   Test: `test_stille_lege_oogst`.
3. **Geen enkele bron in `auto`.** `kies_zoeker()` zet één `::error` met de
   oorzaken (API, zoekpagina, sitemaps) en geeft een `GeenBron` terug, die bij
   elke zoekaanroep faalt zonder netwerk; daarna geval 1. Het zoekwerk van de
   sitemaproute gebeurt in `auto` al in `kies_zoeker()` (`ophalen()`), want
   `bereikbaar()` kijkt alleen naar robots.txt en de index: een koop-sitemap die
   daarna een 403 geeft, staat zo met zijn oorzaak in die ene `::error`. De
   mailbox gaat in `auto` niet open, ook dan niet. Test: `test_auto_keten`.
4. **Detail-endpoint dicht** (`DetailEndpointDicht`), in de zoeker of in de pool,
   ook halverwege de run:
   - meteen bij 401/403/429;
   - bij `DICHT_NA` (5) mislukte calls op rij, ook na eerdere successen. Een
     nette 404 telt niet mee (een antwoord van een werkend endpoint; de e2e zag
     er 1 per 200 calls) en zet de reeks terug op 0, in de zoeker en in de pool.
     De pool telt door vanaf de laatste calls van de zoeker;
   - als de run eindigt met mislukte calls: misschien ging het endpoint net
     dicht. Zonder dit vielen de ververste woningen weg, en bleef dat halve
     rapport staan zolang de volgende runs al bij de eerste call faalden.
   Elke funda-route verrijkt via dit endpoint, dus er is geen terugval naar een
   andere bron. De geslaagde verkenning wordt vóór het stoppen in de
   sitemapcache bewaard; niets wordt als `weg` gemarkeerd. Tests:
   `test_endpoint_halverwege_dicht`, `test_pool_404_beeindigt_reeks`,
   `test_pool_404_bovenaan`; `test_funda_sitemap.py::test_detail_dicht` en
   `test_detail_halverwege`.

De pool draait ná de checks 1 en 2: een stukke zoekbron laat de run luid falen,
ook als de pool wel iets oplevert.

**Geen exit 2:** rente, verrijking en geocoding (fail-soft, "onbekend" in het
rapport), een losse 404 (woning weg, endpoint werkt), en een deel van de
zoek-calls dat mislukt (een melding in de log). Los daarvan stopt de workflow
al vóór de run, in de stap "Geheime config klaarzetten", als
`FUNDA_PWA_PASSWORD` of `FUNDA_PERSONAL_JSON` ontbreekt of de JSON ongeldig is;
zie ook "Encryptie verplicht in CI".

## Belangrijke valkuilen (eerder tegengekomen)

- **Zoek-API dicht sinds 18 aug 2026 (`401 no token provided`).**
  `listing-search-wonen.funda.io/_msearch/template` eist een token dat pyfunda
  niet meestuurt. Oorzaak, volgens de maintainer in 0xMH/pyfunda#15: funda zette
  Firebase App Check op de mobiele zoek-API. Een geldig `x-firebase-appcheck`-token
  komt alleen na device attestation (Play Integrity / App Attest), dus vanaf een
  echte telefoon met de app uit de store. Dit komt niet terug via code; reken de
  zoek-API als dicht. Het detail-endpoint heeft (nog) geen App Check. Op Actions
  zoekt het script via funda's sitemaps (zie de sitemaproute).
  Diagnose: workflow "Funda API debug", alleen handmatig. Job **tests** moet
  groen zijn en zegt iets over de code; job **funda-live** staat op
  `continue-on-error` en zegt iets over funda's kant: rood = funda dicht, groen =
  funda laat weer door. Bewust op job-niveau, want `continue-on-error` op een stap
  laat GitHub die stap als "success" rapporteren, ook als het commando faalde.
  Het echte faalsignaal blijft de dagelijkse workflow, die rood wordt en niets
  publiceert.
- **`www.funda.nl` geeft sinds 8 okt 2026 een 403 vanaf GitHub Actions**:
  zoekpagina, Nuxt-payload en detailpagina's als HTML. robots.txt, de homepage
  (uit Akamai's statische cache) en de sitemaps komen wel door, en de aparte
  API-host `listing-detail-page.funda.io` geeft nog 200. De blokkade zit op het
  netwerk of IP van de runner, niet op hoe de client zich voordoet: twintig
  combinaties van TLS-profiel en headers gaven allemaal 403, dus headers of
  TLS-profielen aanpassen helpt niet, en pyfunda v3.1.5 (roteren bij 403) ook
  niet. Zoeken vanaf Actions gaat daarom via de sitemaps; de zoekpagina kan
  alleen nog vanaf een ander uitgaand IP (lokaal, een self-hosted runner op een
  eigen netwerk, waar dit project oorspronkelijk liep). Metingen in
  `notities/geschiedenis.md`.
- **Bewust niet gedaan: funda's botbescherming omzeilen.** In 0xMH/pyfunda#15 en
  #16 noemen mensen een nieuwere TLS-vingerafdruk (`chrome146`) en de host
  `listing-search-wonen.funda.nl` (de zoekbackend van de website, zonder App
  Check) als manier om weer te zoeken. Op 6 nov 2026 bewust niet uitgeprobeerd
  vanaf een server: vingerafdrukken afwisselen of een andere host kiezen om een
  blokkade te passeren is een botcheck omzeilen. Wat wél kan: funda's eigen
  mails, de sitemaps, het detail-endpoint, en het script draaien vanaf een eigen
  (thuis)netwerk zoals het oorspronkelijk draaide.
  - **Eerlijke client voor funda's API-hosts.** pyfunda v2.9.0 doet zich voor
    als funda's Android-app (de JA3 van de echte Dart/Flutter-app,
    `user-agent: Dart/3.9 (dart:io)`, `x-funda-app-platform: android`,
    datadog-traceheaders) en loopt bij een weigering in
    `_find_working_fingerprint()` zijn `FINGERPRINT_POOL` af tot er één doorkomt
    (pyfunda noemt zelf "bot detection" als reden). Daarom gaat elk verzoek van de
    `Funda`-subklasse (detail, zoek-API, prijshistorie, makelaar) via één gewone
    client: curl zonder browser- of app-profiel, `user-agent:
    funda-dagelijkse-check/1.0 (+https://github.com/rpvos-dhg/Funda)`
    (`EERLIJKE_UA`: één constante in `funda_verrijking.py`, door `funda_zoek`
    opnieuw geëxporteerd en ook gebruikt voor de open bronnen, PDOK, OSRM en de
    rente; niet voor `www.funda.nl`, daar het vaste Safari-profiel van de
    sitemap- en HTML-zoeker), geen app- of traceheaders. Er wordt nooit een
    vingerafdruk gezocht. Het detail-endpoint geeft deze client gewoon 200 met
    JSON (gemeten 6 nov 2026, ook vanaf Actions); de zoek-API geeft een
    `HTTP/2 stream reset by server`, en `auto` gaat dan door naar de volgende
    bron. Weigert het endpoint de eerlijke client ooit, dan is dat een 401/403 en
    faalt de run luid; niet terugzetten naar de app-vermomming zonder dat de
    gebruiker daar bewust voor kiest. Vastgepind in `test_eerlijke_client`.
  - **Statuscodes.** pyfunda maakt van élke status behalve 200 een
    `LookupError("Listing ... not found")`, dus een 403 of 429 halverwege de run
    leek op een verkochte woning. De subklasse vertaalt: 401/403/429 =
    `DetailEndpointDicht` (run stopt, exit 2), 404/410 = `WoningNietGevonden`
    (woning weg, endpoint werkt), de rest blijft een gewone `LookupError` (telt
    als storing). Beide klassen staan in `funda_sitemap_zoek.py`.
  - **Eén vast profiel voor `www.funda.nl` en `links.funda.nl`.** De sitemap- en
    HTML-zoeker gebruiken voor `www.funda.nl` hetzelfde curl_cffi-profiel
    (`safari15_5`, Safari-UA), uit één bron: `funda_sitemap_zoek.UA` en
    `IMPERSONATE`; `funda_html_zoek` importeert ze
    (`test_funda_html.py::test_profiel_www`). Een 401, 403 of bot-controle =
    luid falen. Hetzelfde profiel geldt voor `links.funda.nl` (de mailroute,
    alleen lokaal en alleen als je redirects laat volgen:
    `funda_mail_bron.TRACKER_IMPERSONATE`, ook in `funda_mail_imap_check.py`).
  - **Probes.** `funda_api_debug.py` gebruikt per host één vaste client (de
    eerlijke voor de API-hosts, het safari-profiel voor `www.funda.nl`) en
    draait alleen handmatig. De dagelijkse workflow start na een mislukte run
    geen probe meer: die probeerde vroeger profielen af, precies het wisselen
    dat hierboven verboden is. Alle scripts gebruiken `from funda_zoek import
    Funda`, nooit pyfunda's eigen `Funda` (die wisselt nog steeds). Een latere
    meting van een nieuwe pyfunda loopt ook via de eerlijke client.
- **Zoekmethode kiezen.** `FUNDA_ZOEK_METHODE` of `zoek_methode` in de config:
  `auto` (standaard: api -> html -> sitemap, de eerste die werkt), of `api`,
  `html`, `sitemap`, `mail` (die laatste alleen expliciet, niet in `auto`). In
  `auto` doen `HtmlZoeker.bereikbaar()` en `SitemapZoeker.bereikbaar()` de
  tussenstappen: één of twee goedkope calls, zodat niet alle prijsbanden op een
  403 lopen. Zodra funda de API of de zoekpagina weer openzet, schakelt `auto`
  vanzelf terug. Werkt er geen enkele: zie exit 2, geval 3.
- **Sitemaproute: funda's eigen sitemaps als bron** (`funda_sitemap_zoek.py`). In
  `auto` de derde en laatste stap, en sinds 6 nov 2026 dé bron op Actions
  (besluit van de eigenaar; de mailroute is daarmee niet meer nodig).
  - `robots.txt` van `www.funda.nl` staat `/detail/` en `/zoeken/` toe voor `*`
    en noemt `Sitemap: https://www.funda.nl/sitemap_index.xml/`. Let op de slash:
    `/sitemap.xml` is 404, een eerdere meting vond daardoor niets. De zoeker
    leest robots.txt elke run en stopt als `/detail/` wordt uitgesloten.
    **Maar dat is de robots.txt van `www.funda.nl`**, en de zoeker haalt daar
    nooit een `/detail/`-pagina op: de detail-calls gaan naar
    `listing-detail-page.funda.io`, en die heeft `Disallow: /` (zie "robots.txt
    van de API-hosts" hieronder). De check kan die calls dus niet tegenhouden.
  - De index wijst naar `sitemap-detail-koop1..4.xml` (plus huur, nieuwbouw,
    recreatie, europe): ruim 100.000 koop-URL's, ~23 MB XML, **elk met
    `<lastmod>`**. Steden via `sitemap_steden` ("Den Haag" wordt vanzelf
    "den-haag", `stad_slug()`), daarna een slug-afwijslijst (huis, parkeren,
    bouwgrond): ~3.100 kandidaten. De sitemap loopt ongeveer een dag achter; de
    middagrun (16:30 UTC) ziet dezelfde snapshot als de ochtendrun (08:30 UTC).
  - Werking: de sitemap geeft alleen URL + lastmod; prijs, m2, buurt, status en
    coördinaten komen van het detail-endpoint. `funda_sitemap_cache.json` bewaart
    per woning lastmod en die velden, plus het index-kenmerk en de
    kandidatenlijst. Per run gaan robots.txt en de index altijd (2 verzoeken); de
    koop-sitemaps alleen als de lastmod in de index (anders de
    Last-Modified-header) veranderd is, **met 10 minuten speling per
    koop-sitemap**: de index geeft per verzoek soms een seconde verschil, en een
    exacte vergelijking haalde dan elke run alles opnieuw op. Ongewijzigde lastmod
    en buiten de doelmarkt of afgewezen door een nafilter (`_sitemap_overslaan`,
    met `buiten_zoekcriteria`) = geen call. Woningen die door alle filters komen,
    worden elke run vers opgehaald. Onbekend (bijv. geen coördinaten) =
    doorlaten. De kandidatenlijst uit de cache wordt hooguit **36 uur**
    hergebruikt (`MAX_HERGEBRUIK_UUR`), ook als de index "ongewijzigd" blijft
    zeggen: een index-lastmod die blijft hangen terwijl de koop-sitemaps
    veranderen, mag niet stil nieuw aanbod kosten.
  - **Opstart: achterstand.** Een lege cache betekent ~3.100 woningen zonder
    gegevens. Per run `sitemap_max_verkennen` (standaard 200) detail-calls,
    nieuwste lastmod eerst; bij 2 runs per dag is dat na hooguit ~8 dagen weg
    (verre en te dure woningen kosten maar één call). Nieuw aanbod zit vanaf de
    eerste run in de top. **Sneller:** workflow "Funda dagelijks rapport"
    handmatig starten met input `sitemap_max_verkennen` = 600 (wordt
    `FUNDA_SITEMAP_MAX_VERKENNEN`); leeg laten = standaard. Hoger gaat niet:
    `SITEMAP_MAX_VERKENNEN_PLAFOND` (600) begrenst omgeving en config, zie het
    robots-besluit hieronder. Het verkennen heeft ook een **tijdsbudget** van 15
    minuten (`MAX_SECONDEN`; normaal ~0,8 s per call); wat dan openstaat, blijft
    achterstand. De job heeft `timeout-minutes: 45` als vangnet.
  - Luid falen (bron stuk, detail-endpoint dicht): zie "Wanneer stopt een run met
    exit 2", gevallen 1, 3 en 4.
  - **Meting eerste week** (log, alleen getallen; beoordelen rond 13 nov 2026):
    regel "Meting lastmod" telt gecachte woningen met een gewijzigde lastmod en
    hoeveel daarvan een andere prijs of status kregen, én hoeveel vers opgehaalde
    woningen met ongewijzigde lastmod tóch een andere prijs of status hadden. Dat
    tweede getal hoort 0 te zijn; is het dat niet, dan mist het overslaan op de
    cache prijsdalingen van woningen net boven de grens. Regel "Pool en sitemap"
    telt hoeveel getrackte woningen niet meer in de sitemap staan. "Run-kosten"
    aan het eind: methode, duur, detail-calls (en hoeveel dubbel),
    sitemap-verzoeken en of de koop-sitemaps opnieuw zijn opgehaald.
  - Valideren tegen de echte site: `scripts/funda_sitemap_validatie.py`
    (end-to-end door `main()`, zonder rapport of push) en
    `scripts/funda_sitemap_probe.py` (robots en sitemaps meten).
- **robots.txt van de API-hosts. BESLUIT 6 nov 2026: optie (b), doorgaan.**
  `www.funda.nl` staat `/detail/` en de sitemap toe.
  `listing-detail-page.funda.io` (het detail-endpoint), `local-listings` en
  `listing-detail-summary` (beide `.funda.io`) hebben `Disallow: /`. Elke
  funda-route hier (api, html, sitemap, mail en de pool) verrijkt via die
  detail-host. De robots-check van de sitemapzoeker (`detail_verboden()`) leest
  alleen de robots.txt van `www.funda.nl` en kan de detail-calls dus **niet**
  tegenhouden. De sitemaproute schaalt het verkeer naar die host op ten
  opzichte van de HTML-route (die deed alleen detail-calls voor wat funda's
  zoekopdracht al op prijs, m2 en straal had gefilterd): **opstart ~3.100
  calls** (200 per run, ~8 dagen), **daarna tot ~450 per dag** (2 runs x
  hooguit 200 verkennend plus de ververste woningen in de doelmarkt en de
  pool); de e2e mat 200 en 208 per run. De opties waren (a) de robots.txt van
  `listing-detail-page.funda.io` meenemen in de check (dan staat de
  sitemaproute en elke verrijking uit) of (b) bewust doorgaan met dit volume.
  **Gekozen: (b)**, op 6 nov 2026 na het onderzoek gedelegeerd door de eigenaar.
  Waarborgen, en die blijven staan:
  - eerlijke user-agent met repo-link (`EERLIJKE_UA`), zodat funda ons kan
    herkennen en blokkeren;
  - meteen stoppen bij 401/403/429 (`DetailEndpointDicht`, exit 2), nooit
    omzeilen;
  - standaard hooguit 200 verkennende detail-calls per run
    (`sitemap_max_verkennen`), opstart eenmalig 600 en niet hoger
    (`SITEMAP_MAX_VERKENNEN_PLAFOND`);
  - geen wisselende vingerafdrukken.
  De `Disallow: /` op de detail-host was bij dit besluit bekend en is
  geaccepteerd; dat is dus geen reden om te heroverwegen. Sluit de robots.txt
  van `www.funda.nl` ooit `/detail/` uit, dan zet `detail_verboden()` de
  sitemaproute vanzelf uit (exit 2); dat hoeft niemand te bewaken.
  **Heroverwegen** zodra funda de eerlijke client weigert (401/403/429), funda's
  voorwaarden dit uitdrukkelijk verbieden, of funda erom vraagt. Alternatief:
  Huispedia (prototype op branch `claude/probe-andere-woningsites`). Het
  thuisnetwerk lost die gevallen niet op, want ook daar verrijkt elke route via
  de detail-host. Het verlaagt alleen het volume (de HTML-route, als de
  zoekpagina daar werkt, doet minder detail-calls), en helpt alleen als een
  weigering aan het IP van de runner hangt. `local-listings` en
  `listing-detail-summary` worden door dit script niet aangeroepen.
- **Nafilters: elke route filtert na het ophalen.** `PRIJS_MIN`, `PRIJS_MAX`,
  `M2_MIN` en `object_type` zijn bij de zoek-API en de zoekpagina zoekparameters
  voor funda. De sitemapzoeker filtert per prijsband zelf op prijs, m2 en
  beschikbaarheid (`SitemapZoeker.search_listing`, onbekend = doorlaten), op
  type alleen grof (de slug-afwijslijst) en op straal niet; de mailroute negeert
  alle parameters. Daarom filtert `main()` na het ophalen, voor elke route:
  woningtype (`is_geen_appartement()`), stad, buurt en straat-segment, en prijs,
  m2 en straal (`buiten_zoekcriteria`), naast belegging en begane grond in de
  detailcheck. Algemene regel: **onbekend = doorlaten** (geen type, geen
  coördinaten, geen thuispunt), met één uitzondering: geen vraagprijs gaat
  standaard weg (zie "Prijs op aanvraag").
  - Straal: standaard `snap_straal(radius_km)`, dus 5 bij een ingestelde 6,
    dezelfde waarde die funda's zoekopdracht gebruikte; instelbaar met
    `straal_nafilter_km` (0 = uit). Thuispunt uit `thuis_coords` in de config of
    de geocoding (zie "Geocoding en routes"); lukt dat niet, dan slaat het
    afstandsfilter over met een `::warning::`. Waarom: wijken net buiten de
    straal staan niet in `UITSLUIT_BUURTEN`, omdat funda's straal ze vroeger al
    wegfilterde; zonder nafilter leek het alsof uitgesloten wijken terugkwamen.
  - Woningtype: een **afwijslijst, geen toestaanlijst**. Funda kent voor
    appartementen allerlei subtypes (bovenwoning, portiekflat, maisonnette,
    galerijflat, penthouse, studio, benedenwoning); een toestaanlijst zou die
    stuk voor stuk afwijzen zodra er eentje mist. Eerst `house_type` (funda's
    `soortwoning` uit de detail-API), anders het eerste segment van de URL-slug,
    bewust alleen het eerste: een straatnaam als "Huisduinenstraat" mag niet
    meetellen. Zonder deze filter kwam een huis uit een bewaarde zoekopdracht
    met "Woonhuis" ongefilterd in het rapport, want de begane-grond-filter kijkt
    naar omschrijvingen als "appartement op de begane grond". De vocabulaire van
    `soortwoning` is **niet** gemeten; `scripts/funda_mail_imap_check.py` print
    daarom de woningtypes volgens de URL-slug.
  - Buitenruimte: **bewust geen nafilter.** funda's boolean (`has_balcony`) is
    onbetrouwbaar: een woning met balkon stond er als False in. Het model weegt
    buitenruimte mee in de score (`funda_beoordeling.buitenruimte()`, onbekend =
    geen minpunt).
  - Detail-calls zijn het dure deel: woningen die op stad of straat-segment toch
    al afvallen, worden niet opgehaald (in de sitemaproute ook wat op de cache al
    afviel, `_sitemap_overslaan`).
  - Vastgepind in `test_funda_zoek.py::test_zoekcriteria`, `test_woningtypefilter`,
    `test_buurtfilter`, `test_stadfilter` en `test_sitemap_overslaan`.
- **Voorburg versus de gemeente Leidschendam-Voorburg.** `UITSLUIT_STEDEN` doet
  een substring-match, en Voorburg valt onder de gemeente Leidschendam-Voorburg.
  Zonder voorrangsregel matcht "Leidschendam" daarop en valt al het
  Voorburg-aanbod stil weg: geen foutmelding, gewoon niets in het rapport.
  Daarom `WENS_STEDEN = ["Voorburg"]`, dat voorgaat op de uitsluitlijst. Geeft
  funda alleen de gemeentenaam terug, dan is niet te zien welke van de twee het
  is; die woningen worden getoond met de waarschuwing "STAD ONDUIDELIJK"
  (`is_twijfelstad()`) in plaats van weggegooid, en sorteren net als een
  twijfelbuurt naar onderen. Stil verliezen is erger dan een keer te veel laten
  zien. Vastgepind in `test_funda_zoek.py::test_stadfilter`, inclusief dat het
  detail-call-voorfilter zo'n woning niet overslaat.
- **Pool: bekende woningen blijven in beeld.** Een bron toont een woning niet
  elke run (bij de mailroute stond een woning maar een paar dagen in het rapport,
  zie de notities). `controleer_pool()` haalt daarom elke run de woningen uit
  `funda_tracking.json` (laatst gezien binnen `pool_dagen`, standaard 120) die
  niet al binnenkwamen opnieuw op via het detail-endpoint.
  - Verkocht (ook "verkocht onder voorbehoud") of 3x niet op te halen: in de
    tracking gemarkeerd als `weg` en niet meer opgevraagd. Onder bod/optie: deze
    run niet tonen, wel blijven volgen. Duikt een woning weer op, dan valt `weg`.
  - Mislukte calls tellen alleen mee als het endpoint in dezelfde run wél werkte;
    anders zou een storing van drie runs alle bekende woningen wegmarkeren.
    Bewijs: een geslaagde call van de pool óf van de sitemapzoeker, of een nette
    404 (ook dat is een antwoord, en geen storing).
  - Weigert het endpoint, of mislukken calls op rij: exit 2 (geval 4).
  - Beschikbaarheid leunt op pyfunda's `status` (IsSoldOrRented) en het kenmerk
    "Status". Die vocabulaire is **niet gemeten**; de log print daarom per run
    welke statuswaarden voorkwamen (bij pool en mail), zonder adressen.
  - `tracking[...]["url"]` wordt sinds 6 nov bewaard; oudere records worden op
    globalId opgehaald (`get_listing` accepteert dat).
  - `DetailCacheZoeker` voorkomt dat dezelfde woning drie keer per run wordt
    opgehaald (pool, detail-check, rapport). Het rapport valt bij een mislukte
    prijshistorie alleen terug op de URL als er geen listing is; anders haalde
    pyfunda de woning nog eens op.
  - **Met de sitemaproute: de sitemap bepaalt wat de pool níet hoeft op te
    halen, het detail-endpoint bepaalt wat weg is.** Nooit twee detail-calls voor
    dezelfde woning in één run (`SitemapZoeker.pool_oordeel()`): al opgehaald
    door de zoeker = dat antwoord gebruiken; daar mislukt = niet nog eens; op de
    cache overgeslagen (lastmod gelijk, buiten doelmarkt of filter) = overslaan;
    in de achterstand = de pool haalt hem en legt hem vast in de sitemapcache;
    **niet meer in de sitemap = één controle-call**: verkocht/ingetrokken of niet
    op te halen (terwijl het endpoint deze run wél werkte) = meteen `weg`, nog te
    koop = gewoon tonen (de sitemap loopt een dag achter en of "onder bod" erin
    blijft is niet gemeten).
  - Vastgepind in `test_funda_zoek.py::test_pool`, `test_pool_in_run`,
    `test_geen_dubbele_detail_calls` (twee runs door `main()`, met een verkochte
    én een ingetrokken woning buiten de sitemap) en `test_pool_404_bovenaan`.
- **Mailroute (alleen lokaal).** Sinds 6 nov 2026 niet meer in `auto` en op
  Actions niet meer gebruikt (geen workflow geeft de mail-secrets door); de code
  en tests blijven voor lokaal gebruik.
  - Aanzetten met `FUNDA_ZOEK_METHODE=mail` (of `zoek_methode: mail`).
    `funda_mail_ophalen.py` haalt de mails op via IMAP, `funda_mail_bron.py`
    haalt er de woningen uit; bewust gescheiden, zodat het transport te testen
    is zonder mailbox en de parser zonder netwerk. `tekst_uit_mail()` laat de
    stdlib de multipart-mail decoderen (quoted-printable en base64; op de ruwe
    bytes vindt de parser niets) en plakt plat en html achter elkaar.
  - `FUNDA_MAIL_USER` (of `mail_gebruiker` in de config) en
    `FUNDA_MAIL_PASSWORD`. Het wachtwoord komt **alleen** uit de omgeving, nooit
    uit `funda_personal.json` (`mail_config()` negeert het daar expres).
    Optioneel `FUNDA_MAIL_HOST` (standaard imap.gmail.com) en `FUNDA_MAIL_MAP`;
    laat die map leeg: `kies_map()` zoekt zelf de map met de `\All`-vlag, want
    funda-mails worden gearchiveerd en staan dan niet in INBOX, en de mapnaam is
    taalafhankelijk.
  - Het app-wachtwoord van Gmail vervalt (onder meer als het Google-wachtwoord
    wijzigt). Dan weigert Gmail de login (`AUTHENTICATIONFAILED`) en zet de run
    een `::error::` met die uitleg. Gmail wil voor een app-wachtwoord
    tweestapsverificatie. Terugkijkvenster: `mail_dagen_terug` (14 dagen), zodat
    een paar dagen storing geen woningen kost. Een mislukte IMAP-zoekopdracht
    gooit een `RuntimeError` in plaats van stil niets terug te geven.
  - De bewaarde zoekopdracht is het plafond: wat die mist, bestaat voor ons niet,
    en prijsband-splitsing helpt niet. Gebied en grenzen mag je ruim zetten: de
    nafilters strepen weg, en extra kost alleen detail-calls.
  - `los_tracking_link_op()` volgt een tracking-redirect alleen bij nul directe
    woninglinks, want elke call is een echte klik in funda's tracker; de
    mailroute zelf doet dat nooit, alleen
    `scripts/funda_mail_validatie.py --volg-redirects`. `links.funda.nl` geeft
    vanaf Actions een 403.
  - `scripts/funda_mail_imap_check.py` (de hele keten tegen de echte mailbox)
    **print alleen getallen** en publieke tiny_id's: geen onderwerpen,
    afzenders, mailtekst of tracking-links. In een mailbox staan privédingen.
    Houd dat zo.
  - **Niet in de repo**: echte tracking-tokens en mailinhoud. De fixtures in
    `test_funda_mail.py` hebben dummy-tokens in de gemeten vorm.
  - Valideren: `python scripts/funda_mail_validatie.py <mail.eml>
    [--volg-redirects]` en `python scripts/funda_mail_imap_check.py`. Instellen
    op `https://www.funda.nl/account/email-instellingen` (notificaties bij je
    bewaarde zoekopdracht); de zoekopdrachten zelf op
    `https://www.funda.nl/zoeken/zoekopdracht/`. Wat er aan funda's mails
    gemeten is: docstring van `funda_mail_bron.py`.
- **HTML-route (lokaal bruikbaar; op Actions 403 sinds 8 okt).**
  `funda_html_zoek.py` haalt de woning-URL's van `www.funda.nl/zoeken/koop`
  (server-rendered Vue/Nuxt) en laat het detail-endpoint de rest invullen. Dat
  detail-antwoord bevat dezelfde velden als de oude zoek-API, inclusief
  `neighbourhood`, waar de buurtfilters op draaien. `HtmlZoeker` is een drop-in
  voor het `Funda`-object, dus `main()` en het rapport weten hier niets van.
  - De parser leunt op de klasse `@container` per woningkaart en op de tekst in
    die kaart. Verandert funda's markup, dan faalt `test_funda_html.py` niet
    (die draait op een fixture) maar `scripts/funda_html_validatie.py` wél.
    Structuur opnieuw afleiden: `scripts/funda_html_analyse.py`.
  - **De straal moet een waarde zijn die funda kent** (1, 2, 5, 10, 15, 30, 50).
    Een andere waarde, zoals de 6 km uit de config, geeft géén foutmelding maar
    een lege resultatenpagina: status 200, nul kaarten. `snap_straal()` rondt
    daarom af op de dichtstbijzijnde ondersteunde waarde, net als de oude API.
    Zelfde valkuil bij het gebied: een postcode moet lowercase en zonder spatie.
- **pyfunda pin.** Het script gebruikt de v2.x API (`f.search_listing(...)` en
  `r.data` dicts). v3+ is een dataclass-rewrite zonder die methodes. Daarom is
  pyfunda vastgepind op `v2.9.0` in `requirements.txt`; dat is de enige plek
  (de workflows installeren `requirements.txt`). Niet zomaar upgraden zonder de
  code mee te porten.
- **Niet in OneDrive zetten.** De repo stond eerst in een OneDrive-map. Dat gaf
  afgekapte bestanden bij opslaan en kapotte `.git`-locks. Daarom verplaatst naar
  `C:\dev\Funda`. Houd de repo buiten OneDrive.
- **Encryptie verplicht in CI.** `funda_rapport.py` weigert een onversleuteld
  rapport te schrijven als `FUNDA_REQUIRE_ENCRYPTION=1` (gezet in de workflow),
  zodat er nooit per ongeluk leesbare data publiek komt. Die check staat vóór het
  schrijven: dan verandert er ook verder niets in `docs/`. De workflow stopt al
  eerder als het secret `FUNDA_PWA_PASSWORD` ontbreekt. Gzip vóór AES verandert
  hier niets aan (`test_funda_pwa.py`).
- **Verander de padenlijst van de Actions-cache nooit zonder migratie.** De
  versie van een cache hangt af van de exacte lijst `path`-regels in
  `funda-daily.yml` (restore en save). Na een wijziging vindt
  `restore-keys: funda-state-` de oude caches niet meer ("Cache not found"), en
  begint de run met lege state: alles lijkt nieuw, de tracking is weg. Dat
  gebeurde op 6 nov 2026 en is toen hersteld met een tijdelijke migratie
  (`scripts/state_migratie.py`, idempotent, print alleen aantallen; zie de
  notities). Nieuwe state? Liever in een bestaand bestand, of dezelfde migratie
  opnieuw inbouwen (oude padenlijst exact overnemen, in dezelfde volgorde).
  `BESTANDEN` in `state_migratie.py` is de oude lijst van vijf; bij hergebruik
  bijwerken.
- **Publiceren en pushen.** De workflow commit alleen `docs/` naar `main` en
  doet daarna `git pull --rebase origin main` vóór de push: main kan tijdens de
  run veranderd zijn (een gemergde PR), en dan werd de push geweigerd en ging het
  rapport verloren. `docs/` wijzigt alleen de bot, dus dat rebasen is veilig. Een
  lokale run (`auto_push()`, zonder `--no-push`) commit ook alleen `docs/` (de
  check en de commit krijgen allebei het pad mee; andere gestagede wijzigingen
  blijven gestaged), maar rebaset **niet**: doe lokaal altijd zelf
  `git pull --rebase` voor je commit of draait, anders wordt de push afgewezen.
  Zet nooit twee worktrees op dezelfde branch: commit je in de ene, dan heeft de
  andere die commit als gestagede terugdraaiing. Zet een checkout die zo
  verschoven is bewust gelijk (`git reset --hard HEAD`, als er geen eigen werk
  in staat). Vastgepind in `test_funda_zoek.py::test_auto_push_alleen_docs`.

## Lokaal draaien

```
pip install -r requirements.txt
python funda_zoek.py                 # volledige run + rapport, opent HTML, commit en pusht docs/
python funda_zoek.py --no-push       # zonder commit en push van docs/
python funda_zoek.py --no-open       # zonder browser
python funda_zoek.py --debug-wijken  # buurten met aantallen (alleen lokaal)
```

Alleen kijken? Gebruik `--no-push` (zie "Publiceren en pushen"). De browser
opent alleen bij een interactieve run (of met `--open`).

## Tests

Gewone scripts, offline en zonder netwerk: `python test_x.py`. De workflow "Funda
API debug" (job **tests**) draait elk `test_*.py` vanzelf. Per bestand de
hoofdlijnen; de details staan bij de tests zelf.

- `test_funda_zoek.py` - `main()` met stub-zoekers: de exit-2-gevallen, de
  nafilters, de pool, de auto-volgorde (`auto` opent de mailbox nooit), het
  rapport (fixture-render, prijs op aanvraag), de push (volgorde en tekst; met
  node, anders overgeslagen), de publieke log, de geocoding en de eerlijke client
  (in een subproces tegen het echte pyfunda, met een nep-sessie). `auto_push()`
  staat hier uit: een testrun mag nooit committen of pushen. De echte wordt
  apart getest in een tijdelijke repo met een bare repo als remote
  (`test_auto_push_alleen_docs`).
- `test_funda_sitemap.py` - de sitemaproute, met een vaste klok (`NU`), zodat de
  leeftijdscheck niet afhangt van de dag waarop de tests draaien.
- `test_funda_mail.py` en `test_funda_mail_ophalen.py` - de mailbron en het
  IMAP-transport op een stub-mailbox. Een echte alert-mail staat bewust niet in
  de repo.
- `test_funda_html.py` - de HTML-route op een fixture die is nagebouwd op echte
  markup. `python scripts/funda_html_validatie.py` controleert de parser tegen
  de echte funda.nl: dat is de test die afgaat als funda zijn HTML verandert.
- `test_funda_beoordeling.py` - het model, met de golden file
  `testdata/beoordeling_verwacht.json` (bijwerken: `--schrijf-verwacht`) en de
  jaartest (faalt op 1 januari, bewust).
- `test_funda_ui.py` - de UI op `testdata/beoordeling_v3.json`, het contrast van
  de tokenparen, geen verboden merk- of fontnamen en het slotscherm.
- `test_funda_verrijking.py` en `test_funda_rente.py` - de open bronnen, de rente
  en de geocoding met een nep-HTTP-functie en ingekorte echte antwoorden
  (`testdata/verrijking/`, `testdata/rente/`).
- `test_funda_pwa.py` - gzip vóór AES en terug, geen onversleuteld rapport in CI,
  service worker, manifest, slotscherm en iconen.

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
  stuurt daarna met `scripts/send_web_push.cjs` een Web Push bij nieuwe woningen
  (zie "Twijfel en push"). Instellen en testen: `SETUP_GITHUB_ACTIONS.md`.
- **Financiering is een poort, geen punt.** Eerst: kun je het lenen en wil je
  het elke maand betalen (netto woonlasten tegenover je grens)? Dat bepaalt de
  groep; pas daarbinnen telt de score. Onbekend is geen minpunt, twijfel zet een
  woning onderaan maar nooit weg.
