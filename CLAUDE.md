# CLAUDE.md

Projectcontext voor Claude Code. Lees dit eerst. Hier staan alleen de regels en
besluiten. Het waarom in volle lengte, de metingen, de run-id's en de volledige
tekst van voor de inkorting (19 nov 2026) staan in `notities/geschiedenis.md`;
dat bestand wordt niet automatisch geladen. Lees het erbij als je aan een
onderwerp werkt waar hier "(notities)" bij staat.

Inhoud: 1 Project en bestanden · 2 Privé en secrets · 3 Wat nooit mag ·
4 Exit 2 · 5 Funda als bron · 6 Zoeken, filters en pool · 7 Rapport en model ·
8 Config · 9 Open bronnen, rente, geocoding · 10 PWA en huisstijl ·
11 Publieke log · 12 CI, cache en publiceren · 13 Draaien en testen ·
14 Open punten en ideeën.

## 1. Project en bestanden

Dagelijkse Funda-checker voor een koopappartement (regio Den Haag). Zoekt nieuw
aanbod, toetst betaalbaarheid en bouwt een rapport (markdown, HTML en een
versleutelde PWA). Draait op GitHub Actions, publiceert op GitHub Pages.

- Live: https://rpvos-dhg.github.io/Funda/ (met wachtwoord). Repo:
  https://github.com/rpvos-dhg/Funda (publiek).
- Rooster: 08:30 en 16:30 UTC (GitHub-cron is UTC).
- Instellen op GitHub (secrets, Pages, push): `SETUP_GITHUB_ACTIONS.md`.

Bestanden:

- `funda_zoek.py`: hoofdscript. `main()` roept de stappen aan: `kies_zoeker`,
  `zoek_alle_banden`, `controleer_pool`, `nafilter` (tabel `NAFILTERS`),
  `detailcheck`, `werk_tracking_bij`, `maak_rapport`, `auto_push`. Bevat ook de
  `Funda`-subklasse (eerlijke client, zie 5).
- `funda_sitemap_zoek.py`: de sitemapzoeker, en wat alle zoekers delen: `DropIn`
  en `Resultaat` (drop-in voor pyfunda's `Funda`-object), `DetailEndpointDicht`,
  `WoningNietGevonden`, `publieke_log()`, `log_tekst()`, `UA` en `IMPERSONATE`.
- `funda_html_zoek.py` (zoekpagina) en `funda_mail_bron.py` +
  `funda_mail_ophalen.py` (notificatiemails): alleen lokaal bruikbaar. Beide
  importeren `funda_sitemap_zoek`.
- `funda_rapport.py`: bouwt het rapport per woning en schrijft markdown, HTML en
  de versleutelde PWA in `docs/`.
- `funda_beoordeling.py`: het model. Poort (Past, Krap, Past niet, Prijs
  onbekend), leentoets 2026, scenario's, score 0 tot 10, parsers. Pure functies,
  geen netwerk, geen import van een projectmodule. `beoordeel()` bouwt de items
  met `_items_...`-functies; het contract staat in de docstring.
- `funda_verrijking.py` (open bronnen, geocoding, `EERLIJKE_UA`, tabel `SECTIES`
  van de cache) en `funda_rente.py` (hypotheekrente).
- `funda_ui.py` met `ui/` (`app.css`, `app.js`, `push.js`, `slot.html`,
  `slot.css`, `slot.js`, `leaflet/`): de UI. Importeert `funda_rapport` niet.
  Palet en schrijfregels: `.interface-design/system.md`.
- `.github/workflows/funda-daily.yml` (de run) en `funda-debug.yml` ("Funda API
  debug", alleen handmatig: job **tests** en job **funda-live**).
- `scripts/`: gereedschap buiten de run. `funda_api_debug.py`,
  `funda_html_validatie.py`, `funda_html_analyse.py`,
  `funda_sitemap_validatie.py`, `funda_sitemap_probe.py`,
  `funda_mail_validatie.py`, `funda_mail_imap_check.py`, `state_migratie.py` en
  `send_web_push.cjs` (de push, ook in de workflow).
- `requirements.in` en `requirements.txt`, `package.json` en
  `package-lock.json`: zie 12.
- `data/trhk_2026_tabel1.json`: tabel 1 van de leentoets en de labelbedragen.
- `testdata/`: fictieve fixtures en ingekorte echte antwoorden van open bronnen.
- `funda_personal.example.json`: voorbeeld van de privé-config, fictieve waarden.

## 2. Privébestanden en secrets

Nooit committen; `.gitignore` is de volledige lijst.

- Config en geheimen: `funda_personal.json`, `funda_pwa_password.txt`,
  `subscription.json`.
- State (zeven bestanden, op Actions in de cache): `funda_seen_ids.json`,
  `funda_tracking.json`, `funda_blacklist.json`, `funda_werk_coords.json`,
  `funda_thuis_coords.json`, `funda_enrichment_cache.json`,
  `funda_sitemap_cache.json`.
- Uitvoer van een lokale run: `funda_log.txt`, `funda_run_summary.json`,
  `funda_rapport.md`, `funda_rapport.html`.
- `funda_seeds_lokaal.json` (eigen tiny_id's voor de sitemap-probe en
  -validatie).

Secrets op GitHub: `FUNDA_PERSONAL_JSON` en `FUNDA_PWA_PASSWORD` (verplicht),
`FUNDA_BLACKLIST_JSON` (optioneel, alleen als de cache nog geen blacklist heeft),
`WEB_PUSH_PUBLIC_KEY`, `WEB_PUSH_PRIVATE_KEY`, `WEB_PUSH_SUBSCRIPTION` en
optioneel `WEB_PUSH_SUBJECT`. Een secret vervang je in zijn geheel: plak de hele
`funda_personal.json`, na `python -m json.tool funda_personal.json`.
`FUNDA_MAIL_USER` en `FUNDA_MAIL_PASSWORD` gebruikt geen workflow meer; die
mogen weg.

## 3. Wat nooit mag

Elk punt is een besluit; de uitleg staat in de genoemde sectie.

- **Funda's botbescherming omzeilen**: geen wisselende vingerafdrukken, geen
  andere host om een blokkade te passeren, geen app-vermomming. Bij 401, 403 of
  429 stoppen (5).
- **Bevolkingskenmerken** (herkomst, nationaliteit, inkomen van een buurt)
  lezen, bewaren of tonen (9).
- **Een eurobedrag in de pushmelding**, of inkomen in rapport, log of push (7).
- **Adressen, postcodes, woningnummers of profielbedragen in de log** (11).
- **Een merknaam, kleur of font van derden** in de repo of in een commitbericht
  (10).
- **Echte scenarionamen, persoonsgegevens, echte mailinhoud of tracking-tokens**
  in code, tests, fixtures of notities (8, 6).
- **De padenlijst van de Actions-cache wijzigen zonder migratie** (12).
- **Onversleuteld publiceren** (12).
- **Rekenen met prijs 0** bij een woning zonder vraagprijs (7).
- **Een test uitschakelen of versoepelen** om iets groen te krijgen. De
  scantests (merknaam, scenarionamen, publieke log, jaartest) falen met opzet.
- **Met de hand in `requirements.txt` werken**, of pyfunda upgraden zonder de
  code mee te porten (12).
- **`auto_push()` laten draaien in een test**, of meer dan `docs/` laten
  committen door een run (12).
- **Stil verliezen.** Onbekend = doorlaten of "onbekend" tonen, twijfel =
  onderaan zetten. Een woning verdwijnt nooit door een ontbrekend gegeven
  (uitzondering: geen vraagprijs, zie 7).

## 4. Wanneer stopt een run met exit 2

Exit 2 = stoppen vóór het rapport, via `_stop()` in `funda_zoek.py`. Rapport,
`docs/`, seen-ids en tracking blijven onaangeroerd, niets wordt `weg`, er wordt
niets gepubliceerd en de workflow wordt rood. De caches met wat al is opgehaald
mogen wel bewaard worden (de stap "State bewaren (cache)" heeft `if: always()`).
Reden: "0 woningen" is niet hetzelfde als "zoeken stuk"; zonder deze checks
schrijft een kapotte bron een leeg rapport over het gevulde heen.

1. **Geen enkele geslaagde zoek-call** (`zoek_alle_banden`). Zo eindigt ook een
   kapotte sitemapbron: 401 of 403, HTML in plaats van XML, robots.txt van
   `www.funda.nl` sluit `/detail/` uit (`detail_verboden()`), nul kandidaten, een
   ingestelde stad met nul URL's, of de nieuwste lastmod ouder dan
   `MAX_LEEFTIJD_DAGEN` (3). Tests: `test_alles_faalt`,
   `test_sitemapbron_faalt_luid`; `test_funda_sitemap.py::test_fouten`,
   `test_steden`, `test_leeftijd`.
2. **Alle zoek-calls geslaagd, samen nul woningen** (`zoek_alle_banden`): de
   faalmodus van de HTML-route bij gewijzigde markup, en van de mailroute bij een
   onleesbare mailbox. Test: `test_stille_lege_oogst`.
3. **Geen enkele bron in `auto`.** `kies_zoeker()` zet één `::error::` met de
   oorzaken en geeft een `GeenBron` terug; daarna geval 1. De sitemaproute doet
   in `auto` haar zoekwerk al in `kies_zoeker()` (`ophalen()`), zodat een 403 op
   een koop-sitemap in die ene melding staat. Test: `test_auto_keten`.
4. **Detail-endpoint dicht** (`DetailEndpointDicht`), in de zoeker of de pool:
   meteen bij 401, 403 of 429; bij `DICHT_NA` (5) mislukte calls op rij (een
   nette 404 telt niet en zet de reeks op 0; de pool telt door vanaf de zoeker);
   en als de run eindigt met mislukte calls. Er is geen terugval: elke route
   verrijkt via dit endpoint. Tests: `test_endpoint_halverwege_dicht`,
   `test_pool_404_beeindigt_reeks`, `test_pool_404_bovenaan`;
   `test_funda_sitemap.py::test_detail_dicht`, `test_detail_halverwege`.

De pool draait ná de checks 1 en 2: een stukke zoekbron faalt luid, ook als de
pool iets oplevert.

**Geen exit 2:** rente, verrijking en geocoding (fail-soft: "onbekend" in het
rapport, een `::warning::`, nooit een woning minder), een losse 404, en een deel
van de zoek-calls dat mislukt. De workflow stopt al vóór de run als
`FUNDA_PWA_PASSWORD` of `FUNDA_PERSONAL_JSON` ontbreekt of ongeldig is.

## 5. Funda als bron: wat dicht is en wat we niet doen

Stand (verloop en metingen: notities):

- De zoek-API (`listing-search-wonen.funda.io`) is dicht sinds 18 aug 2026: App
  Check met device attestation. Dat komt niet terug via code.
- `www.funda.nl` geeft sinds 8 okt 2026 een 403 vanaf Actions op de zoekpagina
  en detailpagina's. De blokkade hangt aan het IP van de runner; headers of
  TLS-profielen aanpassen helpt niet. robots.txt en de sitemaps komen wel door.
- Het detail-endpoint (`listing-detail-page.funda.io`) geeft de eerlijke client
  200. Op Actions is de sitemaproute daarom de bron (besluit eigenaar, 6 nov
  2026).

Regels:

- **Niet omzeilen.** Een nieuwere TLS-vingerafdruk of de host
  `listing-search-wonen.funda.nl` is bewust niet geprobeerd. Wat wel mag: de
  sitemaps, het detail-endpoint, funda's eigen mails, en draaien vanaf een eigen
  netwerk.
- **Eerlijke client voor funda's API-hosts.** Elk verzoek van de
  `Funda`-subklasse gaat via curl zonder browser- of app-profiel, met
  `EERLIJKE_UA` (één constante in `funda_verrijking.py`, door `funda_zoek`
  opnieuw geëxporteerd), zonder app- of traceheaders. pyfunda zelf doet zich
  voor als de app en zoekt bij een weigering een werkende vingerafdruk; gebruik
  daarom altijd `from funda_zoek import Funda`, nooit pyfunda's eigen `Funda`.
  Niet terugzetten zonder bewuste keuze van de eigenaar. Test:
  `test_eerlijke_client`.
- **Statuscodes** (in de subklasse): 401/403/429 = `DetailEndpointDicht` (exit
  2), 404/410 = `WoningNietGevonden` (woning weg, endpoint werkt), de rest een
  gewone `LookupError` (storing).
- **Eén vast profiel voor `www.funda.nl` en `links.funda.nl`:**
  `funda_sitemap_zoek.UA` en `IMPERSONATE` (`safari15_5`), ook in de HTML-zoeker
  en als `funda_mail_bron.TRACKER_IMPERSONATE`. Een 401, 403 of bot-controle =
  luid falen. Test: `test_funda_html.py::test_profiel_www`.
- **Probes** draaien alleen handmatig en gebruiken per host één vaste client. De
  dagelijkse workflow start na een mislukte run geen probe.
- **Diagnose:** in "Funda API debug" zegt job tests iets over de code en job
  funda-live (bewust `continue-on-error` op job-niveau) iets over funda. Het
  echte faalsignaal is de rode dagelijkse workflow.

**Besluit robots.txt van de API-hosts (6 nov 2026): doorgaan.** De detail-host
heeft `Disallow: /`; dat was bekend en is geaccepteerd, dus geen reden om te
heroverwegen. `detail_verboden()` leest alleen de robots.txt van `www.funda.nl`
en houdt de detail-calls niet tegen. De waarborgen blijven staan:

- `EERLIJKE_UA` met repo-link, zodat funda ons kan herkennen en blokkeren;
- meteen stoppen bij 401/403/429, nooit omzeilen;
- hooguit `sitemap_max_verkennen` (200) verkennende detail-calls per run,
  eenmalig 600 en niet hoger (`SITEMAP_MAX_VERKENNEN_PLAFOND`);
- geen wisselende vingerafdrukken.

Heroverwegen zodra funda de eerlijke client weigert, funda's voorwaarden dit
uitdrukkelijk verbieden, of funda erom vraagt. Alternatief: Huispedia (prototype
op branch `claude/probe-andere-woningsites`). Een thuisnetwerk lost dat niet op;
ook daar verrijkt elke route via de detail-host. `local-listings` en
`listing-detail-summary` roept dit script niet aan. Afweging en volumes:
notities.

## 6. Zoeken, filters en pool

- **Zoekmethode:** `FUNDA_ZOEK_METHODE` of `zoek_methode`: `auto` (standaard:
  api, dan html, dan sitemap; de eerste die werkt, via `bereikbaar()`), of `api`,
  `html`, `sitemap`, `mail`. `mail` alleen expliciet: `auto` opent de mailbox
  nooit.
- **Prijsbanden:** funda kapt een zoekopdracht af op ongeveer 140 resultaten.
  Daarom zoeken per prijsband (stap 20k) en sortering, met dedup.
- **Sitemaproute** (`SitemapZoeker`; metingen en opstart: notities).
  - Index: `https://www.funda.nl/sitemap_index.xml/` (met slash). De sitemap
    geeft URL en lastmod; de rest komt van het detail-endpoint en staat in
    `funda_sitemap_cache.json`.
  - Steden via `sitemap_steden` (`stad_slug()`), daarna een slug-afwijslijst.
  - Koop-sitemaps alleen opnieuw ophalen als de index veranderde, met 10 minuten
    speling (`INDEX_SPELING_SECONDEN`). Kandidatenlijst hooguit 36 uur
    hergebruiken (`MAX_HERGEBRUIK_UUR`).
  - Geen detail-call bij ongewijzigde lastmod én buiten de doelmarkt of
    afgewezen door een nafilter (`_sitemap_overslaan`). Woningen die door alle
    filters komen: elke run vers.
  - Verkennen: `sitemap_max_verkennen` per run (workflow-input, wordt
    `FUNDA_SITEMAP_MAX_VERKENNEN`), nieuwste lastmod eerst, tijdsbudget
    `MAX_SECONDEN` (15 minuten). De job heeft `timeout-minutes: 45`.
  - De logregels "Meting lastmod", "Pool en sitemap" en "Run-kosten" tellen
    alleen aantallen. Bij "Meting lastmod" hoort het aantal "ongewijzigde
    lastmod, toch andere prijs of status" 0 te zijn.
- **Nafilters: elke route filtert na het ophalen** (`nafilter`, `NAFILTERS`:
  woningtype, niet beschikbaar, prijs/m2/straal, stad, buurt, straat-segment;
  daarna belegging, begane grond en blacklist in `detailcheck`). Niet elke bron
  filtert zelf, dus haal hier nooit een filter weg omdat "funda dat al doet".
  - **Onbekend = doorlaten** (geen type, geen coördinaten, geen thuispunt).
    Uitzondering: geen vraagprijs (7).
  - Woningtype is een **afwijslijst, geen toestaanlijst** (`is_geen_appartement`:
    `house_type`, anders alleen het eerste segment van de URL-slug).
  - Straal: `snap_straal(radius_km)` of `straal_nafilter_km` (0 = uit). Zonder
    thuispunt geen afstandsfilter, met een `::warning::`. Zet daarom
    `thuis_coords` in de config.
  - Buitenruimte: **bewust geen nafilter**; funda's boolean is onbetrouwbaar. Het
    model weegt het mee.
  - Geen detail-call voor wat op stad of straat-segment al afvalt.
  - Tests: `test_zoekcriteria`, `test_woningtypefilter`, `test_buurtfilter`,
    `test_stadfilter`, `test_sitemap_overslaan`.
- **Voorburg:** `WENS_STEDEN` gaat voor op `UITSLUIT_STEDEN` (substring-match;
  "Leidschendam" zou anders Leidschendam-Voorburg en dus heel Voorburg stil
  weggooien). Alleen de gemeentenaam bekend = tonen met "STAD ONDUIDELIJK"
  (`is_twijfelstad()`), onderaan. Test: `test_stadfilter`.
- **Twijfel** (`twijfel_redenen`, `d["_twijfel"]`): de woning blijft staan,
  onderaan in zijn groep.
- **Pool** (`controleer_pool`): haalt elke run de getrackte woningen (laatst
  gezien binnen `pool_dagen`, 120) die niet binnenkwamen opnieuw op.
  - Verkocht, ingetrokken of 3 keer niet op te halen = `weg`. Onder bod of
    optie = niet tonen, wel volgen. Duikt een woning weer op, dan vervalt `weg`.
  - Mislukte calls tellen alleen als het endpoint in dezelfde run aantoonbaar
    werkte (een geslaagde call of een nette 404). Anders markeert een storing
    alles als weg.
  - **Nooit twee detail-calls voor dezelfde woning in één run**
    (`DetailCacheZoeker`, `SitemapZoeker.pool_oordeel()`). De sitemap bepaalt wat
    de pool niet hoeft op te halen, het detail-endpoint bepaalt wat weg is. Niet
    meer in de sitemap = één controle-call.
  - Tests: `test_pool`, `test_pool_in_run`, `test_geen_dubbele_detail_calls`.
- **Tracking** (`funda_tracking.json`): eigen prijsvolging, los van funda.
  Vlaggen voor prijsdaling en "lang op funda".
- **HTML-route** (lokaal; op Actions 403): de straal moet een waarde zijn die
  funda kent (1, 2, 5, 10, 15, 30, 50), anders komt er status 200 met nul
  kaarten; daarom `snap_straal()`. Postcode lowercase zonder spatie. De parser
  leunt op funda's markup: `test_funda_html.py` draait op een fixture,
  `scripts/funda_html_validatie.py` gaat af als funda zijn HTML verandert.
- **Mailroute** (alleen lokaal, `zoek_methode: mail`; details: notities en de
  docstring van `funda_mail_bron.py`).
  - Het mailwachtwoord komt alleen uit de omgeving (`FUNDA_MAIL_PASSWORD`),
    nooit uit `funda_personal.json`.
  - De mailroute volgt nooit een tracking-redirect (elke call is een echte klik
    bij funda); alleen `scripts/funda_mail_validatie.py --volg-redirects`.
  - `scripts/funda_mail_imap_check.py` print alleen getallen en publieke
    tiny_id's: geen onderwerpen, afzenders, mailtekst of tracking-links.
  - Geen echte mail of token in de repo; de fixtures hebben dummy-tokens.

## 7. Rapport en model

- **Volgorde in `genereer_rapport()`:** detail-call (uit de cache van
  `funda_zoek`, dus geen extra funda-verkeer), pyfunda-verrijking, eerst de
  routes (reisafstand telt mee), voorlopige beoordeling, verrijking uit open
  bronnen (Past en Krap eerst, binnen het budget), definitieve beoordeling.
- **Financiering is een poort, geen punt.** Eerst: kun je het lenen en wil je
  het per maand betalen (netto woonlasten tegenover je grens). Dat bepaalt de
  groep; daarbinnen telt de score. Onbekend is geen minpunt.
- **Sorteren** met `funda_beoordeling.sorteer` (geen vraagprijs, poort, twijfel,
  score), dezelfde sleutel als "Aanbevolen" in de UI. Zonder vraagprijs altijd
  achteraan.
- **Push** (`vul_summary_aan()`, `scripts/send_web_push.cjs`): per nieuwe woning
  alleen het poortwoord en de score, de eerste drie in de volgorde van
  "Aanbevolen". **Nooit een eurobedrag:** met de publieke code en woningdata is
  daaruit het inkomen of het eigen geld terug te rekenen, en een melding staat
  op het vergrendelscherm. Het script gooit elk deel met een €-teken weg. Test:
  `test_push_volgorde`.
- **Prijs op aanvraag.** Standaard weg in de nafilter (`buiten_zoekcriteria`).
  Met `prijs_onbekend_tonen: true`: poort "Prijs onbekend", geen leentoets en
  geen woonlasten, altijd achteraan, geen prijs 0 in de tracking. **Nooit
  rekenen met prijs 0** (gaf "Past" en de hoogste score). Tests:
  `test_prijs_onbekend`, `test_prijs_onbekend_rapport`.
- **Eerder zonder prijs:** informatief item, 0 punten, uit de eigen waarneming
  in de sitemapcache (`_zonder_prijs_gezien`) of funda's prijshistorie. Geen
  datum bekend = "datum onbekend" (`ZONDER_PRIJS_ONBEKEND`); verzin er geen.
- **Besluiten van de eigenaar over het model:**
  - **Geen energielabel = rekenen met het slechtste** (18 nov 2026): label G,
    tenzij het bouwjaar een ondergrens geeft (`label_aanname`). Alleen voor de
    energiekosten in de woonlasten; de leentoets krijgt geen label en de score
    geen minpunt. Test: `test_label_aanname`.
  - **Schuin dak = klein minpunt** (18 nov 2026): zeker = "let op" met -0,5
    (`drempels.schuin_dak_punten`, `gewichten.schuin_dak`), mogelijk =
    informatief met 0 punten, plat of geen aanwijzing = geen item. Een
    ontkenning en een zin over berging, complex of buren tellen niet. Test:
    `test_schuin_dak`.
  - **Binnenklimaat = indicatie, geen meting** (19 nov 2026): hooguit twee
    informatieve items, "Zomer" en "Winter", 0 punten, alleen uit aanwijzingen
    die er al zijn (geen nieuw verzoek). Onbekend is geen aanwijzing; zonder
    aanwijzing geen item. Test: `test_binnenklimaat`.
  - **Nieuwe bronnen van 18 nov 2026 tellen 0 punten** (`omgeving_items()`):
    gewichten volgen pas als de spreiding tussen buurten bekend is.
    Politiecijfers zijn altijd feitelijk, zonder oordeel over een buurt.
- **Niet gemeten op echte advertenties** (reken er niet op): de waarden van
  "Soort dak", "Aantal bouwlagen", "Isolatie", "Verwarming" en "Voorzieningen",
  of "1e woonlaag" de begane grond is (telt daarom niet), de vocabulaire van
  `soortwoning` en van de status (de log telt de statuswaarden), en of "onder
  bod" in de sitemap blijft.
- **Jaarwissel:** `test_funda_beoordeling.py` faalt op 1 januari tot
  `data/trhk_2026_tabel1.json`, `NHG_GRENS` en `STARTERS_GRENS` van het nieuwe
  jaar zijn. Los het op, zet de test niet uit.
- **Fixture-render:** de 13 fictieve woningen in `testdata/woningen.json` gaan
  in `test_rapport_testdata` door het echte `genereer_rapport()`.

## 8. Config

`beoordeling` en `financien` in `funda_personal.json` en in
`FUNDA_PERSONAL_JSON`. Alles optioneel; de standaard staat in
`funda_beoordeling.STANDAARD`, die van `beoordeling.verrijking` alleen in
`funda_verrijking.STANDAARD`. Zonder `financien` rekent het model met
`bruto_jaar`, `eigen_inleg`, `duo_maandlast` en `leeftijd`, zonder scenario's.

Geldende sleutels (sinds 7 nov 2026 alleen deze):

- `beoordeling`: `score_basis`, `m2_wens`, `max_woonlaag_zonder_lift`,
  `fiets_kmu`, `lang_op_funda_dagen` (mag ook op het hoogste niveau),
  `max_woonlasten_netto`, `krap_marge`, `financiering` (`alleenstaand`,
  `overbod_pct`, `kk_onzekerheid`, `eigen_geld_tekort_past_niet`,
  `starter_tot`), `harde_eisen`, `werk`, `gewichten`, `drempels`, `verrijking`
  (onder meer `aan`, `bronnen`, `max_calls_per_run`).
- `financien`: `alleenstaand`, `starter_tot`, `planning`, `scenarios` (per id
  `bruto_jaar`, `label`, optioneel `datum`, `eigen_geld`, `voorwaardelijk`; een
  kaal getal mag ook), `studieschuld.maandlast`, `bkr` (`[{limiet, opgezegd}]`
  of `[{maandlast}]`), `eigen_geld` (`nu`, `datum`, `per_maand`, `buffer`),
  `kosten_koper` (`vast`, `nhg_pct`), `rente` (`pct`, `datum`,
  `rentevast_jaren`, `bron`, `nhg`, `ltv`, `max_dagen`).
- Hoogste niveau, voor zoeken: onder meer `zoek_methode`, `sitemap_steden`,
  `sitemap_max_verkennen`, `straal_nafilter_km`, `thuis_coords`, `werk_coords`,
  `prijs_onbekend_tonen`, `pool_dagen`, `mail_dagen_terug`.
- **Oude sleutels** (`funda_beoordeling.OUDE_SLEUTELS`) worden niet gelezen. Het
  rapport rekent dan met de standaard en zet een `::warning::` met alleen de
  vaste paden (`oude_sleutels()`): nooit waarden, nooit een scenario-id.

Scenario's:

- **Geen eigen namen in de code.** Echte id's en labels staan alleen in de
  secret. Code, tests, fixtures en voorbeeld gebruiken `nu`, `later`,
  `later_extra`. `test_geen_scenarionamen` scant elk bijgehouden bestand buiten
  `docs/`, ook op datums en maandnamen.
- De logica kent alleen het id `nu`. Volgorde op datum (`datum`, anders uit een
  id `JJJJ_MM`, anders vandaag). De poort volgt `planning`, anders het eerste
  scenario na `nu`.
- Zet `"voorwaardelijk": true` in de secret waar dat geldt: zonder de vlag is
  het stil een gewoon scenario ("Past ..." in plaats van "Past alleen ...").

## 9. Open bronnen, rente en geocoding

Voor alle drie: fail-soft, `EERLIJKE_UA`, sequentieel, robots.txt per host eerst
(vers per dag; de laatste goede versie alleen als terugval bij time-out of 5xx,
nooit bij een weigering). Bij 401/403/429/5xx stopt de host en blijft hij een
dag dicht. Nooit omzeilen. Hosts, robots-metingen en details per bron: notities
en de docstring van `funda_verrijking.py`.

- **Allowlist van velden.** Herkomst, nationaliteit, inkomen en andere
  bevolkingskenmerken worden nooit gelezen, bewaard of getoond. Van CBS alleen
  `KERN_PDOK`; van funda's buurtcijfers alleen de vraagprijs per m2 (de hele
  cachesectie `market_insights` gaat bij laden en opslaan door de allowlist).
  `woningvoorraad` staat alleen in de cache als noemer, nooit in uitvoer of log.
  Politiecijfers onder 100 woningen: geen cijfer.
- **Eén bron per waarde:** `STANDAARD` van de verrijking, de tabel `SECTIES`,
  `EERLIJKE_UA` in `funda_verrijking`; `LBM_KLASSE`, `FUND_KLASSE`, drempels en
  `STANDAARD_RENTE` in `funda_beoordeling`. Tests: `test_ua`, `test_een_bron`,
  `test_import_zonder_personal`.
- **Bronnen** apart aan of uit in `beoordeling.verrijking.bronnen`
  (`kerncijfers`, `veiligheid`, `lucht`, `groen`, `klimaat`, `erfgoed`, naast
  BAG, fundering, geluid, Leefbaarometer en tevredenheid). Een bron die uit
  staat of niets gaf, levert geen item.
- **Budget:** 90 verzoeken per run (`max_calls_per_run` gaat voor). Wat niet
  past krijgt "budget" en gaat de volgende run verder; Past en Krap eerst.
- **Laagnamen en jaren met een datum** (`RIVM_LAGEN`, `RIVM_LUCHT_LAGEN`,
  `POLITIE_JAAR`): verdwijnt een jaargang, dan "onbekend" tot de constante is
  bijgewerkt. `POLITIE_JAAR` bijwerken als 2026 volledig is.
- **Bewust niet gebruikt:** WOZ-waardeloket en KOOP (robots verbiedt het), de
  PDOK Locatieserver en Nominatim (robots verbiedt het), de eigen API achter de
  rentepagina van ASN en de API van DNB (vragen een sleutel), hitte-eiland en
  gevoelstemperatuur (eenheid niet te onderbouwen), de eigen WFS van de RCE.
- **Cache:** alles in `funda_enrichment_cache.json`, als secties (`SECTIES`,
  plus `price_history`, `market_insights`, `broker`, `robots`,
  `verrijking_weigering`, `rente`). Adres- en puntsleutels zijn gehasht. **Geen
  nieuw cachepad** (12). Van de makelaar alleen naam en reviews; zijn aanbod
  wordt niet opgehaald.
- **Rente:** een handmatige rente gaat altijd voor (`financien.rente.pct` met
  `datum`; de enige plek, `funda_rente` leest die zelf). Anders het nieuwste
  ASN-tariefblad, anders het DNB-cijfer via het ECB Data Portal, anders
  `STANDAARD_RENTE` met een melding. Hooguit één poging per dag. Rentevast korter
  dan 10 jaar = toetsrente 5%. Ouder dan 30 dagen = melding bovenaan.
- **Geocoding** (`funda_verrijking.Geocoder`, BAG-collectie `adres` op
  `api.pdok.nl`): per postcode eerst de config (`werk_coords`, `thuis_coords`),
  dan de caches `funda_werk_coords.json` en `funda_thuis_coords.json`, dan één
  poging per run (`limit=1`, time-out 60 s; het is traag).
  - De sleutel in die caches is een hash (`postcode_sleutel`); een oude leesbare
    sleutel wordt bij het laden omgezet (`coords_cache_lees`).
  - Eén stand voor `api.pdok.nl` per run, gedeeld met de verrijking
    (`neem_cache_over`, `Sessie.neem_over`). Een weigering sluit de host een dag
    voor beide; een time-out van de geocoding sluit de verrijking niet.
  - Mislukt = `::warning::` met alleen aantallen en de reden, nooit de postcode.
    Zonder werkpunt "reisafstand onbekend" (geen minpunt).
  - Route via OSRM met `EERLIJKE_UA`, anders hemelsbreed maal 1,3.

## 10. PWA en huisstijl

Volledige beschrijving (sleutelopbouw, CSP, slotscherm): notities en
`test_funda_pwa.py`. Regels:

- **Sleutels** (`funda_rapport.beveilig_html`): hoofdsleutel = PBKDF2-SHA256 met
  het vaste `APP_ZOUT` en 600.000 iteraties; runsleutel = HKDF met een run-zout,
  voor AES-256-GCM. Zout en IV elke run nieuw. `APP_ZOUT` wijzigen = iedereen
  vult één keer het wachtwoord in.
- **Eerst gzip, dan opvullen (`vul_op`, `BLOK` van 8 kB), dan AES**, zodat de
  bestandsgrootte het aanbod niet verraadt.
- **"Onthoud op dit apparaat"** bewaart de hoofdsleutel als niet-exporteerbare
  HKDF-sleutel in IndexedDB (30 dagen), nooit het wachtwoord. Oude bewaarde
  sleutels en wachtwoorden worden gewist, niet omgezet.
- **Wrapper zonder code:** `ui/slot.html` heeft alleen markup, de CSP en het
  pakket in `#slot-data`. CSS en JS staan als bestanden in `docs/`
  (`schrijf_statisch`, `STATISCH`). Leaflet 1.9.4 is zelf gehost, ongewijzigd,
  sha256 vastgepind in de test.
- **CSP** (`funda_rapport.CSP`): `script-src 'self'` en `style-src 'self'`. Dus
  geen inline script, geen `style=` in de markup, geen externe scripts. Externe
  links met `rel="noopener noreferrer"`; `funda_ui.funda_url` laat alleen
  `https://www.funda.nl/...` door; `#woning-data` escapet `<`, `>` en `&`.
- **Service worker:** cache `funda-shortlist-v7`. Ophogen bij elke nieuwe
  wrapper en bij elk gewijzigd bestand in `ASSETS`, anders blijft een
  geïnstalleerde PWA de oude tonen.
- **Slotscherm:** pauze na vier foute wachtwoorden (teller
  `funda_slot_pogingen` in `localStorage`, het enige wat het slotscherm daar
  bewaart). Ontgrendelt niet in een frame. Zonder `DecompressionStream` zegt het
  dat, niet "fout wachtwoord".
- **Manifest** zonder voornaam ("Woningrapport" / "Woningen"): het staat
  publiek. De verversknop linkt naar de Actions-pagina, zonder token.
- **Push zonder backend:** de webapp toont een subscription-JSON voor de secret
  `WEB_PUSH_SUBSCRIPTION`; de publieke sleutel staat in
  `<meta name="funda-push-key">`.
- **Tekst in het rapport:** de poort heet "Status", het scenario
  "Financiering". Geen "run", hostnaam of bestandsnaam (uitzondering: de naam
  `WEB_PUSH_SUBSCRIPTION` in het meldingenblok). Knoppen in de gebiedende wijs,
  "meldingen" en niet "notificaties", een foutmelding noemt de vervolgstap. De
  bron onder een punt gaat door `funda_ui.bron_tekst()`. Vijf lettermaten (13,
  14, 16, 18, 20 px), vet is 600.
- **Huisstijl: eigen palet "Inkt en blauw", geen huisstijl van een merk**
  (merkrecht, en de CSS van het slotscherm staat publiek). Tokens:
  `.interface-design/system.md`. **Geen merknaam van derden in de repo of in
  commitberichten** (besluit eigenaar, 18 nov 2026): `test_geen_merknaam` scant
  elk bijgehouden bestand, ook dit bestand en de notities. Het paarse palet is
  op 7 nov 2026 afgewezen; `test_funda_ui.py` weigert paarse tokens en pint de
  kernkleuren vast.

## 11. Publieke log

De Actions-log van deze publieke repo is voor iedereen leesbaar. Overal geldt:
**alleen aantallen**. Nooit adressen, postcodes, woningnummers of bedragen van
het profiel. Op Actions (`publieke_log()`, `GITHUB_ACTIONS` gezet) ook:

- postcode als "(verborgen)"; de zoek-URL van de HTML-route zonder prijs- en
  m2-grenzen;
- geen woninglijst maar `toon_aantallen()` (lokaal `toon_lijsten()`);
- geen regel per prijsband en geen aantallen zoek-calls (die verraden het
  budget); elke zoekfout één keer;
- een mislukte detail-call heet "een woning"; `--debug-wijken` werkt alleen
  lokaal;
- elke logregel en `::error::` gaat door `log_tekst()`, dat detailpaden,
  detail-URL's en nummers van 7 of meer cijfers vervangt door "(woning)".
  Nieuwe logregels met een foutmelding van een client ook.

Wat wel mag: labelnamen van funda's kenmerken met aantallen, aantallen per
poort, verrijking per bron en status, rente met bron, statuswaarden.
Test: `test_funda_zoek.py::test_publieke_log`. `test_funda_zoek.py` zet
`GITHUB_ACTIONS` bovenaan uit, zodat de job tests hetzelfde doet als lokaal.

## 12. CI, cache en publiceren

- **Padenlijst van de Actions-cache nooit wijzigen zonder migratie.** De
  cacheversie hangt af van de exacte `path`-regels in `funda-daily.yml`. Na een
  wijziging start de run met lege state: alles lijkt nieuw, de tracking is weg
  (gebeurd op 6 nov 2026). Nieuwe state gaat in een bestaand bestand. Anders de
  migratie met `scripts/state_migratie.py` opnieuw inbouwen (oude padenlijst
  exact, zelfde volgorde; `BESTANDEN` bijwerken). Zie notities.
- **Encryptie verplicht in CI:** met `FUNDA_REQUIRE_ENCRYPTION=1` weigert
  `funda_rapport.py` een onversleuteld rapport, vóór er iets in `docs/`
  verandert.
- **Publiceren:** de workflow commit alleen `docs/` en doet
  `git pull --rebase origin main` vóór de push. Het schrijf-token zit alleen in
  die stap (`persist-credentials: false`, `met_token`). `permissions`: niets voor
  de workflow, `contents: write` voor de job; de debug-workflow alleen
  `contents: read`.
- **Lokaal:** `auto_push()` commit ook alleen `docs/`, maar rebaset niet. Doe
  zelf eerst `git pull --rebase`. Zet nooit twee worktrees op dezelfde branch.
  Test: `test_auto_push_alleen_docs`.
- **Afhankelijkheden staan vast.** `requirements.txt` is gegenereerd uit
  `requirements.in` (commando bovenin dat bestand), met exacte versies en
  hashes. De workflows doen `pip install --require-hashes` (geen
  `--upgrade pip`) en `npm ci --ignore-scripts`. Acties staan op een commit-SHA
  met de tag als commentaar. Bijwerken is een bewuste stap: opnieuw genereren of
  de SHA opzoeken, en de diff lezen.
- **pyfunda staat op 2.9.0** (PyPI, met hash). De code gebruikt de v2-API
  (`search_listing`, `r.data`); v3 is een rewrite zonder die methodes.
- **Niet in OneDrive zetten:** dat gaf afgekapte bestanden en kapotte
  `.git`-locks.

## 13. Lokaal draaien en testen

```
pip install --require-hashes -r requirements.txt
python funda_zoek.py                 # volledige run, opent HTML, commit en pusht docs/
python funda_zoek.py --no-push       # zonder commit en push (gebruik dit om te kijken)
python funda_zoek.py --no-open       # zonder browser
python funda_zoek.py --debug-wijken  # buurten met aantallen (alleen lokaal)
```

Tests zijn gewone scripts, offline: `python test_funda_zoek.py` enzovoort. De
job tests in "Funda API debug" draait elk `test_*.py`.

- `test_funda_zoek.py`: `main()` met stub-zoekers. Exit 2, nafilters, pool,
  auto-volgorde, fixture-render, push (met node, anders overgeslagen), publieke
  log, geocoding, eerlijke client. `auto_push()` staat hier uit.
- `test_funda_sitemap.py`: de sitemaproute, met een vaste klok (`NU`).
- `test_funda_html.py`, `test_funda_mail.py`, `test_funda_mail_ophalen.py`: de
  lokale routes, op fixtures en een stub-mailbox.
- `test_funda_beoordeling.py`: het model, met de golden file
  `testdata/beoordeling_verwacht.json` (bijwerken: `--schrijf-verwacht`, en de
  diff lezen), de jaartest en de scan op scenarionamen.
- `test_funda_ui.py`: de UI op `testdata/beoordeling_v3.json`, contrast, de scan
  op merk- en fontnamen, het slotscherm.
- `test_funda_verrijking.py`, `test_funda_rente.py`: open bronnen, rente en
  geocoding met een nep-HTTP-functie.
- `test_funda_pwa.py`: sleutelopbouw en ontsleutelen (Python, en met node het
  echte `ui/slot.js`), CSP, geen onversleuteld rapport in CI, service worker,
  manifest.

Tegen de echte site, alleen handmatig: `scripts/funda_html_validatie.py`,
`scripts/funda_sitemap_validatie.py`, `scripts/funda_sitemap_probe.py`,
`scripts/funda_mail_validatie.py`, `scripts/funda_mail_imap_check.py`.

## 14. Open punten en ideeën

Bewust niet gebouwd (open):

- `localStorage` versleutelen (bewaard, verborgen en gezien staan leesbaar op
  het apparaat).
- De kaart pas na een tik laden.
- `docs/` publiceren zonder git-geschiedenis.
- Gewichten voor de bronnen van 18 nov 2026 (eerst de spreiding kennen).
- De fotohost in de CSP is niet gemeten; bij een afwijking staat er een
  `::warning::` met een aantal.

Ideeën uit de refactorronde van 19 nov 2026, nog niet uitgevoerd:

- Een versie in de URL van `app.js` en `app.css`, en de lijst van de service
  worker afleiden uit de bestanden.
- Fundering en klimaat in één verzoek, en een budget per woning.
- Een onverwacht antwoord van de Leefbaarometer opvangen.
- Doelmarktwoningen alleen verversen bij een gewijzigde lastmod, en de middagrun
  overslaan bij een ongewijzigde index.
- De detailcheck en de HTML-route laten stoppen bij 401/403/429, in plaats van
  de fout te slikken.
- De VvE-bijdrage begrenzen.
- De Leefbaarometer-score afronden.
- Ontkenningen in `lees_advertentie`.
- De acties bijwerken, wegens de waarschuwing over een verouderde Node-versie.
- De waarden van funda's kenmerken Soort dak, Isolatie, Verwarming en Ligging
  bekijken. De log van 19 nov 2026 laat zien dat ze vaak voorkomen (op 42
  woningen: Aantal woonlagen 41, Verwarming 41, Ligging 38, Isolatie 32, Soort
  dak 29).
- Funda's prijshistorie bevatte geen regels zonder bedrag (0 van 553): nagaan of
  die bron van "Eerder zonder prijs" nog zin heeft.
