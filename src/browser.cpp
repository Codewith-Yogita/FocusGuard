#include "../include/browser.h"

#include <windows.h>
#include <uiautomation.h>

#include <algorithm>
#include <cctype>
#include <string>
#include <iostream>
#include <vector>

#pragma comment(lib, "uiautomationcore.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")

using namespace std;

// ============================================================
// LOWERCASE UTILITY
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
// SUPPORTED BROWSER CHECK
// ============================================================

bool isSupportedBrowser(const string &appName)
{
    string app = toLower(appName);
    return (
        app == "msedge.exe" ||
        app == "chrome.exe" ||
        app == "brave.exe" ||
        app == "firefox.exe" ||
        app == "vivaldi.exe" ||
        app == "opera.exe" ||
        app == "arc.exe");
}

// ============================================================
// GET BROWSER URL
// ============================================================

string getBrowserUrl(HWND hwnd, const string &appName)
{
    if (hwnd == NULL)
        return "";

    HRESULT hr = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    bool shouldUninit = (hr == S_OK || hr == S_FALSE);

    // Get UI Automation instance
    CLSID clsid;
    hr = CLSIDFromString(L"{FF48DBA4-60EF-4201-AA87-54103EEF594E}", &clsid);
    if (FAILED(hr))
    {
        if (shouldUninit)
            CoUninitialize();
        return "";
    }

    IUIAutomation *automation = nullptr;
    hr = CoCreateInstance(clsid, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&automation));
    if (FAILED(hr) || automation == nullptr)
    {
        if (shouldUninit)
            CoUninitialize();
        return "";
    }

    IUIAutomationElement *windowElement = nullptr;
    hr = automation->ElementFromHandle(hwnd, &windowElement);
    if (FAILED(hr) || windowElement == nullptr)
    {
        automation->Release();
        if (shouldUninit)
            CoUninitialize();
        return "";
    }

    // Prepare condition for Edit or ComboBox controls (address bars)
    VARIANT vtEdit, vtCombo;
    VariantInit(&vtEdit);
    VariantInit(&vtCombo);
    vtEdit.vt = VT_I4;
    vtEdit.lVal = UIA_EditControlTypeId;
    vtCombo.vt = VT_I4;
    vtCombo.lVal = UIA_ComboBoxControlTypeId;

    IUIAutomationCondition *editCond = nullptr;
    IUIAutomationCondition *comboCond = nullptr;
    automation->CreatePropertyCondition(UIA_ControlTypePropertyId, vtEdit, &editCond);
    automation->CreatePropertyCondition(UIA_ControlTypePropertyId, vtCombo, &comboCond);

    IUIAutomationCondition *orCond = nullptr;
    if (editCond && comboCond)
    {
        automation->CreateOrCondition(editCond, comboCond, &orCond);
    }

    IUIAutomationElement *addressBar = nullptr;

    if (orCond)
    {
        windowElement->FindFirst(TreeScope_Descendants, orCond, &addressBar);
    }
    else if (editCond)
    {
        windowElement->FindFirst(TreeScope_Descendants, editCond, &addressBar);
    }

    // Cleanup conditions
    if (editCond) editCond->Release();
    if (comboCond) comboCond->Release();
    if (orCond) orCond->Release();
    VariantClear(&vtEdit);
    VariantClear(&vtCombo);

    string url = "";

    if (addressBar != nullptr)
    {
        IUIAutomationValuePattern *valuePattern = nullptr;
        hr = addressBar->GetCurrentPatternAs(UIA_ValuePatternId, IID_PPV_ARGS(&valuePattern));

        if (SUCCEEDED(hr) && valuePattern != nullptr)
        {
            BSTR value = nullptr;
            hr = valuePattern->get_CurrentValue(&value);

            if (SUCCEEDED(hr) && value != nullptr)
            {
                int sizeNeeded = WideCharToMultiByte(CP_UTF8, 0, value, -1, nullptr, 0, nullptr, nullptr);
                if (sizeNeeded > 1)
                {
                    string converted(sizeNeeded - 1, '\0');
                    WideCharToMultiByte(CP_UTF8, 0, value, -1, &converted[0], sizeNeeded, nullptr, nullptr);
                    url = converted;
                }
                SysFreeString(value);
            }
            valuePattern->Release();
        }
        addressBar->Release();
    }

    windowElement->Release();
    automation->Release();

    if (shouldUninit)
        CoUninitialize();

    return url;
}

// ============================================================
// YOUTUBE HELPERS
// ============================================================

bool isYouTubeUrl(const string &url)
{
    string lowerUrl = toLower(url);
    return (
        lowerUrl.find("youtube.com") != string::npos ||
        lowerUrl.find("youtu.be") != string::npos);
}

bool isYouTubeShorts(const string &url)
{
    string lowerUrl = toLower(url);
    return (
        lowerUrl.find("youtube.com/shorts/") != string::npos ||
        lowerUrl.find("youtube.com/shorts") != string::npos);
}

// ============================================================
// DETECT BROWSER CONTEXT
// ============================================================

BrowserInfo detectBrowserContext(HWND hwnd, const string &appName)
{
    BrowserInfo info;
    if (hwnd == NULL)
        return info;

    info.isBrowser = isSupportedBrowser(appName);
    info.browserName = appName;

    if (!info.isBrowser)
        return info;

    info.url = getBrowserUrl(hwnd, appName);
    string lowerUrl = toLower(info.url);

    if (!isYouTubeUrl(lowerUrl))
        return info;

    info.isYouTube = true;

    if (isYouTubeShorts(lowerUrl))
    {
        info.isYouTubeShort = true;
        return info;
    }

    if (lowerUrl.find("youtube.com/feed/history") != string::npos)
    {
        info.isYouTubeHistory = true;
        return info;
    }

    if (lowerUrl == "https://www.youtube.com/" ||
        lowerUrl == "https://youtube.com/" ||
        lowerUrl.find("youtube.com/?") != string::npos)
    {
        info.isYouTubeHome = true;
        return info;
    }

    return info;
}