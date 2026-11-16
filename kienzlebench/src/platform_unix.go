//go:build !windows

package main

import (
	"os"
	"os/exec"
	"runtime"
)

func hideFile(string)                   {}
func replaceFile(src, dst string) error { return os.Rename(src, dst) }
func openBrowser(url string) error {
	name := "xdg-open"
	if runtime.GOOS == "darwin" {
		name = "open"
	}
	c := exec.Command(name, url)
	if e := c.Start(); e != nil {
		return e
	}
	go c.Wait()
	return nil
}
