#pragma once
// The WebView2 callbacks only require IUnknown. Keep the native build usable
// with both MSVC and LLVM-MinGW without depending on WRL's MSVC-only helpers.
#include <atomic>
#include <utility>
#include <wrl/client.h>
template<class Interface, class Function, class Signature> class ComCallback;
template<class Interface, class Function, class... Args>
class ComCallback<Interface, Function, HRESULT (STDMETHODCALLTYPE Interface::*)(Args...)> final : public Interface {
    std::atomic<ULONG> references{1};
    Function function;
public:
    explicit ComCallback(Function fn) : function(std::move(fn)) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid != __uuidof(IUnknown) && iid != __uuidof(Interface)) return E_NOINTERFACE;
        *out = static_cast<Interface*>(this); AddRef(); return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override {
        ULONG count = --references; if (!count) delete this; return count;
    }
    HRESULT STDMETHODCALLTYPE Invoke(Args... args) override { return function(args...); }
};
template<class Interface, class Function>
Microsoft::WRL::ComPtr<Interface> Callback(Function fn) {
    Microsoft::WRL::ComPtr<Interface> value;
    value.Attach(new ComCallback<Interface, Function, decltype(&Interface::Invoke)>(std::move(fn)));
    return value;
}
