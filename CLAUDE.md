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

`test_funda.py` (indien aanwezig) stubt de funda-library en test band-splitsing,
tracking, prijsdaling-detectie en rapport-rendering offline (geen netwerk nodig):
`python test_funda.py`.

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
