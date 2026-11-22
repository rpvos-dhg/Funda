# Plan: van GitHub Actions en Pages naar Cloudflare

Status: voorstel, 19 nov 2026. Nog niets uitgevoerd. Dit plan wordt per fase
afgevinkt; elke fase eindigt met een beslismoment. Lees eerst `CLAUDE.md`: alle
regels daar blijven gelden, ook na de verhuizing.

Feiten over Cloudflare komen uit het onderzoek van 19 nov 2026 (officiële
documentatie, gelezen die dag). Wat daar als "niet bevestigd" stond, staat hier
als te meten punt in fase 0. Geen getal uit dit plan als feit overnemen zonder
de bron opnieuw te lezen: limieten veranderen.

## 1. Waarom en wat het oplevert

Aanleiding: GitHub start geplande runs sinds begin oktober 2026 structureel 4,5
tot 10 uur te laat (ook door anderen gemeld, geen reactie van GitHub). Verder
staat de repo publiek, inclusief Actions-logs en een git-geschiedenis met 350
versleutelde rapporten.

Wat de verhuizing oplevert:

| Doel | Hoe | Fase |
|---|---|---|
| Runs op tijd | Cron Trigger op Cloudflare | 1 |
| Rapport niet meer publiek te downloaden | Cloudflare Access voor het subdomein | 1 |
| Repo privé, logs niet meer publiek | Pages werkt gratis met een privérepo | 1 |
| Geen rapporten meer in de git-geschiedenis | Publiceren naar Pages, niet als commit | 1 |
| Eén platform voor rekenen, opslag en hosting | Workers, Workflows, R2 | 3 tot 5 |

Belangrijk: de eerste vier doelen haal je al in fase 1, zonder één regel
Python om te schrijven. De volledige herbouw (fase 3 tot 5) levert daarna vooral
op dat GitHub Actions overbodig wordt. Dat is een keuze, geen noodzaak.

## 2. Wat er niet verandert

- De regels uit `CLAUDE.md`, sectie 3 ("Wat nooit mag"), gelden onverkort.
- **Niet omzeilen.** Weigert funda verzoeken vanaf Cloudflare, dan is dat het
  antwoord. Geen andere host, geen proxy, geen ander IP om eromheen te komen.
- Het model (poort, score, besluiten van de eigenaar) verandert niet door de
  verhuizing. Elke gedragswijziging is een aparte, eigen stap.
- De PWA, het slotscherm en de versleuteling in de browser blijven gelijk; een
  geïnstalleerde app moet blijven werken (behalve het nieuwe adres, zie fase 1).

## 3. Harde grenzen van Cloudflare voor dit project

Gelezen op 19 nov 2026 (bronnen in het onderzoeksverslag, zie de notities):

- **Gratis plan is onbruikbaar** voor het rekenwerk: 10 ms CPU en 50 uitgaande
  verzoeken per aanroep. Een run doet er 300 tot 400. Nodig: **Workers Paid,
  5 dollar per maand** (30 s tot 5 min CPU per aanroep, 10.000 verzoeken).
- **Cron:** hooguit 15 minuten wandklok per aanroep. De huidige run past daar
  niet zeker in (verkennen alleen al tot 15 minuten). Daarom **Workflows**: een
  run als reeks stappen, elke stap apart opnieuw te proberen, zonder
  totaallimiet op de duur.
- **PBKDF2 is in productie beperkt tot 100.000 iteraties** (open issue bij
  Cloudflare). Wij gebruiken er 600.000. Oplossing: de hoofdsleutel hangt
  alleen af van het wachtwoord en het vaste `APP_ZOUT`, dus die wordt eenmalig
  lokaal afgeleid en als secret opgeslagen. Per run alleen HKDF en AES-GCM.
  De browser blijft 600.000 iteraties doen; daar verandert niets.
- **Geen eigen TLS-profiel en een gedeeld IP.** Elke uitgaande fetch krijgt de
  header `CF-Worker`. Voor de eerlijke client is dat prima: funda ziet wie we
  zijn. Maar `curl_cffi` en het vaste profiel voor `www.funda.nl` bestaan dan
  niet meer. Of funda Cloudflare doorlaat, is onbekend: **fase 0**.
- **Geheugen 128 MB.** De koop-sitemaps (samen ongeveer 23 MB XML) moeten
  gestreamd worden, niet in één keer ingelezen.
- **Opslag:** KV is niet geschikt (een schrijfactie is elders pas na een minuut
  zichtbaar). Gebruik **R2** (sterk consistent, 10 GB gratis) voor de state.
- **Access en een eigen domein** vragen een Cloudflare-zone: de nameservers van
  het domein moeten naar Cloudflare. Alleen een CNAME bij de huidige
  DNS-provider is genoeg voor Pages zonder Access, niet voor Access of voor een
  Worker op het eigen domein. Een "partial setup" kost een Business-plan.

## 4. Keuze van de taal

**TypeScript op Workers**, met één uitzondering die in fase 0 wordt beslist:

- Het I/O-deel (zoeken, detail-calls, open bronnen, rente, opslag, push,
  publiceren) wordt TypeScript. Netwerkcode moet toch herschreven worden, want
  `curl_cffi`, `pyfunda` en de synchrone `requests`-stijl werken niet op
  Workers.
- **Het model** (`funda_beoordeling.py`, bijna 2.400 regels pure functies, geen
  netwerk) kan misschien ongewijzigd mee als **Python Worker**. Python Workers
  draaien de stdlib (met `re`, `json`, `datetime`, `math`) in Pyodide; de
  GA-status staat alleen in bronnen van derden. Voordeel: de golden file en de
  ruim 130 testzinnen blijven gelden zonder vertaling. Nadeel: twee talen en
  twee toolchains, en een koude start van ongeveer een seconde.
- **Advies:** het model eerst als Python Worker (fase 0 meet of het werkt),
  later eventueel omzetten naar TypeScript als losse stap met dezelfde golden
  file. Werkt het niet, dan meteen naar TypeScript (fase 4).

## 5. Doelarchitectuur

```
Cron Trigger (08:30 en 16:30 UTC)
  -> Workflow "run"
       stap 1  robots.txt en sitemap-index lezen; koop-sitemaps streamen als
               de index veranderde; kandidaten in R2
       stap 2..n  detail-calls in blokken van ~25 (sitemap, pool, detailcheck)
       stap    nafilters, tracking, seen-ids (R2)
       stap    verrijking open bronnen in blokken (budget per woning)
       stap    model (Python Worker via service binding, of TS-module)
       stap    rapport bouwen, gzip, opvullen, AES-GCM met afgeleide sleutel
       stap    publiceren naar R2 of Pages; pushmelding
Pages of Worker met static assets  ->  <subdomein> achter Cloudflare Access
R2: state (de zeven bestanden), caches, het versleutelde rapport
Secrets: hoofdsleutel, VAPID-sleutels, subscription, config (FUNDA_PERSONAL_JSON)
```

Exit 2 wordt: de Workflow stopt vóór de stap "tracking en seen-ids" en vóór het
publiceren, en markeert de run als mislukt (melding naar de eigenaar, zie fase
5). Wat al is opgehaald mag in R2 blijven, zoals nu met de Actions-cache.

## 6. Fasen

Elke fase: eigen branch, eigen PR, review, en pas door naar de volgende na het
beslismoment. Tot en met fase 5 draait het huidige systeem gewoon door.

### Fase 0. Meten en beslissen (één sessie, geen productiecode)

Doel: weten of de volledige verhuizing kan, vóór er tijd in gaat.

Metingen, elk met een klein Worker-script op een tijdelijk `workers.dev`-adres,
met `EERLIJKE_UA`, robots.txt eerst, en zo weinig mogelijk verzoeken:

1. **Funda detail-endpoint vanaf een Worker**: 5 verzoeken naar
   `listing-detail-page.funda.io` voor bekende publieke woningen. Krijgen we 200
   met JSON? Bij 401, 403 of 429: stoppen, niet opnieuw proberen, niet
   omzeilen.
2. **Funda sitemaps vanaf een Worker**: robots.txt, de index en één
   koop-sitemap (gestreamd). Status, grootte, duur, geheugen.
3. **Open bronnen vanaf een Worker**: één verzoek per host (PDOK, RIVM,
   klimaatkaart, CBS-OData, Leefbaarometer, OSRM, ASN, ECB).
4. **Crypto**: HKDF plus AES-GCM in een Worker op een rapport van 500 kB, en
   controleren dat `ui/slot.js` het ontsleutelt. PBKDF2 met 600.000 iteraties
   proberen, om het plafond te bevestigen.
5. **Python Worker met het model**: `funda_beoordeling.py` ongewijzigd laden en
   de 13 fixturewoningen beoordelen; uitkomst byte voor byte tegen
   `testdata/beoordeling_verwacht.json`. Koude start en CPU-tijd meten.
6. **Web Push vanuit een Worker** met een Web Crypto-bibliotheek (kandidaten:
   `@pushforge/builder`, `@block65/webcrypto-web-push`): één testmelding.
7. **Cron-nauwkeurigheid**: een lege cron een paar dagen elk uur laten lopen en
   de afwijking loggen.

Beslismoment:

| Uitkomst | Besluit |
|---|---|
| 1 of 2 geweigerd | Volledige verhuizing stopt. Alleen fase 1 (hybride). |
| 1 en 2 werken, 5 werkt | Fase 1 tot 5 met het model in Python. |
| 1 en 2 werken, 5 werkt niet | Fase 1 tot 5 met het model in TypeScript (meer werk). |
| 6 werkt niet | Push blijft tijdelijk op Actions, of een andere bibliotheek. |

Alle metingen in `testdata/` of `notities/` vastleggen, zonder adressen.

### Fase 1. Fundament en hybride (twee sessies)

Dit levert de meeste winst en is ook het eindpunt als fase 0 negatief is.

1. **Nameservers naar Cloudflare** (eigenaar, bij de registrar). Registratie
   blijft waar hij is. Vooraf alle bestaande records (mail: MX, SPF, DKIM,
   DMARC; website) in Cloudflare overnemen en controleren; de wissel kan tot 24
   uur duren. Gebeurt dit niet, dan Pages via CNAME zonder Access (minder
   winst).
2. **Cloudflare-account**, Workers Paid (5 dollar per maand), API-token met
   alleen de rechten voor dit project.
3. **Pages-project** op `<subdomein>.<eigen domein>`, **Access** ervoor met
   alleen het e-mailadres van de eigenaar.
4. **Publiceren**: de workflow publiceert het versleutelde rapport en de
   statische bestanden met `wrangler pages deploy` naar Pages, in plaats van
   een commit van `docs/`. De stap "Versleuteld rapport publiceren" en
   `auto_push()` passen mee aan; `test_auto_push_alleen_docs` wordt een test van
   de nieuwe publiceerstap.
5. **Cron Worker** die op 08:30 en 16:30 UTC de GitHub-workflow start
   (`workflow_dispatch` via de REST API) met een fine-grained token: alleen
   deze repo, alleen "Actions: read and write". GitHub's eigen `schedule` blijft
   als vangnet, met een vroege stap "is er dit dagdeel al gedraaid?".
6. **Repo privé** zetten. Pas daarna de oude geschiedenis opruimen (zie de
   notities over het opnieuw aanmaken van de repo) en `docs/` uit de repo
   halen.
7. **Overgang voor de gebruiker**: nieuw adres op het beginscherm, één keer het
   wachtwoord, meldingen opnieuw aanzetten (nieuwe subscription in de secret).
   Bewaarde en verborgen woningen horen bij het oude adres en beginnen leeg.
   Het oude adres op GitHub Pages toont een korte verwijzing en gaat daarna uit.

Beslismoment: draait de hybride een week goed (runs op tijd, Access werkt op de
telefoon, push werkt)? Dan fase 2, of hier stoppen.

### Fase 2. Projectopzet en de eerste module (één sessie)

1. Map `cf/` in dezelfde repo: TypeScript, `wrangler`, `vitest` met de
   Workers-pool, eigen `package-lock.json`, `npm ci --ignore-scripts`.
2. Afspraken voor de hele herbouw:
   - één module per Python-module, met dezelfde namen voor functies en
     constanten waar dat kan, zodat `CLAUDE.md` blijft kloppen;
   - fixtures uit `testdata/` gedeeld, niet gekopieerd;
   - elke module krijgt een **differentiële test**: dezelfde invoer door Python
     en TypeScript, uitvoer byte voor byte gelijk (zoals de nulmetingen van de
     refactoring);
   - geen `any` in TypeScript, `strict` aan.
3. Eerste module: **de versleuteling** (`beveilig_html`, `vul_op`). Klein,
   goed getest en met een harde controle: `ui/slot.js` moet het resultaat
   ontsleutelen. Hoofdsleutel als secret (zie sectie 3).

### Fase 3. Het I/O-deel omzetten (vier tot zes sessies)

Volgorde van laag naar hoog risico. Per module: omzetten, differentiële test,
review.

1. **Rente** (`funda_rente.py`): ASN-tariefblad (PDF) en ECB. Let op: de PDF
   uitlezen in een Worker; als dat niet goed gaat, alleen ECB plus handmatige
   rente.
2. **Verrijking en geocoding** (`funda_verrijking.py`): `Sessie` met robots.txt,
   `EERLIJKE_UA`, budget per woning, stoppen bij 401/403/429/5xx, de tabel
   `SECTIES`. De cache gaat van JSON-bestand naar R2 (zelfde vorm).
3. **Sitemapzoeker** (`funda_sitemap_zoek.py`): streaming XML, lastmod-logica,
   `MAX_LEEFTIJD_DAGEN`, `MAX_HERGEBRUIK_UUR`, verkennen met het plafond van 600.
4. **Detail-client**: eerlijk, zonder pyfunda. Statuscodes zoals nu:
   401/403/429 = stoppen, 404/410 = weg, rest = storing. De velden die pyfunda
   uit het antwoord haalt, moeten precies zo worden overgenomen: de
   differentiële test draait op opgenomen echte antwoorden uit fase 0.
5. **Zoeken en pool** (`funda_zoek.py`): `zoek_alle_banden`, `nafilter` met
   `NAFILTERS`, `detailcheck`, `controleer_pool`, `werk_tracking_bij`, de exit
   2-gevallen. De HTML-route en de mailroute gaan **niet** mee (alleen lokaal
   bruikbaar, en de HTML-route werkt vanaf servers niet).
6. **Rapport en UI** (`funda_rapport.py`, `funda_ui.py`): de HTML-opbouw.
   `ui/` blijft zoals het is.
7. **Push** (`send_web_push.cjs`): met de Web Crypto-bibliotheek uit fase 0.

### Fase 4. Het model (één tot vier sessies)

- Bij "Python werkt": `funda_beoordeling.py` als Python Worker achter een
  service binding. De Python-tests blijven de bron van waarheid.
- Bij "Python werkt niet": omzetten naar TypeScript, met de golden file, alle
  testzinnen en een differentiële proef op minstens 2.500 gegenereerde
  woningen, zoals bij de refactoring. Dit is het grootste en meest
  foutgevoelige deel; de parsers hebben in november drie fixrondes gekost.

### Fase 5. Schaduwdraaien en overstappen (twee weken looptijd, twee sessies)

1. **Workflow** in elkaar zetten (stappen uit sectie 5).
2. **Schaduwdraaien zonder dubbel verkeer naar funda.** De Worker doet de
   echte run en bewaart de ruwe antwoorden van funda en de open bronnen in R2.
   GitHub Actions draait daarna de Python-code op diezelfde antwoorden (met de
   bestaande stub-client) in plaats van zelf te verzoeken. Beide rapporten,
   seen-ids en tracking worden vergeleken. Zo blijft het volume naar funda
   gelijk aan nu (de waarborg uit het robots-besluit).
3. **Criteria om over te stappen:** twee weken lang elke run gelijk (of elk
   verschil verklaard en bedoeld), geen exit 2 dat niet ook in Python optrad,
   runs binnen een kwartier na het geplande tijdstip.
4. **Overstap:** de state uit de Actions-cache eenmalig naar R2 kopiëren
   (migratiescript, idempotent, alleen aantallen in de uitvoer). Daarna de
   Worker als enige bron; de GitHub-workflow uitzetten maar laten staan.
5. **Melden bij een mislukte run:** nu is een rode workflow het signaal. Op
   Cloudflare: een pushmelding "Run mislukt, rapport niet bijgewerkt" (zonder
   details), of een mail via een gratis dienst.

### Fase 6. Opruimen (één sessie, na een maand stabiel)

- Python-code die niet meer draait naar een archiefmap of uit de repo; de
  mailroute en de HTML-route blijven als lokaal gereedschap als de eigenaar dat
  wil.
- `CLAUDE.md` herschrijven voor de nieuwe opzet; regels die blijven gelden,
  meeverhuizen.
- GitHub-secrets die niet meer nodig zijn verwijderen; tokens met een
  verloopdatum.

## 7. Wat er met de regels uit CLAUDE.md gebeurt

| Regel | Op Cloudflare |
|---|---|
| Eerlijke client | `EERLIJKE_UA` blijft; de `CF-Worker`-header maakt het nog duidelijker |
| Vast profiel `www.funda.nl` | Bestaat niet meer (geen eigen TLS); een weigering = stoppen |
| Stoppen bij 401/403/429 | Ongewijzigd, ook in de Workflow-stappen |
| Plafond verkennende calls | Ongewijzigd (200, eenmalig 600) |
| Publieke log | Workers-logs zijn privé; de regels blijven toch, voor als er ooit iets publiek wordt |
| Bevolkingskenmerken | Ongewijzigd |
| Geen eurobedrag in de push | Ongewijzigd |
| Padenlijst van de cache | Vervalt; R2-sleutels krijgen een eigen versie en migratieregel |
| Onversleuteld publiceren | Blijft verboden; Access is een extra laag, geen vervanging |
| Tests niet uitschakelen | Ongewijzigd, ook voor de TypeScript-tests |

## 8. Risico's

| Risico | Kans | Gevolg | Maatregel |
|---|---|---|---|
| Funda weigert Cloudflare | onbekend | volledige verhuizing kan niet | fase 0 meet het eerst; dan hybride |
| Funda weigert later alsnog | klein tot middel | run stopt | zoals nu: stoppen, oud rapport blijft; terug naar Actions kan zolang die niet is opgeruimd |
| Verschillen tussen Python en TS in het model | hoog bij omzetten | verkeerde poort of score | Python Worker als het kan; anders differentiële proef en schaduwdraaien |
| Limieten van Cloudflare veranderen | middel | stappen passen niet meer | blokken klein houden; limieten in de Workflow loggen |
| Cron toch onnauwkeurig | klein | late runs | fase 0 meet het; vangnet via GitHub tot fase 6 |
| Nameservers verhuizen breekt mail | klein | mail komt niet aan | records vooraf overnemen en controleren; wissel buiten werktijd |
| Kosten lopen op | klein | meer dan 5 dollar | gebruik ligt ver onder de tegoeden; een budgetwaarschuwing instellen |
| Geheimen op twee plekken | zeker | groter aanvalsoppervlak | tokens zo smal mogelijk, met verloopdatum |

## 9. Kosten en tijd

- **Geld:** 5 dollar per maand (Workers Paid). Pages, R2, Workflows, Access
  (bij een Cloudflare-zone) en de DNS-zone vallen binnen de gratis tegoeden.
- **Tijd**, ruwe schatting in werksessies zoals die van november:
  fase 0: 1; fase 1: 2; fase 2: 1; fase 3: 4 tot 6; fase 4: 1 tot 4;
  fase 5: 2 (plus twee weken looptijd); fase 6: 1. Samen 12 tot 17 sessies.
- **Wat de eigenaar zelf doet:** de nameservers omzetten, het
  Cloudflare-account en het abonnement, de tokens aanmaken, Access testen op de
  telefoon, de app opnieuw installeren.

## 10. Advies

1. **Doe fase 0 en fase 1.** Die lossen het rooster, de publieke downloadbaarheid
   en de publieke repo op, voor 5 dollar per maand en drie sessies.
2. **Beslis daarna** over fase 2 tot 6. De volledige herbouw is mogelijk, maar
   het is veel werk met een reëel risico op nieuwe fouten in het model, en het
   lost geen probleem op dat fase 1 laat liggen. De sterkste reden om toch door
   te gaan: één platform in plaats van twee, en geen afhankelijkheid meer van
   GitHub's rooster.
3. **Begin elke fase in een nieuwe chat** met de opdracht "Voer fase N uit van
   `notities/plan-cloudflare.md`".
