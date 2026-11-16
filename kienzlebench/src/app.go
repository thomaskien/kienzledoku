package main

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"
)

const version = "1.2"

type Config struct {
	Models    []string `json:"models"`
	Modes     []string `json:"modes"`
	Whisper   bool     `json:"whisper"`
	Heat      bool     `json:"heat"`
	HeatModel string   `json:"heat_model"`
	HeatMode  string   `json:"heat_mode"`
}
type Connection struct {
	URL      string `json:"url"`
	Token    string `json:"token"`
	LLMURL   string `json:"llm_url"`
	LLMToken string `json:"llm_token"`
}
type Reading struct {
	Host    string    `json:"host"`
	Fetched time.Time `json:"fetched"`
	Data    Obj       `json:"data"`
	Error   string    `json:"error,omitempty"`
}
type Minute struct {
	Phase    string    `json:"phase"`
	Minute   int       `json:"minute"`
	Elapsed  float64   `json:"elapsed"`
	Time     time.Time `json:"time"`
	Readings []Reading `json:"readings"`
}
type Result struct {
	Model       string   `json:"model"`
	Mode        string   `json:"mode"`
	Case        string   `json:"case"`
	Iteration   int      `json:"iteration"`
	Phase       string   `json:"phase"`
	Seconds     *float64 `json:"seconds"`
	HTTPSeconds float64  `json:"http_seconds"`
	Metrics     []Obj    `json:"metrics,omitempty"`
	Error       string   `json:"error,omitempty"`
	Note        string   `json:"note,omitempty"`
}
type State struct {
	Version          string       `json:"version"`
	URL              string       `json:"url"`
	SettingsWarning  bool         `json:"settings_warning"`
	Hosts            []Host       `json:"hosts"`
	Models           []Obj        `json:"models"`
	Connected        bool         `json:"connected"`
	Connecting       bool         `json:"connecting"`
	Running          bool         `json:"running"`
	Status           string       `json:"status"`
	Progress         string       `json:"progress"`
	Config           Config       `json:"config"`
	Started          time.Time    `json:"started"`
	Ended            time.Time    `json:"ended"`
	Results          []Result     `json:"results"`
	Minutes          []Minute     `json:"minutes"`
	Current          []Reading    `json:"current"`
	Errors           []string     `json:"errors"`
	Restorations     []Obj        `json:"restorations"`
	Saved            string       `json:"saved"`
	Report           string       `json:"report"`
	ReportParts      []ReportPart `json:"report_parts"`
	HeatStarted      time.Time    `json:"heat_started"`
	HeatEnded        time.Time    `json:"heat_ended"`
	HeatDrainSeconds float64      `json:"heat_drain_seconds"`
}
type App struct {
	mu                  sync.Mutex
	st                  State
	store               Store
	cancel              context.CancelFunc
	root                context.Context
	thermalWake         chan struct{}
	done                chan struct{}
	heatDuration        time.Duration
	minuteDuration      time.Duration
	pollDuration        time.Duration
	drainTimeout        time.Duration
	heatSessionRequests int
}

func newApp(ctx context.Context, dir string) *App {
	a := &App{root: ctx, store: Store{Dir: dir}, thermalWake: make(chan struct{}, 1), done: make(chan struct{}), heatDuration: 30 * time.Minute, minuteDuration: time.Minute, pollDuration: 5 * time.Second, drainTimeout: 20 * time.Minute}
	a.heatSessionRequests = 3800 // Below Commander's 4096 remembered request IDs per session.
	s, bad := a.store.settings()
	a.st = State{Version: version, URL: s.URL, SettingsWarning: bad, Status: "Bereit"}
	return a
}
func (a *App) connect(ctx context.Context, v Connection) error {
	a.mu.Lock()
	if a.st.Running || a.st.Connecting {
		a.mu.Unlock()
		return errors.New("Ein Vorgang läuft bereits.")
	}
	a.st.Connecting = true
	a.st.Connected = false
	a.persistLocked()
	a.mu.Unlock()
	defer func() { a.mu.Lock(); a.st.Connecting = false; a.mu.Unlock() }()
	c, e := newClient(v.URL, v.Token)
	if e != nil {
		return e
	}
	h, e := connectHost(ctx, c)
	if e != nil {
		return e
	}
	hosts := []Host{h}
	if v.LLMURL != "" {
		lc, e := newClient(v.LLMURL, v.LLMToken)
		if e != nil {
			return e
		}
		if lc.URL == c.URL {
			return errors.New("Die zweite Adresse muss einen anderen Commander bezeichnen.")
		}
		lh, e := connectHost(ctx, lc)
		if e != nil {
			return fmt.Errorf("LLM-Commander: %w", e)
		}
		hosts = append(hosts, lh)
	}
	target := hosts[len(hosts)-1]
	models := []Obj{}
	for _, v := range arr(target.Inventory["models"]) {
		models = append(models, obj(v))
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	// A new target begins a new report; never attach old results to new hardware.
	warning := a.st.SettingsWarning
	a.st = State{Version: version, SettingsWarning: warning, Connecting: true}
	a.store.ReportPath = ""
	a.st.Hosts = hosts
	a.st.Models = models
	a.st.URL = c.URL
	a.st.Connected = true
	a.st.Current = nil
	a.st.Status = "Verbunden"
	a.st.Progress = "Modelle auswählen und Tests starten."
	a.store.saveSettings(c.URL)
	select {
	case a.thermalWake <- struct{}{}:
	default:
	}
	return nil
}
func role(h Host, want string) bool {
	for _, r := range arr(h.Capabilities["benchmark_roles"]) {
		if str(r) == want {
			return true
		}
	}
	return false
}
func findModel(models []Obj, id string) Obj {
	for _, m := range models {
		if m["id"] == id {
			return m
		}
	}
	return nil
}
func validateConfig(c Config, s State) error {
	if !s.Connected || len(s.Hosts) == 0 {
		return errors.New("Zuerst mit einem Commander verbinden.")
	}
	if len(c.Models) == 0 && !c.Whisper && !c.Heat {
		return errors.New("Mindestens einen Test auswählen.")
	}
	if len(c.Models) > 0 && len(c.Modes) == 0 {
		return errors.New("Seriell und/oder parallel auswählen.")
	}
	seen := map[string]bool{}
	for _, mode := range c.Modes {
		if (mode != "serial" && mode != "parallel") || seen[mode] {
			return errors.New("Ungültige Betriebsart.")
		}
		seen[mode] = true
	}
	seen = map[string]bool{}
	for _, id := range c.Models {
		m := findModel(s.Models, id)
		if m == nil || !yes(m["available"]) || seen[id] {
			return errors.New("Modell nicht verfügbar oder doppelt ausgewählt.")
		}
		seen[id] = true
	}
	if c.Heat {
		m := findModel(s.Models, c.HeatModel)
		if m == nil || !yes(m["available"]) {
			return errors.New("Ein verfügbares LLM für den Wärmetest auswählen.")
		}
		if c.HeatMode != "serial" && c.HeatMode != "parallel" {
			return errors.New("Ungültige Wärmetest-Betriebsart.")
		}
		if c.HeatMode == "parallel" && !yes(m["parallel_available"]) {
			return errors.New("Wärmetest: dieses Modell hat kein freigegebenes Parallelprofil.")
		}
	}
	if (c.Whisper || c.Heat) && !role(s.Hosts[0], "asr") {
		return errors.New("Der erste Commander muss Whisper/ASR bereitstellen.")
	}
	if (len(c.Models) > 0 || c.Heat) && !role(s.Hosts[len(s.Hosts)-1], "llm") {
		return errors.New("Den getrennten LLM-Commander mit eigener Adresse verbinden; Token nur bei aktiviertem Zugangsschutz.")
	}
	for _, h := range s.Hosts {
		if !yes(h.Capabilities["benchmark_control"]) {
			return errors.New("Dieser Commander gibt die Benchmarksteuerung nicht frei. Für tokenfreien Zugriff wird der neue Commander benötigt.")
		}
	}
	return nil
}
func (a *App) start(c Config) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.st.Running || a.st.Connecting {
		return errors.New("Ein Vorgang läuft bereits.")
	}
	if e := validateConfig(c, a.st); e != nil {
		return e
	}
	a.persistLocked()
	a.st.Config = c
	a.st.Results = nil
	a.st.Errors = nil
	a.st.Restorations = nil
	a.st.Minutes = nil
	a.st.Saved = ""
	a.store.ReportPath = ""
	a.st.HeatStarted = time.Time{}
	a.st.HeatEnded = time.Time{}
	a.st.HeatDrainSeconds = 0
	a.st.Started = time.Now()
	a.st.Ended = time.Time{}
	a.st.Running = true
	a.st.Status = "Läuft"
	a.st.Progress = "Benchmarksitzung wird vorbereitet."
	ctx, cancel := context.WithCancel(a.root)
	a.cancel = cancel
	a.done = make(chan struct{})
	go a.run(ctx, c, append([]Host(nil), a.st.Hosts...))
	return nil
}
func (a *App) abort() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.cancel != nil && a.st.Running {
		a.st.Status = "Wird abgebrochen"
		a.cancel()
	}
}
func (a *App) progress(v string) { a.mu.Lock(); a.st.Progress = v; a.mu.Unlock() }
func (a *App) add(r Result)      { a.mu.Lock(); a.st.Results = append(a.st.Results, r); a.mu.Unlock() }
func (a *App) fail(e error) {
	if e == nil {
		return
	}
	a.mu.Lock()
	a.st.Errors = append(a.st.Errors, e.Error())
	a.mu.Unlock()
}
func (a *App) persistLocked() {
	if a.st.Started.IsZero() {
		return
	}
	body := report(a.st)
	if a.store.saveReport(body, a.st.Started) {
		a.st.Saved = a.store.ReportPath
	}
}
func (a *App) snapshot() State {
	a.mu.Lock()
	defer a.mu.Unlock()
	s := a.st
	s.ReportParts = reportParts(s)
	s.Report = joinReport(s.ReportParts)
	return s
}

func (a *App) details() string { a.mu.Lock(); defer a.mu.Unlock(); return technicalReport(a.st) }
func fetchTemperatures(ctx context.Context, hosts []Host) []Reading {
	out := make([]Reading, len(hosts))
	var wg sync.WaitGroup
	for i, h := range hosts {
		wg.Add(1)
		go func(i int, h Host) {
			defer wg.Done()
			data, e := h.client.get(ctx, "/v1/runtime/temperatures")
			r := Reading{Host: h.URL, Fetched: time.Now(), Data: data}
			if e != nil {
				r.Error = e.Error()
			}
			out[i] = r
		}(i, h)
	}
	wg.Wait()
	return out
}
func (a *App) temperatures(ctx context.Context) {
	timer := time.NewTimer(0)
	defer timer.Stop()
	var phaseKey string
	nextMinute := 0
	for {
		select {
		case <-ctx.Done():
			return
		case <-a.thermalWake:
		case <-timer.C:
		}
		a.mu.Lock()
		hosts := append([]Host(nil), a.st.Hosts...)
		runStart := a.st.Started
		runEnd := a.st.Ended
		a.mu.Unlock()
		readings := fetchTemperatures(ctx, hosts)
		if ctx.Err() != nil {
			return
		}
		now := time.Now()
		a.mu.Lock()
		// Skip observations belonging to a connection or run which changed during I/O.
		same := len(hosts) == len(a.st.Hosts) && runStart == a.st.Started
		for i, h := range hosts {
			if i >= len(a.st.Hosts) || h.client != a.st.Hosts[i].client {
				same = false
			}
		}
		if same {
			a.st.Current = readings
		}
		same = same && runEnd == a.st.Ended
		phase := ""
		start := time.Time{}
		if !runEnd.IsZero() {
			phase = "Nachkühlung"
			start = runEnd
		}
		key := phase + start.String()
		if phaseKey != key {
			phaseKey = key
			nextMinute = 0
		}
		if same && phase != "" && len(readings) > 0 {
			elapsed := now.Sub(start)
			minute := int(elapsed / a.minuteDuration)
			if minute >= nextMinute {
				// Never synthesize temperatures for missed boundaries.
				for n := nextMinute; n < minute; n++ {
					a.st.Minutes = append(a.st.Minutes, Minute{Phase: phase, Minute: n, Elapsed: -1})
				}
				a.st.Minutes = append(a.st.Minutes, Minute{phase, minute, elapsed.Seconds(), now, readings})
				nextMinute = minute + 1
				a.persistLocked()
			}
		}
		a.mu.Unlock()
		delay := a.pollDuration
		if phase != "" {
			d := time.Until(start.Add(time.Duration(nextMinute) * a.minuteDuration))
			if d > 0 && d < delay {
				delay = d
			}
		}
		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
		timer.Reset(delay)
	}
}

// Separate boundary clock: a 5-second live poll must not be relabelled as a minute sample.
func (a *App) heatMinutes(ctx context.Context, hosts []Host, start time.Time) {
	for n := 0; n < int(a.heatDuration/a.minuteDuration); n++ {
		boundary := start.Add(time.Duration(n) * a.minuteDuration)
		if delay := time.Until(boundary); delay > 0 {
			if pause(ctx, delay) != nil {
				return
			}
		}
		if ctx.Err() != nil {
			return
		}
		readings := fetchTemperatures(ctx, hosts)
		if ctx.Err() != nil {
			return
		}
		now := time.Now()
		a.mu.Lock()
		a.st.Minutes = append(a.st.Minutes, Minute{"Last", n, now.Sub(start).Seconds(), now, readings})
		a.mu.Unlock()
	}
}
