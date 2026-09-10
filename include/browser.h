#ifndef BROWSER_H
#define BROWSER_H

#include <string>
#include <windows.h>

struct BrowserInfo
{
    bool isBrowser = false;

    bool isYouTube = false;
    bool isYouTubeShort = false;
    bool isYouTubeHistory = false;
    bool isYouTubeHome = false;

    bool isInstagram = false;
    bool isSnapchat = false;
    bool isFacebook = false;
    bool isWhatsApp = false;
    bool isLinkedIn = false;

    std::string browserName;
    std::string url;
    std::string pageTitle;
};

// Returns true if the process name corresponds to a supported browser (Edge, Chrome, Brave, etc.)
bool isSupportedBrowser(const std::string &appName);

// Detects URL and context from a browser window handle
BrowserInfo detectBrowserContext(HWND hwnd, const std::string &appName = "");

// Extracts active tab URL via UI Automation
std::string getBrowserUrl(HWND hwnd, const std::string &appName = "");

// YouTube URL helpers
bool isYouTubeUrl(const std::string &url);
bool isYouTubeShorts(const std::string &url);

#endif