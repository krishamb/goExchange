package api

import (
	"context"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"github.com/krishamb/goExchange/tictactoe/internal/auth"
)

// statusRecorder remembers the status code sent through it, for the logging
// and panic-recovery middleware.
type statusRecorder struct {
	http.ResponseWriter
	status int // 0 until the header is written
}

func (rec *statusRecorder) WriteHeader(status int) {
	if rec.status == 0 {
		rec.status = status
	}
	rec.ResponseWriter.WriteHeader(status)
}

func (rec *statusRecorder) Write(b []byte) (int, error) {
	if rec.status == 0 {
		rec.status = http.StatusOK // what net/http sends for a Write without WriteHeader
	}
	return rec.ResponseWriter.Write(b)
}

// Unwrap lets http.ResponseController reach the underlying writer.
func (rec *statusRecorder) Unwrap() http.ResponseWriter { return rec.ResponseWriter }

// logRequests logs one line per request.
func (s *server) logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w}
		next.ServeHTTP(rec, r)
		status := rec.status
		if status == 0 {
			status = http.StatusOK // the handler wrote nothing, so net/http sends 200
		}
		s.log.LogAttrs(r.Context(), slog.LevelInfo, "request",
			slog.String("method", r.Method),
			slog.String("path", r.URL.Path),
			slog.Int("status", status),
			slog.Duration("duration", time.Since(start)),
		)
	})
}

// recoverPanics turns a panicking handler into a logged 500 JSON response.
// Left to net/http, the panic would drop the connection without a response.
func (s *server) recoverPanics(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rec := &statusRecorder{ResponseWriter: w}
		defer func() {
			v := recover()
			if v == nil {
				return
			}
			if v == http.ErrAbortHandler {
				panic(v) // a deliberate abort: let net/http drop the connection quietly
			}
			s.log.ErrorContext(r.Context(), "panic serving request",
				"method", r.Method, "path", r.URL.Path,
				"panic", v, "stack", string(debug.Stack()))
			if rec.status != 0 {
				// Too late for a clean 500. Aborting the connection at least
				// stops the client from taking a truncated body for a whole one.
				panic(http.ErrAbortHandler)
			}
			writeError(rec, http.StatusInternalServerError, "INTERNAL", internalErrorMessage)
		}()
		next.ServeHTTP(rec, r)
	})
}

// claimsKey is the context key for the authenticated caller's auth.Claims.
type claimsKey struct{}

// requireAuth lets a request through to next only if it carries a valid
// bearer token, and passes the token's claims on in the request context.
func (s *server) requireAuth(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		token, ok := bearerToken(r)
		if !ok {
			unauthorized(w, `an "Authorization: Bearer <token>" header is required`)
			return
		}
		claims, err := s.tokens.Verify(token)
		if err != nil {
			// The reason (expired, bad signature, ...) helps debugging but
			// is not the client's business.
			s.log.DebugContext(r.Context(), "token rejected", "err", err)
			unauthorized(w, auth.ErrInvalidToken.Error())
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), claimsKey{}, claims)))
	}
}

func unauthorized(w http.ResponseWriter, message string) {
	w.Header().Set("WWW-Authenticate", "Bearer")
	writeError(w, http.StatusUnauthorized, "UNAUTHORIZED", message)
}

// bearerToken extracts the token from an "Authorization: Bearer <token>"
// header. Auth schemes are case-insensitive (RFC 9110, section 11.1).
func bearerToken(r *http.Request) (string, bool) {
	scheme, token, ok := strings.Cut(r.Header.Get("Authorization"), " ")
	if !ok || !strings.EqualFold(scheme, "Bearer") {
		return "", false
	}
	token = strings.TrimSpace(token)
	return token, token != ""
}

// caller returns the claims of the player making the request. The player is
// always the token's user: handlers never take a player ID from the body.
func caller(r *http.Request) auth.Claims {
	claims, ok := r.Context().Value(claimsKey{}).(auth.Claims)
	if !ok {
		// Only reachable if a route that needs a player lacks requireAuth;
		// recoverPanics turns this into a logged 500.
		panic("api: no claims in request context; is the route missing requireAuth?")
	}
	return claims
}
