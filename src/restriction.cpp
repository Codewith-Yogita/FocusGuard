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
    int cooldownSeconds)
{
    restrictedUntil[normalize(application)] =
        steady_clock::now() + seconds(cooldownSeconds);
}

// ============================================================
// CHECK RESTRICTION
// ============================================================

bool RestrictionManager::isRestricted(
    const string &application) const
{
    auto it = restrictedUntil.find(normalize(application));
    if (it == restrictedUntil.end())
    {
        return false;
    }

    if (steady_clock::now() >= it->second)
    {
        return false;
    }

    return true;
}

// ============================================================
// CLEAR RESTRICTION
// ============================================================

void RestrictionManager::clearRestriction(
    const string &application)
{
    restrictedUntil.erase(normalize(application));
}

// ============================================================
// REMAINING TIME
// ============================================================

long long RestrictionManager::remainingSeconds(
    const string &application) const
{
    auto it = restrictedUntil.find(normalize(application));
    if (it == restrictedUntil.end())
    {
        return 0;
    }

    auto now = steady_clock::now();
    if (now >= it->second)
    {
        return 0;
    }

    return duration_cast<seconds>(it->second - now).count();
}