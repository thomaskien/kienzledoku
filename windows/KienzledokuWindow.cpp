#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <shobjidl.h>
#include <wtsapi32.h>
#include <wrl.h>
#include <string>
#include "WebView2.h"
using Microsoft::WRL::ComPtr;
using Microsoft::WRL::Callback;
static HWND windowHandle;
static ComPtr<ICoreWebView2Controller> controller;
static ComPtr<ICoreWebView2> webview;
static std::wstring startURL, origin, profileDirectory;
static bool ready = false;

static bool sameOrigin(const wchar_t* value) {
    if (!value) return false;
    std::wstring url(value);
    return url.rfind(origin + L"/", 0) == 0 || url == origin;
}
static void fail(const wchar_t* text) {
    MessageBoxW(windowHandle, text, L"kienzledoku record 1.3.3", MB_OK | MB_ICONERROR);
    DestroyWindow(windowHandle);
}
static LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
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
        if (ready && webview) {
            webview->ExecuteScript(L"window.dispatchEvent(new Event('kienzledoku-close-request'));", nullptr);
        } else if (MessageBoxW(hwnd,L"Fenster schließen? Bereits vorhandene Arbeit wird beim nächsten Start zur Wiederherstellung angeboten.",L"kienzledoku record",MB_YESNO | MB_ICONQUESTION)==IDYES) {
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
    if (std::wstring(args[1]) != L"--url-stdin") { LocalFree(args); return 2; }
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
    SetCurrentProcessExplicitAppUserModelID(L"de.kienzledoku.record");
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
    int width=min(1440,work.right-work.left-40), height=min(960,work.bottom-work.top-40);
    windowHandle=CreateWindowExW(0,wc.lpszClassName,L"kienzledoku record 1.3.3",WS_OVERLAPPEDWINDOW,
        work.left+20,work.top+20,width,height,nullptr,nullptr,instance,nullptr);
    if (!windowHandle) { CoUninitialize(); return 1; }
    WTSRegisterSessionNotification(windowHandle,NOTIFY_FOR_THIS_SESSION);
    ShowWindow(windowHandle,show); UpdateWindow(windowHandle);
    HRESULT result=CreateCoreWebView2EnvironmentWithOptions(nullptr,profileDirectory.c_str(),nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
        [](HRESULT hr,ICoreWebView2Environment* environment)->HRESULT {
            if (FAILED(hr) || !environment) { fail(L"WebView2 Runtime fehlt oder konnte nicht gestartet werden. Bitte die Microsoft Edge WebView2 Runtime installieren."); return S_OK; }
            return environment->CreateCoreWebView2Controller(windowHandle,
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
                                if (uri && (std::wstring(uri)==L"https://kienzledoku.de/" || std::wstring(uri)==L"https://kienzledoku.de"))
                                    ShellExecuteW(nullptr,L"open",uri,nullptr,nullptr,SW_SHOWNORMAL);
                            }
                            CoTaskMemFree(uri); return S_OK;
                        }).Get(),&token);
                    webview->add_NewWindowRequested(Callback<ICoreWebView2NewWindowRequestedEventHandler>(
                        [](ICoreWebView2*,ICoreWebView2NewWindowRequestedEventArgs* e)->HRESULT { e->put_Handled(TRUE); return S_OK; }).Get(),&token);
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
                                if (SUCCEEDED(e->TryGetWebMessageAsString(&message)) && message && std::wstring(message)==L"record-close") DestroyWindow(windowHandle);
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
