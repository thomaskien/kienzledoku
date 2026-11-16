package main

import (
	"context"
	"embed"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"sync/atomic"
	"time"
)

//go:embed assets/*
var assets embed.FS

type Web struct {
	app          *App
	prefix, host string
	viewers      atomic.Int64
	lastView     atomic.Int64
	shutdown     chan struct{}
}

func (w *Web) handler(rw http.ResponseWriter, r *http.Request) {
	rw.Header().Set("Cache-Control", "no-store")
	rw.Header().Set("X-Content-Type-Options", "nosniff")
	rw.Header().Set("Referrer-Policy", "no-referrer")
	rw.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
	if r.Host != w.host || !strings.HasPrefix(r.URL.Path, w.prefix) {
		http.NotFound(rw, r)
		return
	}
	if origin := r.Header.Get("Origin"); origin != "" && origin != "http://"+w.host {
		http.Error(rw, "Fremder Ursprung", http.StatusForbidden)
		return
	}
	path := strings.TrimPrefix(r.URL.Path, w.prefix)
	if r.Method == "GET" && (path == "" || path == "app.js" || path == "style.css") {
		file := path
		typ := "text/html; charset=utf-8"
		if file == "" {
			file = "index.html"
		}
		if file == "app.js" {
			typ = "text/javascript; charset=utf-8"
		}
		if file == "style.css" {
			typ = "text/css; charset=utf-8"
		}
		b, e := assets.ReadFile("assets/" + file)
		if e != nil {
			http.NotFound(rw, r)
			return
		}
		rw.Header().Set("Content-Type", typ)
		rw.Write(b)
		return
	}
	if r.Method == "GET" && path == "api/events" {
		rw.Header().Set("Content-Type", "text/event-stream")
		rw.Header().Set("X-Accel-Buffering", "no")
		f, ok := rw.(http.Flusher)
		if !ok {
			return
		}
		w.viewers.Add(1)
		w.lastView.Store(time.Now().UnixNano())
		defer func() { w.viewers.Add(-1); w.lastView.Store(time.Now().UnixNano()) }()
		t := time.NewTicker(2 * time.Second)
		defer t.Stop()
		for {
			data, _ := json.Marshal(w.app.snapshot())
			if _, e := fmt.Fprintf(rw, "data: %s\n\n", data); e != nil {
				return
			}
			f.Flush()
			select {
			case <-r.Context().Done():
				return
			case <-t.C:
			}
		}
	}
	if r.Method == "GET" && path == "api/state" {
		writeJSON(rw, w.app.snapshot())
		return
	}
	if r.Method == "GET" && path == "api/details" {
		writeJSON(rw, Obj{"text": w.app.details()})
		return
	}
	if r.Method != "POST" || r.Header.Get("X-Kienzlebench") != strings.Trim(w.prefix, "/") {
		http.Error(rw, "Anfrage abgewiesen", http.StatusForbidden)
		return
	}
	var err error
	switch path {
	case "api/connect":
		var c Connection
		err = decode(rw, r, &c)
		if err == nil {
			err = w.app.connect(r.Context(), c)
		}
	case "api/start":
		var c Config
		err = decode(rw, r, &c)
		if err == nil {
			err = w.app.start(c)
		}
	case "api/abort":
		w.app.abort()
	case "api/save":
		w.app.mu.Lock()
		w.app.persistLocked()
		w.app.mu.Unlock()
	case "api/close":
		w.app.abort()
		select {
		case w.shutdown <- struct{}{}:
		default:
		}
	default:
		http.NotFound(rw, r)
		return
	}
	if err != nil {
		rw.WriteHeader(400)
		writeJSON(rw, Obj{"error": err.Error()})
		return
	}
	writeJSON(rw, Obj{"ok": true})
}
func decode(w http.ResponseWriter, r *http.Request, v any) error {
	r.Body = http.MaxBytesReader(w, r.Body, 32768)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		return fmt.Errorf("Ungültige Eingabe")
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return fmt.Errorf("Ungültige Eingabe")
	}
	return nil
}
func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	json.NewEncoder(w).Encode(v)
}
func main() {
	noOpen := flag.Bool("no-open", false, "Browser nicht automatisch öffnen (Prüfbetrieb)")
	stay := flag.Bool("stay", false, "Ohne Browserfenster weiterlaufen (Prüfbetrieb)")
	showVersion := flag.Bool("version", false, "Version ausgeben")
	flag.Parse()
	if *showVersion {
		fmt.Println("Kienzlebench " + version)
		return
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	a := newApp(ctx, programDir())
	listener, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		fmt.Fprintln(os.Stderr, "Kienzlebench: Lokales Fenster konnte nicht geöffnet werden.")
		return
	}
	w := &Web{app: a, prefix: "/" + freshID() + freshID() + "/", host: listener.Addr().String(), shutdown: make(chan struct{}, 1)}
	server := &http.Server{Handler: http.HandlerFunc(w.handler), ReadHeaderTimeout: 5 * time.Second, MaxHeaderBytes: 16 << 10, IdleTimeout: 30 * time.Second}
	tempDone := make(chan struct{})
	go func() { defer close(tempDone); a.temperatures(ctx) }()
	go server.Serve(listener)
	url := "http://" + w.host + w.prefix
	fmt.Println("Kienzlebench " + version + " · " + url)
	if !*noOpen {
		if e = openBrowser(url); e != nil {
			fmt.Println("Bitte die angezeigte lokale Adresse im Browser öffnen.")
		}
	}
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt)
	defer signal.Stop(sig)
	tick := time.NewTicker(time.Second)
	defer tick.Stop()
	start := time.Now()
loop:
	for {
		select {
		case <-sig:
			break loop
		case <-w.shutdown:
			break loop
		case <-tick.C:
			if !*stay && w.viewers.Load() == 0 {
				last := w.lastView.Load()
				if last != 0 && time.Since(time.Unix(0, last)) > 40*time.Second {
					break loop
				}
				if last == 0 && time.Since(start) > 5*time.Minute {
					break loop
				}
			}
		}
	}
	a.abort()
	a.mu.Lock()
	running := a.st.Running
	done := a.done
	a.mu.Unlock()
	if running {
		select {
		case <-done:
		case <-time.After(25 * time.Second):
			a.mu.Lock()
			a.st.Status = "Abgebrochen beim Schließen – Wiederherstellung noch nicht bestätigt"
			a.st.Errors = append(a.st.Errors, "Fenster geschlossen; aktive Anfragen laufen serverseitig begrenzt aus. Commander-Lease beendet die Sitzung spätestens nach 120 s ohne Verlängerung.")
			a.persistLocked()
			a.mu.Unlock()
		}
	}
	a.mu.Lock()
	a.persistLocked()
	a.mu.Unlock()
	cancel()
	select {
	case <-tempDone:
	case <-time.After(time.Second):
	}
	sc, cc := context.WithTimeout(context.Background(), 2*time.Second)
	defer cc()
	server.Shutdown(sc)
}
