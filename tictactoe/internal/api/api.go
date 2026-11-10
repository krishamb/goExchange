// Package api serves the REST endpoints. Handlers are stateless: identity
// comes from the bearer token on each request and all game state is read
// from and written to the store.
package api

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"golang.org/x/crypto/bcrypt"

	"github.com/krishamb/goExchange/tictactoe/internal/auth"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
)

// Config holds the API's dependencies.
type Config struct {
	Store      *store.Store
	Tokens     *auth.Tokens
	BcryptCost int          // bcrypt.DefaultCost in production; bcrypt.MinCost in tests
	Logger     *slog.Logger // nil means slog.Default()
}

// server holds what the handlers share. Nothing in it changes after New, so
// one server can handle any number of concurrent requests, and any number of
// servers can run side by side against the same database.
type server struct {
	store      *store.Store
	tokens     *auth.Tokens
	bcryptCost int
	log        *slog.Logger

	// dummyHash is checked on logins for unknown usernames so that they cost
	// the same bcrypt work as a wrong password: otherwise response times
	// would reveal which usernames exist.
	dummyHash string
}

// New returns the handler serving the whole API.
func New(cfg Config) (http.Handler, error) {
	if cfg.Store == nil {
		return nil, errors.New("api: Config.Store is required")
	}
	if cfg.Tokens == nil {
		return nil, errors.New("api: Config.Tokens is required")
	}
	if cfg.BcryptCost == 0 {
		cfg.BcryptCost = bcrypt.DefaultCost
	}
	// bcrypt quietly swaps a cost below its minimum for its default, which
	// would hide a misconfiguration, so reject out-of-range costs here.
	if cfg.BcryptCost < bcrypt.MinCost || cfg.BcryptCost > bcrypt.MaxCost {
		return nil, fmt.Errorf("api: Config.BcryptCost %d is outside [%d, %d]",
			cfg.BcryptCost, bcrypt.MinCost, bcrypt.MaxCost)
	}
	if cfg.Logger == nil {
		cfg.Logger = slog.Default()
	}

	// The password is irrelevant: logins for unknown users fail whatever
	// the check returns. Only the cost has to match real users' hashes.
	dummyHash, err := auth.HashPassword("timing-equalizer", cfg.BcryptCost)
	if err != nil {
		return nil, fmt.Errorf("api: hash dummy password: %w", err)
	}

	s := &server{
		store:      cfg.Store,
		tokens:     cfg.Tokens,
		bcryptCost: cfg.BcryptCost,
		log:        cfg.Logger,
		dummyHash:  dummyHash,
	}
	// Logging is outermost so that it also records the 500s written when
	// recoverPanics catches a panic.
	return s.logRequests(s.recoverPanics(s.routes())), nil
}

// routes maps each endpoint to its handler. Requests that match no route get
// JSON 404 and 405 errors instead of ServeMux's plain-text ones, so clients
// can rely on every response being JSON.
func (s *server) routes() http.Handler {
	mux := http.NewServeMux()
	allowed := make(map[string][]string) // path pattern -> methods served there

	handle := func(method, path string, h http.HandlerFunc) {
		mux.HandleFunc(method+" "+path, h)
		allowed[path] = append(allowed[path], method)
		if method == http.MethodGet {
			allowed[path] = append(allowed[path], http.MethodHead) // GET patterns serve HEAD too
		}
	}
	handle(http.MethodPost, "/v1/auth/register", s.register)
	handle(http.MethodPost, "/v1/auth/login", s.login)
	handle(http.MethodPost, "/v1/games", s.requireAuth(s.createGame))
	handle(http.MethodGet, "/v1/games/{id}", s.requireAuth(s.getGame))
	handle(http.MethodPost, "/v1/games/{id}/join", s.requireAuth(s.joinGame))
	handle(http.MethodPost, "/v1/games/{id}/moves", s.requireAuth(s.playMove))
	handle(http.MethodGet, "/v1/games/{id}/moves", s.requireAuth(s.listMoves))
	handle(http.MethodGet, "/healthz", s.healthz)

	// A pattern without a method is less specific than the same path with
	// one, so these only see the methods the routes above don't serve.
	for path, methods := range allowed {
		allow := strings.Join(methods, ", ")
		mux.HandleFunc(path, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Allow", allow)
			writeError(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED",
				r.Method+" is not allowed here; use "+allow)
		})
	}
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeError(w, http.StatusNotFound, "NOT_FOUND", "no such endpoint")
	})
	return mux
}

// healthCheckTimeout bounds the database ping so that a probe fails fast
// rather than hanging while the database is unreachable.
const healthCheckTimeout = 2 * time.Second

type healthResponse struct {
	Status string `json:"status"`
}

func (s *server) healthz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), healthCheckTimeout)
	defer cancel()
	if err := s.store.Ping(ctx); err != nil {
		s.log.WarnContext(r.Context(), "health check failed", "err", err)
		writeJSON(w, http.StatusServiceUnavailable, healthResponse{Status: "unavailable"})
		return
	}
	writeJSON(w, http.StatusOK, healthResponse{Status: "ok"})
}
