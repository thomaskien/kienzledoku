package main

import (
	"fmt"
	"sort"
	"strings"
	"time"
)

func gib(v any) string {
	n, ok := num(v)
	if !ok {
		return "nicht verfügbar"
	}
	return fmt.Sprintf("%.2f GiB", n/(1024*1024*1024))
}
func clockText(t time.Time) string {
	if t.IsZero() {
		return "–"
	}
	return t.Format("02.01.2006 15:04:05 MST (UTC-07:00)")
}
func seconds(v *float64) string {
	if v == nil {
		return "–"
	}
	return fmt.Sprintf("%.3f s", *v)
}
func number(v any) string {
	n, ok := num(v)
	if !ok {
		return "–"
	}
	return fmt.Sprintf("%.3f", n)
}
func median(xs []float64) *float64 {
	if len(xs) == 0 {
		return nil
	}
	xs = append([]float64(nil), xs...)
	sort.Float64s(xs)
	v := xs[len(xs)/2]
	if len(xs)%2 == 0 {
		v = (v + xs[len(xs)/2-1]) / 2
	}
	return &v
}
func flat(b *strings.Builder, prefix string, v any) {
	if m, ok := v.(map[string]any); ok {
		keys := make([]string, 0, len(m))
		for k := range m {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			flat(b, prefix+"."+k, m[k])
		}
		return
	}
	if list, ok := v.([]any); ok {
		for i, x := range list {
			flat(b, fmt.Sprintf("%s[%d]", prefix, i), x)
		}
		if len(list) == 0 {
			fmt.Fprintf(b, "  %s: []\n", prefix)
		}
		return
	}
	fmt.Fprintf(b, "  %s: %s\n", prefix, str(v))
}
func sensorValue(r Reading, kind string) string {
	if r.Error != "" {
		return "nicht verfügbar (" + r.Error + ")"
	}
	var values []string
	for _, v := range arr(r.Data["sensors"]) {
		s := obj(v)
		if s["kind"] != kind {
			continue
		}
		n, ok := num(s["value"])
		if !ok || s["status"] != "available" && s["status"] != "ok" {
			values = append(values, str(s["name"])+": n/v ("+str(s["reason"])+")")
			continue
		}
		values = append(values, fmt.Sprintf("%s %.1f °C", str(s["name"]), n))
	}
	if len(values) == 0 {
		return "nicht verfügbar"
	}
	return strings.Join(values, ", ")
}
func technicalReport(s State) string {
	var b strings.Builder
	fmt.Fprintf(&b, "KIENZLEBENCH %s — TECHNISCHE DETAILS\n%s\nStatus: %s\nBeginn: %s\nEnde:   %s\n\n", version, strings.Repeat("=", 86), s.Status, clockText(s.Started), clockText(s.Ended))
	if s.Started.IsZero() {
		b.WriteString("Noch kein Benchmark gestartet. Die Hardwaredaten stammen vom verbundenen Commander.\n\n")
	}
	b.WriteString("HARDWARE DER COMMANDER\n")
	for i, h := range s.Hosts {
		hw := h.Hardware
		cpu := obj(hw["cpu"])
		ram := obj(hw["memory"])
		board := obj(hw["board"])
		system := obj(hw["system"])
		fmt.Fprintf(&b, "\nHost %d: %s | Rollen: %s | Commander %s\n", i+1, h.URL, str(h.Capabilities["benchmark_roles"]), str(h.Capabilities["commander_version"]))
		fmt.Fprintf(&b, "System: %s %s · %s · %s\nCPU:    %s · Kerne %s · Threads %s\n", str(system["os"]), str(system["version"]), str(system["architecture"]), str(system["execution"]), str(cpu["model"]), str(cpu["physical_cores"]), str(cpu["logical_processors"]))
		fmt.Fprintf(&b, "RAM:    installiert %s · sichtbar %s · verfügbar %s\n", gib(ram["installed_bytes"]), gib(ram["visible_bytes"]), gib(ram["available_bytes"]))
		if yes(ram["unified"]) {
			b.WriteString("        Unified Memory: CPU/GPU teilen Speicher; Größen nicht addieren.\n")
		}
		if ram["free_plus_inactive_bytes"] != nil {
			fmt.Fprintf(&b, "        frei + inaktiv: %s (kein MemAvailable-Äquivalent)\n", gib(ram["free_plus_inactive_bytes"]))
		}
		fmt.Fprintf(&b, "Board:  %s %s · Firmware %s\n", str(board["manufacturer"]), str(board["model"]), str(board["firmware"]))
		for _, v := range arr(hw["gpus"]) {
			g := obj(v)
			fmt.Fprintf(&b, "GPU:    %s · %s · %s\n", str(g["model"]), gib(g["memory_bytes"]), str(g["memory_kind"]))
		}
		if len(arr(hw["storage"])) == 0 {
			b.WriteString("SSD:    nicht verfügbar\n")
		}
		for _, v := range arr(hw["storage"]) {
			d := obj(v)
			fmt.Fprintf(&b, "SSD/Laufwerk: %s · %s · %s · physisch %s\n              Rolle %s · Volume %s · frei %s · Modelle %s\n", str(d["model"]), str(d["type"]), str(d["interface"]), gib(d["capacity_bytes"]), str(d["role"]), gib(d["volume_total_bytes"]), gib(d["volume_free_bytes"]), str(d["models"]))
		}
		if hw["unavailable"] != nil {
			fmt.Fprintf(&b, "Hardwarehinweis: %s\n", str(hw["unavailable"]))
		}
	}
	b.WriteString("\nTESTBEDINGUNGEN\n")
	fmt.Fprintf(&b, "Ausgewählte LLMs: %s\nBetriebsarten: %s\nWhisper: %t · Wärmetest: %t · Wärme-LLM: %s · Wärme-Modus: %s\n", strings.Join(s.Config.Models, ", "), strings.Join(s.Config.Modes, ", "), s.Config.Whisper, s.Config.Heat, s.Config.HeatModel, s.Config.HeatMode)
	b.WriteString("Modelle nacheinander. G60_01A = 5 Minuten Kontakt; G60_30B = 20 Minuten Kontakt.\nKontaktbezeichnungen sind keine Audiodauern. Erstlauf separat + fünf Messläufe.\nLLM seriell: bestätigter LLM-Ladebeginn bis vollständige Backendantwort.\nLLM parallel: Inferenz am residenten Modell. Warteschlange, HTTP und Rückwechsel separat.\nWhisper: Husten 113,16 s, 13 Originalblöcke mit Kontext, ohne Echtzeitpausen.\nWhisper seriell nur mit bestätigtem ASR-Neuladen vergleichbar; sonst explizit geladen.\nWhisper parallel: clientseitige Verarbeitung bis Empfang des letzten Blocks.\nSampling: temperature 0.1, seed 42, top_k 40, top_p 0.95, min_p 0.05, repeat_penalty 1, max_tokens 1600.\nPromptcache aus. OS-Dateicache unverändert/unbekannt; kein belegter SSD-Kaltstart.\nThinking/Flash-Attention/Fit und vollständiger Backend-Build sind über API 1.8 nicht steuerbar/bestätigt.\nTTFT nicht verfügbar (nicht streamender Commander-Pfad). Historische Vergleichbarkeit deshalb begrenzt.\nKein Qualitätsnachweis für medizinische Anwendung; JSON-Prüfung ist nur eine Formatprüfung.\n")
	for _, m := range s.Models {
		if contains(s.Config.Models, str(m["id"])) || (s.Config.Heat && s.Config.HeatModel == m["id"]) {
			fmt.Fprintf(&b, "Modellprofil: %s | %s | %s | %s | Kontext/Slot %s | Slots %s | KV %s\n", str(m["id"]), str(m["label"]), str(m["backend"]), str(m["quantization"]), str(m["context_per_slot"]), str(m["slots"]), str(m["kv"]))
		}
	}
	b.WriteString("\nBENCHMARKERGEBNISSE · MEDIAN NUR BEI 5 GÜLTIGEN MESSLÄUFEN\n")
	fmt.Fprintf(&b, "%-24s %-9s %-19s %12s %12s %9s\n", "Modell", "Modus", "Fall", "Erstlauf", "Median", "Gültig")
	keys := []string{}
	groups := map[string][]Result{}
	for _, r := range s.Results {
		if r.Phase == "Wärmetest" {
			continue
		}
		k := r.Model + "\x00" + r.Mode + "\x00" + r.Case
		if _, ok := groups[k]; !ok {
			keys = append(keys, k)
		}
		groups[k] = append(groups[k], r)
	}
	for _, k := range keys {
		rows := groups[k]
		first := (*float64)(nil)
		xs := []float64{}
		for _, r := range rows {
			if r.Error == "" && r.Seconds != nil {
				if r.Iteration == 0 {
					first = r.Seconds
				} else {
					xs = append(xs, *r.Seconds)
				}
			}
		}
		med := (*float64)(nil)
		if len(xs) == 5 {
			med = median(xs)
		}
		r := rows[0]
		fmt.Fprintf(&b, "%-24s %-9s %-19s %12s %12s %7d/5\n", r.Model, r.Mode, r.Case, seconds(first), seconds(med), len(xs))
		if r.Model == "Whisper" && med != nil {
			fmt.Fprintf(&b, "  RTF %.4f · %.2f× Echtzeit\n", *med/113.16, 113.16 / *med)
		}
	}
	b.WriteString("\nEINZELLÄUFE (kein Ersatz fehlgeschlagener Läufe)\n")
	for _, r := range s.Results {
		if r.Phase == "Wärmetest" {
			continue
		}
		label := fmt.Sprintf("Messung %d", r.Iteration)
		if r.Iteration == 0 {
			label = "Erstlauf"
		}
		fmt.Fprintf(&b, "%s | %s | %s | %s: %s · HTTP %.3f s\n", r.Model, r.Mode, r.Case, label, seconds(r.Seconds), r.HTTPSeconds)
		if r.Error != "" {
			fmt.Fprintf(&b, "  FEHLER: %s\n", r.Error)
		}
		if r.Note != "" {
			fmt.Fprintf(&b, "  Hinweis: %s\n", r.Note)
		}
		for i, m := range r.Metrics {
			fmt.Fprintf(&b, "  Auftrag %d %s: Modell %s · Queue %s s · Vorbereitung %s s · Inferenz %s s · Antwort %s s · Rückkehr %s s (vollständig %s)\n", i+1, str(m["request_id"]), str(m["model_id"]), number(m["queue_seconds"]), number(m["model_preparation_seconds"]), number(m["inference_seconds"]), number(m["response_seconds"]), number(m["return_seconds"]), str(m["return_complete"]))
			if m["usage"] != nil {
				fmt.Fprintf(&b, "    Token: %s · Backend-Timings: %s\n", str(m["usage"]), str(m["timings"]))
			}
		}
	}
	if s.Config.Heat {
		fmt.Fprintf(&b, "\nWÄRMETEST · Soll 30:00 Minuten · %s · %s\nBeginn: %s\nLastende: %s\nNachlauf: %.3f s (außerhalb des Lastfensters)\n", s.Config.HeatModel, s.Config.HeatMode, clockText(s.HeatStarted), clockText(s.HeatEnded), s.HeatDrainSeconds)
		llm, asr, failed := 0, 0, 0
		var li, ai [][2]float64
		for _, r := range s.Results {
			if r.Phase != "Wärmetest" {
				continue
			}
			if r.Error != "" {
				failed++
			}
			for _, m := range r.Metrics {
				st, ok := num(m["inference_started_at"])
				en, ok2 := num(m["completed_at"])
				if m["role"] == "llm" {
					llm++
					if ok && ok2 {
						li = append(li, [2]float64{st, en})
					}
				} else if m["role"] == "asr" {
					asr++
					if ok && ok2 {
						ai = append(ai, [2]float64{st, en})
					}
				}
			}
		}
		fmt.Fprintf(&b, "LLM-Aufträge: %d · ASR-Blöcke: %d · fehlgeschlagene Durchläufe: %d\n", llm, asr, failed)
		if len(s.Hosts) == 1 {
			overlap := 0.0
			for _, l := range li {
				for _, r := range ai {
					start := l[0]
					if r[0] > start {
						start = r[0]
					}
					end := l[1]
					if r[1] < end {
						end = r[1]
					}
					if end > start {
						overlap += end - start
					}
				}
			}
			fmt.Fprintf(&b, "Belegte ASR/LLM-Inferenzüberlappung: %.3f s (gleiche Server-Zeitbasis)\n", overlap)
		} else {
			b.WriteString("Getrennte Hosts: monotone Serveruhren nicht gegeneinander verrechnet.\n")
		}
	}
	b.WriteString("\nTEMPERATURVERLAUF · EINZELWERTE AN DEN MINUTENGRENZEN\nKeine interpolierten Werte oder Minutenmittel. Abfrageversatz ist ausgewiesen.\n")
	for _, m := range s.Minutes {
		fmt.Fprintf(&b, "%s · Minute %02d · tatsächlich +%.1f s · %s\n", m.Phase, m.Minute, m.Elapsed, clockText(m.Time))
		if len(m.Readings) == 0 {
			b.WriteString("  Messwert ausgefallen\n")
		}
		for _, r := range m.Readings {
			fmt.Fprintf(&b, "  %s | CPU %s | GPU %s\n", r.Host, sensorValue(r, "cpu"), sensorValue(r, "gpu"))
			for _, v := range arr(r.Data["sensors"]) {
				x := obj(v)
				fmt.Fprintf(&b, "    %s · Quelle %s · gemessen %s\n", str(x["name"]), str(x["source"]), str(x["measured_at"]))
			}
		}
	}
	b.WriteString("\nAKTUELLE TEMPERATUREN (auch nach Ende des Tests)\n")
	for _, r := range s.Current {
		fmt.Fprintf(&b, "%s · abgefragt %s | CPU %s | GPU %s\n", r.Host, clockText(r.Fetched), sensorValue(r, "cpu"), sensorValue(r, "gpu"))
	}
	b.WriteString("\nWIEDERHERSTELLUNG\n")
	for _, v := range s.Restorations {
		r := obj(v["result"])
		fmt.Fprintf(&b, "%s · %s · %s: %s\n", str(v["host"]), str(v["model"]), str(v["mode"]), str(r["state"]))
		flat(&b, "Sitzung", v)
	}
	if len(s.Errors) > 0 {
		b.WriteString("\nFEHLER / TEILERGEBNISSE\n")
		for _, e := range s.Errors {
			fmt.Fprintf(&b, "- %s\n", e)
		}
	}
	b.WriteString("\nHARDWAREQUELLEN UND EFFEKTIVE EINSTELLUNGEN\n")
	for _, h := range s.Hosts {
		fmt.Fprintf(&b, "Host %s\n", h.URL)
		flat(&b, "Hardware", h.Hardware)
		flat(&b, "Betrieb", h.Capabilities["effective_settings"])
	}
	b.WriteString("\nREFERENZEN\nGP60 G60_01A SHA256 ddd201525e3560279765c14bc6713f90777bb4004880411896837fe15ae0c232\nGP60 G60_30B SHA256 60119716b2a8f7f321df3c4b4b974303dfeae0958837ffd9e060a9a4d32258b1\nPrompt SHA256 c402ac6a9e8e8111ab5b0405cf53f6009a9fdb4ac1d12fd83e97e5cf9b72a153\nHusten PCM SHA256 38f620f4549bbd4820e229e03fac4462fb076e1fa4e84a4a55424eaf9438db8a\nAudio: Der Husten geht nicht weg – Hörtexte Deutsch\nQuelle: https://www.hoertexte-deutsch.at/mp3/husten.mp3\nLizenz laut Referenzprotokoll: CC BY-NC-ND 3.0 AT\nhttps://creativecommons.org/licenses/by-nc-nd/3.0/at/\n")
	return b.String()
}
func contains(xs []string, v string) bool {
	for _, x := range xs {
		if x == v {
			return true
		}
	}
	return false
}
