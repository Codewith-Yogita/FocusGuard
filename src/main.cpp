#include "../include/policy.h"

#include <iostream>

using namespace std;

int main()
{
    cout << "========================================"
         << endl;

    cout << "        FOCUS GUARD"
         << endl;

    cout << "========================================"
         << endl;

    cout << endl;

    // ========================================================
    // USER POLICY
    // ========================================================

    PolicyManager policyManager;

    // Instagram -> completely blocked
    policyManager.addPolicy(
        "Instagram",
        RestrictionMode::BLOCK,
        60,
        3600);

    // Snapchat -> completely blocked
    policyManager.addPolicy(
        "Snapchat",
        RestrictionMode::BLOCK,
        60,
        3600);

    // YouTube -> content-aware
    // Shorts can be restricted while normal videos remain usable.
    policyManager.addPolicy(
        "YouTube",
        RestrictionMode::CONTENT_AWARE,
        60,
        3600);

    policyManager.displayPolicies();

    cout << endl;

    cout << "Focus Guard policy engine initialized."
         << endl;

    return 0;
}