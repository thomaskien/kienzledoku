package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Obj = map[string]any

func obj(v any) Obj {
	if x, ok := v.(map[string]any); ok && x != nil {
		return x
	}
	return Obj{}
}
func arr(v any) []any {
	if x, ok := v.([]any); ok {
		return x
	}
	return nil
}
func str(v any) string {
	if v == nil {
		return "nicht verfügbar"
	}
	if s, ok := v.(string); ok {
		return s
	}
	b, _ := json.Marshal(v)
	return string(b)
}
func num(v any) (float64, bool) { f, ok := v.(float64); return f, ok }
func yes(v any) bool            { b, _ := v.(bool); return b }
func freshID() string {
	b := make([]byte, 16)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	return hex.EncodeToString(b)
}
func validURL(s string) (string, error) {
	u, e := url.Parse(strings.TrimSpace(s))
	if e != nil || u.Hostname() == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
		return "", errors.New("Commander-Adresse als http(s)://Host:Port eingeben; ohne Zugangsdaten, Pfad oder URL-Parameter.")
	}
	return strings.TrimRight(u.String(), "/"), nil
}

type Client struct {
	URL, Token string
	HTTP       *http.Client
}

func newClient(address, token string) (*Client, error) {
	u, e := validURL(address)
	if e != nil {
		return nil, e
	}
	if strings.ContainsAny(token, "\r\n") {
		return nil, errors.New("Ungültiger Token.")
	}
	return &Client{u, token, &http.Client{Timeout: 20 * time.Minute, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}
func (c *Client) request(ctx context.Context, method, path, session, contentType, id string, body []byte) (Obj, error) {
	req, e := http.NewRequestWithContext(ctx, method, c.URL+path, bytes.NewReader(body))
	if e != nil {
		return nil, errors.New("Ungültige Anfrage.")
	}
	req.Header.Set("Accept", "application/json")
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	if session != "" {
		req.Header.Set("X-Kienzledoku-Benchmark-Session", session)
	}
	if id != "" {
		req.Header.Set("Idempotency-Key", id)
	}
	res, e := c.HTTP.Do(req)
	if e != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, errors.New("Commander nicht erreichbar oder Zeitlimit überschritten.")
	}
	defer res.Body.Close()
	b, e := io.ReadAll(io.LimitReader(res.Body, 8<<20+1))
	if e != nil || len(b) > 8<<20 {
		return nil, errors.New("Ungültige oder zu große Commander-Antwort.")
	}
	var out Obj
	if json.Unmarshal(b, &out) != nil {
		return nil, fmt.Errorf("Commander HTTP %d: keine gültige JSON-Antwort", res.StatusCode)
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		code := str(obj(out["error"])["code"])
		if code == "nicht verfügbar" {
			code = str(out["code"])
		}
		// Never echo backend text, credentials or arbitrary response content into reports.
		allowed := map[string]bool{"busy": true, "invalid_request": true, "conflict": true, "backend_failure": true, "benchmark_auth_required": true, "unauthorized": true}
		if !allowed[code] {
			code = "Anfrage abgewiesen"
		}
		return nil, fmt.Errorf("Commander HTTP %d: %s", res.StatusCode, code)
	}
	if out == nil {
		return nil, errors.New("Leere Commander-Antwort.")
	}
	return out, nil
}
func (c *Client) json(ctx context.Context, method, path, session string, body any) (Obj, error) {
	var b []byte
	if body != nil {
		b, _ = json.Marshal(body)
	}
	return c.request(ctx, method, path, session, "application/json", "", b)
}
func (c *Client) get(ctx context.Context, path string) (Obj, error) {
	ctx, cancel := context.WithTimeout(ctx, 18*time.Second)
	defer cancel()
	return c.json(ctx, "GET", path, "", nil)
}

type Host struct {
	URL          string `json:"url"`
	Capabilities Obj    `json:"capabilities"`
	Inventory    Obj    `json:"inventory"`
	Hardware     Obj    `json:"hardware"`
	client       *Client
}

func connectHost(ctx context.Context, c *Client) (Host, error) {
	h := Host{URL: c.URL, client: c}
	var e error
	h.Capabilities, e = c.get(ctx, "/v1/runtime/capabilities")
	if e != nil {
		return h, e
	}
	if h.Capabilities["schema_version"] != float64(1) || !yes(h.Capabilities["hardware_inventory"]) {
		return h, errors.New("Commander 1.8 mit Benchmark-Schnittstelle erforderlich.")
	}
	h.Inventory, e = c.get(ctx, "/v1/runtime/inventory")
	if e != nil {
		return h, e
	}
	h.Hardware, e = c.get(ctx, "/v1/runtime/hardware")
	if e != nil {
		h.Hardware = Obj{"unavailable": e.Error()}
	}
	return h, nil
}
