# Meetgeschiedenis

De metingen en run-id's waarop de regels in `CLAUDE.md` rusten. `CLAUDE.md` houdt
de regels en besluiten; hier staat waarom en hoe dat is vastgesteld. Dit bestand
wordt niet automatisch geladen. Het staat bewust niet in `docs/`, want GitHub
Pages publiceert die map.

Geen persoonsgegevens hier: geen postcodes, adressen, bedragen van het profiel of
namen. Run-id's verwijzen naar de Actions-runs van rpvos-dhg/Funda.

## Zoek-API dicht (aug 2026)

- 18 aug 2026: `listing-search-wonen.funda.io/_msearch/template` geeft
  `401 no token provided`. pyfunda stuurt geen token mee, ook v3.1.4 niet.
  Upstream issue 0xMH/pyfunda#15 van dezelfde datum; toen nog open en zonder
  commits sinds 17 juli.
- 19 aug 2026, de maintainer in #15: funda zette Firebase App Check op de mobiele
  zoek-API. Een geldig `x-firebase-appcheck`-token komt alleen na device
  attestation (Play Integrity / App Attest).

## www.funda.nl dicht vanaf Actions (okt 2026)

Sinds 8 okt 2026 geeft de zoekpagina een 403 vanaf GitHub Actions. Gemeten op
9 okt met drie scripts die in de opruimronde van nov 2026 zijn weggehaald
(`scripts/funda_403_probe.py`, `scripts/funda_bronnen_probe.py`,
`scripts/funda_v315_probe.py`; terug te vinden met `git log -- <pad>`, de laatste
versie met `git show 87f9695^:<pad>`):

- Zes TLS-profielen (safari15_5/17_0, chrome120/124/131, firefox133) maal drie
  headersets (minimaal, browser-achtig, met referer), plus twee varianten die
  eerst de homepage bezoeken: alle twintig 403, body ongeveer 536 bytes. De
  blokkade zit dus op het netwerk of IP van de runner, niet op hoe de client zich
  voordoet.
- Per pad: zoekpagina met en zonder slash 403, Nuxt-payload 403, detailpagina als
  HTML ook 403, `/sitemap.xml` 404 (de echte sitemap staat op
  `/sitemap_index.xml/`, met slash; een eerdere meting vond daardoor niets),
  robots.txt 200, homepage 200 (uit Akamai's statische cache). De API-host
  `listing-detail-page.funda.io` gaf wel 200.
- pyfunda v3.1.5 voegde in augustus een webroute toe (chrome124, roteren bij 403,
  backoff). `search()` gaf `curl (92) HTTP/2 stream reset by server`. Upgraden
  helpt dus niet, en kost ook de incompatibele v3-rewrite.
- Mail als bron: op 9 okt stonden er geen alert-mails van een bewaarde
  zoekopdracht in de mailbox. Funda mailt wel transactioneel via
  `notificaties@service.funda.nl`, dus het kanaal werkte.

## Mailroute (okt en nov 2026)

- 9 okt 2026: twee transactionele funda-mails bekeken (één uit 2022, één uit
  2026). In het text/plain-deel stonden inhoudelijke links onverpakt. Eén mail
  volledig uitgelezen (plat en html, 30.206 tekens) had 9 tracking-links: funda
  gebruikt zijn tracker in het html-deel ruim. De "online versie"-link is een
  ondoorzichtige redirect (`links.funda.nl/s/vb/<token>/<token>/23` en
  `links.funda.nl/e/evib?_t=..&_m=..&_e=..`), zonder `?url=` met de echte URL.
- 9 okt 2026: `links.funda.nl` gaf vanaf Actions een 403 (`probeer_trackerhost()`
  in de IMAP-check, op de wortel van de host, zodat er geen eenmalig klik-token
  sneuvelde).
- 9 okt 2026: de check tegen de echte mailbox gaf nul funda-mails over 14 dagen
  in INBOX, terwijl Gmail er die dag één liet zien. Die mail had de labels
  `IMPORTANT` en `CATEGORY_UPDATES`, maar niet `INBOX`: gearchiveerd. Daarom zoekt
  `kies_map()` de map met de `\All`-vlag op.
- 17 okt t/m 4 nov 2026: de mailroute leverde op Actions 35 woningen. Over 38
  runs stonden 27 van die 35 er maar 8 tot 9 runs in (ongeveer 4 dagen), omdat de
  mail daarna buiten het terugkijkvenster viel. Aanleiding voor de pool.
- 4 nov 2026 22:02: Gmail weigerde de login (`AUTHENTICATIONFAILED`); daarna
  faalde elke run op de (al weken bekende) 403 van de zoekpagina. Aanleiding voor
  de `::error::` met uitleg en het terugkijkvenster van 14 dagen.
- 6 nov 2026: de job `mail-live` uit "Funda API debug" en de mailroute uit `auto`
  weggehaald; de sitemaproute is de bron op Actions.

## Straal-nafilter (6 nov 2026)

De 35 woningen uit de mailperiode, gegeocodeerd op postcode: 24 lagen verder dan
5 km van de zoekpostcode, tot 8,1 km, in wijken die niet in `UITSLUIT_BUURTEN`
staan omdat funda's straal ze vroeger al wegfilterde. Alle 59 woningen uit de
API- en HTML-runs lagen binnen 4,8 km. Zonder nafilter leek het daardoor alsof
uitgesloten wijken terugkwamen.

## Sitemaproute (6 nov 2026)

- Runs 42260153909, 42261516145 en 42262032618 (`scripts/funda_sitemap_probe.py`
  en `scripts/funda_sitemap_validatie.py`): robots.txt (200, text/plain) staat
  `/detail/` en `/zoeken/` toe voor `*` en noemt
  `Sitemap: https://www.funda.nl/sitemap_index.xml/`. De index en de vier
  koop-sitemaps geven 200 met XML.
- Omvang: 102.365 koop-URL's, ongeveer 23 MB XML, elk met `<lastmod>`. Den Haag
  3.695, Voorburg 262; na de slug-afwijslijst (huis, parkeren, bouwgrond) 3.103
  kandidaten. Alle 35 woningen uit de mailperiode staan erin.
- Vertraging: index-lastmod 04:59 NL, om 18:29 NL nog dezelfde snapshot.
  Dagelijks verversen is vermoed, niet over meerdere dagen gemeten.
- Speling op de lastmod: de index gaf per verzoek soms een seconde verschil
  (koop3 04:59:26 en 04:59:27, zelfde ETag). Een exacte vergelijking haalde
  daardoor elke run alle koop-sitemaps opnieuw op (e2e-run 42272395594); nu 10
  minuten speling per koop-sitemap.
- Eerste e2e-run 42271742515: crash in `main()` op een woning zonder vraagprijs
  (`price=None` in `sort()`); opgelost, vastgepind in
  `test_funda_zoek.py::test_prijs_onbekend`.
- E2e in `auto`, run 42273695515 (TEST-config met straal 6 -> 5 km, twee runs in
  één job, geen secrets): API 401 en zoekpagina 403, dus `sitemap`.
  - Run 1 (lege cache): 6 sitemap-verzoeken, 200 detail-calls (1x 404), 8 in de
    doelmarkt, 6 na de filters (2 niet beschikbaar), 167 s.
  - Run 2: 2 sitemap-verzoeken (koop-sitemaps uit de cache), 208 detail-calls
    (8 ververst, 200 verkend), 191 op de cache overgeslagen, 16 in de doelmarkt,
    8 na de filters (2 nieuw, 6 eerder gezien), 154 s.
  - Beide runs 0 dubbele detail-calls.
- Prijs op aanvraag: in diezelfde e2e rekende het rapport een woning zonder
  vraagprijs met prijs 0 ("€ 0 | 145 m2"): budget "PAST", minimale maandlast,
  hoogste score, dus bovenaan. Run 42290940091 toonde een appartement van 145 m2
  ver buiten het budget. Sinds 6 nov 2026 gaan woningen zonder vraagprijs
  standaard weg, en heeft het rapport de poort "Prijs onbekend".
- Codex-review PR #13: in de pool telden time-outs met 404's ertussen door tot 5,
  terwijl het endpoint gewoon antwoordde. Nu zet een nette 404 de reeks terug op 0
  (`test_pool_404_beeindigt_reeks`).

## Eerlijke client (6 nov 2026)

- Tot nov 2026 zette de `Funda`-subklasse pyfunda vast op
  `FINGERPRINT_POOL[0]`: niet meer wisselen, maar wel de sterkste vermomming, de
  app zelf.
- Gemeten: een client met Python-TLS, eigen user-agent en geen app-headers krijgt
  van het detail-endpoint 200 met JSON, eerst vanaf een sandbox en daarna vanaf
  Actions in e2e-run 42281508702: twee runs in `auto`, 200 en 208 detail-calls,
  alleen nette 404's als fout (1 en 2, `[404, 404]`: pyfunda probeert tinyId en
  daarna globalId), 0 dubbele calls, 153 s en 146 s (was 167 s en 154 s met de
  app-vermomming), zelfde aantallen als de e2e daarvoor. De zoek-API gaf met deze
  client geen 401 maar een `HTTP/2 stream reset by server`.
- Probes: tot nov 2026 draaide de dagelijkse workflow na een mislukte run
  automatisch `funda_api_debug.py`, en die probeerde de zoek-API met safari15_5,
  chrome124, zonder impersonate en met een nep-`x-funda-app-version`. Dat is het
  wisselen dat `CLAUDE.md` verbiedt, twee keer per dag zolang het stuk was. Die
  stap is weg.
- `links.funda.nl` gebruikte tot nov 2026 het profiel `chrome124`; nu hetzelfde
  vaste `safari15_5` als `www.funda.nl`.

## Geocoding via PDOK (7 nov 2026)

Gemeten op de postcode van het stadhuis (4 adressen): `limit=1` in 7,7 en 11,3 s,
`limit=10` in 36,6 s, `limit=50` in 24 s. Met minder adressen dan de limit zoekt
de server de hele postcode af. Daarom `limit=1`, time-out 60 s en één poging per
postcode per run. OSRM (`router.project-osrm.org`) heeft geen robots.txt: op
`/robots.txt` komt een JSON-fout terug.

## Actions-cache en publiceren (6 nov 2026)

- PR #13 voegde `funda_thuis_coords.json` en `funda_sitemap_cache.json` toe aan de
  padenlijst van de cache. Daarna vond `restore-keys: funda-state-` de oude caches
  niet meer ("Cache not found"). De opstartrun 42287980238 begon met 0 gezien,
  lege tracking en geen blacklist, en meldde 9 "nieuwe" woningen. Hersteld met een
  tijdelijke migratie in `funda-daily.yml` (de oude cache apart ophalen met de
  oude padenlijst, samenvoegen met `scripts/state_migratie.py`). Gemeten in run
  42290940091: seen 137+9 -> 142, tracking 137+9 -> 142. Daarna zijn de
  migratiestappen weer uit de workflow gehaald.
- Run 42290940091 schreef het rapport, maar de push werd geweigerd
  (`rejected ... fetch first`): tijdens de run was een PR in main gemerged. Sindsdien
  doet de publiceerstap `git pull --rebase origin main` vóór de push.
- Twee worktrees op dezelfde branch: in de ene werd gecommit, en de andere
  checkout had daarna die commit als gestagede terugdraaiing. Een lokale run zou
  die als "auto: rapport" hebben gepusht. Sindsdien commit `auto_push()` alleen
  `docs/`.

## Log van 19 nov 2026: kenmerken en prijshistorie

Uit de log van de dagelijkse run (alleen aantallen, 42 woningen):

- Labeltelling van funda's kenmerken: Aantal woonlagen 41, Verwarming 41,
  Ligging 38, Isolatie 32, Soort dak 29. Die kenmerken komen dus vaak voor; de
  waarden zelf zijn nog niet bekeken (zie "Open punten en ideeën" in
  `CLAUDE.md`).
- Regel "[rapport] Prijshistorie": 0 van de 553 regels in funda's prijshistorie
  had geen bedrag. Het item "Eerder zonder prijs" leunt in de praktijk dus op de
  eigen waarneming in de sitemapcache.

## Refactor zonder gedragsverandering (19 nov 2026)

Na PR #28 is de code opgedeeld, zonder ander gedrag:

- De vier zoekers delen `DropIn` en `Resultaat` in `funda_sitemap_zoek.py`. De
  eigen `Resultaat`-klassen per zoeker zijn weg; `funda_html_zoek` en
  `funda_mail_bron` importeren `funda_sitemap_zoek`.
- `main()` in `funda_zoek.py` roept benoemde stappen aan: `zoek_alle_banden`,
  `controleer_pool`, `nafilter` (tabel `NAFILTERS`), `detailcheck`,
  `werk_tracking_bij` en `maak_rapport`. De exit-2-checks 1 en 2 staan in
  `zoek_alle_banden`, en elke stop loopt via `_stop()`. `sort_key` heet nu
  `_console_volgorde`.
- `beoordeel()` in `funda_beoordeling.py` bouwt de items per onderdeel met
  `_items_...`-functies en vat samen in `_samenvatten()`.
- `funda_verrijking.py` heeft één tabel `SECTIES` (cachesectie, bewaartermijn en
  toegestane velden).

## Uitgebreide tekst uit CLAUDE.md (stand 19 nov 2026)

Op 19 nov 2026 is `CLAUDE.md` ingekort tot de regels en besluiten. Hieronder
staat de volledige tekst van voor de inkorting, ongewijzigd op drie bijgewerkte
functienamen na: het waarom, de metingen en de details per onderwerp. Het is
de stand van die dag. Wijkt dit af van `CLAUDE.md` of van de code, dan gelden
`CLAUDE.md` en de code.

### Rapport, beoordeling en PWA (bouwronde nov 2026)

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
  "<adres>, <stad> · Past · 8,3", zonder beoordeling "<adres>, <stad> · 68 m²".
  De push toont de eerste drie, en `vul_summary_aan()` zet de nieuwe woningen
  daarvoor in de volgorde van "Aanbevolen" (`funda_beoordeling.sorteer`; zonder
  beoordeling achteraan), niet die van `_console_volgorde` in `funda_zoek.py` (console en
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
  of 5xx, nooit bij een weigering. `EERLIJKE_UA`, sequentieel met pauze, time-out 10 s, budget 90
  verzoeken per run (zie "Budget" hieronder; daarna bijna alles uit de cache).
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
  **Bronnen van 18 nov 2026** (gemeten die dag, robots.txt per host opnieuw
  gelezen en ongewijzigd; `testdata/verrijking/meting.json`). Elk apart aan of
  uit in `beoordeling.verrijking.bronnen`, met een eigen status per woning, en in
  het model **allemaal 0 punten** (informatief of "let op" zonder gewicht): de
  spreiding tussen buurten is nog niet bekend, gewichten volgen later. Geen
  nieuwe host: alles op hosts die al gebruikt werden.
  - `kerncijfers`: CBS Wijken en buurten 2024 uit dezelfde PDOK-call als de
    buurtcode (geen extra verzoek): gemiddelde WOZ, koop, huur en corporatie,
    meergezins, stadsverwarming en aardgasvrij, afstand tot supermarkt, station
    en huisarts. Alleen `KERN_PDOK` wordt gelezen (het antwoord heeft 244
    velden, ook bevolkingsvelden). Missend = -99997. De uitgave 2025 mist WOZ en
    afstanden, daarom 2024. Het aantal woningen (`woningvoorraad`) staat alleen
    in de cache, als noemer; nooit in de uitvoer, het rapport of de log.
  - `veiligheid`: politiecijfers via `dataderden.cbs.nl`, tabel 47018NED
    (misdrijven: totaal, woninginbraak 1.1.1, vernieling 2.2.1) en 47024NED
    (overlast, totaal), jaar 2025 (`POLITIE_JAAR`; bijwerken als 2026 volledig
    is). Per 1.000 woningen, met het gemeentecijfer uit hetzelfde antwoord (de
    noemer van de gemeente: één PDOK-verzoek per gemeente). Onder 100 woningen
    geen cijfer. Altijd informatief en feitelijk; geen oordeel over een buurt.
  - `lucht` (met `groen` als schakelaar voor het percentage): RIVM-WMS,
    jaargemiddelde NO2 en PM2,5 van 2024 en het percentage groen binnen 500 m
    (2022), één verzoek. Duiding tegen het WHO-advies (10 en 5) en de
    EU-grenswaarden (40 en 25, vanaf 2030 20 en 10; `drempels`). Laagnamen met
    datum in `RIVM_LUCHT_LAGEN`: verdwijnt een jaargang, dan "onbekend".
  - `klimaat`: Klimaateffectatlas, één verzoek: wateroverlast rond het pand bij
    een extreme bui (klasse per pand), overstromingskans (klasse 1 tot 5) en
    grondwateroverlast 2050. Klassen uit de legenda. **Niet opgenomen:**
    hitte-eiland en gevoelstemperatuur (eenheid niet te onderbouwen).
  - `erfgoed`: RCE via `api.pdok.nl` (`/rce/beschermde-gebieden-cultuurhistorie`):
    beschermd stads- of dorpsgezicht op het punt en het aantal rijksmonumenten
    binnen 25 m (punten; kan het pand zelf zijn of een buurpand). Twee verzoeken.
    De eigen WFS van de RCE (`data.geo.cultureelerfgoed.nl`, geen robots.txt)
    gaf bij de meting geen treffers en wordt niet gebruikt.
  - **Budget.** Een nieuwe woning kost ongeveer 9 verzoeken (was 5), een nieuwe
    buurt 3 erbij en een nieuwe gemeente 2; daarom 90 per run in plaats van 60
    (`funda_verrijking.STANDAARD`; een `max_calls_per_run` in de secret gaat
    voor). Buurtgegevens staan per buurtcode in de cache (kerncijfers 365 dagen,
    politiecijfers 180), puntgegevens per gehasht punt (365, erfgoed 180). Wat
    niet past, krijgt "budget" en gaat de volgende run verder; Past en Krap eerst.
  - **In het rapport.** `funda_beoordeling.omgeving_items()` maakt de items
    (onderdeel `omgeving`); een bron die uit staat of niets gaf, levert geen item
    en geen "onbekend". `funda_ui` toont ze per kaart in het uitklapblok "Buurt
    en omgeving" (`INFO_TONEN`), de markdown in een eigen regel. Informatieve
    items over de woning zelf ("Schuin dak: mogelijk", "Eerder zonder prijs";
    `INFO_WONING`) staan in het blok Woning, in de markdown in de regel "Over
    de woning".
- **Geocoding en routes.** Postcodes worden punten via de BAG-collectie `adres`
  op `api.pdok.nl` (`funda_verrijking.Geocoder`, filter op postcode, het punt
  van het eerste adres): de werkpostcodes (`funda_rapport.get_werk_coords`) en
  de zoekpostcode (`funda_zoek.thuis_coords`, alleen met het afstandsfilter
  aan). Per postcode gaat de config voor (`werk_coords` als
  `{postcode: [lat, lon]}`, `thuis_coords` als `[lat, lon]`), dan de caches
  `funda_werk_coords.json` en `funda_thuis_coords.json`, dan één poging via
  PDOK; een gevonden punt blijft voorgoed in die cache. De sleutel in die
  bestanden is sinds 18 nov 2026 een hash van de postcode
  (`funda_verrijking.postcode_sleutel`, dezelfde hashfunctie als de andere
  cachesleutels): een oude leesbare sleutel wordt bij het laden omgezet en niet
  meer teruggeschreven (`coords_cache_lees`), ook als het punt zelf uit de
  config komt. Zelfde bestandsnamen, geen nieuw
  pad; de config-sleutels blijven leesbaar. Een
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
  `verrijking_weigering` en `rente`, en sinds 18 nov 2026 `kerncijfers`,
  `misdrijven`, `overlast` (per buurtcode), `gemeente` (per gemeentecode),
  `lucht`, `klimaat` en `erfgoed` (per punt). Adres- en puntsleutels zijn gehasht. Geen
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
- **Eerder zonder prijs.** Heeft een woning nu een vraagprijs maar stond hij
  eerder zonder, dan toont het rapport het informatieve item "Eerder zonder
  prijs" met de datum (0 punten). Twee bronnen: de eigen waarneming (het
  cache-element in `funda_sitemap_cache.json` onthoudt `zonder_prijs`, ook van
  woningen die de nafilter afwees; `SitemapZoeker._element`, doorgegeven als
  `d["_zonder_prijs_gezien"]`) en een vraagprijsregel zonder bedrag na de
  laatste verkoop in funda's prijshistorie (`prijshistorie()["zonder_prijs"]`).
  Een cache-element van voor 19 nov 2026 hield geen datum bij: stond de woning
  daarin zonder prijs te koop, dan komt het item zonder datum ("gezien, datum
  onbekend", `ZONDER_PRIJS_ONBEKEND`); er wordt geen datum verzonnen.
  Hoe funda zo'n aanbieding in de prijshistorie zet, is **niet gemeten**: de
  logregel "[rapport] Prijshistorie" telt per run de statuswaarden en de regels
  zonder bedrag (alleen aantallen). Verder verandert er niets aan "Prijs op
  aanvraag": nooit rekenen met prijs 0.
- **PWA (aangescherpt 18 nov 2026, `funda_rapport.beveilig_html`).**
  - **Sleutelopbouw.** Hoofdsleutel = PBKDF2-SHA256(wachtwoord, vast app-zout
    `APP_ZOUT`, 600.000 iteraties). Runsleutel = HKDF-SHA256(hoofdsleutel, salt =
    run-zout van 16 bytes, info = `KDF_INFO`) voor AES-256-GCM met een IV van 12
    bytes; zout en IV elke run nieuw. Waarom: "Onthoud op dit apparaat" bewaart
    de hoofdsleutel, en wie de opslag leest mag daarmee niet sneller naar het
    wachtwoord raden dan met de publieke ciphertext. De oude opbouw bewaarde de
    PBKDF2-basissleutel; daaruit was een afleiding met 1 iteratie te halen.
    `APP_ZOUT` wijzigen = iedereen vult één keer het wachtwoord in.
  - **Klare tekst.** gzip (niveau 9, mtime 0), dan opvulling (`vul_op`: lengte
    van 4 bytes, data, nullen), dan AES. De ciphertext is zo altijd een veelvoud
    van 8 kB (`BLOK`): de bestandsgrootte volgt het aanbod niet meer per woning.
    Ciphertext comprimeert niet, dus gzip moet vooraf.
  - **Wrapper zonder code.** `ui/slot.html` (`funda_ui.vul_slot`) bevat alleen
    markup, de CSP en het pakket als JSON in `#slot-data`. CSS en JavaScript
    staan als bestanden in `docs/` (`schrijf_statisch`, lijst `STATISCH`):
    `app.css`, `slot.css`, `app.js`, `push.js`, `slot.js` en Leaflet 1.9.4 zelf
    gehost in `leaflet/` (bron `ui/leaflet/`, ongewijzigd uit het npm-pakket,
    sha256 vastgepind in `test_funda_pwa.py`; geen unpkg meer). De publieke
    Web Push-sleutel staat in `<meta name="funda-push-key">`. Het lokale
    `funda_rapport.html` houdt CSS en JS inline en laadt Leaflet uit
    `docs/leaflet/`.
  - **CSP** (meta-tag, `funda_rapport.CSP`): `default-src 'none'`, `script-src
    'self'`, `style-src 'self'` (geen `unsafe-inline`: geen `style=` in de
    markup), `img-src 'self' https://cloud.funda.nl
    https://tile.openstreetmap.org data:`, `connect-src`, `manifest-src` en
    `worker-src 'self'`, `base-uri` en `form-action 'none'`. `data:` is nodig:
    Leaflet zet een afgebroken tegel op een lege GIF. De fotohost is niet
    gemeten (dat kan alleen met een funda-verzoek); wijkt hij af, dan staat er
    een `::warning::` met een aantal in de log. `<meta name="referrer"
    content="no-referrer">` en `rel="noopener noreferrer"` op externe links;
    alleen de kaarttegels sturen de kale herkomst mee (`referrerPolicy:
    'origin'`), omdat OpenStreetMap tegels zonder referrer weigert.
  - **Slotscherm (`ui/slot.js`).** Zonder `DecompressionStream` (iOS ouder dan
    16.4) zegt het dat, in plaats van "fout wachtwoord". "Onthoud op dit
    apparaat" bewaart de hoofdsleutel als niet-exporteerbare HKDF-sleutel
    (alleen `deriveKey`) in IndexedDB (30 dagen), nooit het wachtwoord. Een
    bewaarde sleutel van het oude soort en een oud bewaard wachtwoord worden
    gewist, niet omgezet: één keer het wachtwoord invullen. In een frame
    ontgrendelt het niet (`frame-ancestors` werkt niet in een meta-tag).
    "Vergrendel" (blok "Dit apparaat" in de voet) wist de sleutel en herlaadt.
    Na vier foute wachtwoorden volgt een pauze: 30 seconden, daarna telkens
    het dubbele, hooguit een kwartier; de teller staat in `localStorage`
    (`funda_slot_pogingen`, het enige wat het slotscherm daar bewaart) en
    overleeft herladen. Dat remt raden op het apparaat zelf, niet een aanval
    op het publieke versleutelde bestand: daar beschermt alleen het wachtwoord.
  - **Service worker** cache `funda-shortlist-v7` (ophogen bij elke nieuwe
    wrapper en bij elk gewijzigd bestand in `ASSETS`, anders blijft een
    geïnstalleerde PWA de oude tonen), met de
    statische bestanden in `ASSETS`; alleen same-origin GET's komen in de cache.
  - **Verder.** `#woning-data` escapet `<`, `>` en `&` als `\u003c` enzovoort;
    `funda_ui.funda_url` laat alleen `https://www.funda.nl/...` door. Manifest
    "Woningrapport" / "Woningen" (geen voornaam: het staat publiek), kleuren
    `funda_ui.THEME_COLOR` en `funda_ui.ACHTERGROND`, iconen in hetzelfde palet.
    "Nieuw" geldt per apparaat en telt pas als gezien als de kaart minstens half
    een seconde in beeld was, tussen de vaste top- en onderbalk.
  - **Schrijfregels van de zichtbare tekst** (audit schrijfstijl en componenten,
    nov 2026; ook `.interface-design/system.md`). De poort heet overal "Status",
    het scenario "Financiering" (kaart, filter, vergelijken, popup, markdown).
    Geen "run", hostnaam of bestandsnaam in de tekst van het rapport (wel in de
    log); één uitzondering: de naam van de instelling `WEB_PUSH_SUBSCRIPTION` in
    het meldingenblok, omdat je die nodig hebt. Knoppen in de gebiedende wijs
    ("Ontgrendel", "Verberg"), "meldingen" en niet "notificaties", een
    foutmelding noemt de vervolgstap. De bron onder een punt gaat door
    `funda_ui.bron_tekst()` (gewone taal; het model houdt zijn eigen `bron`).
    Vijf lettermaten (13, 14, 16, 18, 20 px), vet is 600.
  - **Bewust niet gebouwd (open):** localStorage versleutelen (bewaard,
    verborgen en gezien staan leesbaar op het apparaat), de kaart pas na een tik
    laden, en `docs/` publiceren zonder git-geschiedenis.
- **Huisstijl: eigen palet "Inkt en blauw", bewust geen huisstijl van een merk.**
  Kleuren, stylesheet, iconen en fonts van het designsysteem van een bestaand
  merk zijn eigendom van dat merk (merkrecht), en de CSS van het slotscherm
  staat buiten de versleuteling publiek op GitHub Pages. Daarom een eigen palet
  (tokens licht en donker, feedbackkleuren alleen voor feedback, WCAG AA
  gemeten). Tokens en regels: `.interface-design/system.md`. `test_funda_ui.py`
  weigert het merkblauw `#003d86`, geel `#ffcd00` en de merk- en fontnamen. **Geen
  merknaam van derden in de repo of in commitberichten** (besluit eigenaar, 18
  nov 2026): de test bouwt de verboden namen daarom uit losse delen op
  (`VERBODEN_WOORDEN`) en `test_geen_merknaam` weigert ze in elk bijgehouden
  bestand. Het eerdere
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

### Wanneer stopt een run met exit 2

Exit 2 betekent: de run stopt vóór het rapport. Rapport, `docs/`, seen-ids en
tracking blijven onaangeroerd (niets wordt nieuw, gezien of `weg`), er wordt
niets gepubliceerd en de dagelijkse workflow wordt rood. Wat de run al ophaalde,
mag wel in de caches blijven (`funda_sitemap_cache.json`, ook de verkenning uit
geval 4, en `funda_thuis_coords.json`): de stap "State bewaren (cache)" draait
met `if: always()`, dus de volgende run hoeft dat werk niet opnieuw te doen.
"0 woningen" is niet hetzelfde als "zoeken stuk": zonder deze checks schrijft een
kapotte zoekmethode een leeg of half rapport over het gevulde heen, terwijl de
Action groen blijft. De checks staan in `zoek_alle_banden()`, `kies_zoeker()` en `main()` (`funda_zoek.py`; ze stoppen via `_stop()`); de tests in
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

### Belangrijke valkuilen (eerder tegengekomen)

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
  alle parameters. Daarom filtert `nafilter()` (tabel `NAFILTERS`, aangeroepen uit `main()`) na het ophalen, voor elke route:
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
  pyfunda vastgepind op `2.9.0`, sinds 18 nov 2026 van PyPI met hash en niet
  meer van de git-tag (een tag kan verzet worden; de wheel is vergeleken met
  commit `1bbe5d3` van tag v2.9.0: identiek). Niet zomaar upgraden zonder de
  code mee te porten.
- **Afhankelijkheden staan vast (beveiligingsronde 18 nov 2026).**
  `requirements.in` heeft de losse eisen, `requirements.txt` is daaruit
  gegenereerd met exacte versies en hashes (het commando staat bovenin
  `requirements.in`; `uv`, met `--universal` zodat het ook op Windows klopt).
  Werk nooit met de hand in `requirements.txt`. De workflows doen
  `pip install --require-hashes -r requirements.txt` en geen `pip install
  --upgrade pip` meer. Voor de push staan `web-push` en wat eronder hangt in
  `package.json` en `package-lock.json` (in de root, zodat
  `scripts/send_web_push.cjs` het pakket vindt); de workflow doet
  `npm ci --ignore-scripts`. De acties in de workflows staan op een commit-SHA
  met de tag als commentaar. Bijwerken is steeds een bewuste stap: opnieuw
  genereren of de SHA opzoeken, en de diff lezen.
- **Niet in OneDrive zetten.** De repo stond eerst in een OneDrive-map. Dat gaf
  afgekapte bestanden bij opslaan en kapotte `.git`-locks. Daarom verplaatst naar
  `C:\dev\Funda`. Houd de repo buiten OneDrive.
- **Encryptie verplicht in CI.** `funda_rapport.py` weigert een onversleuteld
  rapport te schrijven als `FUNDA_REQUIRE_ENCRYPTION=1` (gezet in de workflow),
  zodat er nooit per ongeluk leesbare data publiek komt. Die check staat vóór het
  schrijven: dan verandert er ook verder niets in `docs/`. De workflow stopt al
  eerder als het secret `FUNDA_PWA_PASSWORD` ontbreekt (`test_funda_pwa.py`).
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
  rapport verloren. `docs/` wijzigt alleen de bot, dus dat rebasen is veilig. Het
  schrijf-token zit alleen in die stap: checkout draait met
  `persist-credentials: false`, en de pull en de push krijgen het token als
  header mee (`met_token`), zodat pip, de run zelf en npm er niet bij kunnen.
  `permissions` staat op niets voor de workflow en `contents: write` voor de
  job; "Funda API debug" heeft alleen `contents: read`. Een
  lokale run (`auto_push()`, zonder `--no-push`) commit ook alleen `docs/` (de
  check en de commit krijgen allebei het pad mee; andere gestagede wijzigingen
  blijven gestaged), maar rebaset **niet**: doe lokaal altijd zelf
  `git pull --rebase` voor je commit of draait, anders wordt de push afgewezen.
  Zet nooit twee worktrees op dezelfde branch: commit je in de ene, dan heeft de
  andere die commit als gestagede terugdraaiing. Zet een checkout die zo
  verschoven is bewust gelijk (`git reset --hard HEAD`, als er geen eigen werk
  in staat). Vastgepind in `test_funda_zoek.py::test_auto_push_alleen_docs`.

### Kernfeatures (waarom de code is zoals hij is)

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
- **Geen energielabel = rekenen met het slechtste** (besluit eigenaar, 18 nov
  2026). Zonder label rekent het model de energiekosten met label G, tenzij het
  bouwjaar (BAG, anders funda) een ondergrens geeft: vanaf 1975 E, 1992 C, 2000
  B, 2006 A (`funda_beoordeling.label_aanname`, een eigen voorzichtige indeling).
  Alleen voor de energiekosten in de woonlasten: de leentoets krijgt geen label
  en de score geen minpunt op het onderdeel energielabel. Hogere woonlasten
  kunnen de poort en de score wel verschuiven. Het item blijft "onbekend,
  gerekend als G" met de vraag om het label op te vragen. Vastgepind in
  `test_funda_beoordeling.py::test_label_aanname`.
- **Binnenklimaat = indicatie, geen meting** (verzoek eigenaar, 19 nov 2026).
  `funda_beoordeling.binnenklimaat()` geeft hooguit twee informatieve items,
  "Zomer" en "Winter" (0 punten, onderdeel `binnenklimaat`), uit aanwijzingen
  die er al zijn: ligging onder het dak of op een tussenverdieping, schuin dak,
  bouwjaar voor 1975 zonder isolatie in het kenmerk Isolatie, glas, zonligging
  van de buitenruimte, doorzon of hoek, zonwering of airco, groen binnen 500 m,
  verwarming en energielabel. Geen nieuw verzoek. Onbekend is geen aanwijzing;
  zonder aanwijzing geen item. Een onbekend label telt niet mee: naast een
  andere aanwijzing staat het rekenlabel met het woord "aanname" in de uitleg
  onder "Niet meegeteld", net als stads- of blokverwarming (dat gaat over
  kosten). Een ontkenning telt niet, ook achter het woord ("zonwering is niet
  toegestaan"), en een zin over de buren ook niet. `funda_ui` toont ze in
  het blok Woning ("Warmte en kou in huis"), de markdown in eigen regels; de
  vraag staat bij het item en niet in "Zelf nagaan". Niet gemeten op echte
  advertenties: 'Soort dak', 'Aantal bouwlagen', zonwering of airco in
  'Voorzieningen', en of "1e woonlaag" de begane grond is (telt daarom niet).
  Vastgepind in `test_funda_beoordeling.py::test_binnenklimaat`.
- **Schuin dak = klein minpunt** (besluit eigenaar, 18 nov 2026). Ligt de
  woonruimte onder een schuin dak, dan geeft het model "let op" met -0,5 en de
  vraag naar de bruikbare oppervlakte boven 1,50 m (`funda_beoordeling.schuin_dak`,
  onderdeel `schuin_dak`; instelbaar met `drempels.schuin_dak_punten` en
  `gewichten.schuin_dak`). Zeker: de advertentie zegt het, of het kenmerk "Soort
  dak" noemt een schuin dak en de woning ligt aantoonbaar bovenin. In de tekst
  twee soorten: sterk (schuine wanden, kapverdieping, knieschot, dakkapel) en
  zwak (schuin dak, onder de kap, zolderverdieping, vide tot in de nok). Een
  zwakke aanwijzing telt alleen met een woonruimtewoord in dezelfde zin
  (slaapkamer, woning, werkplek), niet in een zin over het complex, de VvE, de
  stalling of de bovenburen, en niet als de woonlaag aantoonbaar onder het
  aantal bouwlagen ligt. Mogelijk (schuin daktype, ligging niet aan te tonen):
  informatief, 0 punten. Plat dak of geen aanwijzing: geen item. Een ontkenning
  (ervoor, of erachter: "is niet bij de woning inbegrepen") en een zin over de
  berging, een gemeenschappelijke zolder of de buren tellen niet. De
  waarden van "Soort dak" en een kenmerk voor het aantal bouwlagen zijn **niet
  gemeten** op echte advertenties (de labeltelling in de log laat ze zien).
  Vastgepind in `test_funda_beoordeling.py::test_schuin_dak`.
