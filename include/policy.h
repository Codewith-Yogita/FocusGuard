#ifndef POLICY_H
#define POLICY_H

#include <string>
#include <unordered_map>

enum class RestrictionMode
{
    ALLOW,
    BLOCK,
    CONTENT_AWARE
};

struct AppPolicy
{
    std::string application;

    RestrictionMode mode;

    int maxDurationSeconds;

    int cooldownSeconds;
};

class PolicyManager
{
private:
    std::unordered_map<std::string, AppPolicy> policies;

public:
    void addPolicy(
        const std::string &application,
        RestrictionMode mode,
        int maxDurationSeconds,
        int cooldownSeconds);

    bool hasPolicy(
        const std::string &application) const;

    AppPolicy getPolicy(
        const std::string &application) const;

    bool shouldRestrict(
        const std::string &application,
        const std::string &classification) const;

    void displayPolicies() const;
};

#endif