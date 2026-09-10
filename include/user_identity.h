#ifndef USER_IDENTITY_H
#define USER_IDENTITY_H

// ============================================================
// USER TYPE
// ============================================================

enum class UserType
{
    UNKNOWN,
    OWNER,
    GUEST
};

// ============================================================
// USER IDENTITY MANAGER
// ============================================================

class UserIdentityManager
{
private:

    UserType currentUser;

public:

    // Constructor
    UserIdentityManager();

    // Set the currently detected user
    void setCurrentUser(UserType user);

    // Get the currently detected user
    UserType getCurrentUser() const;

    // Convenience checks
    bool isOwner() const;
    bool isGuest() const;
    bool isUnknown() const;
};

// Convert UserType to readable text
const char* userTypeToString(UserType user);

#endif
