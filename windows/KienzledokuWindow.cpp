#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#ifndef WINVER
#define WINVER 0x0A00
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#include <windows.h>
#include <shellapi.h>
#include <shobjidl.h>
#include <wtsapi32.h>
#include <wrl/client.h>
#include <algorithm>
#include "ComCallback.h"
#include <string>
#include "WebView2.h"
#include "WebView2UUIDs.h"
using Microsoft::WRL::ComPtr;

static HWND windowHandle;
static ComPtr<ICoreWebView2Controller> controller;
static ComPtr<ICoreWebView2> webview;
static std::wstring startURL, origin, profileDirectory;
static bool ready = false;
static bool installerMode = false, installerBusy = false;
static constexpr int minimumContentWidth = 1100; // Logical pixels, before display scaling.

static bool sameOrigin(const wchar_t* value) {
    if (!value) return false;
    std::wstring url(value);
    return url.rfind(origin + L"/", 0) == 0 || url == origin;
}
static void fail(const wchar_t* text) {
    MessageBoxW(windowHandle, text, L"kienzledoku record 1.8.3", MB_OK | MB_ICONERROR);
    DestroyWindow(windowHandle);
}
static LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_GETMINMAXINFO: {
        UINT dpi = GetDpiForWindow(hwnd);
        if (!dpi) dpi = 96;
        RECT minimum = {0, 0, MulDiv(minimumContentWidth, dpi, 96), 0};
        AdjustWindowRectExForDpi(&minimum, WS_OVERLAPPEDWINDOW, FALSE, 0, dpi);
        LONG width = minimum.right - minimum.left;
        MONITORINFO monitor = {sizeof(monitor)};
        if (GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &monitor))
            width = (std::min)(width, monitor.rcWork.right - monitor.rcWork.left);
        reinterpret_cast<MINMAXINFO*>(lp)->ptMinTrackSize.x = width;
        return 0;
    }
    case WM_PAINT:
        if (installerMode && !ready) {
            PAINTSTRUCT paint; HDC dc=BeginPaint(hwnd,&paint); RECT bounds;GetClientRect(hwnd,&bounds);
            FillRect(dc,&bounds,(HBRUSH)GetStockObject(WHITE_BRUSH));SetBkMode(dc,TRANSPARENT);
            DrawTextW(dc,L"Installationsassistent wird geladen …",-1,&bounds,DT_CENTER|DT_VCENTER|DT_SINGLELINE);
            EndPaint(hwnd,&paint);return 0;
        }
        break;
    case WM_SIZE:
        if (controller) { RECT rect; GetClientRect(hwnd, &rect); controller->put_Bounds(rect); }
        return 0;
    case WM_DPICHANGED: {
        RECT* rect = reinterpret_cast<RECT*>(lp);
        SetWindowPos(hwnd, nullptr, rect->left, rect->top, rect->right-rect->left, rect->bottom-rect->top, SWP_NOZORDER | SWP_NOACTIVATE);
        return 0;
    }
    case WM_SETFOCUS:
        if (controller) controller->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
        return 0;
    case WM_CLOSE:
        if (installerMode) {
            if (installerBusy) MessageBoxW(hwnd,L"Ein Installationsschritt läuft. Bitte den Abschluss abwarten.",L"kienzledoku installieren",MB_OK|MB_ICONINFORMATION);
            else DestroyWindow(hwnd);
            return 0;
        }
        if (ready && webview) {
            webview->ExecuteScript(L"window.dispatchEvent(new Event('kienzledoku-close-request'));", nullptr);
        } else if (MessageBoxW(hwnd,L"Fenster schließen und Aufnahme verwerfen? Nicht übernommene Inhalte gehen verloren.",L"kienzledoku record",MB_YESNO | MB_ICONQUESTION)==IDYES) {
            DestroyWindow(hwnd);
        }
        return 0;
    case WM_WTSSESSION_CHANGE:
        if (webview && (wp == WTS_REMOTE_DISCONNECT || wp == WTS_SESSION_LOCK)) {
            webview->ExecuteScript(L"window.dispatchEvent(new Event('kienzledoku-audio-interrupted'));", nullptr);
        }
        return 0;
    case WM_DESTROY:
        WTSUnRegisterSessionNotification(hwnd);
        if (controller) controller->Close();
        webview.Reset(); controller.Reset();
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd,msg,wp,lp);
}

int WINAPI wWinMain(HINSTANCE instance,HINSTANCE, PWSTR,int show) {
    int count=0;
    LPWSTR* args=CommandLineToArgvW(GetCommandLineW(), &count);
    if (count < 3 || count > 4) { LocalFree(args); return 2; }
    installerMode = std::wstring(args[1]) == L"--installer";
    if (!installerMode && std::wstring(args[1]) != L"--url-stdin") { LocalFree(args); return 2; }
    profileDirectory=args[2];
    std::wstring iconPath=count==4 ? args[3] : L"";
    LocalFree(args);
    char privateURL[8192]; DWORD received=0;
    if (!ReadFile(GetStdHandle(STD_INPUT_HANDLE),privateURL,sizeof(privateURL)-1,&received,nullptr) || received==0) return 2;
    privateURL[received]=0;
    std::string encoded(privateURL);
    encoded=encoded.substr(0,encoded.find_first_of("\r\n"));
    int length=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,encoded.data(),static_cast<int>(encoded.size()),nullptr,0);
    if (length<=0) return 2;
    startURL.resize(length);
    MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,encoded.data(),static_cast<int>(encoded.size()),&startURL[0],length);
    const std::wstring prefix=L"http://127.0.0.1:";
    if (startURL.rfind(prefix,0)!=0) return 2;
    auto slash=startURL.find(L'/',prefix.size());
    if (slash==std::wstring::npos) return 2;
    std::wstring port=startURL.substr(prefix.size(),slash-prefix.size());
    if (port.empty() || port.find_first_not_of(L"0123456789")!=std::wstring::npos) return 2;
    origin=startURL.substr(0,slash);
    if (FAILED(CoInitializeEx(nullptr,COINIT_APARTMENTTHREADED))) return 1;
    SetCurrentProcessExplicitAppUserModelID(installerMode ? L"de.kienzledoku.installer" : L"de.kienzledoku.record");
    auto user32=GetModuleHandleW(L"user32.dll");
    auto setDpi=reinterpret_cast<BOOL(WINAPI*)(DPI_AWARENESS_CONTEXT)>(GetProcAddress(user32,"SetProcessDpiAwarenessContext"));
    if (setDpi) setDpi(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    HICON icon=static_cast<HICON>(LoadImageW(nullptr,iconPath.c_str(),IMAGE_ICON,0,0,LR_LOADFROMFILE | LR_DEFAULTSIZE));
    WNDCLASSEXW wc={sizeof(wc)};
    wc.hInstance=instance; wc.lpfnWndProc=WindowProc;
    wc.lpszClassName=L"KienzledokuRecordWindow"; wc.hCursor=LoadCursor(nullptr,IDC_ARROW);
    wc.hIcon=icon; wc.hIconSm=icon;
    if (!RegisterClassExW(&wc)) { CoUninitialize(); return 1; }
    RECT work; SystemParametersInfoW(SPI_GETWORKAREA,0,&work,0);
    UINT dpi=GetDpiForSystem();
    if (!dpi) dpi=96;
    int width=(std::min)(static_cast<LONG>(MulDiv(1440,dpi,96)),work.right-work.left), height=(std::min)(static_cast<LONG>(MulDiv(960,dpi,96)),work.bottom-work.top-40);
    windowHandle=CreateWindowExW(0,wc.lpszClassName,(installerMode ? L"kienzledoku installieren 1.8.3" : L"kienzledoku record 1.8.3"),WS_OVERLAPPEDWINDOW,
        work.left+(work.right-work.left-width)/2,work.top+20,width,height,nullptr,nullptr,instance,nullptr);
    if (!windowHandle) { CoUninitialize(); return 1; }
    WTSRegisterSessionNotification(windowHandle,NOTIFY_FOR_THIS_SESSION);
    ShowWindow(windowHandle,show);
    if (installerMode) { DWORD written=0; WriteFile(GetStdHandle(STD_OUTPUT_HANDLE),"WINDOW_READY\n",13,&written,nullptr); } UpdateWindow(windowHandle);
    HRESULT result=CreateCoreWebView2EnvironmentWithOptions(nullptr,profileDirectory.c_str(),nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
        [](HRESULT hr,ICoreWebView2Environment* environment)->HRESULT {
            if (FAILED(hr) || !environment) { fail(L"WebView2 Runtime fehlt oder konnte nicht gestartet werden. Bitte die Microsoft Edge WebView2 Runtime installieren."); return S_OK; }
            ComPtr<ICoreWebView2Environment10> privateEnvironment;
            ComPtr<ICoreWebView2ControllerOptions> options;
            if (FAILED(environment->QueryInterface(IID_PPV_ARGS(&privateEnvironment))) ||
                FAILED(privateEnvironment->CreateCoreWebView2ControllerOptions(&options)) ||
                FAILED(options->put_IsInPrivateModeEnabled(TRUE))) {
                fail(L"Bitte Microsoft Edge WebView2 aktualisieren. Ein privates Aufnahmefenster konnte nicht erstellt werden.");
                return E_FAIL;
            }
            return privateEnvironment->CreateCoreWebView2ControllerWithOptions(windowHandle,options.Get(),
                Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                [](HRESULT hr,ICoreWebView2Controller* created)->HRESULT {
                    if (FAILED(hr) || !created) { fail(L"Das Record-Fenster konnte nicht erzeugt werden."); return S_OK; }
                    controller=created; controller->get_CoreWebView2(&webview);
                    ComPtr<ICoreWebView2Settings> settings; webview->get_Settings(&settings);
                    settings->put_AreDevToolsEnabled(FALSE); settings->put_AreDefaultContextMenusEnabled(FALSE);
                    settings->put_IsStatusBarEnabled(FALSE); settings->put_IsWebMessageEnabled(TRUE);
                    RECT bounds; GetClientRect(windowHandle,&bounds); controller->put_Bounds(bounds);
                    EventRegistrationToken token;
                    webview->add_NavigationStarting(Callback<ICoreWebView2NavigationStartingEventHandler>(
                        [](ICoreWebView2*,ICoreWebView2NavigationStartingEventArgs* e)->HRESULT {
                            LPWSTR uri=nullptr; e->get_Uri(&uri);
                            if (!sameOrigin(uri)) {
                                e->put_Cancel(TRUE);
                                if (uri && (std::wstring(uri)==L"https://kienzledoku.de/" || std::wstring(uri)==L"https://kienzledoku.de" || (installerMode &&
                                    (std::wstring(uri).rfind(L"https://github.com/thomaskien/kienzledoku",0)==0 || std::wstring(uri)==L"https://huggingface.co/pyannote/speaker-diarization-community-1"))))
                                    ShellExecuteW(nullptr,L"open",uri,nullptr,nullptr,SW_SHOWNORMAL);
                            }
                            CoTaskMemFree(uri); return S_OK;
                        }).Get(),&token);
                    webview->add_NewWindowRequested(Callback<ICoreWebView2NewWindowRequestedEventHandler>(
                        [](ICoreWebView2*,ICoreWebView2NewWindowRequestedEventArgs* e)->HRESULT {
                            e->put_Handled(TRUE);
                            LPWSTR uri=nullptr; e->get_Uri(&uri);
                            if (installerMode && uri && (std::wstring(uri).rfind(L"https://github.com/thomaskien/kienzledoku",0)==0 || std::wstring(uri)==L"https://huggingface.co/pyannote/speaker-diarization-community-1"))
                                ShellExecuteW(nullptr,L"open",uri,nullptr,nullptr,SW_SHOWNORMAL);
                            CoTaskMemFree(uri); return S_OK;
                        }).Get(),&token);
                    webview->add_PermissionRequested(Callback<ICoreWebView2PermissionRequestedEventHandler>(
                        [](ICoreWebView2*,ICoreWebView2PermissionRequestedEventArgs* e)->HRESULT { e->put_State(COREWEBVIEW2_PERMISSION_STATE_DENY); return S_OK; }).Get(),&token);
                    webview->add_NavigationCompleted(Callback<ICoreWebView2NavigationCompletedEventHandler>(
                        [](ICoreWebView2*,ICoreWebView2NavigationCompletedEventArgs* e)->HRESULT { BOOL ok=FALSE; e->get_IsSuccess(&ok); ready=ok; return S_OK; }).Get(),&token);
                    webview->add_WindowCloseRequested(Callback<ICoreWebView2WindowCloseRequestedEventHandler>(
                        [](ICoreWebView2*,IUnknown*)->HRESULT { DestroyWindow(windowHandle); return S_OK; }).Get(),&token);
                    webview->add_WebMessageReceived(Callback<ICoreWebView2WebMessageReceivedEventHandler>(
                        [](ICoreWebView2*,ICoreWebView2WebMessageReceivedEventArgs* e)->HRESULT {
                            LPWSTR source=nullptr; e->get_Source(&source); bool allowed=sameOrigin(source); CoTaskMemFree(source);
                            if (allowed) {
                                LPWSTR message=nullptr;
                                if (SUCCEEDED(e->TryGetWebMessageAsString(&message)) && message) {
                                    std::wstring command(message);
                                    if (installerMode) {
                                        if (command==L"installer-busy") installerBusy=true;
                                        else if (command==L"installer-idle") installerBusy=false;
                                        else if (command==L"installer-close" && !installerBusy) DestroyWindow(windowHandle);
                                    } else if (command==L"record-close") DestroyWindow(windowHandle);
                                }
                                CoTaskMemFree(message);
                            }
                            return S_OK;
                        }).Get(),&token);
                    return webview->Navigate(startURL.c_str());
                }).Get());
        }).Get());
    if (FAILED(result)) fail(L"WebView2 konnte nicht geladen werden. Bitte Installation prüfen.");
    MSG message;
    while (GetMessageW(&message,nullptr,0,0)>0) { TranslateMessage(&message); DispatchMessageW(&message); }
    if (icon) DestroyIcon(icon);
    CoUninitialize();
    return 0;
}
