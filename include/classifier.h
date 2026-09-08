#ifndef CLASSIFIER_H
#define CLASSIFIER_H

#include <string>

std::string classifyContent(
    const std::string &application,
    const std::string &windowTitle,
    const std::string &ocrText = "",
    const std::string &browserUrl = "");

#endif