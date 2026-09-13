/**
 * FocusGuard Chrome Extension - Content Script
 * Pure in-page DOM HUD, Video Pause, and Tab-level Blocker.
 * 
 * Benefits of DOM Injection:
 * 1. Confined ONLY to the webpage viewport inside the distracting tab.
 * 2. Leaves Chrome tabs strip, address bar, and bookmarks 100% clickable.
 * 3. Instantly pauses HTML5 videos and locks page scrolling without OS freezes.
 */

(function () {
  // Never inject HUD or blocker into FocusGuard dashboard or local servers
  const host = window.location.hostname;
  if (
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "0.0.0.0" ||
    host.includes("vercel.app") ||
    host.includes("focusguard")
  ) {
    return;
  }

  let streakSeconds = 0;
  let isOverlayActive = false;
  let goalPausedUntil = 0;
  let lastCheckedHref = "";
  let isPageProductive = false;
  const SERVER_URLS = [
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8765",
    "https://focusguard-bice.vercel.app"
  ];
  let activeServerUrl = "http://127.0.0.1:8000";

  async function fetchFromAnyServer(path, options = {}) {
    // 1. Try background service worker relay first (bypasses HTTPS mixed-content and CORS restrictions)
    try {
      if (chrome.runtime?.sendMessage) {
        const bgRes = await new Promise((resolve) => {
          chrome.runtime.sendMessage({ action: "FETCH_API", path, options }, (response) => {
            if (chrome.runtime.lastError || !response) {
              resolve(null);
            } else {
              resolve(response);
            }
          });
        });
        if (bgRes && bgRes.success && bgRes.data) {
          return {
            ok: true,
            status: bgRes.status || 200,
            json: async () => bgRes.data
          };
        }
      }
    } catch {}

    // 2. Direct fetch fallback
    for (const url of SERVER_URLS) {
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

  let isEnforcementActive = true;
  let isUserEnrolled = false;
  let isGuestUser = false;
  let isEnrolledUserWatching = true;

  function isGoalPaused() {
    return Date.now() < goalPausedUntil;
  }

  // Check goal pause status & face-gated user presence from FocusGuard
  async function syncGoalStatus() {
    try {
      // 1. Sync presence and enforcement status
      const statusRes = await fetchFromAnyServer("/api/status");
      if (statusRes && statusRes.ok) {
        const data = await statusRes.json();
        if (data.focus?.goalPausedUntil) {
          const until = new Date(data.focus.goalPausedUntil).getTime();
          if (until > Date.now()) {
            goalPausedUntil = until;
            dismissAllDomHud();
          } else {
            goalPausedUntil = 0;
          }
        }

        if (data.presence) {
          isUserEnrolled = !!data.presence.is_enrolled;
          isGuestUser = !!data.presence.is_guest;
          isEnrolledUserWatching = data.presence.user_present !== false;
          if (data.presence.enforcement_active !== undefined) {
            isEnforcementActive = !!data.presence.enforcement_active;
          } else if (isUserEnrolled) {
            isEnforcementActive = isEnrolledUserWatching && !isGuestUser;
          } else {
            isEnforcementActive = true;
          }
        }
      }

      // 2. Sync quick goal status
      const res = await fetchFromAnyServer("/api/goal/status");
      if (res && res.ok) {
        const data = await res.json();
        if (data.is_paused) {
          goalPausedUntil = Date.now() + (data.remaining_seconds * 1000);
          dismissAllDomHud();
        }
      }
    } catch {
      // Server offline, use local in-memory state
    }
  }

  setInterval(syncGoalStatus, 2000);
  syncGoalStatus();

  function isDistractionSite(href, title) {
    const url = (href || window.location.href || "").toLowerCase();
    const host = (window.location.hostname || "").toLowerCase();
    const t = (title || document.title || "").toLowerCase();

    // 1. YouTube Shorts is strictly non-productive distraction
    if (url.includes("/shorts") || window.location.pathname.includes("/shorts")) {
      return true;
    }

    // 2. High-distraction social & entertainment domains
    const defaultDistractions = [
      "instagram.com", "snapchat.com", "tiktok.com", "reddit.com",
      "twitter.com", "x.com", "facebook.com", "netflix.com",
      "twitch.tv", "pinterest.com", "discord.com"
    ];
    if (defaultDistractions.some(d => host.includes(d))) {
      return true;
    }

    // 3. Regular YouTube watch pages
    if (host.includes("youtube.com")) {
      // Educational DSA / programming / tutorial / lecture content is ALLOWED
      const dsaTerms = [
        "dsa", "data structure", "algorithm", "leetcode", "striver",
        "tree", "graph", "dp", "binary search", "sorting", "recursion",
        "lecture", "course", "tutorial", "learn", "study", "code",
        "programming", "cpp", "c++", "python", "java", "javascript", "react", "math"
      ];
      if (dsaTerms.some(term => t.includes(term))) {
        return false;
      }
      // Study music / background audio is ALLOWED
      if (t.includes("lofi") || t.includes("study beats") || t.includes("chillhop") || t.includes("ambient study")) {
        return false;
      }
      // Entertainment videos on YouTube are treated as distraction
      return true;
    }

    return false;
  }

  // Evaluate current video / page relevance against focus goal
  async function evaluatePage() {
    const currentHref = window.location.href;
    const currentTitle = document.title;

    if (currentHref.includes("/shorts") || window.location.pathname.includes("/shorts")) {
      isPageProductive = false;
      return;
    }

    if (currentHref === lastCheckedHref) return;
    lastCheckedHref = currentHref;

    try {
      const res = await fetchFromAnyServer("/api/goal/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          app: "chrome.exe",
          title: currentTitle,
          url: currentHref
        })
      });
      if (res && res.ok) {
        const data = await res.json();
        isPageProductive = (data.classification === "PRODUCTIVE" || data.relevant === true);
        if (isPageProductive) {
          dismissAllDomHud();
          streakSeconds = 0;
        }
      }
    } catch {
      // Offline fallback: check DSA keywords in title
      const titleLower = (currentTitle || "").toLowerCase();
      const dsaTerms = ["dsa", "data structure", "algorithm", "leetcode", "striver", "tree", "graph", "dp", "binary search", "sorting", "recursion", "array", "code", "lecture", "tutorial"];
      isPageProductive = dsaTerms.some(t => titleLower.includes(t));
    }
  }

  // 1. Video Playback Stopper
  function stopVideos() {
    document.querySelectorAll("video, audio").forEach(media => {
      try { media.pause(); } catch (e) {}
    });
  }

  // 2. Page Scroll Locker
  function lockScroll() {
    document.documentElement.style.setProperty("overflow", "hidden", "important");
    document.body.style.setProperty("overflow", "hidden", "important");
    window.addEventListener("wheel", blockEvent, { passive: false });
    window.addEventListener("touchmove", blockEvent, { passive: false });
    window.addEventListener("keydown", blockScrollKeys, { passive: false });
  }

  function unlockScroll() {
    document.documentElement.style.removeProperty("overflow");
    document.body.style.removeProperty("overflow");
    window.removeEventListener("wheel", blockEvent);
    window.removeEventListener("touchmove", blockEvent);
    window.removeEventListener("keydown", blockScrollKeys);
  }

  function blockEvent(e) {
    e.preventDefault();
    e.stopPropagation();
    return false;
  }

  function blockScrollKeys(e) {
    if (["Space", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End"].includes(e.code)) {
      if (e.target && e.target.id !== "fg-pin-input") {
        e.preventDefault();
        e.stopPropagation();
        return false;
      }
    }
  }

  // 3. Heads-Up / Warning DOM Banner (4s and 7s)
  function showDomBanner(level, title, message) {
    let banner = document.getElementById("focusguard-dom-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "focusguard-dom-banner";
      banner.style.cssText = `
        position: fixed;
        top: 20px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 2147483640;
        max-width: 600px;
        width: 90%;
        padding: 14px 20px;
        border-radius: 16px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        box-shadow: 0 20px 40px rgba(0,0,0,0.6);
        backdrop-filter: blur(16px);
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        transition: all 0.3s ease;
      `;
      document.body.appendChild(banner);
    }

    const isWarn = (level === 2);
    banner.style.background = isWarn ? "rgba(45, 20, 10, 0.92)" : "rgba(10, 20, 35, 0.92)";
    banner.style.border = isWarn ? "2px solid #f59e0b" : "2px solid #38bdf8";
    banner.style.color = isWarn ? "#fef3c7" : "#e0f2fe";

    banner.innerHTML = `
      <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-size:22px;">${isWarn ? '⚠️' : '💡'}</span>
        <div>
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:${isWarn ? '#f59e0b' : '#38bdf8'};">
            ${title}
          </div>
          <div style="font-size:13px; font-weight:600; margin-top:2px;">
            ${message}
          </div>
        </div>
      </div>
      <div style="display:flex; align-items:center; gap:8px; flex-shrink:0;">
        <button id="fg-banner-pause-btn" style="
          background: rgba(245, 158, 11, 0.2);
          border: 1px solid rgba(245, 158, 11, 0.5);
          color: #fbbf24;
          font-weight: 700;
          font-size: 12px;
          padding: 8px 12px;
          border-radius: 10px;
          cursor: pointer;
          transition: background 0.2s;
        ">⏸️ Pause Goal (5m)</button>
        <button id="fg-banner-close-btn" style="
          background: transparent;
          border: none;
          color: #94a3b8;
          font-size: 16px;
          cursor: pointer;
          padding: 4px;
        ">✕</button>
      </div>
    `;

    document.getElementById("fg-banner-pause-btn")?.addEventListener("click", () => pauseGoal(5));
    document.getElementById("fg-banner-close-btn")?.addEventListener("click", () => dismissAllDomHud());
  }

  // 4. Blocked DOM Overlay (10s)
  let domLockoutInterval = null;

  async function showDomBlockedOverlay() {
    if (document.getElementById("focusguard-dom-blocked-overlay")) return;

    // Stop video and lock scroll
    stopVideos();
    lockScroll();
    isOverlayActive = true;

    // Remove heads up banner
    document.getElementById("focusguard-dom-banner")?.remove();

    // Default random lockout between 2400s and 3600s (~40m to 60m)
    let lockoutRemainingSeconds = Math.floor(Math.random() * (3600 - 2400 + 1)) + 2400;

    const overlay = document.createElement("div");
    overlay.id = "focusguard-dom-blocked-overlay";
    overlay.style.cssText = `
      position: fixed;
      inset: 0;
      z-index: 2147483647;
      background: rgba(8, 14, 26, 0.92);
      backdrop-filter: blur(28px) saturate(160%);
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #f8fafc;
      padding: 20px;
      user-select: none;
    `;

    overlay.innerHTML = `
      <div style="
        background: #0f172a;
        border: 2px solid rgba(244, 63, 94, 0.5);
        border-radius: 24px;
        max-width: 520px;
        width: 100%;
        padding: 32px 28px;
        text-align: center;
        box-shadow: 0 25px 60px rgba(0,0,0,0.85), 0 0 40px rgba(244,63,94,0.3);
      ">
        <div style="
          width: 60px;
          height: 60px;
          margin: 0 auto 14px;
          border-radius: 20px;
          background: rgba(244, 63, 94, 0.15);
          border: 1px solid rgba(244, 63, 94, 0.4);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 28px;
        ">🛑</div>

        <div style="font-size: 11px; font-weight: 800; color: #f43f5e; text-transform: uppercase; letter-spacing: 2px;">
          FocusGuard Lockdown
        </div>
        <h2 style="font-size: 22px; font-weight: 800; margin: 6px 0 8px; color: #ffffff;">
          Window & Tab Disabled
        </h2>

        <!-- Random Tab Lockout Timer Badge -->
        <div id="fg-tab-lockout-badge" style="
          display: inline-flex;
          align-items: center;
          gap: 6px;
          background: rgba(244, 63, 94, 0.15);
          border: 1px solid rgba(244, 63, 94, 0.4);
          color: #fda4af;
          border-radius: 999px;
          padding: 6px 14px;
          font-size: 12px;
          font-weight: 700;
          font-family: monospace;
          margin-bottom: 16px;
        ">
          <span>🔒 Tab Disabled:</span>
          <span id="fg-lockout-timer-text">${Math.floor(lockoutRemainingSeconds / 60)}m ${lockoutRemainingSeconds % 60}s (${lockoutRemainingSeconds}s)</span>
        </div>

        <!-- Groq AI Explanation Box -->
        <div id="fg-groq-explanation-box" style="
          background: rgba(30, 41, 59, 0.7);
          border: 1px solid rgba(59, 130, 246, 0.35);
          border-radius: 14px;
          padding: 14px 16px;
          text-align: left;
          margin-bottom: 20px;
          font-size: 13px;
          line-height: 1.5;
        ">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
            <span style="font-size: 10px; font-weight: 800; color: #60a5fa; text-transform: uppercase; letter-spacing: 1px; display: flex; align-items: center; gap: 4px;">
              ⚡ Groq Intelligence Analysis
            </span>
            <span style="font-size: 10px; color: #94a3b8;">compound-mini</span>
          </div>
          <div id="fg-groq-reason-text" style="color: #e2e8f0; font-style: italic;">
            Connecting to Groq AI to analyze focus conflict...
          </div>
        </div>

        <!-- Action Buttons -->
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <button id="fg-close-tab-btn" style="
            background: #f43f5e;
            border: none;
            color: #ffffff;
            font-size: 14px;
            font-weight: 700;
            padding: 11px 18px;
            border-radius: 12px;
            cursor: pointer;
            transition: opacity 0.2s;
          ">✕ Close Tab & Return to Work</button>

          <button id="fg-clear-every-action-btn" style="
            background: rgba(239, 68, 68, 0.16);
            border: 1px solid rgba(239, 68, 68, 0.45);
            color: #fca5a5;
            font-size: 13px;
            font-weight: 700;
            padding: 10px 18px;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.2s;
          ">🧹 Clear Every Action (Reset All)</button>

          <button id="fg-dom-pause-btn" style="
            background: rgba(245, 158, 11, 0.15);
            border: 1px solid rgba(245, 158, 11, 0.4);
            color: #fbbf24;
            font-size: 13px;
            font-weight: 700;
            padding: 10px 18px;
            border-radius: 12px;
            cursor: pointer;
          ">⏸️ Pause Goal (5m Break)</button>

          <!-- PIN Fallback -->
          <div style="display: flex; gap: 8px; justify-content: center; margin-top: 4px;">
            <input id="fg-pin-input" type="password" maxlength="8" placeholder="PIN (Default: 1234)" style="
              width: 140px;
              padding: 9px 12px;
              border-radius: 10px;
              background: #1e293b;
              border: 1px solid #334155;
              color: #f8fafc;
              font-family: monospace;
              text-align: center;
              font-size: 13px;
              outline: none;
            ">
            <button id="fg-pin-unlock-btn" style="
              background: #0284c7;
              border: none;
              color: #ffffff;
              font-weight: 700;
              font-size: 12px;
              padding: 9px 16px;
              border-radius: 10px;
              cursor: pointer;
            ">🔓 Unlock PIN</button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // Fetch Groq explanation and random cooldown from backend
    (async () => {
      try {
        const isShorts = window.location.href.includes("/shorts");
        const appLabel = isShorts ? "YouTube Shorts" : "YouTube";
        const res = await fetchFromAnyServer("/api/block/explain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            app: appLabel,
            title: document.title,
            url: window.location.href
          })
        });
        if (res && res.ok) {
          const data = await res.json();
          const reasonEl = document.getElementById("fg-groq-reason-text");
          if (reasonEl && data.groq_explanation) {
            reasonEl.textContent = `"${data.groq_explanation}"`;
            reasonEl.style.fontStyle = "normal";
          }
          if (data.cooldown_seconds) {
            lockoutRemainingSeconds = data.cooldown_seconds;
          }
        }
      } catch (err) {
        console.warn("Could not fetch Groq block explanation:", err);
      }
    })();

    // Start live countdown ticker
    if (domLockoutInterval) clearInterval(domLockoutInterval);
    domLockoutInterval = setInterval(() => {
      lockoutRemainingSeconds--;
      const timerEl = document.getElementById("fg-lockout-timer-text");
      if (timerEl) {
        const m = Math.floor(lockoutRemainingSeconds / 60);
        const s = lockoutRemainingSeconds % 60;
        timerEl.textContent = `${m}m ${s}s (${lockoutRemainingSeconds}s)`;
      }

      // Keep videos paused and scroll locked while tab is disabled
      stopVideos();

      if (lockoutRemainingSeconds <= 0) {
        clearInterval(domLockoutInterval);
        dismissAllDomHud();
      }
    }, 1000);

    document.getElementById("fg-close-tab-btn")?.addEventListener("click", () => {
      try {
        window.close();
      } catch (e) {}
      // If window.close() blocked by browser security, redirect to blank
      window.location.href = "about:blank";
    });

    document.getElementById("fg-clear-every-action-btn")?.addEventListener("click", () => {
      clearEveryAction(true);
    });

    document.getElementById("fg-dom-pause-btn")?.addEventListener("click", () => {
      if (domLockoutInterval) clearInterval(domLockoutInterval);
      pauseGoal(5);
    });

    document.getElementById("fg-pin-unlock-btn")?.addEventListener("click", () => {
      if (domLockoutInterval) clearInterval(domLockoutInterval);
      verifyPinUnlock();
    });
  }

  function showToast(message) {
    let toast = document.getElementById("fg-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "fg-toast";
      toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 2147483647;
        background: #0f172a;
        color: #f8fafc;
        border: 1px solid #38bdf8;
        padding: 10px 20px;
        border-radius: 12px;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: 13px;
        font-weight: 600;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        transition: opacity 0.3s ease;
      `;
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.opacity = "1";
    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 300);
    }, 2500);
  }

  // 5. Pause Goal Handler
  async function pauseGoal(minutes = 5) {
    goalPausedUntil = Date.now() + (minutes * 60 * 1000);
    dismissAllDomHud();

    await fetchFromAnyServer("/api/goal/pause", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes: minutes })
    });

    showToast(`⏸️ Goal paused for ${minutes}m. Distraction warnings suspended.`);
  }

  // 6. PIN Unlock Handler
  async function verifyPinUnlock() {
    const pinInput = document.getElementById("fg-pin-input");
    const pin = pinInput ? pinInput.value.trim() : "";
    let valid = false;

    const res = await fetchFromAnyServer("/api/face/pin/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin: pin })
    });
    if (res && res.ok) {
      try {
        const data = await res.json();
        if (data.valid) valid = true;
      } catch {}
    } else {
      if (pin === "1234") valid = true;
    }

    if (valid) {
      dismissAllDomHud();
      goalPausedUntil = Date.now() + (5 * 60 * 1000);
      showToast("🔓 Unlocked with PIN! Distraction restriction cleared.");
    } else {
      showToast("❌ Incorrect PIN. Default is 1234.");
    }
  }

  function dismissAllDomHud() {
    document.getElementById("focusguard-dom-banner")?.remove();
    document.getElementById("focusguard-dom-blocked-overlay")?.remove();
    unlockScroll();
    isOverlayActive = false;
    streakSeconds = 0;
  }

  // 6.5. Clear Every Action & Remove All Restraints
  function clearEveryAction(notifyBackend = true) {
    if (domLockoutInterval) {
      clearInterval(domLockoutInterval);
      domLockoutInterval = null;
    }

    // Remove all DOM elements inserted by FocusGuard
    document.getElementById("focusguard-dom-banner")?.remove();
    document.getElementById("focusguard-dom-blocked-overlay")?.remove();
    document.getElementById("fg-toast")?.remove();

    // Re-enable window scrolling and events
    unlockScroll();

    // Reset tracking counters and flags
    isOverlayActive = false;
    streakSeconds = 0;
    goalPausedUntil = 0;
    lastCheckedHref = "";

    // 30s temporary grace immunity on current page
    isPageProductive = true;
    setTimeout(() => {
      isPageProductive = false;
    }, 30000);

    // Notify backend servers to clear cooldowns and resume goal
    if (notifyBackend) {
      fetchFromAnyServer("/api/cooldown/clear", { method: "POST" }).catch(() => {});
      fetchFromAnyServer("/api/goal/resume", { method: "POST" }).catch(() => {});
      try {
        chrome.runtime.sendMessage({ action: "CLEAR_EVERY_ACTION" }, () => {
          if (chrome.runtime.lastError) {}
        });
      } catch (e) {}
    }

    showToast("🧹 All FocusGuard actions & lockouts cleared!");
  }

  // 7. Active Tab Tick Loop
  setInterval(() => {
    // Only track when user is actively looking at this tab
    if (document.hidden || isGoalPaused()) {
      return;
    }

    const currentHref = window.location.href;
    const currentTitle = document.title;
    const isDistraction = isDistractionSite(currentHref, currentTitle);

    // ============================================================
    // FACE-GATED RESTRICTIONS (GUEST vs ENROLLED USER)
    // ============================================================
    // If Face ID is enrolled, FocusGuard applies restrictions ONLY when
    // the enrolled user is verified watching the screen.
    // If someone else (Guest / non-enrolled person) is using the laptop,
    // or if the enrolled user is not watching:
    // ALL RESTRICTIONS ARE BYPASSED! Instagram, YouTube, etc. work flawlessly without warnings.
    if (isUserEnrolled && (!isEnforcementActive || isGuestUser || !isEnrolledUserWatching)) {
      if (streakSeconds > 0) {
        streakSeconds = 0;
        dismissAllDomHud();
      }
      return;
    }

    // If page is not a distraction or recognized as productive for active goal, reset streak
    if (!isDistraction || isPageProductive) {
      if (streakSeconds > 0) {
        streakSeconds = 0;
        dismissAllDomHud();
      }
      return;
    }

    if (isOverlayActive) {
      stopVideos();
      return;
    }

    streakSeconds += 1;
    console.log(`[FocusGuard Shield] Distraction detected on ${window.location.hostname}: ${streakSeconds}s / 10s`);

    // 4s Heads-Up HUD
    if (streakSeconds >= 4 && streakSeconds < 7) {
      showDomBanner(1, "FocusGuard Heads-Up (4s)", "You have drifted from your goal. Wrap up shortly.");
    }

    // 7s Warning HUD
    if (streakSeconds >= 7 && streakSeconds < 10) {
      const rem = 10 - streakSeconds;
      showDomBanner(2, "FocusGuard Warning (7s)", `⚠️ ${rem}s remaining before distraction lockout. Refocus now!`);
      // Light alert sound
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) {
          const ctx = new AudioContext();
          if (ctx.state === "suspended") ctx.resume();
          const osc = ctx.createOscillator();
          osc.type = "sine";
          osc.frequency.setValueAtTime(700, ctx.currentTime);
          osc.connect(ctx.destination);
          osc.start();
          osc.stop(ctx.currentTime + 0.15);
        }
      } catch {}
    }

    // 10s Blocked Overlay
    if (streakSeconds >= 10) {
      showDomBlockedOverlay();
    }
  }, 1000);

  // Immediate re-evaluation on tab switch & in-page navigation
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      // Tab became active! Force re-evaluation of this tab immediately
      lastCheckedHref = "";
      evaluatePage();
    }
  });

  window.addEventListener("yt-navigate-finish", () => {
    lastCheckedHref = "";
    evaluatePage();
  });

  window.addEventListener("popstate", () => {
    lastCheckedHref = "";
    evaluatePage();
  });

  // Listen for broadcasted CLEAR_EVERY_ACTION across tabs
  try {
    chrome.runtime?.onMessage?.addListener((msg, sender, sendResponse) => {
      if (msg && (msg.action === "CLEAR_EVERY_ACTION" || msg.type === "CLEAR_EVERY_ACTION")) {
        clearEveryAction(false);
        sendResponse({ success: true });
      }
    });
  } catch (e) {}

  // Global hotkey: Alt + Shift + C or Alt + Shift + X clears every action immediately
  window.addEventListener("keydown", (e) => {
    if (e.altKey && e.shiftKey && (e.code === "KeyC" || e.code === "KeyX")) {
      e.preventDefault();
      clearEveryAction(true);
    }
  });
})();
