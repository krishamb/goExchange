package api

// Panic recovery can't be triggered through the real routes, so these tests
// drive the middleware directly.

import (
	"bytes"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPanicBecomesLogged500(t *testing.T) {
	var logs bytes.Buffer
	s := &server{log: slog.New(slog.NewTextHandler(&logs, nil))}
	h := s.logRequests(s.recoverPanics(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("boom")
	})))

	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/v1/games/42", nil))

	if rec.Code != http.StatusInternalServerError {
		t.Errorf("status %d, want 500", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type %q, want application/json", ct)
	}
	if got, want := rec.Body.String(), `{"error":{"code":"INTERNAL","message":"internal server error"}}`+"\n"; got != want {
		t.Errorf("body %s, want %s", got, want)
	}
	for _, want := range []string{
		`level=ERROR msg="panic serving request" method=GET path=/v1/games/42 panic=boom`,
		`level=INFO msg=request method=GET path=/v1/games/42 status=500 duration=`,
	} {
		if !strings.Contains(logs.String(), want) {
			t.Errorf("log lacks %q:\n%s", want, logs.String())
		}
	}
}

func TestPanicAfterHeaderAbortsResponse(t *testing.T) {
	for name, handler := range map[string]http.HandlerFunc{
		// Too late for a 500, so the connection must be dropped instead.
		"panic after the header": func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusOK)
			panic("too late")
		},
		// A handler's deliberate abort passes straight through.
		"ErrAbortHandler": func(http.ResponseWriter, *http.Request) {
			panic(http.ErrAbortHandler)
		},
	} {
		t.Run(name, func(t *testing.T) {
			s := &server{log: slog.New(slog.DiscardHandler)}
			defer func() {
				if v := recover(); v != http.ErrAbortHandler {
					t.Errorf("panicked with %v, want http.ErrAbortHandler", v)
				}
			}()
			s.recoverPanics(handler).ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/", nil))
			t.Error("ServeHTTP returned normally, want a panic")
		})
	}
}
