//go:build windows

package main

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

func reportError(message string) {
	fmt.Fprintln(os.Stderr, "kienzledoku connect:", message)
	if len(os.Args) == 2 && os.Args[1] == "serve-stdio" {
		return
	}
	text, _ := syscall.UTF16PtrFromString(message)
	title, _ := syscall.UTF16PtrFromString("kienzledoku connect")
	syscall.NewLazyDLL("user32.dll").NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(text)), uintptr(unsafe.Pointer(title)), 0x10)
}
