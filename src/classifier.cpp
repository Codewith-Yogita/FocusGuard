#include "../include/classifier.h"

#include <algorithm>
#include <cctype>
#include <regex>
#include <vector>

using namespace std;

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

static bool containsWord(const string &text, const string &word)
{
    // Regex word boundary matching (\bword\b)
    try
    {
        string escaped = "";
        for (char c : word)
        {
            if (c == '+' || c == '.' || c == '*' || c == '?' || c == '(' || c == ')')
                escaped += '\\';
            escaped += c;
        }
        regex pattern("(?:^|[^a-zA-Z0-9_])" + escaped + "(?:$|[^a-zA-Z0-9_])", regex_constants::icase);
        return regex_search(text, pattern);
    }
    catch (...)
    {
        return text.find(word) != string::npos;
    }
}

static bool containsAny(const string &text, const vector<string> &words)
{
    for (const auto &w : words)
    {
        if (text.find(w) != string::npos)
            return true;
    }
    return false;
}

// ============================================================
// CONTENT CLASSIFIER
// ============================================================

string classifyContent(
    const string &application,
    const string &windowTitle,
    const string &browserUrl,
    const string &ocrText)
{
    string app = toLower(application);
    string title = toLower(windowTitle);
    string url = toLower(browserUrl);
    string ocr = toLower(ocrText);

    // ========================================================
    // PRODUCTIVE NATIVE APPLICATIONS (IDEs, Editors, Terminals)
    // ========================================================

    if (app == "code.exe" ||           // VS Code
        app == "devenv.exe" ||         // Visual Studio
        app == "clion64.exe" ||        // CLion
        app == "pycharm64.exe" ||      // PyCharm
        app == "idea64.exe" ||         // IntelliJ
        app == "sublime_text.exe" ||   // Sublime
        app == "notepad++.exe" ||      // Notepad++
        app == "windowsterminal.exe" ||// Windows Terminal
        app == "powershell.exe" ||     // PowerShell
        app == "conhost.exe" ||        // Console Host
        app == "cmd.exe")              // Command Prompt
    {
        return "PRODUCTIVE";
    }

    // ========================================================
    // SYSTEM / DESKTOP / EXPLORER (NEUTRAL)
    // ========================================================

    if (app == "explorer.exe" ||
        app == "system / idle" ||
        app == "system process" ||
        title.find("windows desktop") != string::npos ||
        title.find("taskbar") != string::npos)
    {
        return "NEUTRAL";
    }

    // ========================================================
    // DISTRACTING NATIVE APPLICATIONS
    // ========================================================

    if (app == "instagram.exe" ||
        app == "snapchat.exe" ||
        app == "tiktok.exe" ||
        app == "discord.exe")
    {
        return "DISTRACTION";
    }

    // ========================================================
    // BROWSER URL-BASED CLASSIFICATION (HIGHEST PRIORITY)
    // ========================================================

    if (!url.empty())
    {
        // 1. YouTube Shorts (Always Distraction)
        if (url.find("youtube.com/shorts/") != string::npos ||
            url.find("youtube.com/shorts") != string::npos)
        {
            return "DISTRACTION";
        }

        // 2. Social Media Domains
        if (url.find("instagram.com") != string::npos ||
            url.find("snapchat.com") != string::npos ||
            url.find("tiktok.com") != string::npos ||
            url.find("twitter.com") != string::npos ||
            url.find("x.com") != string::npos)
        {
            return "DISTRACTION";
        }

        // 3. Technical & Educational Domains
        if (url.find("github.com") != string::npos ||
            url.find("stackoverflow.com") != string::npos ||
            url.find("leetcode.com") != string::npos ||
            url.find("codeforces.com") != string::npos ||
            url.find("coursera.org") != string::npos ||
            url.find("udemy.com") != string::npos ||
            url.find("geeksforgeeks.org") != string::npos ||
            url.find("docs.microsoft.com") != string::npos ||
            url.find("developer.mozilla.org") != string::npos)
        {
            return "PRODUCTIVE";
        }
    }

    // ========================================================
    // SOCIAL SITES DETECTED IN WINDOW TITLE
    // ========================================================

    if (title.find("instagram") != string::npos ||
        title.find("snapchat") != string::npos ||
        title.find("tiktok") != string::npos)
    {
        return "DISTRACTION";
    }

    // ========================================================
    // YOUTUBE TITLE & CONTEXT ANALYSIS
    // ========================================================

    if (title.find("youtube") != string::npos || url.find("youtube.com") != string::npos)
    {
        // Secondary shorts check (e.g. #shorts hashtag in title)
        if (title.find("#shorts") != string::npos ||
            containsWord(title, "shorts") && (title.find("tiktok") != string::npos || title.find("reel") != string::npos))
        {
            return "DISTRACTION";
        }

        // Educational / Programming keywords with boundary awareness
        static const vector<string> techPhrases = {
            "dsa", "data structure", "data structures", "algorithm", "algorithms",
            "leetcode", "codeforces", "competitive programming", "web development",
            "frontend", "backend", "full stack", "software engineering", "computer science",
            "interview preparation", "lecture", "tutorial", "crash course",
            "system design", "operating system", "database management", "sql", "machine learning",
            "deep learning", "artificial intelligence", "react tutorial", "python tutorial",
            "c++ tutorial", "cpp tutorial", "javascript tutorial", "rust tutorial"
        };

        if (containsAny(title, techPhrases))
        {
            return "PRODUCTIVE";
        }

        // Word-boundary checks for short keywords
        if (containsWord(title, "c++") ||
            containsWord(title, "cpp") ||
            containsWord(title, "python") ||
            containsWord(title, "coding") ||
            containsWord(title, "programming"))
        {
            return "PRODUCTIVE";
        }

        // Music / Background Audio
        if (containsWord(title, "lofi") ||
            containsWord(title, "ambient") ||
            containsWord(title, "soundtrack") ||
            title.find("chill beats") != string::npos)
        {
            return "NEUTRAL";
        }
    }

    // ========================================================
    // OCR TEXT FALLBACK
    // ========================================================

    if (!ocr.empty())
    {
        if (ocr.find("youtube.com/shorts") != string::npos ||
            ocr.find("#shorts") != string::npos)
        {
            return "DISTRACTION";
        }

        static const vector<string> ocrKeywords = {
            "dsa", "leetcode", "algorithm", "data structure", "class ", "public static void",
            "int main()", "#include <", "def ", "function ", "const ", "git commit"
        };

        if (containsAny(ocr, ocrKeywords))
        {
            return "PRODUCTIVE";
        }
    }

    return "UNKNOWN";
}