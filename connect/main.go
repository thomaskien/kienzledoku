// kienzleconnect is a launcher and a session-scoped HTTP credential proxy.
// FHIR bodies, patient selection and write decisions belong to Record.
package main

import (
	"bufio"
	"context"
	"crypto/rand"
	"crypto/subtle"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// Public T2med integration key; a private release key is supplied at build time
// using -ldflags -X main.apiKey=... and never included in the source tree.
var apiKey = "7QwA7931lJSQfMKuTH4MQXLn4YEiNhE5tggnYKlY4HE"

const capabilityHeader = "X-Kienzledoku-Connect-Token"

type proxyConfig struct {
	Target           string `json:"target"`
	CAFile           string `json:"ca_file"`
	AllowInsecureTLS bool   `json:"allow_insecure_tls"`
}

func targetURL(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Opaque != "" {
		return nil, errors.New("ungueltiges HTTPS-FHIR-Ziel")
	}
	if strings.TrimRight(u.Path, "/") != "/aps/fhir/api/r4" || u.RawPath != "" {
		return nil, errors.New("ungueltiger FHIR-Basispfad")
	}
	if _, err = net.LookupPort("tcp", portOrDefault(u)); err != nil {
		return nil, errors.New("ungueltiger Port")
	}
	u.Path = strings.TrimRight(u.Path, "/")
	return u, nil
}
func portOrDefault(u *url.URL) string {
	if u.Port() != "" {
		return u.Port()
	}
	return "443"
}

func safePath(raw string) bool {
	for i := 0; i < 4; i++ {
		if strings.ContainsAny(raw, "\\\r\n\x00") || strings.HasPrefix(raw, "//") {
			return false
		}
		for _, p := range strings.Split(raw, "/") {
			if p == "." || p == ".." {
				return false
			}
		}
		decoded, err := url.PathUnescape(raw)
		if err != nil {
			return false
		}
		if decoded == raw {
			return true
		}
		raw = decoded
	}
	return false
}

func proxyHandler(target *url.URL, token, localHost string, transport http.RoundTripper) http.Handler {
	proxy := &httputil.ReverseProxy{
		Rewrite: func(p *httputil.ProxyRequest) {
			p.Out.URL.Scheme = target.Scheme
			p.Out.URL.Host = target.Host
			p.Out.Host = target.Host
			suffix := p.In.URL.Path
			rawSuffix := p.In.URL.EscapedPath()
			if suffix == "/" {
				suffix = ""
				rawSuffix = ""
			}
			p.Out.URL.Path = target.Path + suffix
			p.Out.URL.RawPath = target.EscapedPath() + rawSuffix
			p.Out.URL.RawQuery = p.In.URL.RawQuery // preserve exact query encoding
			p.Out.URL.ForceQuery = p.In.URL.ForceQuery
			for key := range p.Out.Header {
				if strings.EqualFold(key, "X-API-Key") || strings.EqualFold(key, capabilityHeader) || strings.EqualFold(key, "Forwarded") || strings.HasPrefix(strings.ToLower(key), "x-forwarded-") {
					delete(p.Out.Header, key)
				}
			}
			p.Out.Header.Set("X-API-Key", apiKey)
		},
		Transport: transport,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Cache-Control", "no-store")
			w.WriteHeader(http.StatusBadGateway)
			io.WriteString(w, `{"error":"connect_transport","message":"T2med-Antwort fehlt. Schreibausgang in T2med pruefen; nicht automatisch wiederholen."}`)
		},
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		supplied := r.Header.Values(capabilityHeader)
		if r.Host != localHost || len(supplied) != 1 || subtle.ConstantTimeCompare([]byte(supplied[0]), []byte(token)) != 1 || r.Header.Get("Origin") != "" {
			http.Error(w, "Connect-Zugriff verweigert", http.StatusForbidden)
			return
		}
		if r.URL.IsAbs() || !safePath(r.URL.EscapedPath()) || r.Header.Get("Upgrade") != "" {
			http.Error(w, "Ungueltiger Request", http.StatusBadRequest)
			return
		}
		switch r.Method {
		case "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS":
		default:
			http.Error(w, "Methode nicht erlaubt", http.StatusMethodNotAllowed)
			return
		}
		// Connection-nominated credential headers must not silently remove OAuth.
		for _, value := range r.Header.Values("Connection") {
			for _, name := range strings.Split(value, ",") {
				name = strings.TrimSpace(name)
				if strings.EqualFold(name, "Authorization") || strings.EqualFold(name, "X-API-Key") || strings.EqualFold(name, capabilityHeader) {
					http.Error(w, "Ungueltige Verbindungsheader", http.StatusBadRequest)
					return
				}
			}
		}
		ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
		defer cancel()
		proxy.ServeHTTP(w, r.WithContext(ctx))
	})
}

func serve(input io.Reader, output io.Writer) error {
	reader := bufio.NewReaderSize(input, 32769)
	line, err := reader.ReadSlice('\n')
	if err != nil || len(line) > 32768 {
		return errors.New("ungueltiger Startauftrag")
	}
	var cfg proxyConfig
	decoder := json.NewDecoder(strings.NewReader(string(line)))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&cfg) != nil {
		return errors.New("ungueltiger Startauftrag")
	}
	target, err := targetURL(cfg.Target)
	if err != nil {
		return err
	}
	tlsConfig := &tls.Config{MinVersion: tls.VersionTLS12, InsecureSkipVerify: cfg.AllowInsecureTLS} // explicit installation-only exception
	if cfg.CAFile != "" {
		roots, e := x509.SystemCertPool()
		if e != nil {
			roots = x509.NewCertPool()
		}
		pem, e := os.ReadFile(cfg.CAFile)
		if e != nil || !roots.AppendCertsFromPEM(pem) {
			return errors.New("CA-Zertifikat kann nicht geladen werden")
		}
		tlsConfig.RootCAs = roots
	}
	transport := &http.Transport{Proxy: nil, TLSClientConfig: tlsConfig, DisableKeepAlives: true,
		DisableCompression: true, DialContext: (&net.Dialer{Timeout: 10 * time.Second}).DialContext,
		TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 30 * time.Second}
	// Disable keep-alive avoids transport replay on stale reused connections,
	// including POSTs with idempotency headers. No redirect-following client.
	defer transport.CloseIdleConnections()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return errors.New("lokale Schnittstelle nicht verfuegbar")
	}
	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(tokenBytes); err != nil {
		listener.Close()
		return err
	}
	token := base64.RawURLEncoding.EncodeToString(tokenBytes)
	server := &http.Server{Handler: proxyHandler(target, token, listener.Addr().String(), transport),
		ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 60 * time.Second, WriteTimeout: 65 * time.Second,
		IdleTimeout: 15 * time.Second, MaxHeaderBytes: 32768}
	defer server.Close()
	go server.Serve(listener)
	if err := json.NewEncoder(output).Encode(map[string]string{"url": "http://" + listener.Addr().String(), "token": token}); err != nil {
		return err
	}
	// Parent owns this session. Pipe closure ends the listener and credentials.
	io.Copy(io.Discard, reader)
	return nil
}

// A Windows release uses its bundled interpreter. A PATH lookup can resolve
// Microsoft's Python Store alias instead of Python, producing exit status 9009.
func recordRuntime(root, platform, override string) (string, string, error) {
	script := filepath.Join(root, "kienzledoku.py")
	if info, err := os.Stat(script); err != nil || !info.Mode().IsRegular() {
		message := "Die Record-Programmdateien fehlen neben Connect. Connect ist nur ein Baustein, kein Installer. "
		if platform == "windows" {
			message += "Bitte zuerst das Windows-Build-Paket entpacken und windows\\build.cmd ausfuehren, danach das erzeugte Record-Setup installieren."
		} else {
			message += "Bitte den Record-Installer fuer diese Plattform ausfuehren."
		}
		return "", "", errors.New(message)
	}
	if override != "" {
		if platform == "windows" {
			info, err := os.Stat(override)
			if !filepath.IsAbs(override) || err != nil || !info.Mode().IsRegular() {
				return "", "", errors.New("KIENZLEDOKU_PYTHON muss auf eine vorhandene Python-EXE mit absolutem Pfad zeigen. Alternativ die Variable entfernen und die gebuendelte Record-Laufzeit verwenden.")
			}
		}
		return override, script, nil
	}
	if platform == "windows" {
		python := filepath.Join(root, "runtime", "pythonw.exe")
		if info, err := os.Stat(python); err == nil && info.Mode().IsRegular() {
			return python, script, nil
		}
		return "", "", errors.New("Die gebuendelte Record-Laufzeit runtime\\pythonw.exe fehlt. Bitte das vollstaendige Record-Paket installieren. Die einzeln heruntergeladene Connect-EXE reicht nicht aus.")
	}
	for _, rel := range []string{"venv/bin/python3", ".venv/bin/python3"} {
		python := filepath.Join(root, filepath.FromSlash(rel))
		if info, err := os.Stat(python); err == nil && info.Mode().IsRegular() {
			return python, script, nil
		}
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		return "", "", errors.New("Python-Laufzeit fehlt. Bitte den Record-Installer fuer diese Plattform erneut ausfuehren.")
	}
	return python, script, nil
}

func launch(args []string) error {
	executable, err := os.Executable()
	if err != nil {
		return errors.New("Programmverzeichnis fehlt")
	}
	root := filepath.Dir(executable)
	if len(args) > 1 {
		return errors.New("ungueltiger Aufruf")
	}
	mode := "--settings"
	link := ""
	if len(args) == 1 {
		link = args[0]
		if len(link) > 65536 {
			return errors.New("Aufruf zu gross")
		}
		u, err := url.Parse(link)
		if err != nil || u.Scheme != "kienzledoku" || u.Host != "record" || (u.Path != "" && u.Path != "/") || u.User != nil || u.Fragment != "" {
			return errors.New("nur kienzledoku://record ist in dieser Version installiert")
		}
		mode = "--deep-link-stdin"
	}
	python, script, err := recordRuntime(root, runtime.GOOS, os.Getenv("KIENZLEDOKU_PYTHON"))
	if err != nil {
		return err
	}
	cmd := exec.Command(python, script, "--from-connect", mode)
	cmd.Dir = root
	cmd.Stdin = strings.NewReader(link)
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	if err := cmd.Start(); err != nil {
		return errors.New("Record konnte nicht gestartet werden")
	}
	if err := cmd.Wait(); err != nil {
		var status *exec.ExitError
		if errors.As(err, &status) {
			if status.ExitCode() == 9009 {
				return errors.New("Die konfigurierte Python-Laufzeit konnte Record nicht starten (Code 9009). Bitte die vollstaendige Record-Installation und gegebenenfalls KIENZLEDOKU_PYTHON pruefen.")
			}
			return fmt.Errorf("kienzledoku record wurde mit Fehlercode %d beendet. Bitte das Record-Diagnoseprotokoll pruefen.", status.ExitCode())
		}
		return errors.New("Der Record-Prozess konnte nicht abgeschlossen werden")
	}
	return nil
}
func main() {
	var err error
	if len(os.Args) == 2 && os.Args[1] == "--deep-link-stdin" {
		data, readErr := io.ReadAll(io.LimitReader(os.Stdin, 65537))
		if readErr != nil || len(data) > 65536 {
			reportError("ungueltiger Aufruf")
			os.Exit(1)
		}
		err = launch([]string{string(data)})
		if err != nil {
			reportError(err.Error())
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 2 && os.Args[1] == "serve-stdio" {
		err = serve(os.Stdin, os.Stdout)
	} else {
		err = launch(os.Args[1:])
	}
	if err != nil {
		reportError(err.Error())
		os.Exit(1)
	}
}
