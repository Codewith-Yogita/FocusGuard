#ifndef RESTRICTION_H
#define RESTRICTION_H

#include <string>
#include <unordered_map>
#include <chrono>

class RestrictionManager
{
private:

    // Stores the time until which an application remains restricted.
    std::unordered_map<
        std::string,
        std::chrono::steady_clock::time_point>
        restrictedUntil;

public:

    // Start a restriction.
    void restrictApplication(
        const std::string &application,
        int cooldownSeconds);

    // Check whether an application is currently restricted.
    bool isRestricted(
        const std::string &application) const;

    // Remove restriction manually.
    void clearRestriction(
        const std::string &application);

    // Get remaining restriction time.
    long long remainingSeconds(
        const std::string &application) const;
};

#endif