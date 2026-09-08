#include "../include/policy.h"

#include <iostream>

using namespace std;

void PolicyManager::addPolicy(
    const string &application,
    RestrictionMode mode,
    int maxDurationSeconds,
    int cooldownSeconds)
{
    AppPolicy policy;

    policy.application = application;
    policy.mode = mode;
    policy.maxDurationSeconds = maxDurationSeconds;
    policy.cooldownSeconds = cooldownSeconds;

    policies[application] = policy;
}

bool PolicyManager::hasPolicy(
    const string &application) const
{
    return policies.find(application) != policies.end();
}

AppPolicy PolicyManager::getPolicy(
    const string &application) const
{
    auto it = policies.find(application);

    if (it != policies.end())
    {
        return it->second;
    }

    return AppPolicy{
        application,
        RestrictionMode::ALLOW,
        0,
        0};
}

bool PolicyManager::shouldRestrict(
    const string &application,
    const string &classification) const
{
    auto it = policies.find(application);

    if (it == policies.end())
    {
        return false;
    }

    const AppPolicy &policy = it->second;

    // Complete application freeze
    if (policy.mode == RestrictionMode::BLOCK)
    {
        return true;
    }

    // Only restrict content classified as distraction
    if (policy.mode == RestrictionMode::CONTENT_AWARE)
    {
        return classification == "DISTRACTION";
    }

    // Explicitly allowed
    return false;
}

void PolicyManager::displayPolicies() const
{
    cout << endl;
    cout << "========== FOCUS GUARD POLICIES =========="
         << endl;

    for (const auto &entry : policies)
    {
        const AppPolicy &policy = entry.second;

        cout << "Application: "
             << policy.application
             << endl;

        cout << "Mode: ";

        switch (policy.mode)
        {
        case RestrictionMode::ALLOW:
            cout << "ALLOW";
            break;

        case RestrictionMode::BLOCK:
            cout << "BLOCK";
            break;

        case RestrictionMode::CONTENT_AWARE:
            cout << "CONTENT AWARE";
            break;
        }

        cout << endl;

        cout << "Maximum Duration: "
             << policy.maxDurationSeconds
             << " seconds"
             << endl;

        cout << "Cooldown: "
             << policy.cooldownSeconds
             << " seconds"
             << endl;

        cout << "------------------------------------------"
             << endl;
    }

    cout << "=========================================="
         << endl;
}