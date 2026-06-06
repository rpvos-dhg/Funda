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

function reportUrl() {
  if (process.env.WEB_PUSH_URL) return process.env.WEB_PUSH_URL;
  const repo = process.env.GITHUB_REPOSITORY || "";
  const [owner, name] = repo.split("/");
  if (owner && name) return `https://${owner}.github.io/${name}/`;
  return "https://rpvos-dhg.github.io/Funda/";
}

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
const homes = Array.isArray(summary.nieuw) ? summary.nieuw : [];
const preview = homes.slice(0, 3).map((home) => {
  const area = home.living_area ? `${home.living_area} m2` : "? m2";
  const city = home.city ? `, ${home.city}` : "";
  return `${home.title}${city} - ${money(home.price)} - ${area}`;
});

const payload = JSON.stringify({
  title: `${count} nieuwe Funda ${count === 1 ? "woning" : "woningen"}`,
  body: preview.join("\n") || "Open de shortlist voor de nieuwste matches.",
  url: reportUrl(),
  tag: "funda-new-listings",
});

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
