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

    bool enforce(
        HWND targetWindow,
        const std::string &logicalApp,
        const std::string &reason,
        int cooldownSeconds);

    bool isRestrictionActive() const;

    void clearRestriction();
};

#endif