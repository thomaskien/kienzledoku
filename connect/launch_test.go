package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func runtimeFixture(t *testing.T, root, rel string) string {
	t.Helper()
	path := filepath.Join(root, filepath.FromSlash(rel))
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("synthetic fixture, never executed"), 0700); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestStandaloneConnectNeedsRecordFiles(t *testing.T) {
	for _, platform := range []string{"windows", "darwin", "linux"} {
		t.Run(platform, func(t *testing.T) {
			root := t.TempDir()
			runtimeFixture(t, root, "runtime/pythonw.exe")
			_, _, err := recordRuntime(root, platform, "")
			if err == nil || !strings.Contains(err.Error(), "Record-Programmdateien fehlen") {
				t.Fatalf("missing application must fail before Python selection: %v", err)
			}
			if strings.Contains(err.Error(), "windows\\build.cmd") != (platform == "windows") {
				t.Fatalf("wrong platform instructions: %v", err)
			}
		})
	}
}

func TestWindowsDoesNotFallBackToPythonStoreAlias(t *testing.T) {
	root := t.TempDir()
	runtimeFixture(t, root, "kienzledoku.py")
	aliasDir := t.TempDir()
	runtimeFixture(t, aliasDir, "python3.exe")
	runtimeFixture(t, aliasDir, "python3")
	t.Setenv("PATH", aliasDir)
	_, _, err := recordRuntime(root, "windows", "")
	if err == nil || !strings.Contains(err.Error(), "runtime\\pythonw.exe fehlt") {
		t.Fatalf("PATH alias must never be selected: %v", err)
	}
	python := runtimeFixture(t, root, "runtime/pythonw.exe")
	actual, script, err := recordRuntime(root, "windows", "")
	if err != nil || actual != python || script != filepath.Join(root, "kienzledoku.py") {
		t.Fatalf("bundled runtime not selected: %q, %q, %v", actual, script, err)
	}
}

func TestWindowsExplicitRuntimeMustBeAnExistingAbsoluteFile(t *testing.T) {
	root := t.TempDir()
	runtimeFixture(t, root, "kienzledoku.py")
	for _, override := range []string{"python3", filepath.Join(root, "missing.exe"), root} {
		if _, _, err := recordRuntime(root, "windows", override); err == nil {
			t.Fatalf("accepted invalid override: %q", override)
		}
	}
	python := runtimeFixture(t, root, "custom/python.exe")
	actual, _, err := recordRuntime(root, "windows", python)
	if err != nil || actual != python {
		t.Fatalf("explicit interpreter rejected: %q, %v", actual, err)
	}
}

func TestUnixRecordRuntimeSelectionRemainsCompatible(t *testing.T) {
	for _, platform := range []string{"darwin", "linux"} {
		t.Run(platform, func(t *testing.T) {
			root := t.TempDir()
			runtimeFixture(t, root, "kienzledoku.py")
			python := runtimeFixture(t, root, "venv/bin/python3")
			actual, _, err := recordRuntime(root, platform, "")
			if err != nil || actual != python {
				t.Fatalf("local venv rejected: %q, %v", actual, err)
			}
			custom := runtimeFixture(t, root, "custom/python3")
			actual, _, err = recordRuntime(root, platform, custom)
			if err != nil || actual != custom {
				t.Fatalf("installer runtime override rejected: %q, %v", actual, err)
			}
		})
	}
}
