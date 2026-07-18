/* Sift frontend: Cognito Hosted UI (implicit flow) + preferences API. */
const C = window.SIFT_CONFIG || {};
const REDIRECT = window.location.origin + "/";
const SUGGESTED = ["AI agents", "AWS", "serverless", "developer tooling", "LLMs",
  "startups", "security", "data engineering", "frontend", "open source"];

function hostedUrl(path) {
  const p = new URLSearchParams({
    client_id: C.clientId, response_type: "token",
    scope: "email openid profile", redirect_uri: REDIRECT,
  });
  return `https://${C.cognitoDomain}/${path}?${p.toString()}`;
}

function getToken() {
  // Token arrives in the URL fragment after Hosted UI redirect.
  if (window.location.hash.includes("id_token")) {
    const h = new URLSearchParams(window.location.hash.slice(1));
    const t = h.get("id_token");
    if (t) {
      sessionStorage.setItem("id_token", t);
      history.replaceState(null, "", REDIRECT);
    }
  }
  return sessionStorage.getItem("id_token");
}

function claims(t) {
  try { return JSON.parse(atob(t.split(".")[1])); } catch { return {}; }
}

async function api(method, body) {
  const r = await fetch(`${C.apiBase}/prefs`, {
    method,
    headers: { "Authorization": "Bearer " + sessionStorage.getItem("id_token"),
               "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { logout(); return null; }
  return r.json();
}

function logout() {
  sessionStorage.removeItem("id_token");
  window.location.href = REDIRECT;
}

function renderChips(selected) {
  const box = document.getElementById("topic-chips");
  box.innerHTML = "";
  const set = new Set(selected.map(s => s.trim().toLowerCase()));
  SUGGESTED.forEach(topic => {
    const el = document.createElement("div");
    el.className = "chip" + (set.has(topic.toLowerCase()) ? " on" : "");
    el.textContent = topic;
    el.onclick = () => el.classList.toggle("on");
    box.appendChild(el);
  });
}

function collectTopics() {
  const chips = [...document.querySelectorAll(".chip.on")].map(c => c.textContent);
  const extra = document.getElementById("topics").value.split(",").map(s => s.trim()).filter(Boolean);
  return [...new Set([...chips, ...extra])].join(", ");
}

async function showDashboard(token) {
  document.getElementById("landing").classList.add("hidden");
  document.getElementById("dashboard").classList.remove("hidden");
  document.getElementById("nav-actions").innerHTML =
    '<button class="btn ghost" id="logout-btn">Log out</button>';
  document.getElementById("logout-btn").onclick = logout;
  document.getElementById("user-email").textContent = claims(token).email || "you";

  const prefs = await api("GET");
  if (!prefs) return;
  renderChips((prefs.topics || "").split(","));
  document.getElementById("topics").value = "";
  document.getElementById("feeds").value = prefs.feeds || "";
  document.getElementById("schedule").value = prefs.schedule || "06:00";
  document.getElementById("obsidian_repo").value = prefs.obsidian_repo || "";
  document.getElementById("enabled").checked = prefs.enabled !== false;

  document.getElementById("save-btn").onclick = async () => {
    const status = document.getElementById("save-status");
    status.textContent = "Saving…";
    const res = await api("PUT", {
      topics: collectTopics(),
      feeds: document.getElementById("feeds").value,
      schedule: document.getElementById("schedule").value,
      obsidian_repo: document.getElementById("obsidian_repo").value,
      enabled: document.getElementById("enabled").checked,
    });
    status.textContent = res && res.saved ? "Saved ✓ Your next brief will use these."
                                          : "Something went wrong.";
    if (res && res.saved) renderChips(collectTopics().split(","));
  };
}

function showLanding() {
  document.getElementById("landing").classList.remove("hidden");
  document.getElementById("signup-btn").onclick = () => location.href = hostedUrl("signup");
  document.getElementById("login-btn").onclick = () => location.href = hostedUrl("login");
}

(function main() {
  if (!C.clientId) { document.body.innerHTML =
    "<p style='padding:40px'>Config not loaded. Deploy writes config.js.</p>"; return; }
  const token = getToken();
  if (token) showDashboard(token); else showLanding();
})();
