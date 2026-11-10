//go:build !windows

package main

import (
	"fmt"
	"os"
)

func reportError(message string) { fmt.Fprintln(os.Stderr, "kienzledoku connect:", message) }
