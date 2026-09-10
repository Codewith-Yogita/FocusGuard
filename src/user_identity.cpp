#include "../include/user_identity.h"

// ============================================================
// CONSTRUCTOR
// ============================================================

UserIdentityManager::UserIdentityManager()
{
    currentUser = UserType::UNKNOWN;
}

// ============================================================
// SET CURRENT USER
// ============================================================

void UserIdentityManager::setCurrentUser(UserType user)
{
    currentUser = user;
}

// ============================================================
// GET CURRENT USER
// ============================================================

UserType UserIdentityManager::getCurrentUser() const
{
    return currentUser;
}

// ============================================================
// CHECK OWNER
// ============================================================

bool UserIdentityManager::isOwner() const
{
    return currentUser == UserType::OWNER;
}

// ============================================================
// CHECK GUEST
// ============================================================

bool UserIdentityManager::isGuest() const
{
    return currentUser == UserType::GUEST;
}

// ============================================================
// CHECK UNKNOWN
// ============================================================

bool UserIdentityManager::isUnknown() const
{
    return currentUser == UserType::UNKNOWN;
}

// ============================================================
// USER TYPE TO STRING
// ============================================================

const char* userTypeToString(UserType user)
{
    switch (user)
    {
        case UserType::OWNER:
            return "OWNER";

        case UserType::GUEST:
            return "GUEST";

        case UserType::UNKNOWN:
            return "UNKNOWN";

        default:
            return "UNKNOWN";
    }
}
