#ifndef POLICY_H
#define POLICY_H

#include <string>
#include <unordered_map>

enum class RestrictionMode
{
    ALLOW,
    BLOCK,
    CONTENT_AWARE
};

struct AppPolicy
{
    std::string application;

    RestrictionMode mode;

    int maxDurationSeconds;

    int cooldownSeconds;
};

struct FaceAuthConfig
{
    bool enabled = true;
    double confidenceThreshold = 0.85;
    int maxRetries = 3;
    int autoLockTimeoutSeconds = 60;
    int cameraIndex = 0;
    // Default SHA-256 for PIN "1234": 03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4
    std::string pinHash = "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4";
};

class PolicyManager
{
private:
    std::unordered_map<std::string, AppPolicy> policies;
    FaceAuthConfig faceAuthConfig;

public:
    PolicyManager();

    void addPolicy(
        const std::string &application,
        RestrictionMode mode,
        int maxDurationSeconds,
        int cooldownSeconds);

    bool hasPolicy(
        const std::string &application) const;

    AppPolicy getPolicy(
        const std::string &application) const;

    bool shouldRestrict(
        const std::string &application,
        const std::string &classification) const;

    void displayPolicies() const;

    // Face Auth & Fallback PIN configurations
    const FaceAuthConfig &getFaceAuthConfig() const { return faceAuthConfig; }
    void setFaceAuthConfig(const FaceAuthConfig &config) { faceAuthConfig = config; }
    void setFallbackPin(const std::string &pin);
    bool verifyPin(const std::string &pin) const;
};

#endif