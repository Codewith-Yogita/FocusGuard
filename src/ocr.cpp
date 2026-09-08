
#include "../include/ocr.h"

#include <windows.h>
#include <fstream>
#include <vector>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <iostream>

using namespace std;

// ============================================================
// SAVE BITMAP AS BMP
// ============================================================

bool saveBitmap(
    HBITMAP bitmap,
    HDC hdc,
    int width,
    int height,
    const string &filename)
{
    BITMAPINFOHEADER bi = {};

    bi.biSize = sizeof(BITMAPINFOHEADER);
    bi.biWidth = width;
    bi.biHeight = -height;
    bi.biPlanes = 1;
    bi.biBitCount = 32;
    bi.biCompression = BI_RGB;

    int imageSize = width * height * 4;

    vector<BYTE> pixels(imageSize);

    if (!GetDIBits(
            hdc,
            bitmap,
            0,
            height,
            pixels.data(),
            (BITMAPINFO *)&bi,
            DIB_RGB_COLORS))
    {
        return false;
    }

    BITMAPFILEHEADER bf = {};

    bf.bfType = 0x4D42;

    bf.bfOffBits =
        sizeof(BITMAPFILEHEADER) +
        sizeof(BITMAPINFOHEADER);

    bf.bfSize =
        bf.bfOffBits + imageSize;

    ofstream file(
        filename,
        ios::binary);

    if (!file)
        return false;

    file.write(
        (char *)&bf,
        sizeof(BITMAPFILEHEADER));

    file.write(
        (char *)&bi,
        sizeof(BITMAPINFOHEADER));

    file.write(
        (char *)pixels.data(),
        imageSize);

    file.close();

    return true;
}

// ============================================================
// CAPTURE SCREEN + OCR
// ============================================================

string captureScreenOCR()
{
    int screenWidth =
        GetSystemMetrics(SM_CXSCREEN);

    int screenHeight =
        GetSystemMetrics(SM_CYSCREEN);

    HDC screenDC =
        GetDC(NULL);

    if (screenDC == NULL)
        return "";

    HDC memoryDC =
        CreateCompatibleDC(screenDC);

    if (memoryDC == NULL)
    {
        ReleaseDC(NULL, screenDC);
        return "";
    }

    HBITMAP bitmap =
        CreateCompatibleBitmap(
            screenDC,
            screenWidth,
            screenHeight);

    if (bitmap == NULL)
    {
        DeleteDC(memoryDC);
        ReleaseDC(NULL, screenDC);
        return "";
    }

    HBITMAP oldBitmap =
        (HBITMAP)SelectObject(
            memoryDC,
            bitmap);

    // --------------------------------------------------------
    // CAPTURE SCREEN
    // --------------------------------------------------------

    bool captured =
        BitBlt(
            memoryDC,
            0,
            0,
            screenWidth,
            screenHeight,
            screenDC,
            0,
            0,
            SRCCOPY);

    if (!captured)
    {
        SelectObject(
            memoryDC,
            oldBitmap);

        DeleteObject(bitmap);
        DeleteDC(memoryDC);
        ReleaseDC(NULL, screenDC);

        return "";
    }

    // --------------------------------------------------------
    // SAVE TEMPORARY SCREENSHOT
    // --------------------------------------------------------

    string imageFile =
        "screen_ocr.bmp";

    saveBitmap(
        bitmap,
        memoryDC,
        screenWidth,
        screenHeight,
        imageFile);

    // --------------------------------------------------------
    // CLEAN WINDOWS RESOURCES
    // --------------------------------------------------------

    SelectObject(
        memoryDC,
        oldBitmap);

    DeleteObject(bitmap);
    DeleteDC(memoryDC);
    ReleaseDC(NULL, screenDC);

   // ============================================================
// RUN TESSERACT OCR
// ============================================================

cout << "Running Tesseract OCR..." << endl;

string command =
    "tesseract screen_ocr.bmp ocr_result --psm 6 >nul 2>&1";

int result = system(command.c_str());

if (result != 0)
{
    cout << "ERROR: Tesseract failed." << endl;
    return "";
}

// ============================================================
// READ OCR RESULT
// ============================================================

ifstream ocrFile("ocr_result.txt");

if (!ocrFile)
{
    cout << "ERROR: Could not open OCR result file."
         << endl;

    return "";
}

string text;
string line;

while (getline(ocrFile, line))
{
    text += line + " ";
}

ocrFile.close();

return text;
}   

