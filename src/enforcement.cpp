#include "../include/enforcement.h"

#include <iostream>
#include <windows.h>

using namespace std;

// ============================================================
// CONSTRUCTOR
// ============================================================

EnforcementManager::EnforcementManager()
{
    restrictionActive = false;
}

// ============================================================
// CLOSE CURRENT BROWSER TAB
// ============================================================

static void closeCurrentBrowserTab(HWND targetWindow)
{
    if (targetWindow == NULL)
        return;

    // --------------------------------------------------------
    // Bring browser window to foreground
    // --------------------------------------------------------

    ShowWindow(
        targetWindow,
        SW_RESTORE);

    SetForegroundWindow(
        targetWindow);

    Sleep(300);

    // --------------------------------------------------------
    // Send CTRL + W
    //
    // This closes the CURRENT browser tab rather than
    // terminating the entire browser process.
    // --------------------------------------------------------

    INPUT inputs[4] = {};

    // CTRL down
    inputs[0].type = INPUT_KEYBOARD;
    inputs[0].ki.wVk = VK_CONTROL;

    // W down
    inputs[1].type = INPUT_KEYBOARD;
    inputs[1].ki.wVk = 'W';

    // W up
    inputs[2].type = INPUT_KEYBOARD;
    inputs[2].ki.wVk = 'W';
    inputs[2].ki.dwFlags = KEYEVENTF_KEYUP;

    // CTRL up
    inputs[3].type = INPUT_KEYBOARD;
    inputs[3].ki.wVk = VK_CONTROL;
    inputs[3].ki.dwFlags = KEYEVENTF_KEYUP;

    SendInput(
        4,
        inputs,
        sizeof(INPUT));

    Sleep(500);
}

// ============================================================
// ENFORCE RESTRICTION
// ============================================================

bool EnforcementManager::enforce(
    HWND targetWindow,
    const string &logicalApp,
    const string &reason,
    int cooldownSeconds)
{
    cout << endl;
    cout << "============================================"
         << endl;

    cout << "       FOCUS GUARD ENFORCEMENT"
         << endl;

    cout << "============================================"
         << endl;

    cout << "Restricted App : "
         << logicalApp
         << endl;

    cout << "Reason         : "
         << reason
         << endl;

    cout << "Cooldown       : "
         << cooldownSeconds
         << " seconds"
         << endl;

    cout << endl;

    // --------------------------------------------------------
    // Show user-facing warning
    // --------------------------------------------------------

    string message =
        "Focus Guard has restricted " +
        logicalApp +
        ".\n\n" +
        reason +
        "\n\n" +
        "This app will remain restricted during the cooldown.";

    MessageBoxA(
        targetWindow,
        message.c_str(),
        "Focus Guard - App Restricted",
        MB_OK |
            MB_ICONWARNING |
            MB_TOPMOST |
            MB_SETFOREGROUND);

    // --------------------------------------------------------
    // Close only current browser tab
    // --------------------------------------------------------

    closeCurrentBrowserTab(targetWindow);

    restrictionActive = true;

    cout << ">>> Enforcement completed."
         << endl;

    cout << ">>> Current browser tab closed."
         << endl;

    cout << "============================================"
         << endl;

    return true;
}

// ============================================================
// CHECK RESTRICTION STATE
// ============================================================

bool EnforcementManager::isRestrictionActive() const
{
    return restrictionActive;
}

// ============================================================
// CLEAR RESTRICTION
// ============================================================

void EnforcementManager::clearRestriction()
{
    restrictionActive = false;
}