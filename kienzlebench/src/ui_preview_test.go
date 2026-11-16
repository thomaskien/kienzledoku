package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"testing"
	"time"
)

// Test-only preview. Example data is never compiled into the portable executable.
func TestUIPreview(t *testing.T) {
	if os.Getenv("KIENZLEBENCH_UI_PREVIEW") != "1" {
		t.Skip("manual visual verification")
	}
	a := newApp(context.Background(), t.TempDir())
	a.st = exampleState()
	a.st.URL = "http://beispiel-server:8185"
	listener, e := net.Listen("tcp4", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	w := &Web{app: a, prefix: "/" + freshID() + "/", host: listener.Addr().String(), shutdown: make(chan struct{}, 1)}
	server := &http.Server{Handler: http.HandlerFunc(w.handler)}
	go server.Serve(listener)
	defer server.Close()
	fmt.Println("PREVIEW http://" + w.host + w.prefix)
	select {
	case <-w.shutdown:
	case <-time.After(10 * time.Minute):
	}
}
