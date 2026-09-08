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

    std::string url;
    std::string pageTitle;
};

BrowserInfo detectBrowserContext(HWND hwnd);

std::string getBrowserUrl(HWND hwnd);

bool isYouTubeUrl(const std::string &url);

bool isYouTubeShorts(const std::string &url);

#endif