#include "../include/enforcement.h"

#include <iostream>
#include <windows.h>
#include <thread>

using namespace std;

// ============================================================
// CONSTRUCTOR
// ============================================================

// ============================================================
// CONSTRUCTOR
// ============================================================

static bool g_sessionPaused = false;

EnforcementManager::EnforcementManager()
{
    restrictionActive = false;
    g_sessionPaused = false;
}

// ============================================================
// ASYNCHRONOUS USER ALERT
// ============================================================

static void showNotificationAsync(const string &title, const string &message)
{
    // Detached thread ensures the main monitoring loop NEVER freezes
    thread([title, message]() {
        MessageBoxA(
            NULL,
            message.c_str(),
            title.c_str(),
            MB_OK | MB_ICONWARNING | MB_TOPMOST | MB_SETFOREGROUND);
    }).detach();
}

// ============================================================
// CLOSE BROWSER TAB (OPTIONAL FOR BROWSERS)
// ============================================================

static void closeCurrentBrowserTab(HWND targetWindow)
{
    if (targetWindow == NULL)
        return;

    ShowWindow(targetWindow, SW_RESTORE);
    SetForegroundWindow(targetWindow);
    Sleep(150);

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

    SendInput(4, inputs, sizeof(INPUT));
}

// ============================================================
// ENFORCE RESTRICTION
// ============================================================

bool EnforcementManager::enforce(
    HWND targetWindow,
    const string &logicalApp,
    const string &reason,
    int cooldownSeconds,
    bool isBrowser)
{
    if (g_sessionPaused)
    {
        return false; // Enforcement suspended while session is locked
    }

    cout << endl;
    cout << "============================================" << endl;
    cout << "       FOCUS GUARD ENFORCEMENT" << endl;
    cout << "============================================" << endl;
    cout << "Restricted App : " << logicalApp << endl;
    cout << "Reason         : " << reason << endl;
    cout << "Cooldown       : " << cooldownSeconds << " seconds" << endl;

    string message =
        "Focus Guard has restricted " + logicalApp + ".\n\n" +
        reason + "\n\n" +
        "Remaining cooldown: " + to_string(cooldownSeconds) + " seconds.\n" +
        "Time to refocus on your goals!";

    // 1. Alert user asynchronously
    showNotificationAsync("Focus Guard - Refocus Notice", message);

    // 2. Minimize window immediately to break distraction loop
    if (targetWindow != NULL)
    {
        if (isBrowser)
        {
            closeCurrentBrowserTab(targetWindow);
        }
        ShowWindow(targetWindow, SW_MINIMIZE);
    }

    restrictionActive = true;
    cout << ">>> Enforcement completed (non-blocking)." << endl;
    cout << "============================================" << endl;

    return true;
}

bool EnforcementManager::isRestrictionActive() const
{
    return restrictionActive;
}

void EnforcementManager::clearRestriction()
{
    restrictionActive = false;
}

void EnforcementManager::pauseEnforcement()
{
    g_sessionPaused = true;
    cout << "[Enforcement] Paused (session locked)." << endl;
}

void EnforcementManager::resumeEnforcement()
{
    g_sessionPaused = false;
    cout << "[Enforcement] Resumed (session unlocked)." << endl;
}

bool EnforcementManager::isEnforcementPaused() const
{
    return g_sessionPaused;
}