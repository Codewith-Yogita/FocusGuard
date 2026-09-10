#include "../include/ocr.h"

#include <windows.h>
#include <fstream>
#include <vector>
#include <string>
#include <cstdlib>
#include <cstdio>
#include <iostream>

using namespace std;

static bool saveBitmap(
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
    bf.bfOffBits = sizeof(BITMAPFILEHEADER) + sizeof(BITMAPINFOHEADER);
    bf.bfSize = bf.bfOffBits + imageSize;

    ofstream file(filename, ios::binary);
    if (!file)
        return false;

    file.write((char *)&bf, sizeof(BITMAPFILEHEADER));
    file.write((char *)&bi, sizeof(BITMAPINFOHEADER));
    file.write((char *)pixels.data(), imageSize);
    file.close();

    return true;
}

string captureScreenOCR()
{
    static bool tesseractAvailable = true;
    if (!tesseractAvailable)
        return "";

    int screenWidth = GetSystemMetrics(SM_CXSCREEN);
    int screenHeight = GetSystemMetrics(SM_CYSCREEN);

    HDC screenDC = GetDC(NULL);
    if (screenDC == NULL)
        return "";

    HDC memoryDC = CreateCompatibleDC(screenDC);
    if (memoryDC == NULL)
    {
        ReleaseDC(NULL, screenDC);
        return "";
    }

    HBITMAP bitmap = CreateCompatibleBitmap(screenDC, screenWidth, screenHeight);
    if (bitmap == NULL)
    {
        DeleteDC(memoryDC);
        ReleaseDC(NULL, screenDC);
        return "";
    }

    HBITMAP oldBitmap = (HBITMAP)SelectObject(memoryDC, bitmap);

    bool captured = BitBlt(
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
        SelectObject(memoryDC, oldBitmap);
        DeleteObject(bitmap);
        DeleteDC(memoryDC);
        ReleaseDC(NULL, screenDC);
        return "";
    }

    string imageFile = "screen_ocr.bmp";
    saveBitmap(bitmap, memoryDC, screenWidth, screenHeight, imageFile);

    SelectObject(memoryDC, oldBitmap);
    DeleteObject(bitmap);
    DeleteDC(memoryDC);
    ReleaseDC(NULL, screenDC);

    // Run Tesseract with low priority
    string command = "tesseract screen_ocr.bmp ocr_result --psm 6 >nul 2>&1";
    int result = system(command.c_str());

    // Clean up temporary bmp immediately
    remove(imageFile.c_str());

    if (result != 0)
    {
        // Don't spam if Tesseract is not installed
        tesseractAvailable = false;
        cout << "[OCR Notice] Tesseract CLI not available in PATH. Delegating to AI vision bridge." << endl;
        return "";
    }

    ifstream ocrFile("ocr_result.txt");
    if (!ocrFile)
    {
        return "";
    }

    string text;
    string line;
    while (getline(ocrFile, line))
    {
        text += line + " ";
    }
    ocrFile.close();

    // Clean up temporary txt result
    remove("ocr_result.txt");

    return text;
}
