#include "../include/restriction.h"

#include <algorithm>
#include <cctype>

using namespace std;
using namespace chrono;

static string normalize(string text)
{
    transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char c) { return static_cast<char>(tolower(c)); });
    return text;
}

// ============================================================
// START RESTRICTION
// ============================================================

void RestrictionManager::restrictApplication(
    const string &application,
    int cooldownSeconds,
    HWND windowHandle)
{
    Restriction restriction;
    restriction.restrictedUntil = steady_clock::now() + seconds(cooldownSeconds);
    restriction.windowHandle = windowHandle;

    restrictions[normalize(application)] = restriction;

    // Immediately minimize the distracting window if provided
    if (windowHandle != NULL)
    {
        ShowWindow(windowHandle, SW_MINIMIZE);
    }
}

// ============================================================
// CHECK RESTRICTION
// ============================================================

bool RestrictionManager::isRestricted(
    const string &application) const
{
    auto it = restrictions.find(normalize(application));
    if (it == restrictions.end())
    {
        return false;
    }

    if (steady_clock::now() >= it->second.restrictedUntil)
    {
        return false;
    }

    return true;
}

// ============================================================
// ENFORCE RESTRICTION
// ============================================================

void RestrictionManager::enforceRestriction(
    const string &application)
{
    auto it = restrictions.find(normalize(application));
    if (it == restrictions.end())
    {
        return;
    }

    if (steady_clock::now() >= it->second.restrictedUntil)
    {
        return;
    }

    HWND hwnd = it->second.windowHandle;
    if (hwnd == NULL)
    {
        return;
    }

    if (IsWindowVisible(hwnd))
    {
        if (GetForegroundWindow() == hwnd)
        {
            ShowWindow(hwnd, SW_MINIMIZE);
        }
    }
}

// ============================================================
// CLEAR RESTRICTION
// ============================================================

void RestrictionManager::clearRestriction(
    const string &application)
{
    restrictions.erase(normalize(application));
}

// ============================================================
// REMAINING TIME
// ============================================================

long long RestrictionManager::remainingSeconds(
    const string &application) const
{
    auto it = restrictions.find(normalize(application));
    if (it == restrictions.end())
    {
        return 0;
    }

    auto now = steady_clock::now();
    if (now >= it->second.restrictedUntil)
    {
        return 0;
    }

    return duration_cast<seconds>(it->second.restrictedUntil - now).count();
}