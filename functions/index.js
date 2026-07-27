const { onSchedule } = require("firebase-functions/v2/scheduler");
const { initializeApp } = require("firebase-admin/app");
const { getDatabase } = require("firebase-admin/database");

initializeApp();

const STALE_MS    = 3  * 60 * 1000;   // 3 min — heartbeat is every 60s
const COOLDOWN_MS = 15 * 60 * 1000;   // don't repeat the same alert for 15 min

exports.checkPiHealth = onSchedule("every 2 minutes", async () => {
  const db  = getDatabase();
  const now = Date.now();

  const [statusSnap, settingsSnap, tokensSnap] = await Promise.all([
    db.ref("status").get(),
    db.ref("settings/notifications").get(),
    db.ref("push_tokens").get(),
  ]);

  const status   = statusSnap.val()   || {};
  const settings = settingsSnap.val() || {};
  const tokens   = tokensSnap.val()   || {};

  const tokenList = Object.values(tokens).filter(Boolean);
  if (!tokenList.length) return;

  const doorStale       = ageMs(status.door_last_seen,       now) > STALE_MS;
  const peripheralStale = ageMs(status.peripheral_last_seen, now) > STALE_MS;
  const alerts          = status.alerts || {};

  // Pi offline — both services silent
  if (doorStale && peripheralStale && settings.offline) {
    if (ageMs(alerts.offline_sent_at, now) > COOLDOWN_MS) {
      await sendPush(tokenList, "Pi is offline or unreachable.");
      await db.ref("status/alerts/offline_sent_at").set(new Date().toISOString());
    }
  }

  // One service down but not both
  if (doorStale !== peripheralStale && settings.service_down) {
    if (ageMs(alerts.service_down_sent_at, now) > COOLDOWN_MS) {
      const which = doorStale ? "Door controller" : "Peripheral controller";
      await sendPush(tokenList, `${which} service stopped responding.`);
      await db.ref("status/alerts/service_down_sent_at").set(new Date().toISOString());
    }
  }
});

function ageMs(isoTimestamp, now) {
  if (!isoTimestamp) return Infinity;
  return now - new Date(isoTimestamp).getTime();
}

async function sendPush(tokens, body) {
  const messages = tokens.map(token => ({
    to: token, title: "Tail Gate RG", body, sound: "default",
  }));
  await fetch("https://exp.host/--/api/v2/push/send", {
    method:  "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body:    JSON.stringify(messages),
  });
}
