cmake_minimum_required(VERSION 3.15)
project(FocusGuard VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)

# Core FocusGuard common library sources
set(FOCUSGUARD_CORE_SOURCES
    src/policy.cpp
    src/restriction.cpp
    src/browser.cpp
    src/classifier.cpp
    src/enforcement.cpp
    src/ocr.cpp
    src/ai_client.cpp
    src/face_auth.cpp
)

# 1. Main Background Monitor Daemon
add_executable(focusguard_monitor
    src/monitor.cpp
    ${FOCUSGUARD_CORE_SOURCES}
)

target_link_libraries(focusguard_monitor PRIVATE
    uiautomationcore
    ole32
    oleaut32
    psapi
    gdi32
    user32
    winhttp
    advapi32
)

# 2. Policy & Rules CLI Demo
add_executable(focusguard_demo
    src/main.cpp
    src/policy.cpp
)

target_link_libraries(focusguard_demo PRIVATE
    user32
)

# 3. Face Auth Automated Unit Tests
add_executable(face_auth_test
    src/test_face_auth.cpp
    src/face_auth.cpp
    src/policy.cpp
    src/enforcement.cpp
)

target_link_libraries(face_auth_test PRIVATE
    user32
    gdi32
    winhttp
    advapi32
)
