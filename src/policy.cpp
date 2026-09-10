#include "../include/policy.h"

#include <iostream>
#include <algorithm>
#include <cctype>
#include <cstdint>
#include <vector>

using namespace std;

static string normalize(string text)
{
    transform(
        text.begin(),
        text.end(),
        text.begin(),
        [](unsigned char c) { return static_cast<char>(tolower(c)); });
    return text;
}

void PolicyManager::addPolicy(
    const string &application,
    RestrictionMode mode,
    int maxDurationSeconds,
    int cooldownSeconds)
{
    AppPolicy policy;
    policy.application = application;
    policy.mode = mode;
    policy.maxDurationSeconds = maxDurationSeconds;
    policy.cooldownSeconds = cooldownSeconds;

    policies[normalize(application)] = policy;
}

bool PolicyManager::hasPolicy(
    const string &application) const
{
    return policies.find(normalize(application)) != policies.end();
}

AppPolicy PolicyManager::getPolicy(
    const string &application) const
{
    auto it = policies.find(normalize(application));
    if (it != policies.end())
    {
        return it->second;
    }

    return AppPolicy{
        application,
        RestrictionMode::ALLOW,
        0,
        0};
}

bool PolicyManager::shouldRestrict(
    const string &application,
    const string &classification) const
{
    auto it = policies.find(normalize(application));
    if (it == policies.end())
    {
        return false;
    }

    const AppPolicy &policy = it->second;

    if (policy.mode == RestrictionMode::BLOCK)
    {
        return true;
    }

    if (policy.mode == RestrictionMode::CONTENT_AWARE)
    {
        return classification == "DISTRACTION";
    }

    return false;
}

// ============================================================
// SHA-256 IMPLEMENTATION
// ============================================================

static inline uint32_t rotr(uint32_t n, uint32_t d) { return (n >> d) | (n << (32 - d)); }
static inline uint32_t ch(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (~x & z); }
static inline uint32_t maj(uint32_t x, uint32_t y, uint32_t z) { return (x & y) ^ (x & z) ^ (y & z); }
static inline uint32_t ep0(uint32_t x) { return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22); }
static inline uint32_t ep1(uint32_t x) { return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25); }
static inline uint32_t sig0(uint32_t x) { return rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3); }
static inline uint32_t sig1(uint32_t x) { return rotr(x, 17) ^ rotr(x, 19) ^ (x >> 10); }

static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

string computeSha256(const string &input)
{
    uint32_t state[8] = {
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    };

    uint64_t bitlen = input.size() * 8;
    vector<uint8_t> data(input.begin(), input.end());
    data.push_back(0x80);
    while ((data.size() % 64) != 56)
    {
        data.push_back(0x00);
    }
    for (int i = 7; i >= 0; --i)
    {
        data.push_back(static_cast<uint8_t>((bitlen >> (i * 8)) & 0xff));
    }

    for (size_t chunk = 0; chunk < data.size(); chunk += 64)
    {
        uint32_t w[64];
        for (int i = 0; i < 16; ++i)
        {
            w[i] = (static_cast<uint32_t>(data[chunk + i * 4]) << 24) |
                   (static_cast<uint32_t>(data[chunk + i * 4 + 1]) << 16) |
                   (static_cast<uint32_t>(data[chunk + i * 4 + 2]) << 8) |
                   (static_cast<uint32_t>(data[chunk + i * 4 + 3]));
        }
        for (int i = 16; i < 64; ++i)
        {
            w[i] = sig1(w[i - 2]) + w[i - 7] + sig0(w[i - 15]) + w[i - 16];
        }

        uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
        uint32_t e = state[4], f = state[5], g = state[6], h = state[7];

        for (int i = 0; i < 64; ++i)
        {
            uint32_t t1 = h + ep1(e) + ch(e, f, g) + K[i] + w[i];
            uint32_t t2 = ep0(a) + maj(a, b, c);
            h = g;
            g = f;
            f = e;
            e = d + t1;
            d = c;
            c = b;
            b = a;
            a = t1 + t2;
        }

        state[0] += a;
        state[1] += b;
        state[2] += c;
        state[3] += d;
        state[4] += e;
        state[5] += f;
        state[6] += g;
        state[7] += h;
    }

    char hexBuf[65] = {0};
    for (int i = 0; i < 8; ++i)
    {
        snprintf(hexBuf + i * 8, 9, "%08x", state[i]);
    }
    return string(hexBuf);
}

PolicyManager::PolicyManager()
{
}

void PolicyManager::setFallbackPin(const string &pin)
{
    faceAuthConfig.pinHash = computeSha256(pin);
}

bool PolicyManager::verifyPin(const string &pin) const
{
    string hash = computeSha256(pin);
    return hash == faceAuthConfig.pinHash;
}

void PolicyManager::displayPolicies() const
{
    cout << endl;
    cout << "========== FOCUS GUARD POLICIES ==========" << endl;

    for (const auto &entry : policies)
    {
        const AppPolicy &policy = entry.second;

        cout << "Application     : " << policy.application << endl;
        cout << "Mode            : ";

        switch (policy.mode)
        {
        case RestrictionMode::ALLOW:
            cout << "ALLOW";
            break;
        case RestrictionMode::BLOCK:
            cout << "BLOCK";
            break;
        case RestrictionMode::CONTENT_AWARE:
            cout << "CONTENT AWARE";
            break;
        }

        cout << endl;
        cout << "Max Duration    : " << policy.maxDurationSeconds << " seconds" << endl;
        cout << "Cooldown        : " << policy.cooldownSeconds << " seconds" << endl;
        cout << "------------------------------------------" << endl;
    }

    cout << "Face Auth       : " << (faceAuthConfig.enabled ? "ENABLED" : "DISABLED") << endl;
    cout << "Auto-Lock       : " << faceAuthConfig.autoLockTimeoutSeconds << "s" << endl;
    cout << "==========================================" << endl;
}