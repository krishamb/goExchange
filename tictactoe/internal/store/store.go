// Package store persists users, games and moves in PostgreSQL.
//
// The database is the only source of truth. Every write runs in a
// transaction, and every concurrency guarantee comes from Postgres (row
// locks, conditional updates, constraints) rather than from in-process
// locks, so any number of stateless server instances can share it.
package store

import (
	"context"
	"errors"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/krishamb/goExchange/tictactoe/internal/game"
)

var (
	// ErrNotFound means the requested row does not exist. A malformed ID is
	// reported as ErrNotFound too.
	ErrNotFound = errors.New("not found")
	// ErrUsernameTaken means another user already has that username.
	ErrUsernameTaken = errors.New("username is already taken")
	// ErrConflict means a database constraint rejected a write that the rule
	// checks let through. It should be unreachable while the row lock is
	// held; it exists so the constraint backstop surfaces as a clean error.
	ErrConflict = errors.New("the game was changed by another request; reload it and retry")
)

// User is a registered player.
type User struct {
	ID           string
	Username     string
	PasswordHash string
	CreatedAt    time.Time
}

// GameView is a game together with its players' usernames and timestamps.
type GameView struct {
	game.Game
	PlayerXName string
	PlayerOName string // "" while waiting
	CreatedAt   time.Time
	UpdatedAt   time.Time
}

// MoveView is a recorded move together with its player's username.
type MoveView struct {
	game.Move
	Username  string
	CreatedAt time.Time
}

// Store is the PostgreSQL repository. It is safe for concurrent use.
type Store struct {
	pool *pgxpool.Pool
}

// New returns a Store backed by pool.
func New(pool *pgxpool.Pool) *Store {
	panic("not implemented") // TODO(store agent)
}

// Migrate applies the embedded SQL migrations that have not been applied
// yet. It is idempotent and safe to call from many instances at once.
func Migrate(ctx context.Context, pool *pgxpool.Pool) error {
	panic("not implemented") // TODO(store agent)
}

// Ping checks that the database is reachable.
func (s *Store) Ping(ctx context.Context) error {
	panic("not implemented") // TODO(store agent)
}

// CreateUser stores a new user. username must already be normalized
// (lower-case). Returns ErrUsernameTaken if it exists.
func (s *Store) CreateUser(ctx context.Context, username, passwordHash string) (User, error) {
	panic("not implemented") // TODO(store agent)
}

// GetUserByUsername returns ErrNotFound if there is no such user.
func (s *Store) GetUserByUsername(ctx context.Context, username string) (User, error) {
	panic("not implemented") // TODO(store agent)
}

// CreateGame creates a waiting game with playerXID as X.
func (s *Store) CreateGame(ctx context.Context, playerXID string) (GameView, error) {
	panic("not implemented") // TODO(store agent)
}

// GetGame returns ErrNotFound if there is no such game.
func (s *Store) GetGame(ctx context.Context, gameID string) (GameView, error) {
	panic("not implemented") // TODO(store agent)
}

// JoinGame seats playerID as O with one conditional UPDATE, so when several
// players race for the seat exactly one gets it. Errors: ErrNotFound,
// game.ErrOwnGame, game.ErrGameFull. Joining again as the current O succeeds
// without changes.
func (s *Store) JoinGame(ctx context.Context, gameID, playerID string) (GameView, error) {
	panic("not implemented") // TODO(store agent)
}

// PlayMove applies a move in one transaction that holds the game's row lock,
// so concurrent moves on the same game are serialized. Rule violations are
// returned as the game.Err* values from game.Game.Play; a missing game is
// ErrNotFound.
func (s *Store) PlayMove(ctx context.Context, gameID, playerID string, row, col int, expectedVersion *int) (GameView, MoveView, error) {
	panic("not implemented") // TODO(store agent)
}

// ListMoves returns the game's moves in order (an empty, non-nil slice if
// there are none). Returns ErrNotFound if there is no such game.
func (s *Store) ListMoves(ctx context.Context, gameID string) ([]MoveView, error) {
	panic("not implemented") // TODO(store agent)
}
