#include "../include/ocr.h"
#include "../include/policy.h"
#include "../include/classifier.h"
#include "../include/restriction.h"
#include "../include/browser.h"

#include <fstream>
#include <iostream>
#include <string>
#include <unordered_map>
#include <chrono>
#include <algorithm>
#include <cctype>
#include <windows.h>
#include <psapi.h>

using namespace std;
using namespace chrono;

// ============================================================
// TEXT UTILITY
// ============================================================

string toLowerCase(string text)
{
    transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char c)
        {
            return static_cast<char>(tolower(c));
        });

    return text;
}

// ============================================================
// FOCUS GUARD SETTINGS
// ============================================================

const int WARNING_TIME = 10;
const int STRONG_WARNING_TIME = 30;
const int INTERVENTION_TIME = 60;
const int OCR_INTERVAL = 5;

// ============================================================
// GET ACTIVE WINDOW
// ============================================================

HWND getActiveWindowHandle()
{
    return GetForegroundWindow();
}

// ============================================================
// GET WINDOW TITLE
// ============================================================

string getWindowTitle(HWND hwnd)
{
    if (hwnd == NULL)
        return "Unknown";

    char title[512] = {};

    int length = GetWindowTextA(
        hwnd,
        title,
        sizeof(title));

    if (length == 0)
        return "Unknown";

    return string(title);
}

// ============================================================
// GET ACTIVE APPLICATION
// ============================================================

string getActiveApplication(HWND hwnd)
{
    if (hwnd == NULL)
        return "Unknown";

    DWORD processId = 0;

    GetWindowThreadProcessId(
        hwnd,
        &processId);

    if (processId == 0)
        return "Unknown";

    HANDLE process = OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
        FALSE,
        processId);

    if (process == NULL)
        return "Unknown";

    char processPath[MAX_PATH] = {};

    DWORD length = GetModuleFileNameExA(
        process,
        NULL,
        processPath,
        MAX_PATH);

    CloseHandle(process);

    if (length == 0)
        return "Unknown";

    string fullPath(processPath);

    size_t position =
        fullPath.find_last_of("\\/");

    if (position != string::npos)
    {
        return fullPath.substr(position + 1);
    }

    return fullPath;
}

// ============================================================
// CONVERT APPLICATION NAME
// ============================================================
//
// Windows gives us:
//     msedge.exe
//
// But policies are stored as:
//     YouTube
//     Instagram
//     Snapchat
//
// This function maps the active browser page to the logical
// application/content name used by Focus Guard.
// ============================================================

string getLogicalApplication(
    const string &application,
    const string &windowTitle)
{
    string app = application;
    string title = windowTitle;

    transform(
        app.begin(),
        app.end(),
        app.begin(),
        [](unsigned char c)
        {
            return static_cast<char>(tolower(c));
        });

    transform(
        title.begin(),
        title.end(),
        title.begin(),
        [](unsigned char c)
        {
            return static_cast<char>(tolower(c));
        });

    // --------------------------------------------------------
    // Browser based applications
    // --------------------------------------------------------

    if (app == "msedge.exe")
    {
        if (title.find("instagram") != string::npos)
            return "Instagram";

        if (title.find("snapchat") != string::npos)
            return "Snapchat";

        if (title.find("youtube") != string::npos)
            return "YouTube";

        if (title.find("facebook") != string::npos)
            return "Facebook";

        if (title.find("whatsapp") != string::npos)
            return "WhatsApp";

        if (title.find("linkedin") != string::npos)
            return "LinkedIn";
    }

    // --------------------------------------------------------
    // Native applications
    // --------------------------------------------------------

    if (app == "instagram.exe")
        return "Instagram";

    if (app == "snapchat.exe")
        return "Snapchat";

    if (app == "code.exe")
        return "VS Code";

    return application;
}

// ============================================================
// SHOW INTERVENTION POPUP
// ============================================================

void showInterventionPopup(
    HWND distractingWindow,
    const string &application,
    long long distractionSeconds)
{
    string message =
        "Focus Guard noticed that you have been using " +
        application +
        " for " +
        to_string(distractionSeconds) +
        " seconds.\n\n"
        "You chose to restrict this activity.\n"
        "Time to return to your goal.";

    if (distractingWindow != NULL)
    {
        ShowWindow(
            distractingWindow,
            SW_RESTORE);

        SetForegroundWindow(
            distractingWindow);
    }

    MessageBoxA(
        distractingWindow,
        message.c_str(),
        "Focus Guard - Time to Refocus",
        MB_OK |
            MB_ICONWARNING |
            MB_TOPMOST |
            MB_SETFOREGROUND);

    // --------------------------------------------------------
    // Minimize distracting window
    // --------------------------------------------------------

    if (distractingWindow != NULL)
    {
        ShowWindow(
            distractingWindow,
            SW_MINIMIZE);
    }
}

// ============================================================
// MAIN
// ============================================================

int main()
{
    cout << "========================================"
         << endl;

    cout << "        FOCUS GUARD MONITOR"
         << endl;

    cout << "========================================"
         << endl;

    cout << endl;

    // ========================================================
    // POLICY MANAGER
    // ========================================================

    PolicyManager policyManager;
    RestrictionManager restrictionManager;

    // --------------------------------------------------------
    // CURRENT DEMO USER POLICY
    // --------------------------------------------------------
    //
    // IMPORTANT:
    // These are temporary.
    //
    // Later these will come from the user's settings/UI.
    // --------------------------------------------------------

    // Instagram completely restricted
    policyManager.addPolicy(
        "Instagram",
        RestrictionMode::BLOCK,
        60,
        60);

    // Snapchat completely restricted
    policyManager.addPolicy(
        "Snapchat",
        RestrictionMode::BLOCK,
        60,
        60);

    // YouTube content-aware
    //
    // Normal videos are allowed.
    // Shorts are classified as distraction.
    policyManager.addPolicy(
        "YouTube",
        RestrictionMode::CONTENT_AWARE,
        60,
        60);

    policyManager.displayPolicies();

    cout << endl;

    // ========================================================
    // ACTIVITY STATE
    // ========================================================

    string previousActivity = "";
    string previousClassification = "";

    auto activityStartTime =
        steady_clock::now();

    // ========================================================
    // DISTRACTION SESSION
    // ========================================================

    bool distractionActive = false;

    steady_clock::time_point distractionStartTime;

    long long distractionStreak = 0;

    // ========================================================
    // WARNING STATE
    // ========================================================

    int lastWarningLevel = 0;

    // ========================================================
    // CUMULATIVE TIME
    // ========================================================

    unordered_map<string, long long> activityTime;

    unordered_map<string, long long> classificationTime;

    // ========================================================
    // LOOP
    // ========================================================

    int loopCount = 0;

    // ========================================================
    // OCR
    // ========================================================

    auto lastOCRTime = steady_clock::now();

    string ocrText = "";

    // ========================================================
    // MAIN MONITORING LOOP
    // ========================================================

    while (true)
    {
        // ====================================================
        // GET CURRENT WINDOW
        // ====================================================

        HWND hwnd =
            getActiveWindowHandle();

        string application =
            getActiveApplication(hwnd);

        string windowTitle =
            getWindowTitle(hwnd);

        // ====================================================
        // BROWSER CONTEXT
        // ====================================================

        BrowserInfo browserInfo;

        if (application == "msedge.exe")
        {
            browserInfo = detectBrowserContext(hwnd);
        }
        // ====================================================
        // GET LOGICAL APPLICATION
        // ====================================================

        string logicalApplication =
            getLogicalApplication(
                application,
                windowTitle);

        // ====================================================
        // OCR
        // ====================================================

        if (application == "msedge.exe")
        {
            string titleClassification =
                classifyContent(
                    application,
                    windowTitle,
                    "");

            if (titleClassification == "UNKNOWN")
            {
                auto now = steady_clock::now();

                long long secondsSinceOCR =
                    duration_cast<seconds>(
                        now - lastOCRTime)
                        .count();

                if (secondsSinceOCR >= OCR_INTERVAL)
                {
                    cout << endl;
                    cout << "[OCR] Scanning screen..."
                         << endl;

                    ocrText =
                        captureScreenOCR();

                    lastOCRTime = now;

                    if (!ocrText.empty())
                    {
                        cout << "[OCR] Screen content detected."
                             << endl;
                    }
                    else
                    {
                        cout << "[OCR] No text detected."
                             << endl;
                    }
                }
            }
            else
            {
                ocrText = "";
            }
        }
        else
        {
            ocrText = "";
        }

        // ====================================================
        // CLASSIFY CONTENT
        // ====================================================

        string classification;

        if (
            browserInfo.isYouTube &&
            browserInfo.isYouTubeShort)
        {
            // ====================================================
            // YOUTUBE SHORTS ALWAYS WIN
            // ====================================================
            //
            // Even if the Short contains:
            // DSA
            // C++
            // LeetCode
            // Programming
            // ISRO
            // Tutorial
            //
            // It is still a Short and therefore a distraction.
            // ====================================================

            classification = "DISTRACTION";
        }
        else if (
            browserInfo.isYouTube &&
            browserInfo.isYouTubeHistory)
        {
            // ====================================================
            // YOUTUBE HISTORY IS NOT CONTENT
            // ====================================================

            classification = "UNKNOWN";
        }
        else
        {
            classification =
                classifyContent(
                    application,
                    windowTitle,
                    ocrText);
        }

        // ============================================================
        // POLICY DECISION
        // ============================================================

        // Browser-specific mapping.
        // Later this will become site-aware.
        string policyApplication = logicalApplication;

        bool policyWantsRestriction =
            policyManager.shouldRestrict(
                policyApplication,
                classification);

        bool currentlyRestricted =
            restrictionManager.isRestricted(
                policyApplication);

        bool shouldRestrict =
            policyWantsRestriction ||
            currentlyRestricted;

        if (currentlyRestricted)
        {
            cout << endl;

            cout << "!!! APPLICATION CURRENTLY RESTRICTED !!!"
                 << endl;

            cout << "Application: "
                 << policyApplication
                 << endl;

            cout << "Remaining cooldown: "
                 << restrictionManager.remainingSeconds(
                        policyApplication)
                 << " seconds"
                 << endl;
        }
        // ====================================================
        // CREATE UNIQUE ACTIVITY
        // ====================================================

        string currentActivity =
            logicalApplication +
            " | " +
            windowTitle;

        // ====================================================
        // HANDLE ACTIVITY CHANGE
        // ====================================================

        if (currentActivity != previousActivity)
        {
            if (!previousActivity.empty())
            {
                auto now =
                    steady_clock::now();

                long long elapsed =
                    duration_cast<seconds>(
                        now - activityStartTime)
                        .count();

                activityTime[previousActivity] += elapsed;

                classificationTime[previousClassification] += elapsed;
            }

            previousActivity =
                currentActivity;

            previousClassification =
                classification;

            activityStartTime =
                steady_clock::now();
        }

        // ====================================================
        // CURRENT ACTIVITY TIME
        // ====================================================

        long long elapsedSeconds =
            duration_cast<seconds>(
                steady_clock::now() -
                activityStartTime)
                .count();

        // ====================================================
        // DETERMINE WHETHER POLICY APPLIES
        // ====================================================

        bool policyRestriction =
            policyManager.shouldRestrict(
                logicalApplication,
                classification);

        // ====================================================
        // DISTRACTION SESSION
        // ====================================================

        if (
            classification == "DISTRACTION" &&
            policyRestriction)
        {
            // ------------------------------------------------
            // START SESSION
            // ------------------------------------------------

            if (!distractionActive)
            {
                distractionActive = true;

                distractionStartTime =
                    steady_clock::now();

                distractionStreak = 0;

                lastWarningLevel = 0;

                cout << endl;

                cout << ">>> RESTRICTED DISTRACTION DETECTED"
                     << endl;

                cout << "Application: "
                     << logicalApplication
                     << endl;
            }

            // ------------------------------------------------
            // CALCULATE STREAK
            // ------------------------------------------------

            distractionStreak =
                duration_cast<seconds>(
                    steady_clock::now() -
                    distractionStartTime)
                    .count();

            // ------------------------------------------------
            // WARNING — 10 SECONDS
            // ------------------------------------------------

            if (
                distractionStreak >= WARNING_TIME &&
                lastWarningLevel < 1)
            {
                cout << endl;

                cout << "!!! FOCUS GUARD WARNING !!!"
                     << endl;

                cout << logicalApplication
                     << " has been distracting you for "
                     << distractionStreak
                     << " seconds."
                     << endl;

                lastWarningLevel = 1;
            }

            // ------------------------------------------------
            // STRONG WARNING — 30 SECONDS
            // ------------------------------------------------

            if (
                distractionStreak >= STRONG_WARNING_TIME &&
                lastWarningLevel < 2)
            {
                cout << endl;

                cout << "!!! FOCUS GUARD ALERT !!!"
                     << endl;

                cout << "You have been distracted for "
                     << distractionStreak
                     << " seconds."
                     << endl;

                cout << "Consider returning to your task."
                     << endl;

                lastWarningLevel = 2;
            }

            // ------------------------------------------------
            // INTERVENTION — 60 SECONDS
            // ------------------------------------------------

            if (
                distractionStreak >= INTERVENTION_TIME &&
                lastWarningLevel < 3)
            {
                cout << endl;

                cout << "================================"
                     << endl;

                cout << "    FOCUS GUARD INTERVENTION"
                     << endl;

                cout << "================================"
                     << endl;

                cout << "Restricted application: "
                     << logicalApplication
                     << endl;

                cout << "60+ seconds of distraction."
                     << endl;

                cout << "Launching refocus popup..."
                     << endl;

                lastWarningLevel = 3;

                // ------------------------------------------------
                // INTERVENTION
                // ------------------------------------------------

                showInterventionPopup(
                    hwnd,
                    logicalApplication,
                    distractionStreak);

                // ========================================================
                // START APPLICATION COOLDOWN
                // ========================================================

                if (policyManager.hasPolicy(policyApplication))
                {
                    AppPolicy policy =
                        policyManager.getPolicy(policyApplication);

                    restrictionManager.restrictApplication(
                        policyApplication,
                        policy.cooldownSeconds);

                    cout << endl;

                    cout << ">>> RESTRICTION ACTIVATED"
                         << endl;

                    cout << "Application: "
                         << policyApplication
                         << endl;

                    cout << "Cooldown: "
                         << policy.cooldownSeconds
                         << " seconds"
                         << endl;
                }

                // ------------------------------------------------
                // RESET
                // ------------------------------------------------

                distractionActive = false;

                distractionStreak = 0;

                lastWarningLevel = 0;
            }
        }
        else
        {
            // =================================================
            // USER LEFT RESTRICTED DISTRACTION
            // =================================================

            if (distractionActive)
            {
                cout << endl;

                cout << ">>> Distraction session ended."
                     << endl;
            }

            distractionActive = false;

            distractionStreak = 0;

            lastWarningLevel = 0;
        }

        // ====================================================
        // DISPLAY TOTALS
        // ====================================================

        long long productiveTime =
            classificationTime["PRODUCTIVE"];

        long long distractionTime =
            classificationTime["DISTRACTION"];

        long long neutralTime =
            classificationTime["NEUTRAL"];

        long long unknownTime =
            classificationTime["UNKNOWN"];

        // Current activity time
        if (classification == "PRODUCTIVE")
        {
            productiveTime += elapsedSeconds;
        }
        else if (classification == "DISTRACTION")
        {
            distractionTime += elapsedSeconds;
        }
        else if (classification == "NEUTRAL")
        {
            neutralTime += elapsedSeconds;
        }
        else
        {
            unknownTime += elapsedSeconds;
        }

        // ====================================================
        // DISPLAY
        // ====================================================

        cout << endl;

        cout << "Loop: "
             << ++loopCount
             << endl;

        cout << "Application: "
             << application
             << endl;

        cout << "Logical App: "
             << logicalApplication
             << endl;

        cout << "Window: "
             << windowTitle
             << endl;

        cout << "Classification: "
             << classification
             << endl;

        cout << "Policy Restriction: "
             << boolalpha
             << policyRestriction
             << endl;

        cout << "Time on current activity: "
             << elapsedSeconds
             << " seconds"
             << endl;

        if (classification == "DISTRACTION")
        {
            cout << "Distraction streak: "
                 << distractionStreak
                 << " seconds"
                 << endl;
        }

        cout << endl;

        cout << "========== TODAY'S TOTALS =========="
             << endl;

        cout << "Productive : "
             << productiveTime
             << " seconds"
             << endl;

        cout << "Distraction: "
             << distractionTime
             << " seconds"
             << endl;

        cout << "Neutral    : "
             << neutralTime
             << " seconds"
             << endl;

        cout << "Unknown    : "
             << unknownTime
             << " seconds"
             << endl;

        cout << "===================================="
             << endl;

        // ====================================================
        // WAIT
        // ====================================================

        Sleep(1000);
    }

    return 0;
}