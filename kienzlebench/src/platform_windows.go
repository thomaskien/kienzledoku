package main

import (
	"syscall"
	"unsafe"
)

var kernel32 = syscall.NewLazyDLL("kernel32.dll")

func hideFile(p string) {
	v, e := syscall.UTF16PtrFromString(p)
	if e == nil {
		a, e := syscall.GetFileAttributes(v)
		if e == nil {
			syscall.SetFileAttributes(v, a|syscall.FILE_ATTRIBUTE_HIDDEN)
		}
	}
}
func replaceFile(src, dst string) error {
	a, e := syscall.UTF16PtrFromString(src)
	if e != nil {
		return e
	}
	b, e := syscall.UTF16PtrFromString(dst)
	if e != nil {
		return e
	}
	// MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH.
	r, _, err := kernel32.NewProc("MoveFileExW").Call(uintptr(unsafe.Pointer(a)), uintptr(unsafe.Pointer(b)), 9)
	if r == 0 {
		return err
	}
	return nil
}
func openBrowser(url string) error {
	u, e := syscall.UTF16PtrFromString(url)
	if e != nil {
		return e
	}
	verb, _ := syscall.UTF16PtrFromString("open")
	r, _, err := syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteW").Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(u)), 0, 0, 1)
	if r <= 32 {
		return err
	}
	return nil
}
