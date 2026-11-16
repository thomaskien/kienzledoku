package main

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

func TestSerialHeatWithResidentWhisper(t *testing.T) {
	f := fake(t)
	a := connected(t, f)
	a.minuteDuration = 20 * time.Millisecond
	a.heatDuration = 30 * a.minuteDuration
	if err := a.start(Config{Heat: true, HeatModel: "a", HeatMode: "serial"}); err != nil {
		t.Fatal(err)
	}
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Abgeschlossen" || s.HeatEnded.Sub(s.HeatStarted) < a.heatDuration {
		t.Fatalf("heat ended early: %s %v %+v", s.Status, s.Errors, s.Results)
	}
	completedWhisper := 0
	for _, r := range s.Results {
		if r.Model == "Whisper" && len(r.Metrics) == 13 {
			if r.Error != "" || r.Seconds == nil || *r.Seconds != r.HTTPSeconds {
				t.Fatalf("resident Whisper rejected or mislabelled: %+v", r)
			}
			completedWhisper++
		}
	}
	if completedWhisper < 2 {
		t.Fatalf("expected repeated successful Whisper cycles, got %d", completedWhisper)
	}
}

func TestSerialBenchmarkStillRequiresWhisperLoadEvidence(t *testing.T) {
	f := fake(t)
	f.omitLoadEvents = true
	a := connected(t, f)
	if err := a.start(Config{Whisper: true, Modes: []string{"serial"}}); err != nil {
		t.Fatal(err)
	}
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Beendet mit Fehlern" || len(s.Results) != 6 {
		t.Fatalf("benchmark missing load evidence was accepted: %s", s.Status)
	}
	for _, r := range s.Results {
		if r.Seconds != nil || r.Error != "Historische serielle Whisper-Zeit nicht verfügbar" {
			t.Fatalf("unverified serial comparison time: %+v", r)
		}
	}
}

func TestSerialHeatRetainsActualWhisperFailure(t *testing.T) {
	f := fake(t)
	f.failAt = 2 // The first LLM succeeds; the first ASR block fails.
	a := connected(t, f)
	a.minuteDuration = 20 * time.Millisecond
	a.heatDuration = 30 * a.minuteDuration
	if err := a.start(Config{Heat: true, HeatModel: "a", HeatMode: "serial"}); err != nil {
		t.Fatal(err)
	}
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Beendet mit Fehlern" || len(s.Results) != 2 || !strings.Contains(s.Results[1].Error, "Block 1:") {
		t.Fatalf("real ASR error hidden: %s %+v", s.Status, s.Results)
	}
}

func TestHeatRenewsSessionsWithinRequestBudget(t *testing.T) {
	for _, mode := range []string{"serial", "parallel"} {
		t.Run(mode, func(t *testing.T) {
			f := fake(t)
			f.requestLimit = 28
			a := connected(t, f)
			a.minuteDuration = 20 * time.Millisecond
			a.heatDuration = 30 * a.minuteDuration
			a.heatSessionRequests = 28
			if err := a.start(Config{Heat: true, HeatModel: "b", HeatMode: mode}); err != nil {
				t.Fatal(err)
			}
			awaitDone(t, a)
			s := a.snapshot()
			if s.Status != "Abgeschlossen" || s.HeatEnded.Sub(s.HeatStarted) < a.heatDuration {
				t.Fatalf("heat stopped at request limit: %s %v", s.Status, s.Errors)
			}
			if len(s.Restorations) < 2 {
				t.Fatal("no session renewal")
			}
			f.mu.Lock()
			defer f.mu.Unlock()
			if f.maxSessionRequests > 28 || !f.ended {
				t.Fatal("request limit exceeded or session left active")
			}
			for _, profile := range f.order {
				if profile != "b:"+mode {
					t.Fatal("profile changed at renewal", f.order)
				}
			}
			wantPeak := 1
			if mode == "parallel" {
				wantPeak = 2
			}
			if f.peak != wantPeak {
				t.Fatal("concurrency changed", f.peak)
			}
			for _, r := range s.Results {
				if r.Error != "" {
					t.Fatal(r.Error)
				}
			}
		})
	}
}

func TestModelStorageDeduplicatesSharedVolumes(t *testing.T) {
	s := exampleState()
	h := s.Hosts[0].Hardware
	storage := arr(h["storage"])
	for i := 0; i < 7; i++ {
		copy := Obj{}
		for k, v := range obj(storage[1]) {
			copy[k] = v
		}
		copy["role"] = "model:another"
		storage = append(storage, copy)
	}
	h["storage"] = storage
	text := reportParts(s)[1].Text
	if strings.Count(text, "Modellspeicher") != 1 {
		t.Fatalf("same volume repeated:\n%s", text)
	}
	other := Obj{}
	for k, v := range obj(storage[1]) {
		other[k] = v
	}
	other["device"] = "nvme1n1"
	h["storage"] = append(storage, other)
	if strings.Count(reportParts(s)[1].Text, "Modellspeicher") != 2 {
		t.Fatal("distinct storage device hidden")
	}
}

func TestCooldownContinuesAndPersistsUntilWindowCloses(t *testing.T) {
	f := fake(t)
	a := connected(t, f)
	a.minuteDuration = 50 * time.Millisecond
	a.pollDuration = 5 * time.Millisecond
	a.st.Started = time.Now().Add(-time.Minute)
	a.st.Ended = time.Now()
	a.st.Status = "Abgeschlossen"
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { defer close(done); a.temperatures(ctx) }()
	defer func() { cancel(); <-done }()
	awaitMinute := func(n int) State {
		t.Helper()
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			s := a.snapshot()
			for _, m := range s.Minutes {
				if m.Phase == "Nachkühlung" && m.Minute >= n && len(m.Readings) > 0 {
					return s
				}
			}
			time.Sleep(5 * time.Millisecond)
		}
		t.Fatalf("no cooldown observation at minute %d", n)
		return State{}
	}
	first := awaitMinute(1)
	last := awaitMinute(40)
	if first.Saved == "" || first.Saved != last.Saved {
		t.Fatal("cooldown must update the original report file")
	}
	seen := map[int]bool{}
	for _, m := range last.Minutes {
		if m.Phase != "Nachkühlung" || seen[m.Minute] {
			t.Fatalf("wrong phase or duplicate minute: %+v", m)
		}
		seen[m.Minute] = true
	}
	for n := 0; n <= 40; n++ {
		if !seen[n] {
			t.Fatalf("minute %d missing", n)
		}
	}
	data, err := os.ReadFile(last.Saved)
	if err != nil || !strings.Contains(string(data), "Min. 40:") {
		t.Fatalf("cooldown not saved: %v", err)
	}
	cancel() // The application root context is closed when the window is closed.
	<-done
	before := len(a.snapshot().Minutes)
	time.Sleep(2 * a.minuteDuration)
	if len(a.snapshot().Minutes) != before {
		t.Fatal("temperature recording continued after application shutdown")
	}
}
