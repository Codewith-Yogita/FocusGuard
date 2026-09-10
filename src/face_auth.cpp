#include "../include/face_auth.h"
#include "../include/policy.h"

#include <windows.h>
#include <winhttp.h>
#include <iostream>
#include <sstream>
#include <regex>
#include <thread>
#include <atomic>

#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "gdi32.lib")

using namespace std;
using namespace chrono;

// ============================================================
// WINHTTP HELPERS (JSON GET / POST WITH STATUS CODE)
// ============================================================

struct HttpResponse
{
    int statusCode = 0;
    string body = "";
};

static HttpResponse httpJsonRequest(
    const string &host,
    int port,
    const wstring &verb,
    const wstring &path,
    const string &jsonPayload = "",
    int timeoutMs = 4000)
{
    HttpResponse response;
    wstring wHost(host.begin(), host.end());

    HINTERNET hSession = WinHttpOpen(
        L"FocusGuard-AuthClient/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS,
        0);

    if (!hSession)
        return response;

    WinHttpSetTimeouts(hSession, timeoutMs, timeoutMs, timeoutMs, timeoutMs);

    HINTERNET hConnect = WinHttpConnect(
        hSession,
        wHost.c_str(),
        (INTERNET_PORT)port,
        0);

    if (!hConnect)
    {
        WinHttpCloseHandle(hSession);
        return response;
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect,
        verb.c_str(),
        path.c_str(),
        nullptr,
        WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES,
        0);

    if (!hRequest)
    {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return response;
    }

    wstring headers = L"Content-Type: application/json\r\n";
    BOOL bResults = FALSE;

    if (!jsonPayload.empty())
    {
        bResults = WinHttpSendRequest(
            hRequest,
            headers.c_str(),
            (DWORD)headers.length(),
            (LPVOID)jsonPayload.c_str(),
            (DWORD)jsonPayload.length(),
            (DWORD)jsonPayload.length(),
            0);
    }
    else
    {
        bResults = WinHttpSendRequest(
            hRequest,
            headers.c_str(),
            (DWORD)headers.length(),
            WINHTTP_NO_REQUEST_DATA,
            0,
            0,
            0);
    }

    if (bResults)
    {
        bResults = WinHttpReceiveResponse(hRequest, nullptr);
    }

    if (bResults)
    {
        DWORD dwStatusCode = 0;
        DWORD dwSize = sizeof(dwStatusCode);
        if (WinHttpQueryHeaders(
                hRequest,
                WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                WINHTTP_HEADER_NAME_BY_INDEX,
                &dwStatusCode,
                &dwSize,
                WINHTTP_NO_HEADER_INDEX))
        {
            response.statusCode = static_cast<int>(dwStatusCode);
        }

        DWORD dwDownloaded = 0;
        do
        {
            dwSize = 0;
            if (!WinHttpQueryDataAvailable(hRequest, &dwSize))
                break;
            if (dwSize == 0)
                break;

            char *pszOutBuffer = new char[dwSize + 1];
            ZeroMemory(pszOutBuffer, dwSize + 1);

            if (WinHttpReadData(hRequest, (LPVOID)pszOutBuffer, dwSize, &dwDownloaded))
            {
                response.body.append(pszOutBuffer, dwDownloaded);
            }
            delete[] pszOutBuffer;
        } while (dwSize > 0);
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    return response;
}

static string extractJsonField(const string &json, const string &field)
{
    regex rgx("\"" + field + "\"\\s*:\\s*\"([^\"]+)\"");
    smatch match;
    if (regex_search(json, match, rgx) && match.size() > 1)
    {
        return match.str(1);
    }
    return "";
}

static double extractJsonDouble(const string &json, const string &field)
{
    regex rgx("\"" + field + "\"\\s*:\\s*([0-9.]+)");
    smatch match;
    if (regex_search(json, match, rgx) && match.size() > 1)
    {
        try
        {
            return stod(match.str(1));
        }
        catch (...)
        {
            return 0.0;
        }
    }
    return 0.0;
}

static bool extractJsonBool(const string &json, const string &field)
{
    regex rgx("\"" + field + "\"\\s*:\\s*(true|false)");
    smatch match;
    if (regex_search(json, match, rgx) && match.size() > 1)
    {
        return match.str(1) == "true";
    }
    return false;
}

// ============================================================
// FACE AUTH CLIENT
// ============================================================

FaceAuthClient::FaceAuthClient(const string &h, int p)
    : host(h), port(p), serviceReachable(false)
{
}

FaceAuthStatus FaceAuthClient::getStatus()
{
    FaceAuthStatus status;
    HttpResponse resp = httpJsonRequest(host, port, L"GET", L"/face/status", "", 1200);
    if (resp.statusCode == 200 && !resp.body.empty())
    {
        serviceReachable = true;
        status.reachable = true;
        status.enrolled = extractJsonBool(resp.body, "enrolled");
        status.cameraAvailable = extractJsonBool(resp.body, "camera_available");
        status.modelLoaded = extractJsonBool(resp.body, "model_loaded");
        status.userId = extractJsonField(resp.body, "user_id");
        if (status.userId.empty())
            status.userId = "default";
    }
    else
    {
        serviceReachable = false;
        status.reachable = false;
    }
    return status;
}

FaceAuthResult FaceAuthClient::authenticate(const string &userId, int timeoutMs)
{
    FaceAuthResult result;
    string payload = "{\"user_id\": \"" + userId + "\", \"timeout_ms\": " + to_string(timeoutMs) + "}";

    HttpResponse resp = httpJsonRequest(host, port, L"POST", L"/face/authenticate", payload, timeoutMs + 2000);
    result.rawResponse = resp.body;

    if (resp.statusCode == 200)
    {
        serviceReachable = true;
        result.authenticated = extractJsonBool(resp.body, "authenticated");
        result.confidence = extractJsonDouble(resp.body, "confidence");
        result.reason = extractJsonField(resp.body, "reason");
    }
    else if (resp.statusCode == 401)
    {
        serviceReachable = true;
        result.authenticated = false;
        result.confidence = extractJsonDouble(resp.body, "confidence");
        result.reason = extractJsonField(resp.body, "reason");
        if (result.reason.empty())
            result.reason = "unauthorized";
    }
    else
    {
        serviceReachable = false;
        result.authenticated = false;
        result.reason = "bridge_offline";
    }

    return result;
}

FaceEnrollResult FaceAuthClient::enroll(const string &userId, int frames)
{
    FaceEnrollResult result;
    string payload = "{\"user_id\": \"" + userId + "\", \"frames\": " + to_string(frames) + "}";

    HttpResponse resp = httpJsonRequest(host, port, L"POST", L"/face/enroll", payload, 20000);
    result.statusCode = resp.statusCode;

    if (resp.statusCode == 200)
    {
        serviceReachable = true;
        result.success = true;
        result.status = extractJsonField(resp.body, "status");
        result.templateId = extractJsonField(resp.body, "template_id");
        result.message = "Successfully enrolled face template.";
    }
    else if (resp.statusCode == 409)
    {
        serviceReachable = true;
        result.success = false;
        result.status = "conflict";
        result.message = "User is already enrolled. Please reset before re-enrolling.";
    }
    else
    {
        result.success = false;
        result.status = extractJsonField(resp.body, "status");
        result.message = extractJsonField(resp.body, "message");
        if (result.message.empty())
            result.message = "Enrollment failed (HTTP " + to_string(resp.statusCode) + ").";
    }

    return result;
}

bool FaceAuthClient::checkPresence(const string &userId, double *outConfidence)
{
    string payload = "{\"user_id\": \"" + userId + "\"}";
    HttpResponse resp = httpJsonRequest(host, port, L"POST", L"/face/presence", payload, 2500);

    if (resp.statusCode == 200)
    {
        serviceReachable = true;
        bool present = extractJsonBool(resp.body, "present");
        if (outConfidence)
        {
            *outConfidence = extractJsonDouble(resp.body, "confidence");
        }
        return present;
    }
    return false;
}

bool FaceAuthClient::resetEnrollment(const string &userId)
{
    string payload = "{\"user_id\": \"" + userId + "\", \"confirm\": true}";
    HttpResponse resp = httpJsonRequest(host, port, L"POST", L"/face/reset", payload, 3000);
    return resp.statusCode == 200;
}

// ============================================================
// FACE AUTH STATE MANAGER & UI
// ============================================================

FaceAuthManager::FaceAuthManager(FaceAuthClient &cli, PolicyManager &pol)
    : client(cli), policyManager(pol), currentState(AuthState::LOCKED),
      failedAttempts(0), pinFallbackActive(false), userPresent(false)
{
    lockoutUntil = steady_clock::now();
    lastPresenceSuccess = steady_clock::now();
}

void FaceAuthManager::triggerLock(const string &reason)
{
    currentState = AuthState::LOCKED;
    cout << "\n============================================" << endl;
    cout << " [LOCK TRIGGERED] Session locked: " << reason << endl;
    cout << "============================================" << endl;
}

void FaceAuthManager::unlockSession()
{
    currentState = AuthState::UNLOCKED;
    failedAttempts = 0;
    pinFallbackActive = false;
    lastPresenceSuccess = steady_clock::now();
    cout << "\n[AUTH] Session unlocked! Monitoring and enforcement active." << endl;
}

bool FaceAuthManager::verifyPin(const string &enteredPin)
{
    if (policyManager.verifyPin(enteredPin))
    {
        unlockSession();
        return true;
    }
    cout << "[AUTH] Invalid PIN entered." << endl;
    return false;
}

bool FaceAuthManager::attemptFaceAuth()
{
    auto now = steady_clock::now();
    if (now < lockoutUntil)
    {
        long long remSec = duration_cast<seconds>(lockoutUntil - now).count();
        cout << "[AUTH] Too many failed attempts. PIN required (or wait " << remSec << "s)." << endl;
        return false;
    }

    currentState = AuthState::AUTHENTICATING;
    cout << "[AUTH] Authenticating live face with camera..." << endl;

    FaceAuthResult res = client.authenticate("default", 6000);

    if (res.authenticated)
    {
        cout << "[AUTH] Verification SUCCESS (confidence: "
             << static_cast<int>(res.confidence * 100) << "%)." << endl;
        unlockSession();
        return true;
    }

    failedAttempts++;
    currentState = AuthState::LOCKED;
    cout << "[AUTH] Face verification FAILED (" << res.reason
         << ", attempt " << failedAttempts << "/"
         << policyManager.getFaceAuthConfig().maxRetries << ")." << endl;

    if (failedAttempts >= policyManager.getFaceAuthConfig().maxRetries)
    {
        pinFallbackActive = true;
        lockoutUntil = steady_clock::now() + seconds(30);
        cout << "[AUTH ALERT] Maximum face retry attempts exceeded. PIN fallback required." << endl;
    }

    return false;
}

bool FaceAuthManager::checkPresenceHeartbeat()
{
    if (currentState == AuthState::LOCKED)
    {
        userPresent = false;
        return false;
    }

    double conf = 0.0;
    bool present = client.checkPresence("default", &conf);
    auto now = steady_clock::now();

    userPresent = present;

    if (present)
    {
        lastPresenceSuccess = now;
        return true;
    }

    long long absentSeconds = duration_cast<seconds>(now - lastPresenceSuccess).count();
    int timeout = policyManager.getFaceAuthConfig().autoLockTimeoutSeconds;

    if (absentSeconds >= timeout)
    {
        triggerLock("User absent (" + to_string(absentSeconds) + "s >= " + to_string(timeout) + "s timeout)");
        return false;
    }

    return true;
}

// ============================================================
// SLEEK WIN32 LOCK SCREEN OVERLAY WINDOW
// ============================================================

#define IDC_PIN_EDIT 101
#define IDC_PIN_BTN 102
#define IDC_FACE_BTN 103
#define IDC_STATUS_TXT 104

static HWND g_hStatusText = NULL;
static HWND g_hPinEdit = NULL;
static HWND g_hLockWnd = NULL;
static FaceAuthManager *g_pManager = nullptr;
static atomic<bool> g_authInProgress(false);

static LRESULT CALLBACK LockScreenWndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_CREATE:
    {
        // Title label
        CreateWindowExA(0, "STATIC", "FOCUSGUARD - SESSION LOCKED",
                        WS_CHILD | WS_VISIBLE | SS_CENTER,
                        20, 20, 440, 30, hwnd, NULL, NULL, NULL);

        // Subtitle prompt
        CreateWindowExA(0, "STATIC", "Face verification or fallback PIN required to resume desktop.",
                        WS_CHILD | WS_VISIBLE | SS_CENTER,
                        20, 55, 440, 25, hwnd, NULL, NULL, NULL);

        // Status banner
        g_hStatusText = CreateWindowExA(0, "STATIC", "Initiating face verification...",
                                        WS_CHILD | WS_VISIBLE | SS_CENTER,
                                        20, 90, 440, 30, hwnd, (HMENU)IDC_STATUS_TXT, NULL, NULL);

        // PIN label & input
        CreateWindowExA(0, "STATIC", "Fallback PIN:",
                        WS_CHILD | WS_VISIBLE | SS_RIGHT,
                        40, 140, 120, 25, hwnd, NULL, NULL, NULL);

        g_hPinEdit = CreateWindowExA(WS_EX_CLIENTEDGE, "EDIT", "",
                                     WS_CHILD | WS_VISIBLE | ES_PASSWORD | ES_NUMBER | ES_AUTOHSCROLL,
                                     170, 138, 120, 26, hwnd, (HMENU)IDC_PIN_EDIT, NULL, NULL);

        // Unlock PIN button
        CreateWindowExA(0, "BUTTON", "Unlock PIN",
                        WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON,
                        305, 138, 100, 26, hwnd, (HMENU)IDC_PIN_BTN, NULL, NULL);

        // Retry Face Auth button
        CreateWindowExA(0, "BUTTON", "Retry Face Auth",
                        WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                        140, 190, 200, 32, hwnd, (HMENU)IDC_FACE_BTN, NULL, NULL);

        // Trigger automatic initial face scan after window appears
        SetTimer(hwnd, 1, 300, NULL);
        return 0;
    }

    case WM_TIMER:
    {
        KillTimer(hwnd, 1);
        if (g_pManager && !g_authInProgress)
        {
            g_authInProgress = true;
            SetWindowTextA(g_hStatusText, "Scanning face... look directly at webcam.");
            thread([]() {
                bool ok = g_pManager->attemptFaceAuth();
                g_authInProgress = false;
                if (ok && g_hLockWnd)
                {
                    PostMessage(g_hLockWnd, WM_CLOSE, 0, 0);
                }
                else if (g_hStatusText)
                {
                    string msg = "Face auth failed. Retry or enter PIN.";
                    if (g_pManager->getFailedAttempts() >= 3)
                        msg = "Max face retries exceeded. Please enter PIN.";
                    SetWindowTextA(g_hStatusText, msg.c_str());
                }
            }).detach();
        }
        return 0;
    }

    case WM_COMMAND:
    {
        int wmId = LOWORD(wParam);
        if (wmId == IDC_PIN_BTN)
        {
            char pinBuf[64] = {0};
            GetWindowTextA(g_hPinEdit, pinBuf, sizeof(pinBuf));
            string pin(pinBuf);

            if (g_pManager && g_pManager->verifyPin(pin))
            {
                SetWindowTextA(g_hStatusText, "PIN Accepted! Unlocking session...");
                Sleep(200);
                DestroyWindow(hwnd);
            }
            else
            {
                SetWindowTextA(g_hStatusText, "Incorrect PIN. Try again.");
                SetWindowTextA(g_hPinEdit, "");
            }
            return 0;
        }

        if (wmId == IDC_FACE_BTN)
        {
            if (!g_authInProgress)
            {
                SetTimer(hwnd, 1, 50, NULL);
            }
            return 0;
        }
        break;
    }

    case WM_CTLCOLORSTATIC:
    {
        HDC hdcStatic = (HDC)wParam;
        SetTextColor(hdcStatic, RGB(220, 220, 240));
        SetBkColor(hdcStatic, RGB(24, 24, 37));
        static HBRUSH hBrushDark = CreateSolidBrush(RGB(24, 24, 37));
        return (INT_PTR)hBrushDark;
    }

    case WM_PAINT:
    {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hwnd, &ps);
        HBRUSH hBrush = CreateSolidBrush(RGB(24, 24, 37));
        FillRect(hdc, &ps.rcPaint, hBrush);
        DeleteObject(hBrush);
        EndPaint(hwnd, &ps);
        return 0;
    }

    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;

    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }

    return DefWindowProc(hwnd, msg, wParam, lParam);
}

bool FaceAuthManager::showLockScreenModal(const string &promptMessage)
{
    g_pManager = this;
    g_authInProgress = false;

    HINSTANCE hInstance = GetModuleHandle(NULL);
    const char *className = "FocusGuardLockScreenClass";

    WNDCLASSA wc = {};
    wc.lpfnWndProc = LockScreenWndProc;
    wc.hInstance = hInstance;
    wc.lpszClassName = className;
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);

    RegisterClassA(&wc);

    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int screenH = GetSystemMetrics(SM_CYSCREEN);
    int w = 480;
    int h = 280;
    int x = (screenW - w) / 2;
    int y = (screenH - h) / 2;

    HWND hwnd = CreateWindowExA(
        WS_EX_TOPMOST | WS_EX_APPWINDOW,
        className,
        "FocusGuard - Locked",
        WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE,
        x, y, w, h,
        NULL, NULL, hInstance, NULL);

    if (!hwnd)
    {
        // Fallback to console input if GUI creation fails
        cout << "\n[FocusGuard Lock Screen Fallback]" << endl;
        cout << promptMessage << endl;
        cout << "Attempting face verification..." << endl;
        if (attemptFaceAuth())
            return true;

        cout << "Face authentication unsuccessful. Enter PIN: ";
        string inputPin;
        cin >> inputPin;
        return verifyPin(inputPin);
    }

    g_hLockWnd = hwnd;
    ShowWindow(hwnd, SW_SHOW);
    UpdateWindow(hwnd);
    SetForegroundWindow(hwnd);

    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0))
    {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    g_hLockWnd = NULL;
    UnregisterClassA(className, hInstance);

    return !isLocked();
}

bool FaceAuthManager::runStartupGate()
{
    if (!policyManager.getFaceAuthConfig().enabled)
    {
        cout << "[FaceAuth] Face authentication disabled in policy. Gating skipped." << endl;
        unlockSession();
        return true;
    }

    cout << "\n========================================" << endl;
    cout << "     FOCUSGUARD STARTUP AUTH GATE" << endl;
    cout << "========================================" << endl;

    FaceAuthStatus status = client.getStatus();
    if (!status.reachable)
    {
        cout << "[Notice] Vision/Face bridge offline at 127.0.0.1:8765." << endl;
        cout << "         Start with: python tools/focusguard_ai.py --serve" << endl;
        cout << "         Falling back to PIN authentication." << endl;
        cout << "Enter FocusGuard PIN to unlock: ";
        string inputPin;
        cin >> inputPin;
        while (!verifyPin(inputPin))
        {
            cout << "Incorrect PIN. Re-enter PIN: ";
            cin >> inputPin;
        }
        return true;
    }

    if (!status.enrolled)
    {
        cout << "[FaceAuth Notice] No face enrolled yet." << endl;
        cout << "                  Run 'focusguard_monitor.exe --enroll' to enroll face biometrics." << endl;
        cout << "                  Proceeding with fallback PIN." << endl;
        cout << "Enter PIN to start FocusGuard: ";
        string inputPin;
        cin >> inputPin;
        while (!verifyPin(inputPin))
        {
            cout << "Incorrect PIN. Re-enter PIN: ";
            cin >> inputPin;
        }
        return true;
    }

    cout << "[FaceAuth] Enrolled face template detected. Launching authentication gate..." << endl;
    return showLockScreenModal("Face verification required to unlock FocusGuard session.");
}

bool FaceAuthManager::runInteractiveEnrollment()
{
    cout << "\n========================================" << endl;
    cout << "    FOCUSGUARD WEBCAM FACE ENROLLMENT" << endl;
    cout << "========================================" << endl;

    FaceAuthStatus status = client.getStatus();
    if (!status.reachable)
    {
        cout << "[Error] Vision/Face bridge is not running at 127.0.0.1:8765." << endl;
        cout << "        Please run the bridge in another terminal first:" << endl;
        cout << "        python tools/focusguard_ai.py --serve" << endl;
        return false;
    }

    if (status.enrolled)
    {
        cout << "[Notice] Face template is already enrolled for user '" << status.userId << "'." << endl;
        cout << "Do you wish to reset and re-enroll? (y/n): ";
        char choice;
        cin >> choice;
        if (choice != 'y' && choice != 'Y')
        {
            cout << "Enrollment cancelled." << endl;
            return false;
        }
        cout << "Resetting previous template..." << endl;
        client.resetEnrollment(status.userId);
    }

    cout << "\nInstructions:" << endl;
    cout << "1. Look directly at your webcam." << endl;
    cout << "2. Maintain natural subtle movements/blinks." << endl;
    cout << "3. Keep lighting clear and steady." << endl;
    cout << "Starting frame capture in 2 seconds..." << endl;
    Sleep(2000);

    cout << "[Capturing frames] Please hold still..." << endl;
    FaceEnrollResult result = client.enroll("default", 20);

    if (result.success)
    {
        cout << "\n========================================" << endl;
        cout << "   SUCCESS: Face Biometrics Enrolled!" << endl;
        cout << "========================================" << endl;
        cout << "Template ID : " << result.templateId << endl;
        cout << "Security    : Windows DPAPI Encrypted (AES-256 bound to Windows user)" << endl;
        cout << "Storage     : Only 128-d feature embeddings saved. Zero raw images." << endl;
        cout << "========================================\n" << endl;
        return true;
    }
    else
    {
        cout << "\n[Enrollment Failed] " << result.message << endl;
        return false;
    }
}
