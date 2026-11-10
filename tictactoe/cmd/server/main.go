// Command server runs the tic-tac-toe REST API.
//
// It is configured through the environment:
//
//	DATABASE_URL  PostgreSQL connection URL (required)
//	JWT_SECRET    secret for signing tokens, at least 32 bytes (required)
//	PORT          port to listen on (default 8080)
//	TOKEN_TTL     how long a login token stays valid, as a Go duration (default 24h)
//
// The server keeps no state between requests, so any number of instances can
// run behind a load balancer as long as they share the database and
// JWT_SECRET.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/krishamb/goExchange/tictactoe/internal/api"
	"github.com/krishamb/goExchange/tictactoe/internal/auth"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
)

const (
	defaultPort     = "8080"
	defaultTokenTTL = 24 * time.Hour

	// shutdownTimeout is how long in-flight requests get to finish once a
	// stop signal arrives.
	shutdownTimeout = 10 * time.Second
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stderr, nil))
	slog.SetDefault(logger)

	cfg, err := loadConfig(os.Getenv)
	if err != nil {
		logger.Error("invalid configuration", "err", err)
		os.Exit(2)
	}
	if err := run(cfg, logger); err != nil {
		logger.Error("server stopped", "err", err)
		os.Exit(1)
	}
}

type config struct {
	databaseURL string
	jwtSecret   []byte
	addr        string
	tokenTTL    time.Duration
}

// loadConfig reads the configuration through getenv and reports every
// problem at once, so a broken deployment can be fixed in one pass.
func loadConfig(getenv func(string) string) (config, error) {
	cfg := config{
		databaseURL: getenv("DATABASE_URL"),
		jwtSecret:   []byte(getenv("JWT_SECRET")),
		tokenTTL:    defaultTokenTTL,
	}
	var problems []string

	if cfg.databaseURL == "" {
		problems = append(problems, "DATABASE_URL is required")
	}
	switch {
	case len(cfg.jwtSecret) == 0:
		problems = append(problems, "JWT_SECRET is required")
	case len(cfg.jwtSecret) < auth.MinSecretLen:
		problems = append(problems, fmt.Sprintf("JWT_SECRET must be at least %d bytes", auth.MinSecretLen))
	}

	port := getenv("PORT")
	if port == "" {
		port = defaultPort
	}
	if n, err := strconv.Atoi(port); err != nil || n < 1 || n > 65535 {
		problems = append(problems, fmt.Sprintf("PORT must be a number from 1 to 65535, got %q", port))
	}
	cfg.addr = ":" + port

	if v := getenv("TOKEN_TTL"); v != "" {
		ttl, err := time.ParseDuration(v)
		if err != nil || ttl <= 0 {
			problems = append(problems, fmt.Sprintf("TOKEN_TTL must be a positive Go duration such as 24h or 90m, got %q", v))
		}
		cfg.tokenTTL = ttl
	}

	if len(problems) > 0 {
		return config{}, errors.New(strings.Join(problems, "; "))
	}
	return cfg, nil
}

// run serves the API until SIGINT or SIGTERM, then shuts down gracefully.
func run(cfg config, logger *slog.Logger) error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	pool, err := pgxpool.New(ctx, cfg.databaseURL)
	if err != nil {
		return fmt.Errorf("open database pool: %w", err)
	}
	// Deferred first so that it runs last: in-flight requests drained by
	// Shutdown below may still be using the pool.
	defer pool.Close()

	if err := store.Migrate(ctx, pool); err != nil {
		return fmt.Errorf("migrate database: %w", err)
	}
	tokens, err := auth.NewTokens(cfg.jwtSecret, cfg.tokenTTL)
	if err != nil {
		return fmt.Errorf("create token issuer: %w", err)
	}
	handler, err := api.New(api.Config{Store: store.New(pool), Tokens: tokens, Logger: logger})
	if err != nil {
		return fmt.Errorf("create API handler: %w", err)
	}

	srv := &http.Server{
		Addr:              cfg.addr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
		ErrorLog:          slog.NewLogLogger(logger.Handler(), slog.LevelWarn),
	}
	serveErr := make(chan error, 1)
	go func() {
		logger.Info("listening", "addr", srv.Addr)
		serveErr <- srv.ListenAndServe()
	}()

	select {
	case err := <-serveErr:
		// Before Shutdown, ListenAndServe returns only on failure, such as
		// the port already being in use.
		return fmt.Errorf("serve: %w", err)
	case <-ctx.Done():
	}
	// From here a second signal kills the process at once, for anyone who
	// doesn't want to wait for the graceful shutdown.
	stop()

	logger.Info("shutting down", "timeout", shutdownTimeout)
	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("shut down: %w", err)
	}
	logger.Info("stopped")
	return nil
}
