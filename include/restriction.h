#ifndef RESTRICTION_H
#define RESTRICTION_H

#include <string>
#include <unordered_map>
#include <chrono>
#include <windows.h>

class RestrictionManager
{
private:

    struct Restriction
    {
        std::chrono::steady_clock::time_point restrictedUntil;
        HWND windowHandle = NULL;
    };

    std::unordered_map<
        std::string,
        Restriction>
        restrictions;

public:

    // Start a restriction for an application/window.
    void restrictApplication(
        const std::string &application,
        int cooldownSeconds,
        HWND windowHandle);

    // Check whether an application is currently restricted.
    bool isRestricted(
        const std::string &application) const;

    // Enforce an active restriction.
    void enforceRestriction(
        const std::string &application);

    // Remove restriction manually.
    void clearRestriction(
        const std::string &application);

    // Get remaining restriction time.
    long long remainingSeconds(
        const std::string &application) const;
};

#endif