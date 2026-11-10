package store_test

import (
	"crypto/rand"
	"errors"
	"fmt"
	"regexp"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/krishamb/goExchange/tictactoe/internal/game"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
	"github.com/krishamb/goExchange/tictactoe/internal/testdb"
)

func TestMigrateTwiceIsANoOp(t *testing.T) {
	s, db := newStore(t)
	ctx := t.Context()
	alice := createUser(t, s, "alice")
	before := appliedMigrations(t, db.Pool)
	if len(before) == 0 {
		t.Fatal("Migrate recorded no migrations")
	}

	if err := store.Migrate(ctx, db.Pool); err != nil {
		t.Fatalf("second Migrate: %v", err)
	}

	if after := appliedMigrations(t, db.Pool); !slices.Equal(after, before) {
		t.Errorf("applied migrations after the second Migrate = %q, want %q", after, before)
	}
	if got, err := s.GetUserByUsername(ctx, "alice"); err != nil || got.ID != alice.ID {
		t.Errorf("after the second Migrate, GetUserByUsername = %+v, %v; want %+v", got, err, alice)
	}
}

func TestMigrateConcurrently(t *testing.T) {
	db := testdb.New(t)
	ctx := t.Context()

	// Five instances starting at the same moment, each with its own pool.
	const instances = 5
	pools := make([]*pgxpool.Pool, instances)
	for i := range pools {
		pools[i] = db.NewPool(t)
		warmUp(t, pools[i], 1)
	}
	errs := make([]error, instances)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i, pool := range pools {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			errs[i] = store.Migrate(ctx, pool)
		}()
	}
	close(start)
	wg.Wait()

	for i, err := range errs {
		if err != nil {
			t.Errorf("instance %d: Migrate: %v", i, err)
		}
	}
	if len(appliedMigrations(t, db.Pool)) == 0 {
		t.Error("no migrations recorded")
	}
	createUser(t, store.New(db.Pool), "alice") // the schema is usable
}

func TestPing(t *testing.T) {
	s, _ := newStore(t)
	if err := s.Ping(t.Context()); err != nil {
		t.Errorf("Ping: %v", err)
	}
}

func TestUsers(t *testing.T) {
	s, _ := newStore(t)
	ctx := t.Context()

	alice, err := s.CreateUser(ctx, "alice", "alice's hash")
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}
	if !uuidPattern.MatchString(alice.ID) || alice.Username != "alice" ||
		alice.PasswordHash != "alice's hash" || alice.CreatedAt.IsZero() {
		t.Errorf("CreateUser = %+v", alice)
	}

	got, err := s.GetUserByUsername(ctx, "alice")
	if err != nil {
		t.Fatalf("GetUserByUsername: %v", err)
	}
	if got.ID != alice.ID || got.Username != alice.Username ||
		got.PasswordHash != alice.PasswordHash || !got.CreatedAt.Equal(alice.CreatedAt) {
		t.Errorf("GetUserByUsername = %+v, want %+v", got, alice)
	}

	if _, err := s.CreateUser(ctx, "alice", "another hash"); !errors.Is(err, store.ErrUsernameTaken) {
		t.Errorf("CreateUser(taken username) error = %v, want ErrUsernameTaken", err)
	}
	if _, err := s.GetUserByUsername(ctx, "bob"); !errors.Is(err, store.ErrNotFound) {
		t.Errorf("GetUserByUsername(missing) error = %v, want ErrNotFound", err)
	}
}

func TestCreateAndGetGame(t *testing.T) {
	s, _ := newStore(t)
	ctx := t.Context()
	x := createUser(t, s, "xavier")

	g, err := s.CreateGame(ctx, x.ID)
	if err != nil {
		t.Fatalf("CreateGame: %v", err)
	}
	want := game.Game{ID: g.ID, PlayerX: x.ID, Board: game.NewBoard(), Status: game.StatusWaiting, Version: 1}
	if !uuidPattern.MatchString(g.ID) || g.Game != want || g.PlayerXName != "xavier" || g.PlayerOName != "" ||
		g.CreatedAt.IsZero() || !g.UpdatedAt.Equal(g.CreatedAt) {
		t.Errorf("CreateGame = %+v", g)
	}

	got, err := s.GetGame(ctx, g.ID)
	if err != nil {
		t.Fatalf("GetGame: %v", err)
	}
	assertSameGame(t, got, g)

	// UUIDs are case-insensitive; IDs always come back lower-case.
	if got, err := s.GetGame(ctx, strings.ToUpper(g.ID)); err != nil || got.ID != g.ID {
		t.Errorf("GetGame(upper-case ID) = %+v, %v; want game %s", got, err, g.ID)
	}

	for _, id := range append([]string{randomUUID()}, malformedIDs...) {
		if _, err := s.GetGame(ctx, id); !errors.Is(err, store.ErrNotFound) {
			t.Errorf("GetGame(%q) error = %v, want ErrNotFound", id, err)
		}
	}
	for _, id := range []string{randomUUID(), "not-a-uuid"} {
		if _, err := s.CreateGame(ctx, id); !errors.Is(err, store.ErrUnknownPlayer) {
			t.Errorf("CreateGame(player %q) error = %v, want ErrUnknownPlayer", id, err)
		}
	}
}

func TestJoinGame(t *testing.T) {
	s, _ := newStore(t)
	ctx := t.Context()
	x, o, third := createUser(t, s, "xavier"), createUser(t, s, "olivia"), createUser(t, s, "trent")
	g := createGame(t, s, x)

	if _, err := s.JoinGame(ctx, g.ID, x.ID); !errors.Is(err, game.ErrOwnGame) {
		t.Errorf("X joining their own waiting game: error = %v, want ErrOwnGame", err)
	}

	joined, err := s.JoinGame(ctx, g.ID, o.ID)
	if err != nil {
		t.Fatalf("JoinGame: %v", err)
	}
	if joined.Status != game.StatusInProgress || joined.Version != 2 || joined.PlayerO != o.ID ||
		joined.PlayerOName != "olivia" || joined.PlayerXName != "xavier" || joined.Board != game.NewBoard() ||
		joined.UpdatedAt.Before(joined.CreatedAt) {
		t.Errorf("JoinGame = %+v", joined)
	}
	stored, err := s.GetGame(ctx, g.ID)
	if err != nil {
		t.Fatalf("GetGame: %v", err)
	}
	assertSameGame(t, stored, joined)

	if _, err := s.JoinGame(ctx, g.ID, third.ID); !errors.Is(err, game.ErrGameFull) {
		t.Errorf("third player joining: error = %v, want ErrGameFull", err)
	}
	if _, err := s.JoinGame(ctx, g.ID, x.ID); !errors.Is(err, game.ErrOwnGame) {
		t.Errorf("X joining their own started game: error = %v, want ErrOwnGame", err)
	}

	again, err := s.JoinGame(ctx, g.ID, o.ID)
	if err != nil {
		t.Fatalf("O joining again: %v", err)
	}
	assertSameGame(t, again, joined)

	open := createGame(t, s, x)
	for _, tc := range []struct {
		name, gameID, playerID string
		want                   error
	}{
		{"missing game", randomUUID(), third.ID, store.ErrNotFound},
		{"malformed game ID", "not-a-uuid", third.ID, store.ErrNotFound},
		{"malformed player ID", open.ID, "not-a-uuid", store.ErrUnknownPlayer},
		{"missing player", open.ID, randomUUID(), store.ErrUnknownPlayer},
	} {
		if _, err := s.JoinGame(ctx, tc.gameID, tc.playerID); !errors.Is(err, tc.want) {
			t.Errorf("%s: error = %v, want %v", tc.name, err, tc.want)
		}
	}
	if stillOpen, err := s.GetGame(ctx, open.ID); err != nil || stillOpen.Status != game.StatusWaiting {
		t.Errorf("after failed joins, GetGame = %+v, %v; want it still waiting", stillOpen, err)
	}
}

func TestJoinGameRace(t *testing.T) {
	s, db := newStore(t)
	ctx := t.Context()
	g := createGame(t, s, createUser(t, s, "host"))

	const racers = 10
	stores := twoInstances(t, db, racers)
	players := make([]store.User, racers)
	for i := range players {
		players[i] = createUser(t, s, fmt.Sprintf("player_%d", i))
	}

	errs := make([]error, racers)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := range racers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			_, errs[i] = stores[i%2].JoinGame(ctx, g.ID, players[i].ID)
		}()
	}
	close(start)
	wg.Wait()

	winner := -1
	for i, err := range errs {
		switch {
		case err == nil && winner >= 0:
			t.Errorf("players %d and %d both joined", winner, i)
		case err == nil:
			winner = i
		case !errors.Is(err, game.ErrGameFull):
			t.Errorf("player %d: error = %v, want ErrGameFull", i, err)
		}
	}
	if winner < 0 {
		t.Fatal("no player joined")
	}
	stored, err := s.GetGame(ctx, g.ID)
	if err != nil {
		t.Fatalf("GetGame: %v", err)
	}
	if stored.PlayerO != players[winner].ID || stored.Version != 2 || stored.Status != game.StatusInProgress {
		t.Errorf("stored game = %+v, want player %d (%s) as O at version 2", stored, winner, players[winner].ID)
	}
}

type cell struct{ row, col int }

func TestPlayMoveFullGames(t *testing.T) {
	tests := []struct {
		name       string
		cells      []cell // X plays the even indexes, O the odd ones
		wantStatus game.Status
		wantBoard  string
	}{
		{"x wins", []cell{{0, 0}, {1, 0}, {0, 1}, {1, 1}, {0, 2}}, game.StatusXWon, "XXXOO...."},
		{"o wins", []cell{{0, 0}, {1, 0}, {0, 1}, {1, 1}, {2, 2}, {1, 2}}, game.StatusOWon, "XX.OOO..X"},
		{"draw", []cell{{0, 0}, {0, 1}, {0, 2}, {1, 1}, {1, 0}, {1, 2}, {2, 1}, {2, 0}, {2, 2}}, game.StatusDraw, "XOXXOOOXX"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s, _ := newStore(t)
			x, o, g := startGame(t, s)

			var played []store.MoveView
			for i, c := range tc.cells {
				player, mark := x, game.X
				if i%2 == 1 {
					player, mark = o, game.O
				}
				var mv store.MoveView
				g, mv = play(t, s, g, player, c)

				wantStatus := game.StatusInProgress
				if i == len(tc.cells)-1 {
					wantStatus = tc.wantStatus
				}
				if g.Version != 3+i || g.Status != wantStatus {
					t.Errorf("after move %d: version %d, status %s; want %d, %s", i+1, g.Version, g.Status, 3+i, wantStatus)
				}
				want := game.Move{Number: i + 1, PlayerID: player.ID, Mark: mark, Row: c.row, Col: c.col}
				if mv.Move != want || mv.Username != player.Username || mv.CreatedAt.IsZero() {
					t.Errorf("move %d = %+v, want %+v by %s", i+1, mv, want, player.Username)
				}
				played = append(played, mv)
			}
			if g.Board.String() != tc.wantBoard {
				t.Errorf("board = %s, want %s", g.Board, tc.wantBoard)
			}

			stored, err := s.GetGame(t.Context(), g.ID)
			if err != nil {
				t.Fatalf("GetGame: %v", err)
			}
			assertSameGame(t, stored, g)

			listed, err := s.ListMoves(t.Context(), g.ID)
			if err != nil {
				t.Fatalf("ListMoves: %v", err)
			}
			if !slices.EqualFunc(listed, played, sameMove) {
				t.Errorf("ListMoves = %+v\nwant %+v", listed, played)
			}
		})
	}
}

func TestPlayMoveRuleErrors(t *testing.T) {
	tests := []struct {
		name    string
		waiting bool   // O has not joined
		before  []cell // played before the rejected move, X first
		player  string // "x", "o" or "outsider"
		at      cell
		version int // the version to expect; 0 sends none
		want    error
	}{
		{name: "row out of bounds", player: "x", at: cell{3, 0}, want: game.ErrOutOfBounds},
		{name: "column out of bounds", player: "x", at: cell{0, -1}, want: game.ErrOutOfBounds},
		{name: "not a player", player: "outsider", at: cell{0, 0}, want: game.ErrNotAPlayer},
		{name: "stale version", player: "x", at: cell{0, 0}, version: 1, want: game.ErrVersionMismatch},
		{name: "game not started", waiting: true, player: "x", at: cell{0, 0}, want: game.ErrGameNotStarted},
		{name: "not your turn", player: "o", at: cell{0, 0}, want: game.ErrNotYourTurn},
		{name: "cell occupied", before: []cell{{1, 1}}, player: "o", at: cell{1, 1}, want: game.ErrCellOccupied},
		{name: "game over", before: []cell{{0, 0}, {1, 0}, {0, 1}, {1, 1}, {0, 2}}, player: "o", at: cell{2, 2}, want: game.ErrGameOver},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			s, _ := newStore(t)
			ctx := t.Context()
			users := map[string]store.User{
				"x":        createUser(t, s, "xavier"),
				"o":        createUser(t, s, "olivia"),
				"outsider": createUser(t, s, "trent"),
			}
			g := createGame(t, s, users["x"])
			if !tc.waiting {
				g = joinGame(t, s, g, users["o"])
			}
			for i, c := range tc.before {
				player := users["x"]
				if i%2 == 1 {
					player = users["o"]
				}
				g, _ = play(t, s, g, player, c)
			}

			var version *int
			if tc.version != 0 {
				version = &tc.version
			}
			_, _, err := s.PlayMove(ctx, g.ID, users[tc.player].ID, tc.at.row, tc.at.col, version)
			if !errors.Is(err, tc.want) {
				t.Fatalf("PlayMove error = %v, want %v", err, tc.want)
			}

			after, err := s.GetGame(ctx, g.ID)
			if err != nil {
				t.Fatalf("GetGame: %v", err)
			}
			assertSameGame(t, after, g)
			moves, err := s.ListMoves(ctx, g.ID)
			if err != nil || len(moves) != len(tc.before) {
				t.Errorf("ListMoves = %d moves, %v; want %d", len(moves), err, len(tc.before))
			}
		})
	}
}

func TestPlayMoveMissingGame(t *testing.T) {
	s, _ := newStore(t)
	ctx := t.Context()
	x, _, g := startGame(t, s)

	for _, tc := range []struct {
		name, gameID, playerID string
		want                   error
	}{
		{"missing game", randomUUID(), x.ID, store.ErrNotFound},
		{"malformed game ID", "not-a-uuid", x.ID, store.ErrNotFound},
		{"malformed player ID", g.ID, "not-a-uuid", store.ErrUnknownPlayer},
		// Well-formed but no such user: just another stranger to this game.
		{"missing player", g.ID, randomUUID(), game.ErrNotAPlayer},
	} {
		if _, _, err := s.PlayMove(ctx, tc.gameID, tc.playerID, 0, 0, nil); !errors.Is(err, tc.want) {
			t.Errorf("%s: error = %v, want %v", tc.name, err, tc.want)
		}
	}
}

func TestPlayMoveRace(t *testing.T) {
	s, db := newStore(t)
	ctx := t.Context()
	x, _, g := startGame(t, s)

	const racers = 20
	stores := twoInstances(t, db, racers)

	// It is X's turn and every racer plays as X, so only one move can be
	// accepted. Racers i, i+9 and i+18 aim at the same cell.
	errs := make([]error, racers)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := range racers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			c := i % game.Cells
			_, _, errs[i] = stores[i%2].PlayMove(ctx, g.ID, x.ID, c/game.Size, c%game.Size, nil)
		}()
	}
	close(start)
	wg.Wait()

	winner := -1
	for i, err := range errs {
		switch {
		case err == nil && winner >= 0:
			t.Errorf("racers %d and %d both moved", winner, i)
		case err == nil:
			winner = i
		case !errors.Is(err, game.ErrNotYourTurn) && !errors.Is(err, game.ErrCellOccupied):
			t.Errorf("racer %d: error = %v, want ErrNotYourTurn or ErrCellOccupied", i, err)
		}
	}
	if winner < 0 {
		t.Fatal("no move was accepted")
	}

	if n := countMoves(t, db.Pool, g.ID); n != 1 {
		t.Errorf("moves table has %d rows for the game, want 1", n)
	}
	stored, err := s.GetGame(ctx, g.ID)
	if err != nil {
		t.Fatalf("GetGame: %v", err)
	}
	wantBoard := game.NewBoard()
	wantBoard[winner%game.Cells] = game.X
	if stored.Version != 3 || stored.Board != wantBoard {
		t.Errorf("stored game: version %d, board %s; want 3, %s", stored.Version, stored.Board, wantBoard)
	}
}

// If the move history and the board ever disagreed, the moves constraints
// would refuse the write, and PlayMove must report a conflict rather than a
// server error, leaving the game as it was.
func TestPlayMoveConstraintBackstop(t *testing.T) {
	s, db := newStore(t)
	x, _, g := startGame(t, s)
	mustExec(t, db.Pool, insertMove, g.ID, 1, x.ID, "X", 2, 2) // behind the store's back: the board still looks empty

	if _, _, err := s.PlayMove(t.Context(), g.ID, x.ID, 0, 0, nil); !errors.Is(err, store.ErrConflict) {
		t.Fatalf("PlayMove error = %v, want ErrConflict", err)
	}
	after, err := s.GetGame(t.Context(), g.ID)
	if err != nil {
		t.Fatalf("GetGame: %v", err)
	}
	assertSameGame(t, after, g)
	if n := countMoves(t, db.Pool, g.ID); n != 1 {
		t.Errorf("moves table has %d rows for the game, want 1", n)
	}
}

// The schema's constraints are the backstop behind the rules: these writes
// bypass the store and must be refused by Postgres itself.
func TestConstraints(t *testing.T) {
	s, db := newStore(t)
	x, o, g := startGame(t, s)
	mustExec(t, db.Pool, insertMove, g.ID, 1, x.ID, "X", 0, 0)

	tests := []struct {
		name       string
		sql        string
		args       []any
		code       string
		constraint string
	}{
		{"two marks in one cell", insertMove, []any{g.ID, 2, o.ID, "O", 0, 0}, "23505", "moves_one_mark_per_cell"},
		{"two moves for one turn", insertMove, []any{g.ID, 1, x.ID, "X", 1, 1}, "23505", "moves_pkey"},
		{"X on an even move", insertMove, []any{g.ID, 2, x.ID, "X", 1, 1}, "23514", "moves_symbol_matches_turn"},
		{"invalid board", "UPDATE games SET board = 'XO?' WHERE id = $1", []any{g.ID}, "23514", "games_board_check"},
		{"waiting game with an opponent", "UPDATE games SET status = 'waiting' WHERE id = $1", []any{g.ID}, "23514", "games_waiting_iff_no_opponent"},
		{"playing against yourself", "UPDATE games SET player_o_id = player_x_id WHERE id = $1", []any{g.ID}, "23514", "games_players_differ"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := db.Pool.Exec(t.Context(), tc.sql, tc.args...)
			var pgErr *pgconn.PgError
			if !errors.As(err, &pgErr) {
				t.Fatalf("error = %v, want SQLSTATE %s on %s", err, tc.code, tc.constraint)
			}
			if pgErr.Code != tc.code || pgErr.ConstraintName != tc.constraint {
				t.Errorf("error = SQLSTATE %s on %q (%s), want %s on %q",
					pgErr.Code, pgErr.ConstraintName, pgErr.Message, tc.code, tc.constraint)
			}
		})
	}
}

func TestListMoves(t *testing.T) {
	s, _ := newStore(t)
	ctx := t.Context()
	_, _, g := startGame(t, s)

	moves, err := s.ListMoves(ctx, g.ID)
	if err != nil || moves == nil || len(moves) != 0 {
		t.Errorf("ListMoves(new game) = %#v, %v; want an empty, non-nil slice", moves, err)
	}
	for _, id := range []string{randomUUID(), "not-a-uuid"} {
		if _, err := s.ListMoves(ctx, id); !errors.Is(err, store.ErrNotFound) {
			t.Errorf("ListMoves(%q) error = %v, want ErrNotFound", id, err)
		}
	}
}

func TestCorruptRowsAreErrors(t *testing.T) {
	s, db := newStore(t)
	ctx := t.Context()
	x, _, g := startGame(t, s)

	// The CHECK constraints keep such rows out, so drop them in this test's
	// private schema to see that the store refuses a corrupt row rather than
	// handing it to the rules.
	mustExec(t, db.Pool, "ALTER TABLE games DROP CONSTRAINT games_board_check, DROP CONSTRAINT games_status_check")
	for _, corruption := range []string{"board = 'XO'", "board = 'XO?......'", "status = 'paused'"} {
		mustExec(t, db.Pool, "UPDATE games SET "+corruption+" WHERE id = $1", g.ID)

		if _, err := s.GetGame(ctx, g.ID); err == nil || errors.Is(err, store.ErrNotFound) {
			t.Errorf("%s: GetGame error = %v, want a corrupt-row error", corruption, err)
		}
		if _, _, err := s.PlayMove(ctx, g.ID, x.ID, 0, 0, nil); err == nil || errors.Is(err, store.ErrNotFound) {
			t.Errorf("%s: PlayMove error = %v, want a corrupt-row error", corruption, err)
		}

		mustExec(t, db.Pool, "UPDATE games SET board = '.........', status = 'in_progress' WHERE id = $1", g.ID)
	}

	play(t, s, g, x, cell{0, 0})
	mustExec(t, db.Pool, "ALTER TABLE moves DROP CONSTRAINT moves_symbol_check, DROP CONSTRAINT moves_symbol_matches_turn")
	mustExec(t, db.Pool, "UPDATE moves SET symbol = '?' WHERE game_id = $1", g.ID)
	if _, err := s.ListMoves(ctx, g.ID); err == nil || errors.Is(err, store.ErrNotFound) {
		t.Errorf("corrupt move symbol: ListMoves error = %v, want a corrupt-row error", err)
	}
}

// A database failure must surface as an error of its own, never as one of
// the sentinels that callers turn into "not found" or "conflict" responses.
func TestDatabaseFailuresAreNotSentinels(t *testing.T) {
	db := testdb.New(t)
	pool := db.NewPool(t)
	pool.Close()
	s := store.New(pool)
	ctx := t.Context()
	id := randomUUID()

	for _, tc := range []struct {
		name string
		call func() error
	}{
		{"Migrate", func() error { return store.Migrate(ctx, pool) }},
		{"Ping", func() error { return s.Ping(ctx) }},
		{"CreateUser", func() error { _, err := s.CreateUser(ctx, "alice", "hash"); return err }},
		{"GetUserByUsername", func() error { _, err := s.GetUserByUsername(ctx, "alice"); return err }},
		{"CreateGame", func() error { _, err := s.CreateGame(ctx, id); return err }},
		{"GetGame", func() error { _, err := s.GetGame(ctx, id); return err }},
		{"JoinGame", func() error { _, err := s.JoinGame(ctx, id, id); return err }},
		{"PlayMove", func() error { _, _, err := s.PlayMove(ctx, id, id, 0, 0, nil); return err }},
		{"ListMoves", func() error { _, err := s.ListMoves(ctx, id); return err }},
	} {
		err := tc.call()
		if err == nil || !strings.HasPrefix(err.Error(), "store: ") {
			t.Errorf("%s on a closed pool: error = %v, want one starting %q", tc.name, err, "store: ")
		}
		for _, sentinel := range []error{store.ErrNotFound, store.ErrUsernameTaken, store.ErrConflict} {
			if errors.Is(err, sentinel) {
				t.Errorf("%s on a closed pool: error %q matches %q", tc.name, err, sentinel)
			}
		}
	}
}

const insertMove = `INSERT INTO moves (game_id, move_number, player_id, symbol, row, col) VALUES ($1, $2, $3, $4, $5, $6)`

// newStore returns a Store on a fresh, migrated schema of its own.
func newStore(t *testing.T) (*store.Store, *testdb.DB) {
	t.Helper()
	db := testdb.New(t)
	if err := store.Migrate(t.Context(), db.Pool); err != nil {
		t.Fatalf("Migrate: %v", err)
	}
	return store.New(db.Pool), db
}

// twoInstances returns two Stores on db with separate pools, as two server
// instances would have, each with enough connections open for its share of
// racers, so that the racers meet at the database rather than while dialing.
func twoInstances(t *testing.T, db *testdb.DB, racers int) []*store.Store {
	t.Helper()
	second := db.NewPool(t)
	warmUp(t, db.Pool, racers/2)
	warmUp(t, second, racers/2)
	return []*store.Store{store.New(db.Pool), store.New(second)}
}

// warmUp opens n connections in pool and returns them to it idle.
func warmUp(t *testing.T, pool *pgxpool.Pool, n int) {
	t.Helper()
	conns := make([]*pgxpool.Conn, n)
	for i := range conns {
		c, err := pool.Acquire(t.Context())
		if err != nil {
			t.Fatalf("acquire connection: %v", err)
		}
		conns[i] = c
	}
	for _, c := range conns {
		c.Release()
	}
}

func createUser(t *testing.T, s *store.Store, username string) store.User {
	t.Helper()
	u, err := s.CreateUser(t.Context(), username, "hash of "+username)
	if err != nil {
		t.Fatalf("CreateUser(%q): %v", username, err)
	}
	return u
}

func createGame(t *testing.T, s *store.Store, x store.User) store.GameView {
	t.Helper()
	g, err := s.CreateGame(t.Context(), x.ID)
	if err != nil {
		t.Fatalf("CreateGame: %v", err)
	}
	return g
}

func joinGame(t *testing.T, s *store.Store, g store.GameView, o store.User) store.GameView {
	t.Helper()
	g, err := s.JoinGame(t.Context(), g.ID, o.ID)
	if err != nil {
		t.Fatalf("JoinGame: %v", err)
	}
	return g
}

// startGame creates two players, xavier and olivia, and seats them in a new game.
func startGame(t *testing.T, s *store.Store) (x, o store.User, g store.GameView) {
	t.Helper()
	x, o = createUser(t, s, "xavier"), createUser(t, s, "olivia")
	return x, o, joinGame(t, s, createGame(t, s, x), o)
}

// play makes a move that must succeed, expecting the version g is at.
func play(t *testing.T, s *store.Store, g store.GameView, player store.User, at cell) (store.GameView, store.MoveView) {
	t.Helper()
	version := g.Version
	g, mv, err := s.PlayMove(t.Context(), g.ID, player.ID, at.row, at.col, &version)
	if err != nil {
		t.Fatalf("PlayMove(%s at %v): %v", player.Username, at, err)
	}
	return g, mv
}

func assertSameGame(t *testing.T, got, want store.GameView) {
	t.Helper()
	if got.Game != want.Game || got.PlayerXName != want.PlayerXName || got.PlayerOName != want.PlayerOName ||
		!got.CreatedAt.Equal(want.CreatedAt) || !got.UpdatedAt.Equal(want.UpdatedAt) {
		t.Errorf("game = %+v\nwant   %+v", got, want)
	}
}

func sameMove(a, b store.MoveView) bool {
	return a.Move == b.Move && a.Username == b.Username && a.CreatedAt.Equal(b.CreatedAt)
}

func appliedMigrations(t *testing.T, pool *pgxpool.Pool) []string {
	t.Helper()
	rows, err := pool.Query(t.Context(),
		"SELECT version || ' at ' || applied_at FROM schema_migrations ORDER BY version")
	if err != nil {
		t.Fatalf("list applied migrations: %v", err)
	}
	applied, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		t.Fatalf("list applied migrations: %v", err)
	}
	return applied
}

func countMoves(t *testing.T, pool *pgxpool.Pool, gameID string) int {
	t.Helper()
	var n int
	if err := pool.QueryRow(t.Context(), "SELECT count(*) FROM moves WHERE game_id = $1", gameID).Scan(&n); err != nil {
		t.Fatalf("count moves: %v", err)
	}
	return n
}

func mustExec(t *testing.T, pool *pgxpool.Pool, sql string, args ...any) {
	t.Helper()
	if _, err := pool.Exec(t.Context(), sql, args...); err != nil {
		t.Fatalf("%s: %v", sql, err)
	}
}

// uuidPattern matches the canonical text form Postgres gives UUIDs.
var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// malformedIDs are rejected before they reach Postgres, including forms
// Postgres itself would accept.
var malformedIDs = []string{
	"",
	"not-a-uuid",
	"123e4567-e89b-12d3-a456-42661417400g",   // not hexadecimal
	"123e4567e-89b-12d3-a456-426614174000",   // hyphen out of place
	"123e4567e89b12d3a456426614174000",       // no hyphens
	"{123e4567-e89b-12d3-a456-426614174000}", // braces
}

// randomUUID returns a well-formed version 4 UUID that no row has.
func randomUUID() string {
	var b [16]byte
	rand.Read(b[:])
	b[6] = b[6]&0x0f | 0x40 // version 4
	b[8] = b[8]&0x3f | 0x80 // RFC 9562 variant
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}
