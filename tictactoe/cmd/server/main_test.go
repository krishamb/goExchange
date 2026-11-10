package main

import (
	"strings"
	"testing"
	"time"
)

func TestLoadConfig(t *testing.T) {
	const (
		url    = "postgres://localhost/tictactoe"
		secret = "0123456789abcdef0123456789abcdef" // exactly the minimum length
	)
	env := func(vars map[string]string) func(string) string {
		return func(key string) string { return vars[key] }
	}

	cfg, err := loadConfig(env(map[string]string{"DATABASE_URL": url, "JWT_SECRET": secret}))
	if err != nil {
		t.Fatalf("defaults: %v", err)
	}
	if cfg.databaseURL != url || string(cfg.jwtSecret) != secret || cfg.addr != ":8080" || cfg.tokenTTL != 24*time.Hour {
		t.Errorf("defaults: got %+v", cfg)
	}

	cfg, err = loadConfig(env(map[string]string{
		"DATABASE_URL": url, "JWT_SECRET": secret, "PORT": "9000", "TOKEN_TTL": "90m",
	}))
	if err != nil {
		t.Fatalf("overrides: %v", err)
	}
	if cfg.addr != ":9000" || cfg.tokenTTL != 90*time.Minute {
		t.Errorf("overrides: addr %q, ttl %v; want :9000, 1h30m", cfg.addr, cfg.tokenTTL)
	}

	for _, tc := range []struct {
		name string
		vars map[string]string
		want []string // substrings of the error
	}{
		{"nothing set", map[string]string{}, []string{"DATABASE_URL is required", "JWT_SECRET is required"}},
		{"short secret", map[string]string{"DATABASE_URL": url, "JWT_SECRET": secret[1:]}, []string{"at least 32 bytes"}},
		{"port not a number", map[string]string{"DATABASE_URL": url, "JWT_SECRET": secret, "PORT": "http"}, []string{"PORT"}},
		{"port out of range", map[string]string{"DATABASE_URL": url, "JWT_SECRET": secret, "PORT": "65536"}, []string{"PORT"}},
		{"ttl not a duration", map[string]string{"DATABASE_URL": url, "JWT_SECRET": secret, "TOKEN_TTL": "1 day"}, []string{"TOKEN_TTL"}},
		{"ttl not positive", map[string]string{"DATABASE_URL": url, "JWT_SECRET": secret, "TOKEN_TTL": "-1h"}, []string{"TOKEN_TTL"}},
	} {
		_, err := loadConfig(env(tc.vars))
		if err == nil {
			t.Errorf("%s: no error", tc.name)
			continue
		}
		for _, want := range tc.want {
			if !strings.Contains(err.Error(), want) {
				t.Errorf("%s: error %q does not mention %q", tc.name, err, want)
			}
		}
	}
}
