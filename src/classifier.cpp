#include "../include/classifier.h"

#include <algorithm>
#include <cctype>

using namespace std;

// ============================================================
// TEXT UTILITY
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
// CONTENT CLASSIFIER
// ============================================================

string classifyContent(
    const string &application,
    const string &windowTitle,
    const string &ocrText,
    const string &browserUrl)
{
    string app = toLowerCase(application);
    string title = toLowerCase(windowTitle);
    string ocr = toLowerCase(ocrText);
    string url = toLowerCase(browserUrl);

    // ========================================================
    // INSTAGRAM
    // ========================================================

    if (app == "instagram.exe")
    {
        return "DISTRACTION";
    }

    if (
        app == "msedge.exe" &&
        title.find("instagram") != string::npos)
    {
        return "DISTRACTION";
    }

    // ========================================================
    // SNAPCHAT
    // ========================================================

    if (app == "snapchat.exe")
    {
        return "DISTRACTION";
    }

    if (
        app == "msedge.exe" &&
        title.find("snapchat") != string::npos)
    {
        return "DISTRACTION";
    }

    // ========================================================
    // VS CODE
    // ========================================================

    if (app == "code.exe")
    {
        return "PRODUCTIVE";
    }

    // ========================================================
    // YOUTUBE
    // ========================================================

    if (
        app == "msedge.exe" &&
        title.find("youtube") != string::npos)
    {
        // ----------------------------------------------------
        // YOUTUBE SHORTS
        // ----------------------------------------------------
        //
        // URL detection has HIGHEST PRIORITY.
        //
        // Example:
        //
        // https://www.youtube.com/shorts/ABC123
        //
        // Even if the title says:
        //
        // "Learn C++ in 30 seconds"
        //
        // it is STILL a Short and therefore a distraction.
        // ----------------------------------------------------

        bool isShort =
            url.find("youtube.com/shorts/") != string::npos ||
            url.find("youtube.com/shorts") != string::npos;

        // ----------------------------------------------------
        // Fallback detection
        //
        // These are weaker signals, but useful if URL
        // detection temporarily fails.
        // ----------------------------------------------------

        if (!isShort)
        {
            isShort =
                title.find("shorts") != string::npos ||
                title.find("#shorts") != string::npos ||
                ocr.find("youtube.com/shorts") != string::npos ||
                ocr.find("youtube.com / shorts") != string::npos;
        }

        if (isShort)
        {
            return "DISTRACTION";
        }

        // ----------------------------------------------------
        // PRODUCTIVE YOUTUBE CONTENT
        // ----------------------------------------------------

        bool productiveSignal =
            title.find("dsa") != string::npos ||
            title.find("data structure") != string::npos ||
            title.find("data structures") != string::npos ||
            title.find("algorithm") != string::npos ||
            title.find("algorithms") != string::npos ||
            title.find("leetcode") != string::npos ||
            title.find("codeforces") != string::npos ||
            title.find("competitive programming") != string::npos ||
            title.find("programming") != string::npos ||
            title.find("coding") != string::npos ||
            title.find("c++") != string::npos ||
            title.find("cpp") != string::npos ||
            title.find("javascript") != string::npos ||
            title.find("react") != string::npos ||
            title.find("python") != string::npos ||
            title.find("java") != string::npos ||
            title.find("web development") != string::npos ||
            title.find("frontend") != string::npos ||
            title.find("backend") != string::npos ||
            title.find("software engineering") != string::npos ||
            title.find("computer science") != string::npos ||
            title.find("placement") != string::npos ||
            title.find("placements") != string::npos ||
            title.find("interview preparation") != string::npos ||
            title.find("tutorial") != string::npos ||
            title.find("course") != string::npos ||
            title.find("lecture") != string::npos ||
            title.find("explained") != string::npos ||
            title.find("theory") != string::npos ||
            title.find("complexity analysis") != string::npos;

        if (productiveSignal)
        {
            return "PRODUCTIVE";
        }

        // ----------------------------------------------------
        // MUSIC
        // ----------------------------------------------------

        bool musicSignal =
            title.find("music") != string::npos ||
            title.find("song") != string::npos ||
            title.find("lofi") != string::npos;

        if (musicSignal)
        {
            return "NEUTRAL";
        }

        // ----------------------------------------------------
        // PRODUCTIVE OCR
        // ----------------------------------------------------

        bool productiveOCR =
            ocr.find("dsa") != string::npos ||
            ocr.find("data structure") != string::npos ||
            ocr.find("algorithm") != string::npos ||
            ocr.find("algorithms") != string::npos ||
            ocr.find("leetcode") != string::npos ||
            ocr.find("codeforces") != string::npos ||
            ocr.find("programming") != string::npos ||
            ocr.find("coding") != string::npos ||
            ocr.find("javascript") != string::npos ||
            ocr.find("react") != string::npos ||
            ocr.find("python") != string::npos ||
            ocr.find("java") != string::npos ||
            ocr.find("placement") != string::npos ||
            ocr.find("tutorial") != string::npos ||
            ocr.find("course") != string::npos ||
            ocr.find("lecture") != string::npos ||
            ocr.find("explained") != string::npos ||
            ocr.find("theory") != string::npos ||
            ocr.find("complexity analysis") != string::npos;

        if (productiveOCR)
        {
            return "PRODUCTIVE";
        }

        return "UNKNOWN";
    }

    // ========================================================
    // DEFAULT
    // ========================================================

    return "UNKNOWN";
}