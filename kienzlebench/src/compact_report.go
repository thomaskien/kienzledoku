package main

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

type ReportPart struct {
	Title string `json:"title"`
	Text  string `json:"text"`
}

func decimal(v float64, digits int) string {
	return strings.ReplaceAll(fmt.Sprintf("%.*f", digits, v), ".", ",")
}
func shortSeconds(v *float64) string {
	if v == nil {
		return "—"
	}
	return decimal(*v, 2) + " s"
}
func friendly(v any) string {
	if v == nil || v == "" {
		return "nicht verfügbar"
	}
	return str(v)
}
func joined(values ...any) string {
	var xs []string
	for _, v := range values {
		if v != nil && v != "" {
			xs = append(xs, str(v))
		}
	}
	if len(xs) == 0 {
		return "nicht verfügbar"
	}
	return strings.Join(xs, " · ")
}
func spaceJoin(values ...any) string { return strings.ReplaceAll(joined(values...), " · ", " ") }
func sizeText(v any) string          { return strings.ReplaceAll(gib(v), ".", ",") }
func volumeSize(v any) string {
	n, ok := num(v)
	if !ok {
		return "nicht verfügbar"
	}
	if n >= 1024*1024*1024*1024 {
		return decimal(n/(1024*1024*1024*1024), 2) + " TiB"
	}
	return sizeText(v)
}
func diskSize(v any) string {
	n, ok := num(v)
	if !ok {
		return "nicht verfügbar"
	}
	return decimal(n/1e12, 2) + " TB"
}
func modeName(mode string) string {
	if mode == "serial" {
		return "seriell"
	}
	if mode == "parallel" {
		return "parallel"
	}
	return mode
}
func modelName(s State, id string) string {
	m := findModel(s.Models, id)
	if label, ok := m["label"].(string); ok && label != "" {
		return label
	}
	return id
}
func selectedModels(s State) []string              { return append([]string(nil), s.Config.Models...) }
func item(b *strings.Builder, label, value string) { fmt.Fprintf(b, "%-15s %s\n", label, value) }
func joinReport(parts []ReportPart) string {
	var b strings.Builder
	for i, p := range parts {
		if i > 0 {
			b.WriteString("\n")
		}
		b.WriteString(p.Title + "\n")
		b.WriteString(strings.Repeat("─", 76) + "\n")
		b.WriteString(strings.TrimRight(p.Text, "\n") + "\n")
	}
	return b.String()
}
func report(s State) string { return joinReport(reportParts(s)) }
func reportParts(s State) []ReportPart {
	var parts []ReportPart
	add := func(title string, b *strings.Builder) {
		parts = append(parts, ReportPart{title, strings.TrimRight(b.String(), "\n")})
		b.Reset()
	}
	var b strings.Builder
	item(&b, "Status", s.Status)
	item(&b, "Beginn", clockText(s.Started))
	item(&b, "Ende", clockText(s.Ended))
	if s.Started.IsZero() {
		b.WriteString("Noch keine Messung gestartet.\n")
	}
	add("KIENZLEBENCH "+version+" — ERGEBNISBERICHT", &b)
	if len(s.Hosts) == 0 {
		b.WriteString("Noch kein Commander verbunden.\n")
	}
	for i, h := range s.Hosts {
		if i > 0 {
			b.WriteString("\n")
		}
		hw := h.Hardware
		cpu := obj(hw["cpu"])
		ram := obj(hw["memory"])
		board := obj(hw["board"])
		system := obj(hw["system"])
		roles := []string{}
		for _, r := range arr(h.Capabilities["benchmark_roles"]) {
			roles = append(roles, strings.ToUpper(str(r)))
		}
		item(&b, "Rechner", h.URL+" · "+strings.Join(roles, " + "))
		item(&b, "Betriebssystem", joined(system["os"], system["version"], system["architecture"], system["execution"]))
		item(&b, "CPU", fmt.Sprintf("%s · %s Kerne / %s Threads", friendly(cpu["model"]), friendly(cpu["physical_cores"]), friendly(cpu["logical_processors"])))
		memory := sizeText(ram["installed_bytes"])
		if ram["type"] != nil {
			memory += " " + str(ram["type"])
		}
		if ram["speed_mhz"] != nil {
			memory += " · " + str(ram["speed_mhz"]) + " MHz"
		}
		memory += " · " + sizeText(ram["available_bytes"]) + " verfügbar"
		if ram["visible_bytes"] != nil && ram["visible_bytes"] != ram["installed_bytes"] {
			memory += " · " + sizeText(ram["visible_bytes"]) + " sichtbar"
		}
		item(&b, "RAM", memory)
		if yes(ram["unified"]) {
			item(&b, "Speicherart", "Unified Memory – gemeinsam für CPU/GPU, nicht addieren")
		}
		if ram["free_plus_inactive_bytes"] != nil {
			item(&b, "Frei + inaktiv", sizeText(ram["free_plus_inactive_bytes"])+" (separate Systemzählung)")
		}
		item(&b, "Mainboard", spaceJoin(board["manufacturer"], board["model"]))
		storage := arr(hw["storage"])
		seen := map[string]bool{}
		seenModelVolumes := map[string]bool{}
		if len(storage) == 0 {
			item(&b, "SSD/Laufwerk", "nicht verfügbar")
		}
		for _, v := range storage {
			d := obj(v)
			identity := str(d["device"]) + "|" + str(d["model"]) + "|" + str(d["capacity_bytes"])
			label := "SSD/Laufwerk"
			if d["type"] == "ssd" {
				label = "SSD"
			}
			if !seen[identity] {
				item(&b, label, joined(d["model"], diskSize(d["capacity_bytes"]), d["interface"], d["type"]))
				seen[identity] = true
			}
			role := str(d["role"])
			if strings.HasPrefix(role, "model:") {
				volumeKey := identity + "|" + str(d["volume_total_bytes"]) + "|" + str(d["volume_free_bytes"])
				if !seenModelVolumes[volumeKey] {
					item(&b, "Modellspeicher", fmt.Sprintf("%s · Volume %s / %s frei", friendly(d["model"]), volumeSize(d["volume_total_bytes"]), volumeSize(d["volume_free_bytes"])))
					seenModelVolumes[volumeKey] = true
				}
			} else if role == "system" {
				item(&b, "Systemvolume", volumeSize(d["volume_total_bytes"])+" / "+volumeSize(d["volume_free_bytes"])+" frei")
			}
		}
		gpus := arr(hw["gpus"])
		if len(gpus) == 0 {
			item(&b, "GPU", "nicht verfügbar")
		}
		for _, v := range gpus {
			g := obj(v)
			item(&b, "GPU", joined(g["model"], sizeText(g["memory_bytes"]), g["memory_kind"]))
		}
		item(&b, "Firmware", friendly(board["firmware"]))
		item(&b, "Software", "Commander "+friendly(h.Capabilities["commander_version"]))
		if hw["unavailable"] != nil {
			item(&b, "Hardwarehinweis", friendly(hw["unavailable"]))
		}
	}
	add("01 ZIELSYSTEM & HARDWARE", &b)
	item(&b, "Fälle", "G60_01A (5 Min.) · G60_30B (20 Min.)")
	item(&b, "Durchläufe", "1 Erstlauf ausgeschlossen + 5 Messungen")
	item(&b, "Auswertung", "Median in Sekunden; Modelle nacheinander")
	profiles := map[string]bool{}
	ids := selectedModels(s)
	if s.Config.Heat && !contains(ids, s.Config.HeatModel) {
		ids = append(ids, s.Config.HeatModel)
	}
	for _, id := range ids {
		m := findModel(s.Models, id)
		profile := fmt.Sprintf("%s Token/Slot · %s Slot(s) · KV %s", friendly(m["context_per_slot"]), friendly(m["slots"]), friendly(m["kv"]))
		profiles[profile] = true
	}
	if len(profiles) == 1 {
		for p := range profiles {
			item(&b, "Profil", p)
		}
	} else {
		for _, id := range ids {
			m := findModel(s.Models, id)
			item(&b, "Profil", fmt.Sprintf("%s: %s Token/Slot · %s Slot(s) · KV %s", modelName(s, id), friendly(m["context_per_slot"]), friendly(m["slots"]), friendly(m["kv"])))
		}
	}
	backends := []string{}
	for _, id := range ids {
		m := findModel(s.Models, id)
		backend := friendly(m["backend"])
		if !contains(backends, backend) {
			backends = append(backends, backend)
		}
	}
	if len(backends) > 0 {
		item(&b, "LLM-Backend", strings.Join(backends, ", "))
	}
	item(&b, "Sampling", "Temperatur 0,1 · Seed 42 · maximal 1.600 Ausgabetoken")
	item(&b, "Thinking", "durch Commander nicht bestätigt")
	item(&b, "Promptcache", "Aus; gemeldete Cache-Nutzung wird als Fehler gewertet")
	item(&b, "Dateicache", "Unverändert; kein SSD-Kaltstart nachgewiesen")
	for _, h := range s.Hosts {
		cache := obj(obj(h.Capabilities["effective_settings"])["cache"])
		item(&b, "Whisper-Cache", friendly(cache["whisper_model_cache"]))
	}
	b.WriteString("5 / 20 Minuten bezeichnen die festen Kontaktfälle, keine Audiodauern.\n")
	add("02 MESSBEDINGUNGEN", &b)
	reportMode(&b, s, "serial")
	add("03 SERIELLER BETRIEB", &b)
	reportMode(&b, s, "parallel")
	add("04 PARALLELER BETRIEB", &b)
	reportHeat(&b, s)
	add("05 WÄRMETEST & TEMPERATURVERLAUF", &b)
	reportStatus(&b, s)
	add("06 STATUS & FEHLENDE ANGABEN", &b)
	return parts
}

type rowStats struct {
	Value        *float64
	Valid, Total int
	WarmupFailed bool
	Error, Note  string
}

func summarize(s State, model, mode, caseID string) rowStats {
	var out rowStats
	values := []float64{}
	seen := map[int]bool{}
	for _, r := range s.Results {
		if r.Phase == "Wärmetest" || r.Model != model || r.Mode != mode || r.Case != caseID {
			continue
		}
		if r.Error != "" {
			out.Error = r.Error
		}
		if r.Note != "" {
			out.Note = r.Note
		}
		if r.Iteration == 0 {
			out.WarmupFailed = out.WarmupFailed || r.Error != ""
			continue
		}
		out.Total++
		if r.Iteration >= 1 && r.Iteration <= 5 && !seen[r.Iteration] && r.Error == "" && r.Seconds != nil && !math.IsNaN(*r.Seconds) && !math.IsInf(*r.Seconds, 0) {
			seen[r.Iteration] = true
			values = append(values, *r.Seconds)
		}
	}
	out.Valid = len(values)
	if out.Valid == 5 {
		out.Value = median(values)
	}
	return out
}
func tableCell(r rowStats) string {
	if r.Value != nil {
		v := shortSeconds(r.Value)
		if r.Error != "" || r.WarmupFailed {
			v += " *"
		}
		return v
	}
	if r.Error != "" || r.Total > 0 {
		return fmt.Sprintf("— (%d/5)", r.Valid)
	}
	return "—"
}
func reportMode(b *strings.Builder, s State, mode string) {
	chosen := contains(s.Config.Modes, mode) || (s.Config.Whisper && len(s.Config.Modes) == 0 && mode == "serial")
	if !chosen {
		b.WriteString("Nicht ausgewählt.\n")
		return
	}
	if mode == "serial" {
		b.WriteString("GP60 – Laden bis zur vollständigen Antwort\n\n")
	} else {
		b.WriteString("GP60 – Whisper und LLM gleichzeitig geladen\n\n")
	}
	ids := selectedModels(s)
	width := 28
	for _, id := range ids {
		if n := utf8.RuneCountInString(modelName(s, id)); n > width {
			width = n
		}
	}
	if len(ids) > 0 {
		fmt.Fprintf(b, "%-*s %13s %13s\n", width, "Modell", "5-Min.-Fall", "20-Min.-Fall")
		b.WriteString(strings.Repeat("─", width+28) + "\n")
		for _, id := range ids {
			short := summarize(s, id, mode, "G60_01A")
			long := summarize(s, id, mode, "G60_30B")
			fmt.Fprintf(b, "%-*s %13s %13s\n", width, modelName(s, id), tableCell(short), tableCell(long))
		}
		b.WriteString("\nMedian aus fünf gültigen Messungen. ASR und Rückwechsel separat.\n")
	} else {
		b.WriteString("Keine LLM-Reihe ausgewählt.\n")
	}
	b.WriteString("\nWHISPER – REFERENZAUFNAHME\n")
	if !s.Config.Whisper {
		b.WriteString("Nicht ausgewählt.\n")
		return
	}
	item(b, "Audio", "„Der Husten geht nicht weg“ · 113,16 s")
	item(b, "Backend", "Modell/Build durch Commander nicht bestätigt")
	item(b, "Verfahren", "13 Final-Blöcke · ohne Echtzeit-Wartepausen")
	r := summarize(s, "Whisper", mode, "Husten 113,16 s")
	label := "Mit Laden"
	if mode == "parallel" {
		label = "Bereits geladen"
	}
	value := tableCell(r)
	if r.Value != nil && *r.Value > 0 {
		value += " · RTF " + decimal(*r.Value/113.16, 3) + " · " + decimal(113.16 / *r.Value, 2) + "× Echtzeit"
	}
	item(b, label, value)
	if id := defaultModel(s.Hosts, s.Config.Models); id != "" {
		item(b, "LLM-Kontext", modelName(s, id))
	}
	// Decoder and missing load evidence are meaningful comparison limitations, not just diagnostics.
	notes := map[string]bool{}
	for _, x := range s.Results {
		if x.Model == "Whisper" && x.Mode == mode && x.Phase != "Wärmetest" && x.Note != "" {
			note := x.Note
			if i := strings.Index(note, ". "); strings.HasPrefix(note, "LLM-Kontext:") && i >= 0 {
				note = note[i+2:]
			}
			if strings.TrimSpace(note) != "" {
				notes[note] = true
			}
		}
	}
	for _, n := range sortedKeys(notes) {
		item(b, "Hinweis", n)
	}
}
func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
func temperatureNumbers(r Reading, kind string) []float64 {
	var xs []float64
	if r.Error != "" {
		return xs
	}
	for _, v := range arr(r.Data["sensors"]) {
		s := obj(v)
		if s["kind"] != kind || (s["status"] != "available" && s["status"] != "ok") {
			continue
		}
		n, ok := num(s["value"])
		if ok && !math.IsNaN(n) && !math.IsInf(n, 0) {
			xs = append(xs, n)
		}
	}
	return xs
}
func orderedSensors(r Reading, kind string) []Obj {
	var sensors []Obj
	for _, v := range arr(r.Data["sensors"]) {
		s := obj(v)
		if s["kind"] == kind {
			sensors = append(sensors, s)
		}
	}
	sort.SliceStable(sensors, func(i, j int) bool {
		return joined(sensors[i]["id"], sensors[i]["name"]) < joined(sensors[j]["id"], sensors[j]["name"])
	})
	return sensors
}
func compactTemperature(r Reading, kind string) string {
	sensors := orderedSensors(r, kind)
	if r.Error != "" || len(sensors) == 0 {
		return "nicht verfügbar"
	}
	parts := []string{}
	for _, s := range sensors {
		n, ok := num(s["value"])
		if !ok || math.IsNaN(n) || math.IsInf(n, 0) || (s["status"] != "available" && s["status"] != "ok") {
			parts = append(parts, "nicht verfügbar")
		} else {
			parts = append(parts, decimal(n, 1)+" °C")
		}
	}
	return strings.Join(parts, " / ")
}
func hostReading(m Minute, host string) Reading {
	for _, r := range m.Readings {
		if r.Host == host {
			return r
		}
	}
	return Reading{Host: host, Error: "Messwert ausgefallen"}
}
func phaseMinutes(s State, phase string) []Minute {
	var ms []Minute
	for _, m := range s.Minutes {
		if m.Phase == phase {
			ms = append(ms, m)
		}
	}
	sort.SliceStable(ms, func(i, j int) bool { return ms[i].Minute < ms[j].Minute })
	return ms
}
func minuteTable(b *strings.Builder, s State, phase string) {
	ms := phaseMinutes(s, phase)
	if len(ms) == 0 {
		b.WriteString("Noch keine Minutenwerte vorhanden.\n")
		return
	}
	for hi, h := range s.Hosts {
		if hi > 0 {
			b.WriteString("\n")
		}
		if len(s.Hosts) > 1 {
			item(b, "Rechner", h.URL)
		}
		for _, kind := range []string{"cpu", "gpu"} {
			for _, m := range ms {
				ss := orderedSensors(hostReading(m, h.URL), kind)
				if len(ss) > 1 {
					names := []string{}
					for _, sensor := range ss {
						names = append(names, friendly(sensor["name"]))
					}
					item(b, strings.ToUpper(kind)+"-Sensoren", strings.Join(names, " / "))
					break
				}
			}
		}
		b.WriteString("Zeit ab Start                  CPU                  GPU\n")
		byMinute := map[int]Minute{}
		last := 0
		for _, m := range ms {
			byMinute[m.Minute] = m
			if m.Minute > last {
				last = m.Minute
			}
		}
		for n := 0; n <= last; n++ {
			m, exists := byMinute[n]
			r := hostReading(m, h.URL)
			if !exists {
				r.Error = "Messwert ausgefallen"
			}
			fmt.Fprintf(b, "Min. %02d:       %20s %20s\n", n, compactTemperature(r, "cpu"), compactTemperature(r, "gpu"))
		}
	}
}

func temperatureSummary(b *strings.Builder, s State) {
	ms := phaseMinutes(s, "Last")
	if len(ms) == 0 {
		return
	}
	b.WriteString("\nTEMPERATUREN – MINUTENWERTE DER LASTPHASE\n")
	for _, h := range s.Hosts {
		if len(s.Hosts) > 1 {
			item(b, "Rechner", h.URL)
		}
		fmt.Fprintf(b, "%-10s %17s %17s %17s\n", "Sensor", "Start", "Maximum", "Ende")
		for _, kind := range []string{"cpu", "gpu"} {
			start, end, maximum := "nicht verfügbar", "nicht verfügbar", "nicht verfügbar"
			maxValue := -math.MaxFloat64
			multi := false
			for _, m := range ms {
				r := hostReading(m, h.URL)
				if m.Minute == 0 {
					start = compactTemperature(r, kind)
				}
				if m.Minute == 30 {
					end = compactTemperature(r, kind)
				}
				if len(orderedSensors(r, kind)) > 1 {
					multi = true
				}
				for _, v := range temperatureNumbers(r, kind) {
					if v > maxValue {
						maxValue = v
					}
				}
			}
			if multi {
				maximum = "siehe Verlauf"
			} else if maxValue != -math.MaxFloat64 {
				maximum = decimal(maxValue, 1) + " °C"
			}
			fmt.Fprintf(b, "%-10s %17s %17s %17s\n", strings.ToUpper(kind), start, maximum, end)
		}
	}
	b.WriteString("Maximum aus Minutenmessungen; Start = Minute 0, Ende = Minute 30.\n")
}
func durationText(d time.Duration) string {
	if d < 0 {
		d = 0
	}
	n := int(d.Seconds())
	return fmt.Sprintf("%02d:%02d min", n/60, n%60)
}
func reportHeat(b *strings.Builder, s State) {
	if !s.Config.Heat {
		b.WriteString("Wärmetest nicht ausgewählt.\n")
	} else {
		item(b, "Modell", modelName(s, s.Config.HeatModel)+" · ein Modell für den ganzen Test")
		flow := "Whisper und LLM im Wechsel"
		if s.Config.HeatMode == "parallel" {
			flow = "Whisper und LLM gleichzeitig"
		}
		item(b, "Ablauf", flow)
		item(b, "Soll-Lastphase", "30:00 min · GP60 kurz/lang + Whisper wiederholt")
		if !s.HeatStarted.IsZero() {
			item(b, "Wärmeteststart", clockText(s.HeatStarted))
		}
		if !s.HeatEnded.IsZero() {
			item(b, "Lastphase", durationText(s.HeatEnded.Sub(s.HeatStarted)))
			item(b, "Nachlauf", decimal(s.HeatDrainSeconds, 2)+" s · außerhalb der Lastphase")
		}
		temperatureSummary(b, s)
		b.WriteString("\nTEMPERATURVERLAUF – LASTPHASE\nMinute 0 = Ausgangswert; danach jede Minute ab Wärmeteststart.\n\n")
		minuteTable(b, s, "Last")
		b.WriteString("Einzelmessungen; fehlende Werte werden nicht ersetzt.\nDrosselung: nicht erfasst.\n")
	}
	if !s.Ended.IsZero() {
		b.WriteString("\nNACHKÜHLUNG – NACH ABSCHLUSS ALLER AUFTRÄGE\n")
		item(b, "Start", clockText(s.Ended))
		b.WriteString("Eigene Zeitachse: Minute 0 = Beginn der Nachkühlung.\n\n")
		minuteTable(b, s, "Nachkühlung")
	}
	if len(s.Current) > 0 {
		b.WriteString("\nAKTUELL – ANZEIGE BLEIBT BEI GEÖFFNETEM FENSTER AKTIV\n")
		for _, r := range s.Current {
			if len(s.Hosts) > 1 {
				item(b, "Rechner", r.Host)
			}
			if time.Since(r.Fetched) > 20*time.Second {
				item(b, "Temperatur", "nicht verfügbar – letzte Abfrage veraltet")
			} else {
				item(b, "Temperatur", "CPU "+compactTemperature(r, "cpu")+" · GPU "+compactTemperature(r, "gpu"))
			}
			item(b, "Abgefragt", clockText(r.Fetched))
		}
	}
}
func reportStatus(b *strings.Builder, s State) {
	item(b, "Gesamtstatus", s.Status)
	issues := map[string]bool{}
	for _, r := range s.Results {
		if r.Error != "" {
			prefix := modelName(s, r.Model) + " · " + modeName(r.Mode) + " · " + r.Case
			if r.Iteration == 0 {
				prefix += " · Erstlauf"
			}
			issues[prefix+": "+r.Error] = true
		}
	}
	for _, e := range s.Errors {
		issues[e] = true
	}
	if len(issues) > 0 {
		for _, e := range sortedKeys(issues) {
			b.WriteString("• " + e + "\n")
		}
	} else if !s.Started.IsZero() {
		b.WriteString("Keine Fehler gemeldet.\n")
	}
	if s.Running {
		b.WriteString("Laufende Reihe: noch keine abschließende Bewertung.\n")
	}
	if len(s.Restorations) > 0 {
		complete := true
		for _, r := range s.Restorations {
			v := obj(r["result"])
			if v["state"] != "completed" || v["restoration_error"] != nil {
				complete = false
			}
		}
		if complete {
			item(b, "Wiederherstellung", "für alle beendeten Sitzungen bestätigt")
		} else {
			item(b, "Wiederherstellung", "nicht vollständig bestätigt – siehe technische Details")
		}
	}
	b.WriteString("— = ausstehend, unvollständig oder nicht verfügbar; Anzahl ggf. in Klammern.\n* = Messmedian vorhanden, aber Fehler/Erstlauf beachten.\n")
	if s.Config.Heat {
		for _, h := range s.Hosts {
			ms := phaseMinutes(s, "Last")
			cpu, gpu := false, false
			for _, m := range ms {
				r := hostReading(m, h.URL)
				cpu = cpu || len(temperatureNumbers(r, "cpu")) > 0
				gpu = gpu || len(temperatureNumbers(r, "gpu")) > 0
			}
			if len(ms) > 0 && (!cpu || !gpu) {
				item(b, "Sensoren", h.URL+": fehlende CPU-/GPU-Werte als nicht verfügbar ausgewiesen")
			}
		}
	}
	b.WriteString("Backend-Build, Thinking und Decoder nur soweit vom Commander bestätigt.\nKein fachlicher Qualitätsnachweis durch diesen Laufzeitvergleich.\n")
	b.WriteString("\nAudio: Hörtexte Deutsch – „Der Husten geht nicht weg“\nhttps://www.hoertexte-deutsch.at/mp3/husten.mp3\nLizenz laut Referenz: CC BY-NC-ND 3.0 AT\nhttps://creativecommons.org/licenses/by-nc-nd/3.0/at/\n")
}
