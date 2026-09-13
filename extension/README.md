# FocusGuard Chrome / Edge Extension

In-Page DOM Distraction Shield for FocusGuard.

## Why DOM Elements?
1. **Never Blocks Browser Tabs**: The DOM overlay lives strictly inside the webpage viewport (`document.body`). The Chrome/Edge tab strip, address bar, and bookmarks remain **100% visible, clickable, and accessible**.
2. **Instant Tab Switching**: You can freely switch to any productive tab (GitHub, Docs, StackOverflow) without the overlay getting in the way.
3. **DOM-Level Video & Audio Control**: Automatically calls `.pause()` on all HTML5 video/audio elements and embedded iframes without touching system volume.
4. **Zero Page Scrolling**: Disables mouse wheel and page scroll on the distracting tab until unlocked or paused.

---

## How to Install in Chrome or Edge (30 Seconds)

1. Open **Google Chrome** (or Edge / Brave / Opera).
2. In the address bar, go to:
   ```
   chrome://extensions
   ```
   *(or `edge://extensions` on Microsoft Edge)*
3. In the top right corner, turn ON **"Developer mode"**.
4. Click the **"Load unpacked"** button in the top left.
5. Select the folder:
   ```
   c:\Users\Mehakpreet Singh\Documents\projects\focuaGAurd\extension
   ```
6. That's it! FocusGuard will now inject in-page DOM warning HUDs directly on YouTube, Reddit, Twitter, Netflix, etc.

---

## Features
- **4s**: Sleek in-page Heads-Up DOM banner at the top of the webpage.
- **7s**: Escalation warning with audio chime.
- **10s**: Frosted glass in-page DOM overlay with video pause and scroll lock.
- **Pause Goal (5m Break)**: Restores the tab for 5 minutes and syncs with the FocusGuard daemon (`http://localhost:8000`).
- **PIN Unlock**: Unlocks the tab instantly with PIN `1234`.
