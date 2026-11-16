package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeCommander struct {
	mu                                                sync.Mutex
	sid, model, mode                                  string
	ended                                             bool
	jobs                                              map[string]Obj
	seen                                              map[string]bool
	order                                             []string
	active, peak                                      int
	delay                                             time.Duration
	failAt                                            int
	server                                            *httptest.Server
	lastCall                                          time.Time
	noToken                                           bool
	omitLoadEvents                                    bool
	sessionRequests, maxSessionRequests, requestLimit int
}

func fake(t *testing.T) *fakeCommander {
	f := &fakeCommander{jobs: map[string]Obj{}, seen: map[string]bool{}, delay: time.Millisecond}
	f.server = httptest.NewServer(http.HandlerFunc(f.handle))
	t.Cleanup(f.server.Close)
	return f
}
func (f *fakeCommander) handle(w http.ResponseWriter, r *http.Request) {
	if (f.noToken && r.Header.Get("Authorization") != "") || (!f.noToken && r.Header.Get("Authorization") != "Bearer test-secret") {
		w.WriteHeader(401)
		writeJSON(w, Obj{"error": Obj{"code": "unauthorized"}})
		return
	}
	p := r.URL.Path
	if p == "/v1/runtime/capabilities" {
		writeJSON(w, Obj{"schema_version": 1, "hardware_inventory": true, "current_temperatures": true, "commander_version": "1.8", "benchmark_control": true, "benchmark_roles": []string{"llm", "asr"}})
		return
	}
	if p == "/v1/runtime/inventory" {
		writeJSON(w, Obj{"models": []Obj{{"id": "a", "label": "A", "available": true, "default": true, "parallel_available": true}, {"id": "b", "label": "B", "available": true, "parallel_available": true}}})
		return
	}
	if p == "/v1/runtime/hardware" {
		writeJSON(w, Obj{"cpu": Obj{"model": "Synthetic CPU", "physical_cores": 8, "logical_processors": 16}, "memory": Obj{"installed_bytes": 34359738368}, "board": Obj{"model": "Synthetic board"}, "storage": []Obj{{"model": "Synthetic SSD", "role": "system"}}, "system": Obj{"os": "Simulated"}})
		return
	}
	if p == "/v1/runtime/temperatures" {
		writeJSON(w, Obj{"sensors": []Obj{{"kind": "gpu", "name": "Simulated GPU", "status": "available", "value": 42, "measured_at": time.Now().Format(time.RFC3339Nano), "source": "test"}}})
		return
	}
	f.mu.Lock()
	if p == "/v1/benchmark/session" && r.Method == "POST" {
		var b Obj
		json.NewDecoder(r.Body).Decode(&b)
		f.sid = freshID()
		f.model = str(b["model_id"])
		f.mode = str(b["mode"])
		f.ended = false
		f.sessionRequests = 0
		f.order = append(f.order, f.model+":"+f.mode)
		writeJSON(w, Obj{"id": f.sid, "state": "active"})
		f.mu.Unlock()
		return
	}
	if r.Header.Get("X-Kienzledoku-Benchmark-Session") != f.sid {
		f.mu.Unlock()
		w.WriteHeader(400)
		writeJSON(w, Obj{})
		return
	}
	if p == "/v1/benchmark/session/end" {
		f.ended = true
		f.mu.Unlock()
		writeJSON(w, Obj{"state": "restoring"})
		return
	}
	if p == "/v1/benchmark/session" || p == "/v1/benchmark/session/keepalive" {
		state := "active"
		if f.ended {
			state = "completed"
		}
		f.mu.Unlock()
		writeJSON(w, Obj{"state": state})
		return
	}
	if strings.HasPrefix(p, "/v1/benchmark/jobs/") {
		v := f.jobs[strings.TrimPrefix(p, "/v1/benchmark/jobs/")]
		f.mu.Unlock()
		writeJSON(w, v)
		return
	}
	f.mu.Unlock()
	var b Obj
	id := r.Header.Get("Idempotency-Key")
	roleName := "asr"
	if strings.HasSuffix(p, "/chat/completions") {
		roleName = "llm"
		json.NewDecoder(r.Body).Decode(&b)
		id = str(b["request_id"])
		if len(arr(b["messages"])) != 2 {
			panic("bad messages")
		}
	}
	if roleName == "asr" {
		if e := r.ParseMultipartForm(2 << 20); e != nil {
			panic(e)
		}
		defer r.MultipartForm.RemoveAll()
		if r.FormValue("language") != "de" {
			panic("language")
		}
		file, _, e := r.FormFile("file")
		if e != nil {
			panic(e)
		}
		file.Close()
	}
	f.mu.Lock()
	if f.seen[id] || f.ended {
		f.mu.Unlock()
		w.WriteHeader(409)
		writeJSON(w, Obj{"error": Obj{"code": "conflict"}})
		return
	}
	f.seen[id] = true
	f.sessionRequests++
	if f.sessionRequests > f.maxSessionRequests {
		f.maxSessionRequests = f.sessionRequests
	}
	if f.requestLimit > 0 && f.sessionRequests > f.requestLimit {
		f.mu.Unlock()
		w.WriteHeader(429)
		writeJSON(w, Obj{"error": Obj{"code": "benchmark_request_limit"}})
		return
	}
	f.active++
	if f.active > f.peak {
		f.peak = f.active
	}
	model, mode, delay := f.model, f.mode, f.delay
	shouldFail := f.failAt > 0 && len(f.seen) == f.failAt
	f.lastCall = time.Now()
	f.mu.Unlock()
	start := float64(time.Now().UnixNano()) / 1e9
	time.Sleep(delay)
	end := float64(time.Now().UnixNano()) / 1e9
	m := Obj{"request_id": id, "model_id": model, "role": roleName, "return_complete": true, "inference_started_at": start, "completed_at": end, "inference_seconds": end - start, "model_changes": []Obj{{"role": "llm", "operation": "load", "success": true, "started_at": start - .001, "phase": "prepare", "seconds": .001}, {"role": "asr", "operation": "load", "success": true, "started_at": end, "phase": "return", "seconds": .001}}}
	// ASR is already resident after the LLM's return transition, just as in Commander.
	if mode == "parallel" || roleName == "asr" || f.omitLoadEvents {
		m["model_changes"] = []Obj{}
	}
	f.mu.Lock()
	f.jobs[id] = m
	f.active--
	f.mu.Unlock()
	if shouldFail {
		w.WriteHeader(502)
		writeJSON(w, Obj{"error": Obj{"code": "backend_failure"}})
		return
	}
	if roleName == "llm" {
		writeJSON(w, Obj{"choices": []Obj{{"finish_reason": "stop", "message": Obj{"content": `{"anamnese":"a","befund":"b","therapie":"t","prozedere":"p"}`}}}, "benchmark": m})
	} else {
		writeJSON(w, Obj{"text": "synthetic husten", "decoder": expectedDecoder, "benchmark": m})
	}
}
func connected(t *testing.T, f *fakeCommander) *App {
	t.Helper()
	a := newApp(context.Background(), t.TempDir())
	a.drainTimeout = time.Second * 3
	if e := a.connect(context.Background(), Connection{URL: f.server.URL, Token: "test-secret"}); e != nil {
		t.Fatal(e)
	}
	return a
}
func awaitDone(t *testing.T, a *App) {
	t.Helper()
	select {
	case <-a.done:
	case <-time.After(15 * time.Second):
		a.abort()
		t.Fatal("runner timeout")
	}
}
func TestFullSequentialMatrixAndWhisper(t *testing.T) {
	f := fake(t)
	a := connected(t, f)
	if e := a.start(Config{Models: []string{"a", "b"}, Modes: []string{"serial", "parallel"}, Whisper: true}); e != nil {
		t.Fatal(e)
	}
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Abgeschlossen" {
		t.Fatalf("%s %v", s.Status, s.Errors)
	}
	if len(s.Results) != 60 {
		t.Fatalf("results %d", len(s.Results))
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.peak != 1 {
		t.Fatalf("models ran concurrently: %d", f.peak)
	}
	want := "a:serial,a:parallel,b:serial,b:parallel,a:serial,a:parallel"
	if strings.Join(f.order, ",") != want {
		t.Fatal(f.order)
	}
	if len(f.seen) != 48+6+156 {
		t.Fatalf("fresh request count %d", len(f.seen))
	}
	if !f.ended {
		t.Fatal("not restored")
	}
	data, e := os.ReadFile(s.Saved)
	if e != nil {
		t.Fatal(e)
	}
	for _, v := range []string{"Synthetic CPU", "Synthetic board", "Synthetic SSD", "32,00 GiB", "Median", "G60_30B", "Husten", "03 SERIELLER BETRIEB", "04 PARALLELER BETRIEB"} {
		if !strings.Contains(string(data), v) {
			t.Error(v)
		}
	}
	if strings.Contains(string(data), "test-secret") {
		t.Fatal("token leaked")
	}
}
func TestFailureRetainedNoReplacement(t *testing.T) {
	f := fake(t)
	f.failAt = 3
	a := connected(t, f)
	a.start(Config{Models: []string{"a"}, Modes: []string{"parallel"}})
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Beendet mit Fehlern" || len(s.Results) != 12 || s.Results[2].Error == "" {
		t.Fatalf("%s %+v", s.Status, s.Results)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.seen) != 12 {
		t.Fatal("retry hid failure")
	}
}
func TestAbortRestores(t *testing.T) {
	f := fake(t)
	f.delay = 100 * time.Millisecond
	a := connected(t, f)
	a.start(Config{Models: []string{"a"}, Modes: []string{"serial"}})
	time.Sleep(30 * time.Millisecond)
	a.abort()
	awaitDone(t, a)
	if a.snapshot().Status != "Abgebrochen – Teilbericht" {
		t.Fatal(a.snapshot().Status)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.ended {
		t.Fatal("session left open")
	}
}
func TestThermalOverlapBoundariesAndCooldown(t *testing.T) {
	f := fake(t)
	f.delay = 12 * time.Millisecond
	a := connected(t, f)
	a.minuteDuration = 12 * time.Millisecond
	a.heatDuration = 30 * a.minuteDuration
	a.pollDuration = 3 * time.Millisecond
	ctx, cancel := context.WithCancel(context.Background())
	tempDone := make(chan struct{})
	defer func() { cancel(); <-tempDone }()
	go func() { defer close(tempDone); a.temperatures(ctx) }()
	a.start(Config{Heat: true, HeatModel: "b", HeatMode: "parallel"})
	awaitDone(t, a)
	time.Sleep(35 * time.Millisecond)
	s := a.snapshot()
	f.mu.Lock()
	peak := f.peak
	last := f.lastCall
	f.mu.Unlock()
	if peak != 2 {
		t.Fatalf("no true overlap: %d", peak)
	}
	if last.After(s.HeatStarted.Add(a.heatDuration + 15*time.Millisecond)) {
		t.Fatal("new work after deadline")
	}
	seen := map[int]bool{}
	cool := false
	for _, m := range s.Minutes {
		if m.Phase == "Last" {
			if seen[m.Minute] {
				t.Fatal("duplicate minute")
			}
			seen[m.Minute] = true
		}
		if m.Phase == "Nachkühlung" {
			cool = true
		}
	}
	if !seen[0] || !seen[30] || !cool {
		t.Fatalf("boundaries %v cooldown %v", seen, cool)
	}
	if s.Config.HeatModel != "b" {
		t.Fatal("default model used")
	}
}
func TestFixtures(t *testing.T) {
	want := map[string]string{"G60_01A.txt": "ddd201525e3560279765c14bc6713f90777bb4004880411896837fe15ae0c232", "G60_30B.txt": "60119716b2a8f7f321df3c4b4b974303dfeae0958837ffd9e060a9a4d32258b1", "prompt_documentation.txt": "c402ac6a9e8e8111ab5b0405cf53f6009a9fdb4ac1d12fd83e97e5cf9b72a153", "husten.pcm": "38f620f4549bbd4820e229e03fac4462fb076e1fa4e84a4a55424eaf9438db8a"}
	for n, w := range want {
		b, _ := assets.ReadFile("assets/" + n)
		h := sha256.Sum256(b)
		if hex.EncodeToString(h[:]) != w {
			t.Fatal(n)
		}
	}
	if len(audioBlocks()) != 13 {
		t.Fatal("block count")
	}
}
func TestPortableWritesAndReadOnly(t *testing.T) {
	dir := t.TempDir()
	s := Store{Dir: dir}
	s.saveSettings("http://localhost:8185")
	got, bad := s.settings()
	if bad || got.URL != "http://localhost:8185" {
		t.Fatal(got, bad)
	}
	when := time.Now()
	if !s.saveReport("first", when) {
		t.Fatal("write")
	}
	path := s.ReportPath
	s.saveReport("updated", when)
	b, _ := os.ReadFile(path)
	if string(b) != "updated" {
		t.Fatal("update")
	}
	other := Store{Dir: dir}
	other.saveReport("second", when)
	if path == other.ReportPath {
		t.Fatal("collision")
	}
	os.Chmod(dir, 0500)
	defer os.Chmod(dir, 0700)
	s.saveSettings("http://newhost:8185")
	if s.saveReport("forbidden", when) {
		t.Fatal("read-only written")
	}
	b, _ = os.ReadFile(path)
	if string(b) != "updated" {
		t.Fatal("report damaged")
	}
	got, _ = s.settings()
	if got.URL != "http://localhost:8185" {
		t.Fatal("settings damaged")
	}
}
func TestCorruptSettingsPreserved(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, ".kienzlebench.json")
	os.WriteFile(p, []byte("broken"), 0600)
	s := Store{Dir: dir}
	s.saveSettings("http://localhost:1")
	b, _ := os.ReadFile(p)
	if string(b) != "broken" {
		t.Fatal("corrupt settings overwritten")
	}
}
func TestURLAndRedirectTokenProtection(t *testing.T) {
	for _, bad := range []string{"file:///tmp/a", "http://user:secret@host", "http://host?token=x", "http://host/path"} {
		if _, e := validURL(bad); e == nil {
			t.Fatal(bad)
		}
	}
	received := false
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { received = true }))
	defer target.Close()
	source := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 302) }))
	defer source.Close()
	c, _ := newClient(source.URL, "secret")
	if _, e := c.get(context.Background(), "/foo"); e == nil {
		t.Fatal("redirect accepted")
	}
	if received {
		t.Fatal("credentials forwarded")
	}
}
func TestWebRejectsForeignOriginAndHost(t *testing.T) {
	a := newApp(context.Background(), t.TempDir())
	web := &Web{app: a, prefix: "/secret/", host: "127.0.0.1:1234"}
	for _, tc := range []struct{ host, origin, token string }{{"evil.test", "", "secret"}, {web.host, "http://evil.test", "secret"}, {web.host, "", "wrong"}} {
		r := httptest.NewRequest("POST", "http://"+tc.host+"/secret/api/abort", strings.NewReader("{}"))
		r.Header.Set("Origin", tc.origin)
		r.Header.Set("X-Kienzlebench", tc.token)
		w := httptest.NewRecorder()
		web.handler(w, r)
		if w.Code < 400 {
			t.Fatal(tc)
		}
	}
}
func TestNoInventedSerialTiming(t *testing.T) {
	m := Obj{"inference_seconds": 2.0, "inference_started_at": 10.0, "completed_at": 12.0}
	if v, _ := llmSeconds(m, "serial"); v != nil {
		t.Fatal("claimed fresh load")
	}
	v, _ := llmSeconds(m, "parallel")
	if v == nil || *v != 2 {
		t.Fatal(v)
	}
}
func TestStateNeverExportsToken(t *testing.T) {
	f := fake(t)
	a := connected(t, f)
	b, _ := json.Marshal(a.snapshot())
	if strings.Contains(string(b), "test-secret") {
		t.Fatal("secret in browser state")
	}
	_ = fmt.Sprint(b)
}
