#ifndef FACE_AUTH_H
#define FACE_AUTH_H

#include <string>
#include <vector>
#include <chrono>
#include <windows.h>
#include "policy.h"

enum class AuthState
{
    LOCKED,
    AUTHENTICATING,
    UNLOCKED
};

struct FaceAuthStatus
{
    bool reachable = false;
    bool enrolled = false;
    bool cameraAvailable = false;
    bool modelLoaded = false;
    std::string userId = "default";
};

struct FaceAuthResult
{
    bool authenticated = false;
    double confidence = 0.0;
    std::string reason; // "no_face", "no_match", "low_confidence", "liveness_failed", "timeout", "camera_unavailable", etc.
    std::string rawResponse;
};

struct FaceEnrollResult
{
    bool success = false;
    int statusCode = 0;
    std::string status;
    std::string templateId;
    std::string message;
};

class FaceAuthClient
{
private:
    std::string host;
    int port;
    bool serviceReachable;

public:
    FaceAuthClient(const std::string &host = "127.0.0.1", int port = 8765);

    // GET /face/status
    FaceAuthStatus getStatus();

    // POST /face/authenticate
    FaceAuthResult authenticate(const std::string &userId = "default", int timeoutMs = 8000);

    // POST /face/enroll
    FaceEnrollResult enroll(const std::string &userId = "default", int frames = 20);

    // POST /face/presence
    bool checkPresence(const std::string &userId = "default", double *outConfidence = nullptr);

    // POST /face/reset
    bool resetEnrollment(const std::string &userId = "default");

    bool isReachable() const { return serviceReachable; }
};

// SHA-256 Utility for PIN hashing and verification
std::string computeSha256(const std::string &input);

class FaceAuthManager
{
private:
    FaceAuthClient &client;
    PolicyManager &policyManager;
    AuthState currentState;
    int failedAttempts;
    std::chrono::steady_clock::time_point lockoutUntil;
    std::chrono::steady_clock::time_point lastPresenceSuccess;
    bool pinFallbackActive;
    bool userPresent;

public:
    FaceAuthManager(FaceAuthClient &cli, PolicyManager &pol);

    AuthState getState() const { return currentState; }
    bool isLocked() const { return currentState == AuthState::LOCKED; }
    int getFailedAttempts() const { return failedAttempts; }
    bool isUserPresent() const { return userPresent; }

    void triggerLock(const std::string &reason);
    void unlockSession();

    // Run the startup gate: blocks until verified via face or PIN fallback
    bool runStartupGate();

    // Verification attempt: returns true if authenticated
    bool attemptFaceAuth();

    // Verify entered fallback PIN
    bool verifyPin(const std::string &enteredPin);

    // Routine presence check (called every few seconds in main loop)
    // Returns true if present, false if absent long enough to trigger auto-lock
    bool checkPresenceHeartbeat();

    // Displays the sleek Win32 lock screen UI (or console fallback)
    bool showLockScreenModal(const std::string &promptMessage = "");

    // Perform interactive enrollment flow (CLI --enroll)
    bool runInteractiveEnrollment();
};

#endif // FACE_AUTH_H
