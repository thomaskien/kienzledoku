package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func exampleState() State {
	zone := time.FixedZone("CET", 3600)
	start := time.Date(2026, 11, 16, 14, 0, 0, 0, zone)
	heat := start.Add(5 * time.Minute)
	end := heat.Add(30 * time.Minute)
	host := "http://beispiel-server:8185"
	s := State{Version: version, Status: "Abgeschlossen · FIKTIVES BEISPIEL", Started: start, Ended: end.Add(3 * time.Second), HeatStarted: heat, HeatEnded: end, HeatDrainSeconds: 3, Config: Config{Models: []string{"q4", "q6"}, Modes: []string{"serial", "parallel"}, Whisper: true, Heat: true, HeatModel: "q6", HeatMode: "parallel"}, Hosts: []Host{{URL: host, Capabilities: Obj{"commander_version": "1.8.1", "benchmark_roles": []any{"asr", "llm"}, "effective_settings": Obj{"cache": Obj{"whisper_model_cache": "RAM"}}}, Hardware: Obj{
		"system": Obj{"os": "Ubuntu", "version": "24.04 LTS", "architecture": "x86_64", "execution": "nativ"}, "cpu": Obj{"model": "AMD Ryzen 9 5900X", "physical_cores": float64(12), "logical_processors": float64(24)}, "memory": Obj{"installed_bytes": float64(64 << 30), "visible_bytes": float64(64 << 30), "available_bytes": float64(52 << 30), "type": "DDR4", "speed_mhz": float64(3200)}, "board": Obj{"manufacturer": "MSI", "model": "B550-A PRO"},
		"storage": []any{Obj{"role": "system", "model": "Samsung 980 PRO", "device": "nvme0n1", "type": "ssd", "capacity_bytes": float64(2e12), "interface": "NVMe", "volume_total_bytes": float64(2e12), "volume_free_bytes": float64(1.2e12)}, Obj{"role": "model:0", "model": "Samsung 980 PRO", "device": "nvme0n1", "type": "ssd", "capacity_bytes": float64(2e12), "interface": "NVMe", "volume_total_bytes": float64(2e12), "volume_free_bytes": float64(1.2e12)}}, "gpus": []any{Obj{"model": "NVIDIA GeForce RTX 3090", "memory_bytes": float64(24 << 30), "memory_kind": "VRAM"}},
	}}}}
	for i, id := range s.Config.Models {
		s.Models = append(s.Models, Obj{"id": id, "label": []string{"Qwen3.5-4B Q4_K_M", "Qwen3.5-9B Q6_K"}[i], "context_per_slot": float64(32768), "slots": float64(1), "kv": "q8_0", "backend": "llama.cpp"})
		for mi, mode := range s.Config.Modes {
			for ci, c := range []string{"G60_01A", "G60_30B"} {
				for n := 0; n < 6; n++ {
					v := [][][]float64{{{4.8, 7.6}, {1.3, 3.1}}, {{10.2, 16.8}, {3.5, 8.3}}}[i][mi][ci]
					if n == 0 {
						v += 1
					}
					s.Results = append(s.Results, Result{Model: id, Mode: mode, Case: c, Iteration: n, Phase: "Benchmark", Seconds: &v, Metrics: []Obj{{"request_id": "INTERNAL-ID-MUST-NOT-BE-IN-MAIN-REPORT"}}})
				}
			}
		}
	}
	for _, mode := range s.Config.Modes {
		for n := 0; n < 6; n++ {
			v := 8.4
			if mode == "serial" {
				v = 19.2
			}
			s.Results = append(s.Results, Result{Model: "Whisper", Mode: mode, Case: "Husten 113,16 s", Iteration: n, Phase: "Benchmark", Seconds: &v})
		}
	}
	for n := 0; n <= 30; n++ {
		cpu := 39 + float64(n)*1.1
		gpu := 33 + float64(n)*1.2
		stamp := heat.Add(time.Duration(n) * time.Minute)
		s.Minutes = append(s.Minutes, Minute{Phase: "Last", Minute: n, Time: stamp, Elapsed: float64(n * 60), Readings: []Reading{{Host: host, Fetched: stamp, Data: Obj{"sensors": []any{Obj{"kind": "cpu", "name": "CPU", "status": "available", "value": cpu}, Obj{"kind": "gpu", "name": "GPU", "status": "available", "value": gpu}}}}}})
	}
	s.Restorations = []Obj{{"host": host, "result": Obj{"state": "completed"}}}
	return s
}
func TestCompactSeparatedModeTables(t *testing.T) {
	s := exampleState()
	text := report(s)
	if len(s.ReportParts) != 0 {
		t.Fatal("renderer mutated state")
	}
	parts := reportParts(s)
	if len(parts) != 7 {
		t.Fatal(len(parts))
	}
	if text != joinReport(parts) {
		t.Fatal("display/export mismatch")
	}
	for _, want := range []string{"01 ZIELSYSTEM & HARDWARE", "02 MESSBEDINGUNGEN", "03 SERIELLER BETRIEB", "04 PARALLELER BETRIEB", "05 WÄRMETEST & TEMPERATURVERLAUF", "06 STATUS & FEHLENDE ANGABEN", "AMD Ryzen 9 5900X", "64,00 GiB DDR4", "MSI B550-A PRO", "Samsung 980 PRO", "2,00 TB", "NVIDIA", "19,20 s", "8,40 s"} {
		if !strings.Contains(text, want) {
			t.Error(want)
		}
	}
	serial, parallel := parts[3].Text, parts[4].Text
	for _, v := range []string{"4,80 s", "7,60 s", "10,20 s", "16,80 s"} {
		if !strings.Contains(serial, v) || strings.Contains(parallel, v) {
			t.Fatal("serial mode mix", v)
		}
	}
	for _, v := range []string{"1,30 s", "3,10 s", "3,50 s", "8,30 s"} {
		if !strings.Contains(parallel, v) || strings.Contains(serial, v) {
			t.Fatal("parallel mode mix", v)
		}
	}
	if strings.Contains(text, "INTERNAL-ID") || strings.Contains(text, "EINZELLÄUFE") {
		t.Fatal("technical data in main report")
	}
	if !strings.Contains(technicalReport(s), "INTERNAL-ID") {
		t.Fatal("details lost")
	}
	for _, m := range s.Models {
		if strings.Count(strings.Split(serial, "WHISPER")[0], str(m["label"])) != 1 || strings.Count(strings.Split(parallel, "WHISPER")[0], str(m["label"])) != 1 {
			t.Fatal("model must occupy one row")
		}
	}
}
func TestMinuteValuesAndMissingSensors(t *testing.T) {
	s := exampleState()
	s.Minutes[2].Readings[0].Data = Obj{"sensors": []any{Obj{"kind": "cpu", "value": nil, "status": "unavailable"}, Obj{"kind": "gpu", "value": 57.0, "status": "available"}}}
	text := reportParts(s)[5].Text
	for n := 0; n <= 30; n++ {
		if strings.Count(text, fmt.Sprintf("Min. %02d:", n)) != 1 {
			t.Fatal("missing/duplicate minute", n)
		}
	}
	if !strings.Contains(text, "nicht verfügbar") || !strings.Contains(text, "57,0 °C") {
		t.Fatal("missing sensor or minute value")
	}
	s.Minutes = append(s.Minutes[:4], s.Minutes[5:]...)
	text = reportParts(s)[5].Text
	if !strings.Contains(text, "Min. 04:") {
		t.Fatal("missing boundary hidden")
	}
	if path := os.Getenv("KIENZLEBENCH_EXAMPLE"); path != "" {
		sample := exampleState()
		out := "FIKTIVE BEISPIELDATEN – KEINE TATSÄCHLICHE HARDWAREMESSUNG\n\n" + report(sample)
		if e := os.WriteFile(path, []byte(out), 0600); e != nil {
			t.Fatal(e)
		}
	}
}
func TestMainReportKeepsFailuresAndWarmup(t *testing.T) {
	s := exampleState()
	s.Results[0].Error = "Erstlauf fehlgeschlagen"
	s.Results[2].Error = "Messung fehlgeschlagen"
	text := report(s)
	if strings.Contains(reportParts(s)[3].Text, "4,80 s") {
		t.Fatal("median hid missing measurement")
	}
	for _, v := range []string{"— (4/5)", "Erstlauf fehlgeschlagen", "Messung fehlgeschlagen"} {
		if !strings.Contains(text, v) {
			t.Fatal(v)
		}
	}
	s = exampleState()
	s.Results[0].Error = "Erstlauf fehlgeschlagen"
	text = report(s)
	if !strings.Contains(text, "4,80 s *") {
		t.Fatal("warmup failure invisible")
	}
}
func TestTokenFreeFullRunAndProtectedServer(t *testing.T) {
	f := fake(t)
	f.noToken = true
	a := newApp(context.Background(), t.TempDir())
	a.drainTimeout = 3 * time.Second
	if e := a.connect(context.Background(), Connection{URL: f.server.URL}); e != nil {
		t.Fatal(e)
	}
	if e := a.start(Config{Models: []string{"a"}, Modes: []string{"serial", "parallel"}, Whisper: true}); e != nil {
		t.Fatal(e)
	}
	awaitDone(t, a)
	s := a.snapshot()
	if s.Status != "Abgeschlossen" {
		t.Fatal(s.Status, s.Errors)
	}
	b, e := os.ReadFile(s.Saved)
	if e != nil {
		t.Fatal(e)
	}
	if string(b) != s.Report {
		t.Fatal("saved and copied reports differ")
	}
	protected := fake(t)
	c, _ := newClient(protected.server.URL, "")
	if _, e := connectHost(context.Background(), c); e == nil {
		t.Fatal("protected commander accepted missing token")
	}
}
func TestCapabilityGateAndOptionalToken(t *testing.T) {
	f := fake(t)
	a := connected(t, f)
	s := a.snapshot()
	s.Hosts[0].client.Token = ""
	if e := validateConfig(Config{Models: []string{"a"}, Modes: []string{"serial"}}, s); e != nil {
		t.Fatal("client imposed token", e)
	}
	s.Hosts[0].Capabilities["benchmark_control"] = false
	if e := validateConfig(Config{Whisper: true}, s); e == nil {
		t.Fatal("ignored server capability")
	}
}
func TestSerializedReportContainsNoSecrets(t *testing.T) {
	s := exampleState()
	a := newApp(context.Background(), t.TempDir())
	a.st = s
	a.persistLocked()
	snapshot := a.snapshot()
	v, _ := json.Marshal(snapshot.ReportParts)
	if strings.Contains(string(v), "INTERNAL-ID") {
		t.Fatal("private diagnostics in report parts")
	}
	if filepath.Ext(a.store.ReportPath) != ".txt" {
		t.Fatal("portable report missing")
	}
}

func TestSensorIdentityAndCooldownSeparation(t *testing.T) {
	reading := Reading{Data: Obj{"sensors": []any{Obj{"id": "gpu:1", "name": "GPU 1", "kind": "gpu", "status": "available", "value": 57.0}, Obj{"id": "gpu:0", "name": "GPU 0", "kind": "gpu", "status": "unavailable", "value": nil}}}}
	if got := compactTemperature(reading, "gpu"); got != "nicht verfügbar / 57,0 °C" {
		t.Fatal(got)
	}
	s := exampleState()
	r := s.Minutes[0].Readings[0]
	r.Data = Obj{"sensors": []any{Obj{"kind": "gpu", "status": "available", "value": 99.0}}}
	s.Minutes = append(s.Minutes, Minute{Phase: "Nachkühlung", Minute: 0, Readings: []Reading{r}})
	var b strings.Builder
	temperatureSummary(&b, s)
	if strings.Contains(b.String(), "99,0") {
		t.Fatal("cooldown polluted load maximum")
	}
	if !strings.Contains(b.String(), "69,0 °C") {
		t.Fatal("load maximum missing")
	}
}
