package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type Settings struct {
	Schema int    `json:"schema_version"`
	URL    string `json:"commander_url"`
}
type Store struct {
	Dir        string
	ReportPath string
}

func programDir() string {
	p, err := os.Executable()
	if err != nil {
		return ""
	}
	if real, err := filepath.EvalSymlinks(p); err == nil {
		p = real
	}
	return filepath.Dir(p)
}
func (s *Store) settings() (Settings, bool) {
	var v Settings
	b, e := os.ReadFile(filepath.Join(s.Dir, ".kienzlebench.json"))
	if os.IsNotExist(e) {
		return v, false
	}
	if e != nil || json.Unmarshal(b, &v) != nil || v.Schema != 1 {
		return Settings{}, true
	}
	if _, e = validURL(v.URL); e != nil {
		return Settings{}, true
	}
	return v, false
}
func (s *Store) saveSettings(url string) {
	if _, bad := s.settings(); bad {
		return
	} // Preserve unreadable/invalid existing settings.
	b, _ := json.MarshalIndent(Settings{1, url}, "", "  ")
	p := filepath.Join(s.Dir, ".kienzlebench.json")
	if atomicWrite(p, append(b, '\n')) == nil {
		hideFile(p)
	}
}
func atomicWrite(path string, data []byte) error {
	dir := filepath.Dir(path)
	f, e := os.CreateTemp(dir, ".kienzlebench-tmp-*")
	if e != nil {
		return e
	}
	tmp := f.Name()
	defer os.Remove(tmp)
	if _, e = f.Write(data); e == nil {
		e = f.Sync()
	}
	closeErr := f.Close()
	if e == nil {
		e = closeErr
	}
	if e != nil {
		return e
	}
	return replaceFile(tmp, path)
}
func (s *Store) saveReport(body string, stamp time.Time) bool {
	if s.Dir == "" {
		return false
	}
	if s.ReportPath != "" {
		return atomicWrite(s.ReportPath, []byte(body)) == nil
	}
	base := "kienzlebench-bericht-" + stamp.Format("2006-01-02_15-04-05")
	for i := 0; i < 1000; i++ {
		suffix := ""
		if i > 0 {
			suffix = fmt.Sprintf("-%02d", i)
		}
		p := filepath.Join(s.Dir, base+suffix+".txt")
		f, e := os.OpenFile(p, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if os.IsExist(e) {
			continue
		}
		if e != nil {
			return false
		}
		_, e = f.WriteString(body)
		if e == nil {
			e = f.Sync()
		}
		ce := f.Close()
		if e == nil {
			e = ce
		}
		if e != nil {
			os.Remove(p)
			return false
		}
		s.ReportPath = p
		return true
	}
	return false
}
