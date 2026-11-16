package main

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"mime/multipart"
	"net/textproto"
	"strings"
	"sync"
	"time"
)

type Session struct {
	client   *Client
	id       string
	model    string
	mode     string
	asr, llm bool
}
type Group struct {
	sessions []*Session
	ctx      context.Context
	cancel   context.CancelFunc
	stop     chan struct{}
	wg       sync.WaitGroup
	mu       sync.Mutex
	err      error
}

func (g *Group) asr() *Session {
	for _, s := range g.sessions {
		if s.asr {
			return s
		}
	}
	return nil
}
func (g *Group) llm() *Session {
	for i := len(g.sessions) - 1; i >= 0; i-- {
		if g.sessions[i].llm {
			return g.sessions[i]
		}
	}
	return nil
}
func (a *App) begin(ctx context.Context, hosts []Host, model, mode string) (*Group, error) {
	gc, cancel := context.WithCancel(ctx)
	g := &Group{ctx: gc, cancel: cancel, stop: make(chan struct{})}
	for _, h := range hosts {
		localModel := any(nil)
		localMode := "serial"
		if role(h, "llm") {
			localModel = model
			localMode = mode
		}
		// ASR-only benchmarks still need an explicit installed profile on a combined host.
		v, e := h.client.json(gc, "POST", "/v1/benchmark/session", "", Obj{"model_id": localModel, "mode": localMode, "lease_seconds": 120})
		if e != nil {
			a.end(g)
			return nil, e
		}
		id, _ := v["id"].(string)
		if id == "" {
			a.end(g)
			return nil, errors.New("Commander liefert keine Sitzungs-ID.")
		}
		s := &Session{h.client, id, model, localMode, role(h, "asr"), role(h, "llm")}
		g.sessions = append(g.sessions, s)
		// Start each lease immediately, also while another host is being contacted.
		g.wg.Add(1)
		go func(s *Session) {
			defer g.wg.Done()
			t := time.NewTicker(25 * time.Second)
			defer t.Stop()
			for {
				select {
				case <-g.stop:
					return
				case <-t.C:
					kc, k := context.WithTimeout(context.Background(), 12*time.Second)
					_, e := s.client.json(kc, "POST", "/v1/benchmark/session/keepalive", s.id, Obj{})
					k()
					if e != nil {
						g.mu.Lock()
						g.err = errors.New("Benchmarksitzung konnte nicht verlängert werden; Test angehalten.")
						g.mu.Unlock()
						g.cancel()
						return
					}
				}
			}
		}(s)
	}
	return g, nil
}
func pause(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}
func (a *App) end(g *Group) error {
	if g == nil {
		return nil
	}
	defer g.cancel()
	close(g.stop)
	g.wg.Wait()
	var failure error
	// Initiate both hosts before waiting for either to drain.
	ctx, cancel := context.WithTimeout(context.Background(), a.drainTimeout)
	defer cancel()
	for _, s := range g.sessions {
		_, e := s.client.json(ctx, "POST", "/v1/benchmark/session/end", s.id, Obj{})
		if e != nil {
			failure = fmt.Errorf("Sitzungsende: %w; Lease begrenzt den weiteren Betrieb", e)
		}
	}
	for _, s := range g.sessions {
		var last Obj
		for {
			v, e := s.client.json(ctx, "GET", "/v1/benchmark/session", s.id, nil)
			if e != nil {
				failure = fmt.Errorf("Wiederherstellung nicht bestätigt: %w", e)
				break
			}
			last = v
			if v["restoration_error"] != nil && v["restoration_error"] != "" {
				failure = errors.New("Commander meldet einen Wiederherstellungsfehler.")
				break
			}
			if v["state"] == "completed" {
				break
			}
			if e = pause(ctx, 250*time.Millisecond); e != nil {
				failure = errors.New("Zeitlimit beim Nachlauf; Wiederherstellung nicht bestätigt.")
				break
			}
		}
		a.mu.Lock()
		a.st.Restorations = append(a.st.Restorations, Obj{"host": s.client.URL, "model": s.model, "mode": s.mode, "result": last})
		a.mu.Unlock()
	}
	g.mu.Lock()
	if failure == nil {
		failure = g.err
	}
	g.mu.Unlock()
	return failure
}
func settled(ctx context.Context, s *Session, id string) (Obj, error) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Minute)
	defer cancel()
	for {
		v, e := s.client.json(ctx, "GET", "/v1/benchmark/jobs/"+id, s.id, nil)
		if e != nil {
			return nil, e
		}
		if yes(v["return_complete"]) {
			return v, nil
		}
		if e = pause(ctx, 100*time.Millisecond); e != nil {
			return nil, e
		}
	}
}
func llmRequest(ctx context.Context, s *Session, caseID string) (Obj, float64, error) {
	transcript, e := assets.ReadFile("assets/" + caseID + ".txt")
	if e != nil {
		return nil, 0, e
	}
	prompt, _ := assets.ReadFile("assets/prompt_documentation.txt")
	body := Obj{"model_id": s.model, "request_id": freshID(), "messages": []Obj{{"role": "system", "content": strings.TrimSpace(string(prompt))}, {"role": "user", "content": "TRANSKRIPT:\n\n" + strings.TrimSpace(string(transcript))}}, "temperature": 0.1, "max_tokens": 1600, "top_p": 0.95, "top_k": 40, "min_p": 0.05, "repeat_penalty": 1.0, "seed": 42}
	start := time.Now()
	v, e := s.client.json(ctx, "POST", "/v1/benchmark/chat/completions", s.id, body)
	return v, time.Since(start).Seconds(), e
}
func llmSeconds(m Obj, mode string) (*float64, string) {
	inference, ok := num(m["inference_seconds"])
	if !ok {
		return nil, "Inferenzzeit fehlt"
	}
	if mode == "parallel" {
		return &inference, ""
	}
	started, ok := num(m["inference_started_at"])
	end, okEnd := num(m["completed_at"])
	found := false
	for _, v := range arr(m["model_changes"]) {
		c := obj(v)
		if c["role"] == "llm" && c["operation"] == "load" && yes(c["success"]) {
			if x, okx := num(c["started_at"]); okx && (!found || x < started) {
				started = x
				found = true
			}
		}
	}
	if !ok || !okEnd || !found {
		return nil, "Kein bestätigtes frisches LLM-Laden; historische serielle Zeit nicht verfügbar"
	}
	total := end - started
	if total < 0 {
		return nil, "Ungültige Zeitbasis"
	}
	return &total, ""
}
func validateLLM(v Obj) error {
	choices := arr(v["choices"])
	if len(choices) == 0 {
		return errors.New("LLM-Antwort fehlt.")
	}
	ch := obj(choices[0])
	if ch["finish_reason"] != "stop" {
		return errors.New("LLM-Antwort nicht vollständig (kein stop).")
	}
	text, ok := obj(ch["message"])["content"].(string)
	var d map[string]any
	if !ok || json.Unmarshal([]byte(text), &d) != nil || len(d) != 4 {
		return errors.New("Antwort entspricht nicht dem GP60-JSON-Vertrag.")
	}
	for _, k := range []string{"anamnese", "befund", "therapie", "prozedere"} {
		if _, ok := d[k].(string); !ok {
			return errors.New("GP60-Textfeld fehlt oder hat falschen Typ.")
		}
	}
	u := obj(v["usage"])
	if n, ok := num(obj(u["prompt_tokens_details"])["cached_tokens"]); ok && n > 0 {
		return errors.New("Backend meldet Prompt-Cache-Nutzung.")
	}
	if n, ok := num(obj(v["timings"])["cache_n"]); ok && n > 0 {
		return errors.New("Backend meldet Prompt-Cache-Nutzung.")
	}
	return nil
}
func (a *App) llmSample(ctx context.Context, g *Group, caseID string, iteration int, phase string) Result {
	s := g.llm()
	r := Result{Model: s.model, Mode: s.mode, Case: caseID, Iteration: iteration, Phase: phase}
	v, elapsed, e := llmRequest(ctx, s, caseID)
	r.HTTPSeconds = elapsed
	if e != nil {
		r.Error = e.Error()
		return r
	}
	m := obj(v["benchmark"])
	if m["model_id"] != s.model {
		r.Error = "Commander bestätigt ein anderes Modell als angefordert."
		return r
	}
	if phase != "Wärmetest" {
		if final, e := settled(ctx, s, str(m["request_id"])); e == nil {
			m = final
		} else {
			r.Error = "Rückwechsel nicht bestätigt: " + e.Error()
		}
	}
	m["usage"] = v["usage"]
	m["timings"] = v["timings"]
	r.Metrics = []Obj{m}
	r.Seconds, r.Note = llmSeconds(m, s.mode)
	if e = validateLLM(v); e != nil {
		r.Error = e.Error()
	}
	if r.Seconds == nil && r.Error == "" {
		r.Error = r.Note
	}
	return r
}

type Segment struct {
	ID    int     `json:"id"`
	Start float64 `json:"physical_start"`
	End   float64 `json:"physical_end"`
	Pad   float64 `json:"pad_tail"`
}

func audioBlocks() [][]byte {
	pcm, _ := assets.ReadFile("assets/husten.pcm")
	raw, _ := assets.ReadFile("assets/audio-segments.json")
	var segments []Segment
	if json.Unmarshal(raw, &segments) != nil {
		panic("Audiosegmentierung ungültig")
	}
	out := make([][]byte, 0, len(segments))
	for _, s := range segments {
		start := int(math.Round(s.Start*16000)) * 2
		end := int(math.Round(s.End*16000)) * 2
		n := end - start + int(math.Round(s.Pad*16000))*2
		b := make([]byte, 44+n)
		copy(b, "RIFF")
		binary.LittleEndian.PutUint32(b[4:], uint32(36+n))
		copy(b[8:], "WAVEfmt ")
		binary.LittleEndian.PutUint32(b[16:], 16)
		binary.LittleEndian.PutUint16(b[20:], 1)
		binary.LittleEndian.PutUint16(b[22:], 1)
		binary.LittleEndian.PutUint32(b[24:], 16000)
		binary.LittleEndian.PutUint32(b[28:], 32000)
		binary.LittleEndian.PutUint16(b[32:], 2)
		binary.LittleEndian.PutUint16(b[34:], 16)
		copy(b[36:], "data")
		binary.LittleEndian.PutUint32(b[40:], uint32(n))
		copy(b[44:], pcm[start:end])
		out = append(out, b)
	}
	return out
}
func asrBlock(ctx context.Context, s *Session, wav []byte) (Obj, error) {
	var b bytes.Buffer
	w := multipart.NewWriter(&b)
	header := textproto.MIMEHeader{}
	header.Set("Content-Disposition", `form-data; name="file"; filename="block.wav"`)
	header.Set("Content-Type", "audio/wav")
	p, _ := w.CreatePart(header)
	p.Write(wav)
	w.WriteField("language", "de")
	w.Close()
	return s.client.request(ctx, "POST", "/v1/benchmark/asr/final-block", s.id, w.FormDataContentType(), freshID(), b.Bytes())
}

var expectedDecoder = Obj{"beam_size": float64(5), "best_of": float64(5), "temperature": float64(0), "vad_filter": false, "word_timestamps": true, "condition_on_previous_text": false}

func checkDecoder(v any) string {
	if v == nil {
		return "Decodervertrag vom Backend nicht bestätigt"
	}
	d := obj(v)
	for k, want := range expectedDecoder {
		if d[k] != want {
			return "Decodervertrag weicht vom historischen Whisper-Test ab"
		}
	}
	return ""
}
func (a *App) whisperSample(ctx context.Context, g *Group, iteration int, phase string, blocks [][]byte, deadline time.Time) Result {
	s := g.asr()
	r := Result{Model: "Whisper", Mode: s.mode, Case: "Husten 113,16 s", Iteration: iteration, Phase: phase}
	if g.llm() != nil {
		r.Mode = g.llm().mode
	}
	var loadStart *float64
	if phase != "Wärmetest" && s.mode == "serial" && g.llm() != nil && g.llm().client == s.client {
		// Force an actual ASR -> LLM -> ASR transition; the priming LLM result is not a measurement.
		v, _, e := llmRequest(ctx, g.llm(), "G60_01A")
		if e != nil {
			r.Error = "Whisper-Ladevorbereitung: " + e.Error()
			return r
		}
		m, e := settled(ctx, g.llm(), str(obj(v["benchmark"])["request_id"]))
		if e != nil {
			r.Error = "Whisper-Ladevorbereitung: " + e.Error()
			return r
		}
		for _, v := range arr(m["model_changes"]) {
			c := obj(v)
			if c["role"] == "asr" && c["operation"] == "load" && yes(c["success"]) {
				if f, ok := num(c["started_at"]); ok {
					n := f
					loadStart = &n
				}
			}
		}
	}
	start := time.Now()
	decoderNote := ""
	lastID := ""
	var end float64
	for i, b := range blocks {
		if ctx.Err() != nil {
			r.Error = ctx.Err().Error()
			break
		}
		if !deadline.IsZero() && !time.Now().Before(deadline) {
			r.Note = fmt.Sprintf("Lastfenster beendet nach %d von 13 Blöcken", i)
			break
		}
		v, e := asrBlock(ctx, s, b)
		if e != nil {
			r.Error = fmt.Sprintf("Block %d: %v", i+1, e)
			break
		}
		m := obj(v["benchmark"])
		if loadStart == nil {
			for _, change := range arr(m["model_changes"]) {
				c := obj(change)
				if c["role"] == "asr" && c["operation"] == "load" && yes(c["success"]) {
					if n, ok := num(c["started_at"]); ok {
						loadStart = &n
						break
					}
				}
			}
		}
		m["decoder"] = v["decoder"]
		r.Metrics = append(r.Metrics, m)
		lastID = str(m["request_id"])
		end, _ = num(m["completed_at"])
		if reason := checkDecoder(v["decoder"]); reason != "" {
			decoderNote = reason
		}
		text, _ := v["text"].(string)
		if strings.TrimSpace(text) == "" && len(arr(v["words"])) == 0 && len(arr(v["segments"])) == 0 {
			r.Error = fmt.Sprintf("Block %d: keine Transkription", i+1)
			break
		}
	}
	r.HTTPSeconds = time.Since(start).Seconds()
	if len(r.Metrics) == 13 && r.Error == "" {
		t := r.HTTPSeconds
		if phase == "Wärmetest" {
			// Successful workload is sufficient for the heat test, even when ASR is
			// already resident after the preceding LLM's return transition.
			r.Note = "Wärmetest: HTTP-Verarbeitungszeit; keine historische serielle Vergleichszeit"
		} else if r.Mode == "serial" {
			if loadStart == nil || end <= *loadStart {
				r.Note = "Kein bestätigtes frisches Whisper-Laden; Verarbeitung ab geladenem Backend steht ausschließlich unter HTTP"
				r.Error = "Historische serielle Whisper-Zeit nicht verfügbar"
			} else {
				t = end - *loadStart
			}
		}
		if r.Error == "" {
			r.Seconds = &t
		}
	}
	if decoderNote != "" {
		if r.Note != "" {
			r.Note += "; "
		}
		r.Note += decoderNote
	}
	if phase != "Wärmetest" && lastID != "" {
		if m, e := settled(ctx, s, lastID); e == nil {
			r.Metrics[len(r.Metrics)-1] = m
		} else {
			r.Error = "Whisper-Rückwechsel nicht bestätigt: " + e.Error()
		}
	}
	return r
}
func defaultModel(hosts []Host, selected []string) string {
	if len(selected) > 0 {
		return selected[0]
	}
	if len(hosts) == 0 {
		return ""
	}
	models := arr(hosts[len(hosts)-1].Inventory["models"])
	for _, v := range models {
		m := obj(v)
		if yes(m["available"]) && yes(m["default"]) {
			return str(m["id"])
		}
	}
	for _, v := range models {
		m := obj(v)
		if yes(m["available"]) {
			return str(m["id"])
		}
	}
	return ""
}
func parallelOK(hosts []Host, id string) bool {
	for _, v := range arr(hosts[len(hosts)-1].Inventory["models"]) {
		m := obj(v)
		if m["id"] == id {
			return yes(m["parallel_available"])
		}
	}
	return false
}
func (a *App) run(ctx context.Context, c Config, hosts []Host) {
	defer func() {
		a.mu.Lock()
		a.st.Running = false
		a.st.Ended = time.Now()
		a.cancel = nil
		if ctx.Err() != nil {
			a.st.Status = "Abgebrochen – Teilbericht"
		} else if len(a.st.Errors) > 0 {
			a.st.Status = "Beendet mit Fehlern"
		} else {
			a.st.Status = "Abgeschlossen"
		}
		a.st.Progress = "Temperaturanzeige und Nachkühlung laufen weiter, solange das Fenster geöffnet ist."
		a.persistLocked()
		a.mu.Unlock()
		select {
		case a.thermalWake <- struct{}{}:
		default:
		}
		close(a.done)
	}()
	for _, model := range c.Models {
		for _, mode := range c.Modes {
			if ctx.Err() != nil {
				return
			}
			if mode == "parallel" && !parallelOK(hosts, model) {
				a.add(Result{Model: model, Mode: mode, Case: "GP60", Error: "Nicht getestet: kein freigegebenes Parallelprofil"})
				continue
			}
			a.progress(model + " · " + mode + " · Sitzung vorbereiten")
			g, e := a.begin(ctx, hosts, model, mode)
			if e != nil {
				a.fail(e)
				return
			}
			for _, caseID := range []string{"G60_01A", "G60_30B"} {
				for n := 0; n < 6; n++ {
					if g.ctx.Err() != nil {
						break
					}
					a.progress(fmt.Sprintf("%s · %s · %s · Lauf %d/6", model, mode, caseID, n+1))
					r := a.llmSample(g.ctx, g, caseID, n, "Benchmark")
					a.add(r)
				}
				if g.ctx.Err() != nil {
					break
				}
			}
			e = a.end(g)
			if e != nil {
				a.fail(e)
				return
			}
			if ctx.Err() != nil {
				return
			}
		}
	}
	blocks := audioBlocks()
	if c.Whisper {
		modes := c.Modes
		if len(modes) == 0 {
			modes = []string{"serial"}
		}
		model := defaultModel(hosts, c.Models)
		for _, mode := range modes {
			if ctx.Err() != nil {
				return
			}
			if mode == "parallel" && !parallelOK(hosts, model) {
				a.add(Result{Model: "Whisper", Mode: mode, Case: "Husten", Error: "Nicht getestet: kein freigegebenes Parallelprofil"})
				continue
			}
			g, e := a.begin(ctx, hosts, model, mode)
			if e != nil {
				a.fail(e)
				return
			}
			for n := 0; n < 6; n++ {
				if g.ctx.Err() != nil {
					break
				}
				a.progress(fmt.Sprintf("Whisper · %s · Husten · Lauf %d/6", mode, n+1))
				r := a.whisperSample(g.ctx, g, n, "Benchmark", blocks, time.Time{})
				r.Note = "LLM-Kontext: " + model + ". " + r.Note
				a.add(r)
			}
			if e = a.end(g); e != nil {
				a.fail(e)
				return
			}
		}
	}
	if c.Heat && ctx.Err() == nil {
		a.heat(ctx, c, hosts, blocks)
	}
	a.mu.Lock()
	for _, r := range a.st.Results {
		if r.Error != "" {
			a.st.Errors = append(a.st.Errors, "Mindestens eine Testreihe ist unvollständig oder fehlgeschlagen.")
			break
		}
	}
	a.mu.Unlock()
}
func (a *App) heat(ctx context.Context, c Config, hosts []Host, blocks [][]byte) {
	heatCtx, cancelHeat := context.WithCancel(ctx)
	defer cancelHeat()
	g, e := a.begin(heatCtx, hosts, c.HeatModel, c.HeatMode)
	if e != nil {
		a.fail(e)
		return
	}
	start := time.Now()
	deadline := start.Add(a.heatDuration)
	sampleCtx, stopSamples := context.WithCancel(heatCtx)
	samplesDone := make(chan struct{})
	a.mu.Lock()
	a.st.HeatStarted = start
	a.st.Progress = "Wärmetest · 30 Minuten · " + c.HeatModel
	a.mu.Unlock()
	go func() { defer close(samplesDone); a.heatMinutes(sampleCtx, hosts, start) }()
	select {
	case a.thermalWake <- struct{}{}:
	default:
	}
	drainCtx, drainCancel := context.WithDeadline(heatCtx, deadline.Add(a.drainTimeout))
	defer drainCancel()
	workDone := make(chan struct{})
	go func() {
		defer close(workDone)
		llmIteration, asrIteration := 0, 0
		current := g
		for {
			// Both workers share the request budget. End the batch together, then
			// renew the session so a fast backend cannot exhaust Commander's IDs.
			var budgetMu sync.Mutex
			used, renew := 0, false
			reserve := func(count int) bool {
				budgetMu.Lock()
				defer budgetMu.Unlock()
				if used+count > a.heatSessionRequests {
					renew = true
				}
				if renew || !time.Now().Before(deadline) || current.ctx.Err() != nil || drainCtx.Err() != nil {
					return false
				}
				used += count
				return true
			}
			workCtx, stopWork := context.WithDeadline(current.ctx, deadline.Add(a.drainTimeout))
			var failed sync.Once
			record := func(r Result) bool {
				a.add(r)
				if r.Error != "" {
					failed.Do(func() {
						if ctx.Err() == nil {
							a.fail(errors.New("Wärmetest wegen fehlgeschlagener Anfrage beendet."))
						}
						cancelHeat()
					})
					return false
				}
				return true
			}
			llm := func() bool {
				n := llmIteration
				llmIteration++
				return record(a.llmSample(workCtx, current, []string{"G60_01A", "G60_30B"}[n%2], n, "Wärmetest"))
			}
			asr := func() bool {
				n := asrIteration
				asrIteration++
				return record(a.whisperSample(workCtx, current, n, "Wärmetest", blocks, deadline))
			}
			if c.HeatMode == "parallel" {
				var workers sync.WaitGroup
				workers.Add(2)
				go func() {
					defer workers.Done()
					for reserve(1) {
						if !llm() {
							return
						}
					}
				}()
				go func() {
					defer workers.Done()
					for reserve(len(blocks)) {
						if !asr() {
							return
						}
					}
				}()
				workers.Wait()
			} else {
				for reserve(1 + len(blocks)) {
					if !llm() {
						break
					}
					if time.Now().Before(deadline) && workCtx.Err() == nil && !asr() {
						break
					}
				}
			}
			stopWork()
			// Do not overlap session restoration or model transitions with a new batch.
			if err := a.end(current); err != nil {
				a.fail(err)
				cancelHeat()
				return
			}
			if !time.Now().Before(deadline) || drainCtx.Err() != nil {
				return
			}
			a.progress("Wärmetest · Benchmarksitzung wird erneuert; Zeitachse läuft weiter.")
			var err error
			current, err = a.begin(drainCtx, hosts, c.HeatModel, c.HeatMode)
			if err != nil {
				a.fail(err)
				cancelHeat()
				return
			}
			a.progress("Wärmetest · 30 Minuten · " + c.HeatModel)
		}
	}()
	t := time.NewTimer(time.Until(deadline))
	defer t.Stop()
	full := false
	select {
	case <-t.C:
		full = true
	case <-heatCtx.Done():
	case <-workDone:
		full = !time.Now().Before(deadline) && heatCtx.Err() == nil
	}
	loadEnd := time.Now()
	stopSamples()
	<-samplesDone
	if full {
		readings := fetchTemperatures(heatCtx, hosts)
		a.mu.Lock()
		hasEnd := false
		for _, m := range a.st.Minutes {
			if m.Phase == "Last" && m.Minute == int(a.heatDuration/a.minuteDuration) {
				hasEnd = true
			}
		}
		if !hasEnd {
			a.st.Minutes = append(a.st.Minutes, Minute{"Last", int(a.heatDuration / a.minuteDuration), time.Since(start).Seconds(), time.Now(), readings})
		}
		a.mu.Unlock()
	}
	a.mu.Lock()
	a.st.HeatEnded = loadEnd
	a.st.Progress = "Lastfenster beendet; aktive Anfragen und Modellvorhaltung werden abgeschlossen."
	a.mu.Unlock()
	// No new work after the deadline. Existing HTTP requests have a bounded drain.
	<-workDone
	a.mu.Lock()
	a.st.HeatDrainSeconds = time.Since(loadEnd).Seconds()
	a.mu.Unlock()
}
