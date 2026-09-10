#ifndef CLASSIFIER_H
#define CLASSIFIER_H

#include <string>

// Classifies desktop activity based on application name, window title, URL, and OCR text
std::string classifyContent(
    const std::string &application,
    const std::string &windowTitle,
    const std::string &browserUrl = "",
    const std::string &ocrText = "");

#endif