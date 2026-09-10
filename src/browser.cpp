#include "../include/browser.h"

#include <windows.h>
#include <uiautomation.h>

#include <algorithm>
#include <cctype>
#include <string>
#include <iostream>

#pragma comment(lib, "uiautomationcore.lib")

using namespace std;

// ============================================================
// LOWERCASE
// ============================================================

static string toLowerCase(string text)
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
// GET BROWSER URL
// ============================================================

string getBrowserUrl(HWND hwnd)
{
    if (hwnd == NULL)
        return "";

    // --------------------------------------------------------
    // Initialize COM
    // --------------------------------------------------------

    HRESULT hr = CoInitializeEx(
        nullptr,
        COINIT_APARTMENTTHREADED);

    bool comInitialized = SUCCEEDED(hr);

    if (FAILED(hr) && hr != RPC_E_CHANGED_MODE)
        return "";

    // --------------------------------------------------------
    // Get UI Automation CLSID
    // --------------------------------------------------------
    //
    // CLSID_CUIAutomation:
    //
    // FF48DBA4-60EF-4201-AA87-54103EEF594E
    //
    // We use CLSIDFromString instead of directly referencing
    // CLSID_CUIAutomation because MinGW may not export the
    // symbol in the same way as MSVC.
    // --------------------------------------------------------

    CLSID clsid;

    hr = CLSIDFromString(
        L"{FF48DBA4-60EF-4201-AA87-54103EEF594E}",
        &clsid);

    if (FAILED(hr))
    {
        if (comInitialized)
            CoUninitialize();

        return "";
    }

    // --------------------------------------------------------
    // Create UI Automation
    // --------------------------------------------------------

    IUIAutomation *automation = nullptr;

    hr = CoCreateInstance(
        clsid,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&automation));

    if (FAILED(hr) || automation == nullptr)
    {
        if (comInitialized)
            CoUninitialize();

        return "";
    }

    // --------------------------------------------------------
    // Get browser window element
    // --------------------------------------------------------

    IUIAutomationElement *windowElement = nullptr;

    hr = automation->ElementFromHandle(
        hwnd,
        &windowElement);

    if (FAILED(hr) || windowElement == nullptr)
    {
        automation->Release();

        if (comInitialized)
            CoUninitialize();

        return "";
    }

    // --------------------------------------------------------
    // Find Edit controls
    // --------------------------------------------------------

    VARIANT controlType;
    VariantInit(&controlType);

    controlType.vt = VT_I4;
    controlType.lVal = UIA_EditControlTypeId;

    IUIAutomationCondition *condition = nullptr;

    hr = automation->CreatePropertyCondition(
        UIA_ControlTypePropertyId,
        controlType,
        &condition);

    VariantClear(&controlType);

    if (FAILED(hr) || condition == nullptr)
    {
        windowElement->Release();
        automation->Release();

        if (comInitialized)
            CoUninitialize();

        return "";
    }

    // --------------------------------------------------------
    // Find first Edit control
    // --------------------------------------------------------

    IUIAutomationElement *addressBar = nullptr;

    hr = windowElement->FindFirst(
        TreeScope_Descendants,
        condition,
        &addressBar);

    condition->Release();

    if (FAILED(hr) || addressBar == nullptr)
    {
        windowElement->Release();
        automation->Release();

        if (comInitialized)
            CoUninitialize();

        return "";
    }

    // --------------------------------------------------------
    // Read ValuePattern
    // --------------------------------------------------------

    IUIAutomationValuePattern *valuePattern = nullptr;

    hr = addressBar->GetCurrentPatternAs(
        UIA_ValuePatternId,
        IID_PPV_ARGS(&valuePattern));

    string url = "";

    if (SUCCEEDED(hr) && valuePattern != nullptr)
    {
        BSTR value = nullptr;

        hr = valuePattern->get_CurrentValue(
            &value);

        if (SUCCEEDED(hr) && value != nullptr)
        {
            int sizeNeeded =
                WideCharToMultiByte(
                    CP_UTF8,
                    0,
                    value,
                    -1,
                    nullptr,
                    0,
                    nullptr,
                    nullptr);

            if (sizeNeeded > 0)
            {
                string converted(
                    sizeNeeded - 1,
                    '\0');

                WideCharToMultiByte(
                    CP_UTF8,
                    0,
                    value,
                    -1,
                    &converted[0],
                    sizeNeeded,
                    nullptr,
                    nullptr);

                url = converted;
            }

            SysFreeString(value);
        }

        valuePattern->Release();
    }

    // --------------------------------------------------------
    // Cleanup
    // --------------------------------------------------------

    addressBar->Release();
    windowElement->Release();
    automation->Release();

    if (comInitialized)
        CoUninitialize();

    return url;
}

// ============================================================
// CHECK YOUTUBE
// ============================================================

bool isYouTubeUrl(const string &url)
{
    string lowerUrl =
        toLowerCase(url);

    return (
        lowerUrl.find("youtube.com") != string::npos ||
        lowerUrl.find("youtu.be") != string::npos);
}

// ============================================================
// CHECK YOUTUBE SHORTS
// ============================================================

bool isYouTubeShorts(const string &url)
{
    string lowerUrl =
        toLowerCase(url);

    return (
        lowerUrl.find("youtube.com/shorts/") != string::npos ||
        lowerUrl.find("youtube.com/shorts") != string::npos);
}

bool isInstagramUrl(const string &url)
{
    string lowerUrl = toLowerCase(url);

    return (
        lowerUrl.find("instagram.com") != string::npos);
}

bool isSnapchatUrl(const string &url)
{
    string lowerUrl = toLowerCase(url);

    return (
        lowerUrl.find("snapchat.com") != string::npos);
}

bool isFacebookUrl(const string &url)
{
    string lowerUrl = toLowerCase(url);

    return (
        lowerUrl.find("facebook.com") != string::npos ||
        lowerUrl.find("fb.com") != string::npos);
}

bool isWhatsAppUrl(const string &url)
{
    string lowerUrl = toLowerCase(url);

    return (
        lowerUrl.find("web.whatsapp.com") != string::npos ||
        lowerUrl.find("whatsapp.com") != string::npos);
}

bool isLinkedInUrl(const string &url)
{
    string lowerUrl = toLowerCase(url);

    return (
        lowerUrl.find("linkedin.com") != string::npos);
}
// ============================================================
// DETECT BROWSER CONTEXT
// ============================================================

BrowserInfo detectBrowserContext(HWND hwnd)
{
    BrowserInfo info;

    if (hwnd == NULL)
        return info;

    info.isBrowser = true;

    // --------------------------------------------------------
    // GET CURRENT URL
    // --------------------------------------------------------

    info.url = getBrowserUrl(hwnd);

    cout << "[BROWSER URL] "
         << info.url
         << endl;

    string url = toLowerCase(info.url);

    // --------------------------------------------------------
    // NO URL
    // --------------------------------------------------------

    if (url.empty())
        return info;

    // ========================================================
    // YOUTUBE
    // ========================================================

    if (isYouTubeUrl(url))
    {
        info.isYouTube = true;

        // ----------------------------------------------------
        // YOUTUBE SHORTS
        // ----------------------------------------------------

        if (isYouTubeShorts(url))
        {
            info.isYouTubeShort = true;
            return info;
        }

        // ----------------------------------------------------
        // YOUTUBE HISTORY
        // ----------------------------------------------------

        if (
            url.find("youtube.com/feed/history") !=
            string::npos)
        {
            info.isYouTubeHistory = true;
            return info;
        }

        // ----------------------------------------------------
        // YOUTUBE HOME
        // ----------------------------------------------------

        if (
            url == "https://www.youtube.com/" ||
            url == "https://youtube.com/" ||
            url.find("youtube.com/?") !=
                string::npos)
        {
            info.isYouTubeHome = true;
            return info;
        }

        return info;
    }

    // ========================================================
    // INSTAGRAM
    // ========================================================

    if (isInstagramUrl(url))
    {
        info.isInstagram = true;
        return info;
    }

    // ========================================================
    // SNAPCHAT
    // ========================================================

    if (isSnapchatUrl(url))
    {
        info.isSnapchat = true;
        return info;
    }

    // ========================================================
    // FACEBOOK
    // ========================================================

    if (isFacebookUrl(url))
    {
        info.isFacebook = true;
        return info;
    }

    // ========================================================
    // WHATSAPP
    // ========================================================

    if (isWhatsAppUrl(url))
    {
        info.isWhatsApp = true;
        return info;
    }

    // ========================================================
    // LINKEDIN
    // ========================================================

    if (isLinkedInUrl(url))
    {
        info.isLinkedIn = true;
        return info;
    }

    return info;
}