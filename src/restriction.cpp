#include "../include/restriction.h"

using namespace std;
using namespace chrono;


// ============================================================
// START RESTRICTION
// ============================================================

void RestrictionManager::restrictApplication(
    const string &application,
    int cooldownSeconds)
{
    restrictedUntil[application] =
        steady_clock::now() +
        seconds(cooldownSeconds);
}


// ============================================================
// CHECK RESTRICTION
// ============================================================

bool RestrictionManager::isRestricted(
    const string &application) const
{
    auto it =
        restrictedUntil.find(application);

    if (it == restrictedUntil.end())
    {
        return false;
    }

    // Restriction has expired.
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
    restrictedUntil.erase(application);
}


// ============================================================
// REMAINING TIME
// ============================================================

long long RestrictionManager::remainingSeconds(
    const string &application) const
{
    auto it =
        restrictedUntil.find(application);

    if (it == restrictedUntil.end())
    {
        return 0;
    }

    auto now =
        steady_clock::now();

    if (now >= it->second)
    {
        return 0;
    }

    return duration_cast<seconds>(
        it->second - now)
        .count();
}