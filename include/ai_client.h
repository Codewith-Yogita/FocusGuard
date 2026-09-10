#ifndef AI_CLIENT_H
#define AI_CLIENT_H

#include <string>

struct AIClassification
{
    bool success = false;
    std::string activity;
    std::string classification; // PRODUCTIVE, DISTRACTION, NEUTRAL, UNKNOWN
    double confidence = 0.0;
    std::string reason;
};

class AIClient
{
private:
    std::string host;
    int port;
    bool serviceReachable;

public:
    AIClient(const std::string &host = "127.0.0.1", int port = 8765);

    // Checks if the local Qwen 2.5-VL bridge is reachable
    bool checkHealth();

    // Queries the AI bridge for an instant visual classification
    AIClassification requestClassification();

    bool isReachable() const { return serviceReachable; }
};

#endif
