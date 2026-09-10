#ifndef ENFORCEMENT_H
#define ENFORCEMENT_H

#include <windows.h>
#include <string>

class EnforcementManager
{
private:
    bool restrictionActive;

public:
    EnforcementManager();

    // Executes non-blocking enforcement (alerts user asynchronously, minimizes distracting window)
    bool enforce(
        HWND targetWindow,
        const std::string &logicalApp,
        const std::string &reason,
        int cooldownSeconds,
        bool isBrowser = false);

    bool isRestrictionActive() const;
    void clearRestriction();

    void pauseEnforcement();
    void resumeEnforcement();
    bool isEnforcementPaused() const;
};

#endif