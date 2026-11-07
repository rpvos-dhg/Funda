// Web Push naar de PWA bij nieuwe woningen. Leest funda_run_summary.json (funda_zoek.py).
//
// Per woning één regel. Met beoordeling (funda_zoek.vul_summary_aan zet status en score):
//   "<adres>, <stad> · Past · € 196 onder je grens · 8,3"
// Zonder beoordeling het oude formaat: "<adres>, <stad> - € 265.000 - 68 m2".
// Nooit inkomensbedragen en nooit "€ 0": zonder vraagprijs staat er "prijs op aanvraag".
//
//   node scripts/send_web_push.cjs                       (in de workflow, met de Web Push-secrets)
//   require("./scripts/send_web_push.cjs").regel(home)   (tests, zonder te versturen)
const fs = require("fs");

const SUMMARY_FILE = "funda_run_summary.json";

function required(name) {
  const value = process.env[name];
  if (!value) {
    console.log(`[push] ${name} ontbreekt, push overgeslagen.`);
    process.exit(0);
  }
  return value;
}

function money(value) {
  const n = Number(value || 0);
  return `€ ${Math.round(n).toLocaleString("nl-NL")}`;
}

function scoreTekst(value) {
  return Number(value).toFixed(1).replace(".", ",");
}

// "€ 0" mag nooit in een melding (een prijs of grens van 0 betekent: onbekend).
const NUL_EURO = /€\s*0(?![\d.,])/;

function regel(home) {
  const city = home.city ? `, ${home.city}` : "";
  const status = typeof home.status === "string" ? home.status.trim() : "";
  if (status) {
    // Alleen het poortwoord als de reden toch een "€ 0" zou bevatten.
    const veilig = NUL_EURO.test(status) ? status.split(" · ")[0] : status;
    const score = typeof home.score === "number" && Number.isFinite(home.score) ? ` · ${scoreTekst(home.score)}` : "";
    return `${home.title}${city} · ${veilig}${score}`;
  }
  const area = home.living_area ? `${home.living_area} m2` : "? m2";
  // price is null bij "prijs op aanvraag"; dan geen "€ 0" in de melding.
  const prijs = home.price ? money(home.price) : "prijs op aanvraag";
  return `${home.title}${city} - ${prijs} - ${area}`;
}

function reportUrl() {
  if (process.env.WEB_PUSH_URL) return process.env.WEB_PUSH_URL;
  const repo = process.env.GITHUB_REPOSITORY || "";
  const [owner, name] = repo.split("/");
  if (owner && name) return `https://${owner}.github.io/${name}/`;
  return "https://rpvos-dhg.github.io/Funda/";
}

function payloadVoor(summary) {
  const count = Number(summary.nieuw_count || 0);
  const homes = Array.isArray(summary.nieuw) ? summary.nieuw : [];
  return {
    title: `${count} nieuwe ${count === 1 ? "woning" : "woningen"}`,
    body: homes.slice(0, 3).map(regel).join("\n") || "Open het rapport voor de nieuwste woningen.",
    url: reportUrl(),
    tag: "funda-new-listings",
  };
}

function main() {
  if (!fs.existsSync(SUMMARY_FILE)) {
    console.log(`[push] ${SUMMARY_FILE} niet gevonden, push overgeslagen.`);
    process.exit(0);
  }

  const summary = JSON.parse(fs.readFileSync(SUMMARY_FILE, "utf8"));
  const count = Number(summary.nieuw_count || 0);
  if (count <= 0) {
    console.log("[push] Geen nieuwe woningen, push overgeslagen.");
    process.exit(0);
  }

  const publicKey = required("WEB_PUSH_PUBLIC_KEY");
  const privateKey = required("WEB_PUSH_PRIVATE_KEY");
  const rawSubscription = required("WEB_PUSH_SUBSCRIPTION");
  const subject = process.env.WEB_PUSH_SUBJECT || reportUrl();
  const webpush = require("web-push");

  let parsedSubscription;
  try {
    parsedSubscription = JSON.parse(rawSubscription);
  } catch (error) {
    console.error("[push] WEB_PUSH_SUBSCRIPTION is geen geldige JSON.");
    throw error;
  }

  const subscriptions = Array.isArray(parsedSubscription) ? parsedSubscription : [parsedSubscription];
  const payload = JSON.stringify(payloadVoor(summary));

  webpush.setVapidDetails(subject, publicKey, privateKey);

  (async () => {
    let sent = 0;
    for (const subscription of subscriptions) {
      try {
        await webpush.sendNotification(subscription, payload);
        sent += 1;
      } catch (error) {
        const status = error.statusCode ? ` (${error.statusCode})` : "";
        console.error(`[push] Verzenden mislukt${status}: ${error.body || error.message}`);
        if (error.statusCode === 404 || error.statusCode === 410) {
          console.error("[push] Subscription is verlopen; maak een nieuwe subscription in de PWA.");
        }
        process.exitCode = 1;
      }
    }
    console.log(`[push] Verzonden naar ${sent}/${subscriptions.length} subscription(s).`);
  })();
}

module.exports = { regel, payloadVoor, scoreTekst };

if (require.main === module) main();
