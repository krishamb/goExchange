// Package api serves the REST endpoints. Handlers are stateless: identity
// comes from the bearer token on each request and all game state is read
// from and written to the store.
package api

import (
	"log/slog"
	"net/http"

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

// New returns the handler serving the whole API.
func New(cfg Config) (http.Handler, error) {
	panic("not implemented") // TODO(api agent)
}
