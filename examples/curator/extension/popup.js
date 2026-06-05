// Read the Indico event the user is viewing — in their own authenticated session,
// so protected events work — and hand the export to their own local wrangle-ai
// agent. Nothing is sent anywhere but localhost.

const $ = (id) => document.getElementById(id);
const FIELDS = ["endpoint", "token", "interests"];

// Restore saved settings.
chrome.storage.local.get(FIELDS, (v) => {
  for (const f of FIELDS) if (v[f] != null) $(f).value = v[f];
});
for (const f of FIELDS) {
  $(f).addEventListener("change", () => chrome.storage.local.set({ [f]: $(f).value }));
}

function setStatus(msg, cls) {
  const s = $("status");
  s.className = cls || "";
  s.innerHTML = msg;
}

// Runs in the PAGE's world, so the fetch carries the user's Indico session cookies.
function fetchExportInPage(url) {
  return fetch(url, { credentials: "include" })
    .then((r) => (r.ok ? r.text() : "ERR:" + r.status))
    .catch((e) => "ERR:" + e);
}

$("go").addEventListener("click", async () => {
  const endpoint = $("endpoint").value.replace(/\/+$/, "");
  const token = $("token").value.trim();
  const interests = $("interests").value.trim();
  if (!token) return setStatus("set the token first", "err");

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const m = tab && tab.url && tab.url.match(/\/event\/(\d+)/);
  if (!m) return setStatus("not an Indico event page", "err");

  const origin = new URL(tab.url).origin;
  const exportUrl = `${origin}/export/event/${m[1]}.json?detail=contributions&pretty=no`;

  setStatus("reading the event in your session…");
  $("go").disabled = true;
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: fetchExportInPage,
      args: [exportUrl],
    });
    if (typeof result !== "string" || result.startsWith("ERR:")) {
      return setStatus("could not read the Indico export (" + result + ")", "err");
    }

    setStatus("handing it to your agent…");
    const resp = await fetch(endpoint + "/curate", {
      method: "POST",
      headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
      body: JSON.stringify({
        url: tab.url, title: tab.title, mode: "indico", content: result, interests,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) return setStatus("agent: " + (data.error || resp.status), "err");

    setStatus(
      `queued. <a href="${endpoint}/picks" target="_blank">open my picks &rarr;</a>`,
      "ok"
    );
  } catch (e) {
    setStatus("failed: " + e, "err");
  } finally {
    $("go").disabled = false;
  }
});
