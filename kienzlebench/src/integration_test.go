package main

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

// Uses the real Commander scheduler/API with a synthetic runtime, never real models.
func TestCommander18Contract(t *testing.T) {
	url := os.Getenv("KIENZLEBENCH_TEST_COMMANDER")
	if url == "" {
		t.Skip("optional local Commander fixture")
	}
	a := newApp(context.Background(), t.TempDir())
	a.drainTimeout = 5 * time.Second
	token, configured := os.LookupEnv("KIENZLEBENCH_TEST_TOKEN")
	if !configured {
		token = "synthetic-token"
	}
	if e := a.connect(context.Background(), Connection{URL: url, Token: token}); e != nil {
		t.Fatal(e)
	}
	if e := a.start(Config{Models: []string{"chosen"}, Modes: []string{"serial", "parallel"}, Whisper: true}); e != nil {
		t.Fatal(e)
	}
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Abgeschlossen" {
		for _, r := range s.Results {
			if r.Error != "" {
				t.Log(r.Case, r.Mode, r.Error, r.Note)
			}
		}
		t.Fatalf("%s %v", s.Status, s.Errors)
	}
	if len(s.Results) != 36 {
		t.Fatalf("rows %d", len(s.Results))
	}
	a.minuteDuration = 30 * time.Millisecond
	a.heatDuration = 30 * a.minuteDuration
	a.pollDuration = 3 * time.Millisecond
	a.heatSessionRequests = 28 // Force renewal while keeping the production time axis intact.
	ctx, cancel := context.WithCancel(context.Background())
	tempDone := make(chan struct{})
	defer func() { cancel(); <-tempDone }()
	go func() { defer close(tempDone); a.temperatures(ctx) }()
	var heatReports []string
	for _, mode := range []string{"serial", "parallel"} {
		if e := a.start(Config{Heat: true, HeatModel: "chosen", HeatMode: mode}); e != nil {
			t.Fatal(e)
		}
		awaitDone(t, a)
		s = a.snapshot()
		if s.Status != "Abgeschlossen" || s.HeatEnded.Sub(s.HeatStarted) < a.heatDuration {
			t.Fatal(mode, s.Status, s.Errors)
		}
		completeWhisper := false
		for _, r := range s.Results {
			if r.Model == "Whisper" && len(r.Metrics) == 13 && r.Error == "" {
				completeWhisper = true
			}
		}
		if !completeWhisper {
			t.Fatal(mode, "no complete heat-test Whisper cycle")
		}
		if len(s.Restorations) < 2 {
			t.Fatal(mode, "heat session was not renewed")
		}
		for _, v := range s.Restorations {
			if obj(v["result"])["state"] != "completed" {
				t.Fatal("not restored", v)
			}
		}
		heatReports = append(heatReports, s.Report)
	}
	if path := os.Getenv("KIENZLEBENCH_TEST_REPORT"); path != "" {
		if e := os.WriteFile(path, []byte("SIMULIERTE INFERENZ – KEINE HARDWARE-BENCHMARKERGEBNISSE\n\n"+strings.Join(heatReports, "\n\n")), 0600); e != nil {
			t.Fatal(e)
		}
	}
}
