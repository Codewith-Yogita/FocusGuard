/**
 * FocusGuard Chrome Extension - Background Service Worker
 * Coordinates goal status and tab events.
 */

chrome.runtime.onInstalled.addListener(() => {
  console.log("FocusGuard Tab Distraction Shield extension installed.");
});

// Broadcast action clearing across all tabs
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) return false;

  if (message.action === "CLEAR_EVERY_ACTION" || message.type === "CLEAR_EVERY_ACTION") {
    try {
      chrome.tabs.query({}, (tabs) => {
        (tabs || []).forEach((tab) => {
          if (!tab || !tab.id) return;
          const url = tab.url || "";
          if (url.startsWith("chrome://") || url.startsWith("edge://") || url.startsWith("about:") || url.startsWith("chrome-extension://")) {
            return;
          }
          try {
            chrome.tabs.sendMessage(tab.id, { action: "CLEAR_EVERY_ACTION" }, () => {
              if (chrome.runtime.lastError) {
                // Ignore benign error if tab doesn't have content script
              }
            });
          } catch (e) {}
        });
      });
    } catch (err) {}
    sendResponse({ success: true });
    return false;
  }

  // Network request relay: bypasses mixed-content and CORS restrictions in HTTPS tabs
  if (message.action === "FETCH_API") {
    const { path, options } = message;
    const SERVER_URLS = [
      "http://127.0.0.1:8000",
      "http://127.0.0.1:8765",
      "https://focusguard-bice.vercel.app"
    ];

    (async () => {
      for (const urlBase of SERVER_URLS) {
        try {
          const url = `${urlBase}${path}`;
          const res = await fetch(url, options || {});
          if (res.ok) {
            const data = await res.json().catch(() => ({}));
            sendResponse({ success: true, status: res.status, data, urlBase });
            return;
          }
        } catch (e) {}
      }
      sendResponse({ success: false, error: "Backend unreachable" });
    })();
    return true; // Keep channel open for asynchronous response
  }

  sendResponse({ received: true });
  return false;
});
