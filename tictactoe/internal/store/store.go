// Package store persists users, games and moves in PostgreSQL.
//
// The database is the only source of truth. Every write runs in a
// transaction, and every concurrency guarantee comes from Postgres (row
// locks, conditional updates, constraints) rather than from in-process
// locks, so any number of stateless server instances can share it.
package store

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"path"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
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
	return &Store{pool: pool}
}

//go:embed migrations/*.sql
var migrations embed.FS

// migrateLockKey names the advisory lock that serializes Migrate across
// instances. The value is arbitrary ("tictacto" in ASCII), but every
// instance must use the same one, so it must never change.
const migrateLockKey int64 = 0x746963746163746f

// readCommitted is Postgres's default isolation level, requested explicitly
// because the transactions that wait on a lock depend on it: each statement
// sees everything committed before it started, so a migration that waited
// for another instance sees that instance's work, and a move that waited for
// another move's row lock reads the board as that move left it. Under
// REPEATABLE READ both would fail instead.
var readCommitted = pgx.TxOptions{IsoLevel: pgx.ReadCommitted}

// Migrate applies the embedded SQL migrations that have not been applied
// yet. It is idempotent and safe to call from many instances at once.
func Migrate(ctx context.Context, pool *pgxpool.Pool) error {
	files, err := fs.Glob(migrations, "migrations/*.sql")
	if err != nil {
		return fmt.Errorf("store: migrate: %w", err)
	}
	slices.Sort(files) // each migration builds on the ones before it

	tx, err := pool.BeginTx(ctx, readCommitted)
	if err != nil {
		return fmt.Errorf("store: migrate: %w", err)
	}
	defer tx.Rollback(ctx) // a no-op once committed

	// Instances that start together queue here instead of racing to create
	// the same tables. The lock is released when the transaction ends.
	if _, err := tx.Exec(ctx, "SELECT pg_advisory_xact_lock($1)", migrateLockKey); err != nil {
		return fmt.Errorf("store: migrate: lock: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		CREATE TABLE IF NOT EXISTS schema_migrations (
			version    TEXT        PRIMARY KEY,
			applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
		)`); err != nil {
		return fmt.Errorf("store: migrate: %w", err)
	}
	rows, err := tx.Query(ctx, "SELECT version FROM schema_migrations")
	if err != nil {
		return fmt.Errorf("store: migrate: %w", err)
	}
	applied, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("store: migrate: %w", err)
	}

	for _, file := range files {
		version := path.Base(file)
		if slices.Contains(applied, version) {
			continue
		}
		sql, err := migrations.ReadFile(file)
		if err != nil {
			return fmt.Errorf("store: migrate %s: %w", version, err)
		}
		// Without arguments pgx uses the simple query protocol, which
		// accepts a whole file of statements at once.
		if _, err := tx.Exec(ctx, string(sql)); err != nil {
			return fmt.Errorf("store: migrate %s: %w", version, err)
		}
		if _, err := tx.Exec(ctx, "INSERT INTO schema_migrations (version) VALUES ($1)", version); err != nil {
			return fmt.Errorf("store: migrate %s: %w", version, err)
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("store: migrate: commit: %w", err)
	}
	return nil
}

// Ping checks that the database is reachable.
func (s *Store) Ping(ctx context.Context) error {
	if err := s.pool.Ping(ctx); err != nil {
		return fmt.Errorf("store: ping: %w", err)
	}
	return nil
}

// CreateUser stores a new user. username must already be normalized
// (lower-case). Returns ErrUsernameTaken if it exists.
func (s *Store) CreateUser(ctx context.Context, username, passwordHash string) (User, error) {
	u := User{Username: username, PasswordHash: passwordHash}
	err := s.pool.QueryRow(ctx, `
		INSERT INTO users (username, password_hash) VALUES ($1, $2)
		RETURNING id::text, created_at`,
		username, passwordHash,
	).Scan(&u.ID, &u.CreatedAt)
	switch {
	case pgErrorCode(err) == uniqueViolation:
		// The ID is generated, so the username is the only unique value
		// that can collide.
		return User{}, ErrUsernameTaken
	case err != nil:
		return User{}, fmt.Errorf("store: create user: %w", err)
	}
	return u, nil
}

// GetUserByUsername returns ErrNotFound if there is no such user.
func (s *Store) GetUserByUsername(ctx context.Context, username string) (User, error) {
	var u User
	err := s.pool.QueryRow(ctx, `
		SELECT id::text, username, password_hash, created_at
		FROM users
		WHERE username = $1`,
		username,
	).Scan(&u.ID, &u.Username, &u.PasswordHash, &u.CreatedAt)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return User{}, ErrNotFound
	case err != nil:
		return User{}, fmt.Errorf("store: get user: %w", err)
	}
	return u, nil
}

// CreateGame creates a waiting game with playerXID as X.
func (s *Store) CreateGame(ctx context.Context, playerXID string) (GameView, error) {
	playerX, ok := canonicalUUID(playerXID)
	if !ok {
		return GameView{}, ErrNotFound
	}
	v, err := scanGameView(s.pool.QueryRow(ctx, `
		WITH g AS (
			INSERT INTO games (player_x_id) VALUES ($1)
			RETURNING *
		)`+gameViewQuery,
		playerX,
	))
	switch {
	case pgErrorCode(err) == foreignKeyViolation:
		return GameView{}, ErrNotFound // there is no such player
	case err != nil:
		return GameView{}, fmt.Errorf("store: create game: %w", err)
	}
	return v, nil
}

// GetGame returns ErrNotFound if there is no such game.
func (s *Store) GetGame(ctx context.Context, gameID string) (GameView, error) {
	id, ok := canonicalUUID(gameID)
	if !ok {
		return GameView{}, ErrNotFound
	}
	v, err := s.getGame(ctx, id)
	if err != nil && !errors.Is(err, ErrNotFound) {
		return GameView{}, fmt.Errorf("store: get game: %w", err)
	}
	return v, err
}

// JoinGame seats playerID as O with one conditional UPDATE, so when several
// players race for the seat exactly one gets it. Errors: ErrNotFound,
// game.ErrOwnGame, game.ErrGameFull. Joining again as the current O succeeds
// without changes.
func (s *Store) JoinGame(ctx context.Context, gameID, playerID string) (GameView, error) {
	id, okGame := canonicalUUID(gameID)
	player, okPlayer := canonicalUUID(playerID)
	if !okGame || !okPlayer {
		return GameView{}, ErrNotFound
	}

	// Under READ COMMITTED (Postgres's default) a racing UPDATE waits for the
	// winner's row lock and then re-checks its WHERE clause against the row
	// the winner left, which no longer matches.
	v, err := scanGameView(s.pool.QueryRow(ctx, `
		WITH g AS (
			UPDATE games
			SET player_o_id = $2, status = 'in_progress', version = version + 1, updated_at = now()
			WHERE id = $1 AND status = 'waiting' AND player_o_id IS NULL AND player_x_id <> $2
			RETURNING *
		)`+gameViewQuery,
		id, player,
	))
	switch {
	case err == nil:
		return v, nil
	case pgErrorCode(err) == foreignKeyViolation:
		return GameView{}, ErrNotFound // there is no such player
	case !errors.Is(err, pgx.ErrNoRows):
		return GameView{}, fmt.Errorf("store: join game: %w", err)
	}

	// Nothing matched: the game is missing, or seat O is not open to this
	// player. A taken seat never reopens, so the current row tells the rules
	// which it is.
	v, err = s.getGame(ctx, id)
	switch {
	case errors.Is(err, ErrNotFound):
		return GameView{}, ErrNotFound
	case err != nil:
		return GameView{}, fmt.Errorf("store: join game: %w", err)
	}
	g := v.Game // Join seats the player on its receiver; v must stay as stored
	if err := g.Join(player); err != nil {
		return GameView{}, err // game.ErrOwnGame or game.ErrGameFull
	}
	if v.PlayerO != player {
		// Unreachable: Join found the seat open, but then the UPDATE above
		// would have taken it. Reporting success would claim a seat the
		// player does not hold.
		return GameView{}, fmt.Errorf("store: join game %s: seat O is open but was not taken", id)
	}
	return v, nil // the player already holds seat O, so a retried join changes nothing
}

// PlayMove applies a move in one transaction that holds the game's row lock,
// so concurrent moves on the same game are serialized. Rule violations are
// returned as the game.Err* values from game.Game.Play; a missing game is
// ErrNotFound.
func (s *Store) PlayMove(ctx context.Context, gameID, playerID string, row, col int, expectedVersion *int) (GameView, MoveView, error) {
	id, okGame := canonicalUUID(gameID)
	player, okPlayer := canonicalUUID(playerID)
	if !okGame || !okPlayer {
		return GameView{}, MoveView{}, ErrNotFound
	}

	tx, err := s.pool.BeginTx(ctx, readCommitted)
	if err != nil {
		return GameView{}, MoveView{}, fmt.Errorf("store: play move: %w", err)
	}
	defer tx.Rollback(ctx) // a no-op once committed

	g, err := lockGame(ctx, tx, id)
	switch {
	case errors.Is(err, ErrNotFound):
		return GameView{}, MoveView{}, ErrNotFound
	case err != nil:
		return GameView{}, MoveView{}, fmt.Errorf("store: play move: %w", err)
	}

	m, err := g.Play(player, row, col, expectedVersion)
	if err != nil {
		return GameView{}, MoveView{}, err // a rule violation, for the caller to report
	}

	mv := MoveView{Move: m}
	err = tx.QueryRow(ctx, `
		INSERT INTO moves (game_id, move_number, player_id, symbol, row, col)
		VALUES ($1, $2, $3, $4, $5, $6)
		RETURNING created_at`,
		id, m.Number, m.PlayerID, m.Mark.String(), m.Row, m.Col,
	).Scan(&mv.CreatedAt)
	if code := pgErrorCode(err); code == uniqueViolation || code == checkViolation {
		// The constraints refused a second move for this turn or this cell,
		// or the wrong symbol for the turn. The row lock should make that
		// impossible; if it happens anyway, the client should reload the
		// game rather than see a server error.
		return GameView{}, MoveView{}, ErrConflict
	}
	if err != nil {
		return GameView{}, MoveView{}, fmt.Errorf("store: play move: record move: %w", err)
	}

	v, err := scanGameView(tx.QueryRow(ctx, `
		WITH g AS (
			UPDATE games
			SET board = $2, status = $3, version = $4, updated_at = now()
			WHERE id = $1
			RETURNING *
		)`+gameViewQuery,
		id, g.Board.String(), string(g.Status), g.Version,
	))
	if err != nil {
		return GameView{}, MoveView{}, fmt.Errorf("store: play move: update game: %w", err)
	}
	mv.Username = v.PlayerXName
	if m.Mark == game.O {
		mv.Username = v.PlayerOName
	}

	if err := tx.Commit(ctx); err != nil {
		return GameView{}, MoveView{}, fmt.Errorf("store: play move: commit: %w", err)
	}
	return v, mv, nil
}

// ListMoves returns the game's moves in order (an empty, non-nil slice if
// there are none). Returns ErrNotFound if there is no such game.
func (s *Store) ListMoves(ctx context.Context, gameID string) ([]MoveView, error) {
	id, ok := canonicalUUID(gameID)
	if !ok {
		return nil, ErrNotFound
	}
	rows, err := s.pool.Query(ctx, `
		SELECT m.move_number, m.player_id::text, m.symbol, m.row, m.col, u.username, m.created_at
		FROM moves m
		JOIN users u ON u.id = m.player_id
		WHERE m.game_id = $1
		ORDER BY m.move_number`,
		id,
	)
	if err != nil {
		return nil, fmt.Errorf("store: list moves: %w", err)
	}
	moves, err := pgx.CollectRows(rows, scanMoveView)
	if err != nil {
		return nil, fmt.Errorf("store: list moves: %w", err)
	}
	if len(moves) > 0 {
		return moves, nil
	}

	// Moves reference their game, so only an empty result leaves open
	// whether the game exists.
	var exists bool
	err = s.pool.QueryRow(ctx, "SELECT EXISTS (SELECT 1 FROM games WHERE id = $1)", id).Scan(&exists)
	if err != nil {
		return nil, fmt.Errorf("store: list moves: %w", err)
	}
	if !exists {
		return nil, ErrNotFound
	}
	return []MoveView{}, nil
}

// gameViewQuery selects the columns scanGameView reads from g, the games rows
// named by a WITH clause written in front of it. With a SELECT there it
// serves reads; with INSERT … or UPDATE … RETURNING * a write returns the
// GameView it produced in the same statement. Either way the joins and the
// column order live in one place.
const gameViewQuery = `
	SELECT g.id::text, g.player_x_id::text, COALESCE(g.player_o_id::text, ''),
	       g.board, g.status, g.version,
	       x.username, COALESCE(o.username, ''),
	       g.created_at, g.updated_at
	FROM g
	JOIN users x ON x.id = g.player_x_id
	LEFT JOIN users o ON o.id = g.player_o_id`

// getGame reads the game with the canonical UUID id, returning ErrNotFound
// if there is none.
func (s *Store) getGame(ctx context.Context, id string) (GameView, error) {
	v, err := scanGameView(s.pool.QueryRow(ctx,
		"WITH g AS (SELECT * FROM games WHERE id = $1)"+gameViewQuery, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return GameView{}, ErrNotFound
	}
	return v, err
}

// scanGameView reads the one row of a gameViewQuery.
func scanGameView(row pgx.Row) (GameView, error) {
	var (
		v             GameView
		board, status string
	)
	err := row.Scan(&v.ID, &v.PlayerX, &v.PlayerO, &board, &status, &v.Version,
		&v.PlayerXName, &v.PlayerOName, &v.CreatedAt, &v.UpdatedAt)
	if err != nil {
		return GameView{}, err
	}
	if err := decodeState(&v.Game, board, status); err != nil {
		return GameView{}, err
	}
	return v, nil
}

// lockGame reads the rules state of the game with the canonical UUID id and
// locks its row until tx ends, returning ErrNotFound if there is no such
// game. It locks only the games row: FOR UPDATE on a query joined with users
// would lock the players' rows too, stalling every other game they create,
// join or move in meanwhile, since those writes' foreign-key checks
// share-lock the user's row.
func lockGame(ctx context.Context, tx pgx.Tx, id string) (game.Game, error) {
	g := game.Game{ID: id}
	var board, status string
	err := tx.QueryRow(ctx, `
		SELECT player_x_id::text, COALESCE(player_o_id::text, ''), board, status, version
		FROM games
		WHERE id = $1
		FOR UPDATE`,
		id,
	).Scan(&g.PlayerX, &g.PlayerO, &board, &status, &g.Version)
	if errors.Is(err, pgx.ErrNoRows) {
		return game.Game{}, ErrNotFound
	}
	if err != nil {
		return game.Game{}, err
	}
	if err := decodeState(&g, board, status); err != nil {
		return game.Game{}, err
	}
	return g, nil
}

// decodeState parses a games row's board and status columns into g. The
// table's CHECK constraints should keep this from failing; checking anyway
// stops a corrupt row from reaching the rules looking like a valid game.
func decodeState(g *game.Game, board, status string) error {
	b, err := game.ParseBoard(board)
	if err != nil {
		return fmt.Errorf("game %s: corrupt board: %w", g.ID, err)
	}
	st := game.Status(status)
	if !st.Valid() {
		return fmt.Errorf("game %s: unknown status %q", g.ID, status)
	}
	g.Board, g.Status = b, st
	return nil
}

// scanMoveView reads one row of the ListMoves query.
func scanMoveView(row pgx.CollectableRow) (MoveView, error) {
	var (
		mv     MoveView
		symbol string
	)
	err := row.Scan(&mv.Number, &mv.PlayerID, &symbol, &mv.Row, &mv.Col, &mv.Username, &mv.CreatedAt)
	if err != nil {
		return MoveView{}, err
	}
	switch symbol {
	case "X":
		mv.Mark = game.X
	case "O":
		mv.Mark = game.O
	default:
		return MoveView{}, fmt.Errorf("move %d: unknown symbol %q", mv.Number, symbol)
	}
	return mv, nil
}

// SQLSTATE codes of the constraint violations the store translates.
const (
	foreignKeyViolation = "23503"
	uniqueViolation     = "23505"
	checkViolation      = "23514"
)

// pgErrorCode returns err's SQLSTATE if it came from Postgres, or "".
func pgErrorCode(err error) string {
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) {
		return pgErr.Code
	}
	return ""
}

// canonicalUUID reports whether s is a UUID in the usual 8-4-4-4-12
// hexadecimal form and returns it lower-cased, the form IDs read back as
// text take, so that player IDs can be compared as strings. Checking here
// means Postgres never sees a malformed ID, which it would answer with an
// error rather than with no rows.
func canonicalUUID(s string) (string, bool) {
	if len(s) != 36 {
		return "", false
	}
	for i := range len(s) {
		switch c := s[i]; i {
		case 8, 13, 18, 23:
			if c != '-' {
				return "", false
			}
		default:
			if !isHexDigit(c) {
				return "", false
			}
		}
	}
	return strings.ToLower(s), true
}

func isHexDigit(c byte) bool {
	return '0' <= c && c <= '9' || 'a' <= c && c <= 'f' || 'A' <= c && c <= 'F'
}
