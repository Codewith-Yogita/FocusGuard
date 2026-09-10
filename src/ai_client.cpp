#include "../include/ai_client.h"

#include <windows.h>
#include <winhttp.h>
#include <iostream>
#include <sstream>
#include <regex>

#pragma comment(lib, "winhttp.lib")

using namespace std;

AIClient::AIClient(const string &h, int p)
    : host(h), port(p), serviceReachable(false)
{
}

static string httpGet(const string &host, int port, const wstring &path, int timeoutMs = 1500)
{
    string responseText = "";

    wstring wHost(host.begin(), host.end());

    HINTERNET hSession = WinHttpOpen(
        L"FocusGuard-Client/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS,
        0);

    if (!hSession)
        return "";

    // Configure fast timeouts (resolve, connect, send, receive)
    WinHttpSetTimeouts(hSession, timeoutMs, timeoutMs, timeoutMs, timeoutMs);

    HINTERNET hConnect = WinHttpConnect(
        hSession,
        wHost.c_str(),
        (INTERNET_PORT)port,
        0);

    if (!hConnect)
    {
        WinHttpCloseHandle(hSession);
        return "";
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect,
        L"GET",
        path.c_str(),
        nullptr,
        WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES,
        0);

    if (!hRequest)
    {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return "";
    }

    BOOL bResults = WinHttpSendRequest(
        hRequest,
        WINHTTP_NO_ADDITIONAL_HEADERS,
        0,
        WINHTTP_NO_REQUEST_DATA,
        0,
        0,
        0);

    if (bResults)
    {
        bResults = WinHttpReceiveResponse(hRequest, nullptr);
    }

    if (bResults)
    {
        DWORD dwSize = 0;
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
                responseText.append(pszOutBuffer, dwDownloaded);
            }

            delete[] pszOutBuffer;
        } while (dwSize > 0);
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    return responseText;
}

bool AIClient::checkHealth()
{
    string resp = httpGet(host, port, L"/health", 800);
    if (!resp.empty() && resp.find("ready") != string::npos)
    {
        serviceReachable = true;
        return true;
    }
    serviceReachable = false;
    return false;
}

static string extractJsonField(const string &json, const string &field)
{
    // Search for "field": "value"
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

AIClassification AIClient::requestClassification()
{
    AIClassification result;
    result.success = false;
    result.classification = "UNKNOWN";

    string resp = httpGet(host, port, L"/classify", 3000);
    if (resp.empty())
    {
        serviceReachable = false;
        return result;
    }

    serviceReachable = true;
    result.classification = extractJsonField(resp, "classification");
    result.activity = extractJsonField(resp, "activity");
    result.reason = extractJsonField(resp, "reason");
    result.confidence = extractJsonDouble(resp, "confidence");

    if (!result.classification.empty())
    {
        result.success = true;
    }
    else
    {
        result.classification = "UNKNOWN";
    }

    return result;
}
