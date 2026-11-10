package main

import (
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }
func TestRequestAndResponsePreserved(t *testing.T) {
	target, _ := targetURL("https://t2med.local:16567/aps/fhir/api/r4")
	for _, keys := range [][]string{nil, {""}, {"old"}, {"old", "other"}} {
		t.Run(strings.Join(keys, "-"), func(t *testing.T) {
			calls := 0
			handler := proxyHandler(target, "session-token", "127.0.0.1:9999", transportFunc(func(r *http.Request) (*http.Response, error) {
				calls++
				if r.URL.String() != "https://t2med.local:16567/aps/fhir/api/r4/Patient?identifier=a%7Cb&x=1&x=2" {
					t.Fatal(r.URL)
				}
				if r.Host != "t2med.local:16567" || r.Method != "POST" {
					t.Fatal("target/method changed")
				}
				if r.Header.Get("Authorization") != "Bearer oauth" || r.Header.Get("X-Fhir-Profile") != "profile" {
					t.Fatal("FHIR headers changed")
				}
				if len(r.Header.Values("X-API-Key")) != 1 || r.Header.Get("X-API-Key") != apiKey {
					t.Fatal("key not replaced")
				}
				if r.Header.Get(capabilityHeader) != "" || r.Header.Get("X-Forwarded-Host") != "" {
					t.Fatal("local credentials leaked")
				}
				body, _ := io.ReadAll(r.Body)
				if string(body) != "  {\"unparsed\": true}  " {
					t.Fatal("body changed")
				}
				return &http.Response{StatusCode: 422, Header: http.Header{"Content-Type": {"application/fhir+json"}, "X-Fhir-Result": {"unchanged"}}, Body: io.NopCloser(strings.NewReader(`{"resourceType":"OperationOutcome"}`))}, nil
			}))
			request := httptest.NewRequest("POST", "http://127.0.0.1:9999/Patient?identifier=a%7Cb&x=1&x=2", strings.NewReader("  {\"unparsed\": true}  "))
			request.URL.Scheme = ""
			request.URL.Host = "" // origin-form incoming HTTP
			request.Header["X-Api-Key"] = keys
			request.Header.Set(capabilityHeader, "session-token")
			request.Header.Set("Authorization", "Bearer oauth")
			request.Header.Set("X-FHIR-Profile", "profile")
			request.Header.Set("X-Forwarded-Host", "evil.example")
			reply := httptest.NewRecorder()
			handler.ServeHTTP(reply, request)
			if reply.Code != 422 || reply.Body.String() != `{"resourceType":"OperationOutcome"}` || calls != 1 {
				t.Fatalf("%d %s %d", reply.Code, reply.Body.String(), calls)
			}
		})
	}
}
func TestAuthenticationAndPaths(t *testing.T) {
	target, _ := targetURL("https://t2med.local/aps/fhir/api/r4")
	for _, test := range []struct{ path, host, token, origin, method, connection string }{
		{"/Patient", "127.0.0.1:9", "bad", "", "GET", ""},
		{"/Patient", "evil.example", "valid", "", "GET", ""},
		{"/Patient", "127.0.0.1:9", "valid", "https://evil.example", "GET", ""},
		{"/%2e%2e/private", "127.0.0.1:9", "valid", "", "GET", ""},
		{"/%252e%252e/private", "127.0.0.1:9", "valid", "", "GET", ""},
		{"//other/path", "127.0.0.1:9", "valid", "", "GET", ""},
		{"/Patient", "127.0.0.1:9", "valid", "", "CONNECT", ""},
		{"/Patient", "127.0.0.1:9", "valid", "", "POST", "Authorization"},
	} {
		handler := proxyHandler(target, "valid", "127.0.0.1:9", transportFunc(func(r *http.Request) (*http.Response, error) { t.Fatal("must not reach upstream"); return nil, nil }))
		request := httptest.NewRequest(test.method, "http://127.0.0.1:9"+test.path, nil)
		request.URL.Scheme = ""
		request.URL.Host = ""
		request.Host = test.host
		request.Header.Set(capabilityHeader, test.token)
		request.Header.Set("Origin", test.origin)
		request.Header.Set("Connection", test.connection)
		reply := httptest.NewRecorder()
		handler.ServeHTTP(reply, request)
		if reply.Code < 400 {
			t.Fatal("accepted invalid request")
		}
	}
}
func TestRootPostAndTransportFailureNeverRetried(t *testing.T) {
	target, _ := targetURL("https://t2med.local/aps/fhir/api/r4/")
	calls := 0
	handler := proxyHandler(target, "token", "127.0.0.1:9", transportFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Path != "/aps/fhir/api/r4" {
			t.Fatal(r.URL.Path)
		}
		return nil, errors.New("secret internal detail")
	}))
	req := httptest.NewRequest("POST", "/", strings.NewReader("{}"))
	req.Host = "127.0.0.1:9"
	req.Header.Set(capabilityHeader, "token")
	res := httptest.NewRecorder()
	handler.ServeHTTP(res, req)
	if calls != 1 || res.Code != 502 || strings.Contains(res.Body.String(), "secret") {
		t.Fatal(calls, res)
	}
}
func TestConfiguredTarget(t *testing.T) {
	for _, raw := range []string{"http://host/aps/fhir/api/r4", "https://user:pass@host/aps/fhir/api/r4", "https://host/aps/fhir/api/r4?x=1", "https://host/aps/fhir/api/r4/../../private", "https://host/not-fhir", "https://host:99999/aps/fhir/api/r4"} {
		if _, err := targetURL(raw); err == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
}
