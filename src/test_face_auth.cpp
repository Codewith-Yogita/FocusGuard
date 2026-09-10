#include "../include/face_auth.h"
#include "../include/policy.h"
#include "../include/enforcement.h"

#include <iostream>
#include <cassert>
#include <chrono>

using namespace std;

void test_sha256_pin()
{
    cout << "[TEST] Running SHA-256 PIN test..." << endl;
    // Known SHA-256 for "1234" is 03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4
    string hash1234 = computeSha256("1234");
    assert(hash1234 == "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4");

    // PolicyManager PIN verification
    PolicyManager pol;
    assert(pol.verifyPin("1234") == true);
    assert(pol.verifyPin("0000") == false);
    assert(pol.verifyPin("wrong") == false);

    // Change fallback PIN to "9876"
    pol.setFallbackPin("9876");
    assert(pol.verifyPin("9876") == true);
    assert(pol.verifyPin("1234") == false);

    cout << "  -> SHA-256 PIN hashing and verification PASSED." << endl;
}

void test_face_auth_state_machine()
{
    cout << "[TEST] Running FaceAuthManager state machine test..." << endl;
    PolicyManager pol;
    FaceAuthClient dummyClient("127.0.0.1", 8765);
    FaceAuthManager manager(dummyClient, pol);

    // Initial state is LOCKED
    assert(manager.isLocked() == true);
    assert(manager.getState() == AuthState::LOCKED);
    assert(manager.getFailedAttempts() == 0);

    // Verify correct PIN unlocks session
    bool pinOk = manager.verifyPin("1234");
    assert(pinOk == true);
    assert(manager.isLocked() == false);
    assert(manager.getState() == AuthState::UNLOCKED);

    // Trigger lock
    manager.triggerLock("Manual lock test");
    assert(manager.isLocked() == true);
    assert(manager.getState() == AuthState::LOCKED);

    // Failed PIN entry does not unlock
    bool badPin = manager.verifyPin("9999");
    assert(badPin == false);
    assert(manager.isLocked() == true);

    cout << "  -> FaceAuthManager state transitions PASSED." << endl;
}

void test_enforcement_pause_on_lock()
{
    cout << "[TEST] Running EnforcementManager lock pause test..." << endl;
    EnforcementManager enf;
    assert(enf.isEnforcementPaused() == false);

    // Pause enforcement
    enf.pauseEnforcement();
    assert(enf.isEnforcementPaused() == true);

    // Enforce returns false when paused
    bool enforced = enf.enforce(NULL, "Instagram", "Cooldown period", 60, false);
    assert(enforced == false);

    // Resume enforcement
    enf.resumeEnforcement();
    assert(enf.isEnforcementPaused() == false);

    cout << "  -> EnforcementManager lock pause PASSED." << endl;
}

int main()
{
    cout << "========================================" << endl;
    cout << "    FOCUSGUARD C++ FACE AUTH TESTS" << endl;
    cout << "========================================" << endl;

    test_sha256_pin();
    test_face_auth_state_machine();
    test_enforcement_pause_on_lock();

    cout << "\n>>> ALL C++ UNIT TESTS PASSED SUCCESSFULLY! <<<\n" << endl;
    return 0;
}
