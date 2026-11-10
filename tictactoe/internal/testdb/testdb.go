// Package testdb gives each test its own empty PostgreSQL schema, so tests
// (and test packages running in parallel) never see each other's rows.
//
// Tests that use it are skipped when TEST_DATABASE_URL is not set.
package testdb

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// EnvVar names the environment variable holding the connection URL.
const EnvVar = "TEST_DATABASE_URL"

// DB is one test's private schema. Run store.Migrate on Pool before use.
type DB struct {
	URL    string        // connection URL from TEST_DATABASE_URL
	Schema string        // the private schema's name
	Pool   *pgxpool.Pool // bound to Schema through search_path
}

// New creates a fresh, empty schema and returns a pool bound to it. On test
// cleanup the pools are closed and the schema is dropped.
func New(t testing.TB) *DB {
	t.Helper()
	url := os.Getenv(EnvVar)
	if url == "" {
		t.Skipf("%s is not set; skipping test that needs PostgreSQL", EnvVar)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	var suffix [6]byte
	if _, err := rand.Read(suffix[:]); err != nil {
		t.Fatalf("testdb: random schema name: %v", err)
	}
	schema := "test_" + hex.EncodeToString(suffix[:])

	admin, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatalf("testdb: connect: %v", err)
	}
	defer admin.Close(ctx)
	if _, err := admin.Exec(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatalf("testdb: create schema: %v", err)
	}

	// Registered first, so it runs last: after every pool is closed.
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		conn, err := pgx.Connect(ctx, url)
		if err != nil {
			t.Errorf("testdb: connect for cleanup: %v", err)
			return
		}
		defer conn.Close(ctx)
		if _, err := conn.Exec(ctx, "DROP SCHEMA "+schema+" CASCADE"); err != nil {
			t.Errorf("testdb: drop schema %s: %v", schema, err)
		}
	})

	d := &DB{URL: url, Schema: schema}
	d.Pool = d.NewPool(t)
	return d
}

// NewPool opens another pool on the same schema, for example to stand in for
// a second server instance. It is closed on test cleanup.
func (d *DB) NewPool(t testing.TB) *pgxpool.Pool {
	t.Helper()
	cfg, err := pgxpool.ParseConfig(d.URL)
	if err != nil {
		t.Fatalf("testdb: parse %s: %v", EnvVar, err)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = d.Schema
	cfg.MaxConns = 25 // enough for the concurrency tests to really race
	pool, err := pgxpool.NewWithConfig(context.Background(), cfg)
	if err != nil {
		t.Fatalf("testdb: open pool: %v", err)
	}
	t.Cleanup(pool.Close)
	return pool
}
