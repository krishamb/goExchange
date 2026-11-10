# Development helpers. Override any variable on the command line,
# e.g. `make run PORT=9090`.

DATABASE_URL      ?= postgres://tictactoe:tictactoe@localhost:5432/tictactoe?sslmode=disable
TEST_DATABASE_URL ?= $(DATABASE_URL)
# Development-only secret. Use a long random value anywhere real.
JWT_SECRET        ?= dev-only-secret-change-me-0123456789abcdef
PORT              ?= 8080

.PHONY: db run test vet

# Start PostgreSQL in Docker and wait until it accepts connections.
db:
	docker compose up -d --wait db

# Run the API server (applies database migrations on startup).
run:
	DATABASE_URL='$(DATABASE_URL)' JWT_SECRET='$(JWT_SECRET)' PORT='$(PORT)' go run ./cmd/server

# Run every test with the race detector. Database tests use their own
# throwaway schemas, so they never touch the server's data.
test:
	TEST_DATABASE_URL='$(TEST_DATABASE_URL)' go test -race -count=1 ./...

vet:
	go vet ./...
