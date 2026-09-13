const SERVER_PORTS = [8000, 8765, 8080];
let activeServerUrl = "http://127.0.0.1:8000";

async function fetchFromAnyServer(path, options = {}) {
  try {
    const res = await fetch(`${activeServerUrl}${path}`, options);
    if (res.ok) return res;
  } catch {}

  for (const port of SERVER_PORTS) {
    const url = `http://127.0.0.1:${port}`;
    if (url === activeServerUrl) continue;
    try {
      const res = await fetch(`${url}${path}`, options);
      if (res.ok) {
        activeServerUrl = url;
        return res;
      }
    } catch {}
  }
  return null;
}

async function checkStatus() {
  const statusEl = document.getElementById("goal-status");
  const res = await fetchFromAnyServer("/api/goal/status");
  if (res && res.ok) {
    const data = await res.json();
    if (data.is_paused) {
      statusEl.textContent = `⏸️ Goal Paused (${data.remaining_seconds}s remaining)`;
      statusEl.style.color = "#fbbf24";
    } else if (data.active) {
      statusEl.textContent = `🎯 Goal: ${data.topic || data.text || "Active"}`;
      statusEl.style.color = "#4ade80";
    } else {
      statusEl.textContent = "🎯 Goal Active (Interventions armed)";
      statusEl.style.color = "#4ade80";
    }
  } else {
    statusEl.textContent = "FocusGuard Server Offline (Standalone mode)";
    statusEl.style.color = "#94a3b8";
  }
}

document.getElementById("clear-all-actions-btn")?.addEventListener("click", async () => {
  const statusEl = document.getElementById("goal-status");
  if (statusEl) {
    statusEl.textContent = "🧹 Clearing all actions & locks...";
    statusEl.style.color = "#f87171";
  }

  // 1. Notify backend servers to clear cooldowns and resume
  await fetchFromAnyServer("/api/cooldown/clear", { method: "POST" }).catch(() => {});
  await fetchFromAnyServer("/api/goal/resume", { method: "POST" }).catch(() => {});

  // 2. Broadcast CLEAR_EVERY_ACTION to all tabs via background relay
  try {
    chrome.runtime.sendMessage({ action: "CLEAR_EVERY_ACTION" }, () => {
      if (chrome.runtime.lastError) {}
    });
  } catch (e) {}

  setTimeout(() => {
    if (statusEl) {
      statusEl.textContent = "✨ All actions & restrictions cleared!";
      statusEl.style.color = "#38bdf8";
    }
  }, 400);
});

document.getElementById("pause-goal-btn").addEventListener("click", async () => {
  await fetchFromAnyServer("/api/goal/pause", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ minutes: 5 })
  });
  checkStatus();
});

document.getElementById("open-dashboard-btn").addEventListener("click", () => {
  chrome.tabs.create({ url: `${activeServerUrl}` });
});

checkStatus();
setInterval(checkStatus, 1500);
