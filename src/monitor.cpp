#include "../include/ocr.h"
#include "../include/user_identity.h"
#include "../include/policy.h"
#include "../include/classifier.h"
#include "../include/restriction.h"
#include "../include/browser.h"
#include "../include/enforcement.h"
#include "../include/ai_client.h"
#include "../include/face_auth.h"

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

enum class UserIdentity {
    USER,
    GUEST
};

// ============================================================
// TEXT UTILITY
// ============================================================

static string toLower(string text)
{
    transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char c) { return static_cast<char>(tolower(c)); });
    return text;
}

// ============================================================
// FOCUS GUARD SETTINGS
// ============================================================

const int WARNING_TIME = 10;
const int STRONG_WARNING_TIME = 30;
const int OCR_AI_INTERVAL = 5;

// ============================================================
// GET ACTIVE WINDOW
// ============================================================

HWND getActiveWindowHandle()
{
    return GetForegroundWindow();
}

// ============================================================
// GET WINDOW TITLE (UTF-8 SAFE)
// ============================================================

string getWindowTitle(HWND hwnd)
{
    if (hwnd == NULL)
        return "Desktop / No Focused Window";

    wchar_t wTitle[512] = {};
    int length = GetWindowTextW(hwnd, wTitle, sizeof(wTitle) / sizeof(wchar_t));
    if (length == 0)
    {
        char className[256] = {};
        if (GetClassNameA(hwnd, className, sizeof(className)) > 0)
        {
            string cls(className);
            if (cls == "Progman" || cls == "WorkerW")
                return "Windows Desktop";
            if (cls == "Shell_TrayWnd")
                return "Taskbar";
        }
        return "Active Window (No Title)";
    }

    int sizeNeeded = WideCharToMultiByte(CP_UTF8, 0, wTitle, length, nullptr, 0, nullptr, nullptr);
    if (sizeNeeded > 0)
    {
        string utf8Title(sizeNeeded, '\0');
        WideCharToMultiByte(CP_UTF8, 0, wTitle, length, &utf8Title[0], sizeNeeded, nullptr, nullptr);
        return utf8Title;
    }

    return "Active Window";
}

// ============================================================
// GET ACTIVE APPLICATION (MODERN WIN32 API + UWP SUPPORT)
// ============================================================

string getActiveApplication(HWND hwnd)
{
    if (hwnd == NULL)
        return "System / Idle";

    DWORD processId = 0;
    GetWindowThreadProcessId(hwnd, &processId);
    if (processId == 0)
        return "System / Idle";

    HANDLE process = OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        FALSE,
        processId);

    if (process == NULL)
    {
        char className[256] = {};
        if (GetClassNameA(hwnd, className, sizeof(className)) > 0)
        {
            string cls(className);
            if (cls == "Progman" || cls == "WorkerW" || cls == "Shell_TrayWnd")
                return "explorer.exe";
        }
        return "System Process";
    }

    char processPath[MAX_PATH] = {};
    DWORD size = MAX_PATH;

    BOOL success = QueryFullProcessImageNameA(
        process,
        0,
        processPath,
        &size);

    CloseHandle(process);

    if (!success || size == 0)
        return "System Process";

    string fullPath(processPath);
    size_t position = fullPath.find_last_of("\\/");
    string exeName = (position != string::npos) ? fullPath.substr(position + 1) : fullPath;

    // Unwrap UWP / Windows Store apps
    string lowerExe = toLower(exeName);
    if (lowerExe == "applicationframehost.exe")
    {
        HWND child = FindWindowExA(hwnd, NULL, "Windows.UI.Core.CoreWindow", NULL);
        if (child != NULL)
        {
            DWORD childPid = 0;
            GetWindowThreadProcessId(child, &childPid);
            if (childPid != 0 && childPid != processId)
            {
                HANDLE childProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, childPid);
                if (childProc != NULL)
                {
                    char childPath[MAX_PATH] = {};
                    DWORD childSize = MAX_PATH;
                    if (QueryFullProcessImageNameA(childProc, 0, childPath, &childSize) && childSize > 0)
                    {
                        string cPath(childPath);
                        size_t cPos = cPath.find_last_of("\\/");
                        exeName = (cPos != string::npos) ? cPath.substr(cPos + 1) : cPath;
                    }
                    CloseHandle(childProc);
                }
            }
        }
    }

    return exeName;
}

// ============================================================
// CONVERT APPLICATION NAME TO LOGICAL APPLICATION
// ============================================================

string getLogicalApplication(
    const string &application,
    const string &windowTitle)
{
    string app = toLower(application);
    string title = toLower(windowTitle);

    // Browser-hosted web apps
    if (isSupportedBrowser(app))
    {
        if (title.find("youtube") != string::npos)
            return "YouTube";
        if (title.find("instagram") != string::npos)
            return "Instagram";
        if (title.find("snapchat") != string::npos)
            return "Snapchat";
        if (title.find("tiktok") != string::npos)
            return "TikTok";
        if (title.find("facebook") != string::npos)
            return "Facebook";
        if (title.find("whatsapp") != string::npos)
            return "WhatsApp";
        if (title.find("linkedin") != string::npos)
            return "LinkedIn";
        if (title.find("github") != string::npos)
            return "GitHub";
        if (title.find("leetcode") != string::npos)
            return "LeetCode";
        if (title.find("stackoverflow") != string::npos)
            return "StackOverflow";
    }

    // Native applications
    if (app == "instagram.exe")
        return "Instagram";
    if (app == "snapchat.exe")
        return "Snapchat";
    if (app == "code.exe" || app == "devenv.exe")
        return "VS Code";
    if (app == "windowsterminal.exe")
        return "Windows Terminal";
    if (app == "powershell.exe")
        return "PowerShell";
    if (app == "cmd.exe" || app == "conhost.exe")
        return "Command Prompt";
    if (app == "discord.exe")
        return "Discord";
    if (app == "explorer.exe")
        return "File Explorer / Desktop";
    if (app == "system / idle" || app == "system process")
        return "Desktop / Idle";

    return application;
}

// ============================================================
// MAIN MONITORING DAEMON
// ============================================================

int main(int argc, char *argv[])
{
    cout << "========================================" << endl;
    cout << "     FOCUS GUARD MONITOR (Qwen 2.5-VL)" << endl;
    cout << "========================================" << endl;
    cout << endl;

    // Policy & Restriction engines
    PolicyManager policyManager;
    RestrictionManager restrictionManager;
    EnforcementManager enforcementManager;
    AIClient aiClient("127.0.0.1", 8765);
    FaceAuthClient faceClient("127.0.0.1", 8765);
    FaceAuthManager faceAuthManager(faceClient, policyManager);
    UserIdentity currentIdentity = UserIdentity::USER;

    // CLI Arguments Handling
    bool startLocked = false;
    for (int i = 1; i < argc; ++i)
    {
        string arg = argv[i];
        if (arg == "--help" || arg == "-h")
        {
            cout << "FocusGuard Monitor CLI Options:\n"
                 << "  --enroll          Enroll webcam face biometrics (interactive)\n"
                 << "  --reset-face      Reset enrolled face biometrics\n"
                 << "  --lock            Start FocusGuard in locked state\n"
                 << "  --pin <pin>       Set or update fallback PIN\n"
                 << "  --no-face-auth    Disable face authentication gating\n"
                 << "  --help, -h        Display this help message\n"
                 << endl;
            return 0;
        }
        else if (arg == "--enroll")
        {
            bool enrolled = faceAuthManager.runInteractiveEnrollment();
            return enrolled ? 0 : 1;
        }
        else if (arg == "--reset-face")
        {
            cout << "[FaceAuth] Resetting face enrollment..." << endl;
            bool ok = faceClient.resetEnrollment("default");
            if (ok)
                cout << "[FaceAuth] Face template reset successfully." << endl;
            else
                cout << "[FaceAuth Error] Failed to reset face template." << endl;
            return ok ? 0 : 1;
        }
        else if (arg == "--pin" && i + 1 < argc)
        {
            string newPin = argv[++i];
            policyManager.setFallbackPin(newPin);
            cout << "[FaceAuth] Fallback PIN updated successfully to: " << newPin << endl;
        }
        else if (arg == "--lock")
        {
            startLocked = true;
        }
        else if (arg == "--no-face-auth")
        {
            FaceAuthConfig cfg = policyManager.getFaceAuthConfig();
            cfg.enabled = false;
            policyManager.setFaceAuthConfig(cfg);
            cout << "[FaceAuth] Face authentication disabled via CLI." << endl;
        }
    }

    // Check AI bridge health
    cout << "[AI] Probing local Qwen 2.5-VL vision bridge..." << endl;
    if (aiClient.checkHealth())
    {
        cout << "[AI] Connected to FocusGuard AI Bridge (port 8765)." << endl;
    }
    else
    {
        cout << "[AI Notice] AI bridge offline at 127.0.0.1:8765. (Will use Win32 & OCR heuristics)." << endl;
        cout << "            To start vision AI: python tools/focusguard_ai.py --serve" << endl;
    }

    // Default distraction policies
    policyManager.addPolicy("Instagram", RestrictionMode::BLOCK, 60, 120);
    policyManager.addPolicy("Snapchat", RestrictionMode::BLOCK, 60, 120);
    policyManager.addPolicy("TikTok", RestrictionMode::BLOCK, 60, 120);
    policyManager.addPolicy("YouTube", RestrictionMode::CONTENT_AWARE, 60, 120);

    policyManager.displayPolicies();
    cout << endl;

    // Startup Face Auth Gate
    if (policyManager.getFaceAuthConfig().enabled)
    {
        enforcementManager.pauseEnforcement();
        if (startLocked)
        {
            faceAuthManager.triggerLock("CLI requested lock");
            faceAuthManager.showLockScreenModal("FocusGuard starting in locked mode.");
        }
        else
        {
            bool authed = faceAuthManager.runStartupGate();
            if (!authed)
            {
                cout << "[FocusGuard] Authentication was not completed. Exiting daemon." << endl;
                return 1;
            }
        }
        enforcementManager.resumeEnforcement();
    }

    // Tracking state
    string previousActivity = "";
    auto activityStartTime = steady_clock::now();

    bool distractionActive = false;
    steady_clock::time_point distractionStartTime;
    long long distractionStreak = 0;
    int lastWarningLevel = 0;

    // Time totals
    unordered_map<string, long long> activityTime;
    unordered_map<string, long long> classificationTime;

    int loopCount = 0;
    auto lastAITime = steady_clock::now();
    auto lastPresenceCheck = steady_clock::now();
    string ocrText = "";

    cout << ">>> FocusGuard monitoring started. Press Ctrl+C to exit.\n" << endl;

    while (true)
    {
        // Check Windows session lock / screensaver
        BOOL isScreensaver = FALSE;
        SystemParametersInfo(SPI_GETSCREENSAVERRUNNING, 0, &isScreensaver, 0);
        HDESK hDesk = OpenInputDesktop(0, FALSE, DESKTOP_SWITCHDESKTOP);
        bool isDesktopLocked = (hDesk == NULL);
        if (hDesk)
            CloseDesktop(hDesk);

        if ((isScreensaver || isDesktopLocked) && !faceAuthManager.isLocked() && policyManager.getFaceAuthConfig().enabled)
        {
            faceAuthManager.triggerLock("Windows Workstation / Screensaver Locked");
        }

        // Periodic presence heartbeat (every 5 seconds)
        if (policyManager.getFaceAuthConfig().enabled && !faceAuthManager.isLocked())
        {
            if (duration_cast<seconds>(steady_clock::now() - lastPresenceCheck).count() >= 5)
            {
                lastPresenceCheck = steady_clock::now();
                faceAuthManager.checkPresenceHeartbeat();

                if (faceAuthManager.isUserPresent())
                {
                    if (currentIdentity != UserIdentity::USER)
                    {
                        cout << "\n[Identity] USER detected. FocusGuard active." << endl;
                    }
                    currentIdentity = UserIdentity::USER;
                }
                else
                {
                    if (currentIdentity != UserIdentity::GUEST)
                    {
                        cout << "\n[Identity] GUEST detected. Personal restrictions paused." << endl;
                    }
                    currentIdentity = UserIdentity::GUEST;
                }
            }
        }

        // If locked, block monitoring and show lock screen
        if (faceAuthManager.isLocked())
        {
            enforcementManager.pauseEnforcement();
            distractionActive = false;
            distractionStreak = 0;
            lastWarningLevel = 0;
            faceAuthManager.showLockScreenModal("FocusGuard session is locked.");
            if (!faceAuthManager.isLocked())
            {
                enforcementManager.resumeEnforcement();
                activityStartTime = steady_clock::now();
            }
            Sleep(1000);
            continue;
        }

        HWND hwnd = getActiveWindowHandle();
        string application = getActiveApplication(hwnd);

        string windowTitle = getWindowTitle(hwnd);

        // 1. Browser context detection
        BrowserInfo browserInfo;
        if (isSupportedBrowser(application))
        {
            browserInfo = detectBrowserContext(hwnd, application);
        }

        // 2. Logical application mapping
        string logicalApp = getLogicalApplication(application, windowTitle);

        // 3. Fast classification via URL & Title heuristics
        string classification = classifyContent(
            application,
            windowTitle,
            browserInfo.url,
            ocrText);

        // YouTube Shorts strict priority rule
        if (browserInfo.isYouTube && browserInfo.isYouTubeShort)
        {
            classification = "DISTRACTION";
        }
        else if (browserInfo.isYouTube && browserInfo.isYouTubeHistory)
        {
            classification = "NEUTRAL";
        }

        // 4. AI Vision fallback if classification is UNKNOWN
        auto now = steady_clock::now();
        long long secondsSinceAI = duration_cast<seconds>(now - lastAITime).count();

        if (classification == "UNKNOWN" && secondsSinceAI >= OCR_AI_INTERVAL)
        {
            lastAITime = now;

            if (aiClient.checkHealth())
            {
                cout << "[AI] Querying Qwen 2.5-VL for visual classification..." << endl;
                AIClassification aiResult = aiClient.requestClassification();
                if (aiResult.success)
                {
                    classification = aiResult.classification;
                    cout << "[AI Result] " << aiResult.activity
                         << " -> " << aiResult.classification
                         << " (" << aiResult.confidence * 100 << "% confidence)" << endl;
                }
            }
            else
            {
                // Fallback to local Tesseract OCR if available
                ocrText = captureScreenOCR();
                if (!ocrText.empty())
                {
                    classification = classifyContent(application, windowTitle, browserInfo.url, ocrText);
                }
            }
        }

        // 5. Check if currently restricted under cooldown
        bool isAppRestricted =
            currentIdentity == UserIdentity::USER &&
            restrictionManager.isRestricted(logicalApp);

        if (isAppRestricted)
        {
            long long remaining = restrictionManager.remainingSeconds(logicalApp);
            cout << "\n[RESTRICTION ACTIVE] " << logicalApp
                 << " is restricted (" << remaining << "s cooldown remaining)." << endl;

            // Immediately enforce: minimize window without restarting a 60s streak
            enforcementManager.enforce(
                hwnd,
                logicalApp,
                "This application is currently in its cooldown restriction period.",
                static_cast<int>(remaining),
                browserInfo.isBrowser);

            distractionStreak = 0;
            distractionActive = false;
            lastWarningLevel = 0;
        }

        // 6. Policy decision & Distraction streak handling
        bool policyApplies =
            currentIdentity == UserIdentity::USER &&
            policyManager.shouldRestrict(logicalApp, classification);

        if (classification == "DISTRACTION" && policyApplies && !isAppRestricted)
        {
            if (!distractionActive)
            {
                distractionActive = true;
                distractionStartTime = steady_clock::now();
                distractionStreak = 0;
                lastWarningLevel = 0;

                cout << "\n>>> DISTRACTION DETECTED: " << logicalApp << endl;
            }

            distractionStreak = duration_cast<seconds>(steady_clock::now() - distractionStartTime).count();

            // 10s Warning
            if (distractionStreak >= WARNING_TIME && lastWarningLevel < 1)
            {
                cout << "\n[WARNING] You have been on " << logicalApp
                     << " for " << distractionStreak << " seconds." << endl;
                lastWarningLevel = 1;
            }

            // 30s Strong Warning
            if (distractionStreak >= STRONG_WARNING_TIME && lastWarningLevel < 2)
            {
                cout << "\n[ALERT] Distraction streak: " << distractionStreak
                     << "s. Consider returning to work." << endl;
                lastWarningLevel = 2;
            }

            // Intervention threshold
            AppPolicy policy = policyManager.getPolicy(logicalApp);
            int interventionTime = (policy.maxDurationSeconds > 0) ? policy.maxDurationSeconds : 60;

            if (distractionStreak >= interventionTime && lastWarningLevel < 3)
            {
                lastWarningLevel = 3;

                // Start cooldown
                int cooldown = (policy.cooldownSeconds > 0) ? policy.cooldownSeconds : 120;
                restrictionManager.restrictApplication(logicalApp, cooldown, hwnd);

                // Non-blocking enforcement
                enforcementManager.enforce(
                    hwnd,
                    logicalApp,
                    "Maximum allotted time (" + to_string(interventionTime) + "s) exceeded.",
                    cooldown,
                    browserInfo.isBrowser);

                distractionActive = false;
                distractionStreak = 0;
                lastWarningLevel = 0;
            }
        }
        else if (!isAppRestricted)
        {
            if (distractionActive)
            {
                cout << "\n>>> Returned to focus / distraction ended." << endl;
            }
            distractionActive = false;
            distractionStreak = 0;
            lastWarningLevel = 0;
        }

        // 7. Robust real-time time accumulation (1-second increments)
        string currentActivity = logicalApp + " | " + windowTitle;
        if (currentIdentity == UserIdentity::USER)
        {
            activityTime[currentActivity] += 1;
            classificationTime[classification] += 1;
        }

        if (currentActivity != previousActivity)
        {
            previousActivity = currentActivity;
            activityStartTime = steady_clock::now();
        }

        long long elapsedSeconds = duration_cast<seconds>(steady_clock::now() - activityStartTime).count();

        // 8. Console summary
        cout << "\n----------------------------------------" << endl;
        cout << "Loop           : " << ++loopCount << endl;
        cout << "Application    : " << application << " (" << logicalApp << ")" << endl;
        cout << "Identity       : " << (currentIdentity == UserIdentity::USER ? "USER" : "GUEST") << endl;
        cout << "Title          : " << windowTitle << endl;
        if (!browserInfo.url.empty())
        {
            cout << "Browser URL    : " << browserInfo.url << endl;
        }
        cout << "Classification : " << classification << endl;
        cout << "Time on window : " << elapsedSeconds << "s" << endl;
        if (classification == "DISTRACTION")
        {
            cout << "Streak         : " << distractionStreak << "s" << endl;
        }

        cout << "\n[Totals Today]" << endl;
        cout << "  Productive   : " << classificationTime["PRODUCTIVE"] << "s" << endl;
        cout << "  Distraction  : " << classificationTime["DISTRACTION"] << "s" << endl;
        cout << "  Neutral      : " << classificationTime["NEUTRAL"] << "s" << endl;
        cout << "  Unknown      : " << classificationTime["UNKNOWN"] << "s" << endl;
        cout << "----------------------------------------" << endl;

        Sleep(1000);
    }

    return 0;
}