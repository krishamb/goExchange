package api_test

import (
	"net/http"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/krishamb/goExchange/tictactoe/internal/api"
	"github.com/krishamb/goExchange/tictactoe/internal/auth"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
)

// turn is one move in a scripted game and what the game looks like after it.
type turn struct {
	p        player
	row, col int
	board    string // as rendered by board
	next     string // next_turn afterwards: "X", "O" or "null"
}

// playTurns plays the turns in order, checking each response, and returns
// the game after the last one. The game must be in progress at version 2.
func playTurns(t *testing.T, c *client, id string, turns []turn) gameView {
	t.Helper()
	var g gameView
	for i, tc := range turns {
		played := c.move(t, tc.p, id, tc.row, tc.col)
		m, symbol := played.Move, []string{"X", "O"}[i%2]
		if m.MoveNumber != i+1 || m.Symbol != symbol || m.Row != tc.row || m.Col != tc.col ||
			m.Player != (userView{ID: tc.p.id, Username: tc.p.name}) || m.CreatedAt.IsZero() {
			t.Errorf("move %d = %+v, want %s at (%d,%d) by %s", i+1, m, symbol, tc.row, tc.col, tc.p.name)
		}
		g = played.Game
		if got := board(t, g); got != tc.board {
			t.Errorf("after move %d: board %s, want %s", i+1, got, tc.board)
		}
		if got := orNull(g.NextTurn); got != tc.next {
			t.Errorf("after move %d: next_turn %s, want %s", i+1, got, tc.next)
		}
		if g.Version != 3+i {
			t.Errorf("after move %d: version %d, want %d", i+1, g.Version, 3+i)
		}
	}
	return g
}

func TestFullGame(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice, bob := c.signUp(t, "alice"), c.signUp(t, "bob")

	// Alice creates a game and waits for an opponent.
	res := c.do(t, http.MethodPost, "/v1/games", alice.token, nil)
	g := decode[gameView](t, res, http.StatusCreated)
	if got, want := res.header.Get("Location"), "/v1/games/"+g.ID; got != want {
		t.Errorf("Location %q, want %q", got, want)
	}
	if g.Status != "waiting" || g.Version != 1 || board(t, g) != ".../.../..." {
		t.Errorf("new game: status %s, version %d, board %s; want waiting, 1, empty", g.Status, g.Version, board(t, g))
	}
	wantNull(t, res.body, "players.O", "next_turn", "winner")
	wantUser(t, "players.X", g.Players.X, alice)
	if g.CreatedAt.IsZero() || !g.UpdatedAt.Equal(g.CreatedAt) {
		t.Errorf("new game: created_at %v, updated_at %v; want equal and set", g.CreatedAt, g.UpdatedAt)
	}

	// Bob joins as O, and X moves first.
	g = c.join(t, bob, g.ID)
	if g.Status != "in_progress" || g.Version != 2 || orNull(g.NextTurn) != "X" || g.Winner != nil {
		t.Errorf("joined game: status %s, version %d, next_turn %s, winner %s; want in_progress, 2, X, null",
			g.Status, g.Version, orNull(g.NextTurn), orNull(g.Winner))
	}
	wantUser(t, "players.O", g.Players.O, bob)
	wantUser(t, "players.X", g.Players.X, alice)

	// They alternate until X completes the top row.
	turns := []turn{
		{alice, 0, 0, "X../.../...", "O"},
		{bob, 1, 0, "X../O../...", "X"},
		{alice, 0, 1, "XX./O../...", "O"},
		{bob, 1, 1, "XX./OO./...", "X"},
		{alice, 0, 2, "XXX/OO./...", "null"},
	}
	g = playTurns(t, c, g.ID, turns)
	if g.Status != "x_won" || orNull(g.Winner) != "X" || g.NextTurn != nil || g.Version != 7 {
		t.Errorf("final game: status %s, winner %s, next_turn %s, version %d; want x_won, X, null, 7",
			g.Status, orNull(g.Winner), orNull(g.NextTurn), g.Version)
	}

	// The game is over.
	wantError(t, c.do(t, http.MethodPost, "/v1/games/"+g.ID+"/moves", bob.token, moveAt(2, 2)),
		http.StatusConflict, "GAME_NOT_IN_PROGRESS")

	// The history lists the moves in order, with who made them.
	moves := c.moves(t, bob, g.ID)
	if len(moves) != len(turns) {
		t.Fatalf("got %d moves, want %d: %+v", len(moves), len(turns), moves)
	}
	for i, m := range moves {
		tc := turns[i]
		want := moveView{
			MoveNumber: i + 1,
			Symbol:     []string{"X", "O"}[i%2],
			Row:        tc.row,
			Col:        tc.col,
			Player:     userView{ID: tc.p.id, Username: tc.p.name},
			CreatedAt:  m.CreatedAt,
		}
		if m != want || m.CreatedAt.IsZero() {
			t.Errorf("moves[%d] = %+v, want %+v", i, m, want)
		}
	}

	// Reading the game back gives exactly what the last move returned.
	if got := c.game(t, alice, g.ID); !reflect.DeepEqual(got, g) {
		t.Errorf("GET game = %+v\nwant (from the last move) %+v", got, g)
	}
}

func TestDraw(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice, bob := c.signUp(t, "alice"), c.signUp(t, "bob")
	id := c.createGame(t, alice).ID
	c.join(t, bob, id)

	g := playTurns(t, c, id, []turn{
		{alice, 0, 0, "X../.../...", "O"},
		{bob, 0, 1, "XO./.../...", "X"},
		{alice, 0, 2, "XOX/.../...", "O"},
		{bob, 1, 1, "XOX/.O./...", "X"},
		{alice, 1, 0, "XOX/XO./...", "O"},
		{bob, 1, 2, "XOX/XOO/...", "X"},
		{alice, 2, 1, "XOX/XOO/.X.", "O"},
		{bob, 2, 0, "XOX/XOO/OX.", "X"},
		{alice, 2, 2, "XOX/XOO/OXX", "null"},
	})
	if g.Status != "draw" || g.Winner != nil || g.NextTurn != nil || g.Version != 11 {
		t.Errorf("final game: status %s, winner %s, next_turn %s, version %d; want draw, null, null, 11",
			g.Status, orNull(g.Winner), orNull(g.NextTurn), g.Version)
	}
	res := c.do(t, http.MethodGet, "/v1/games/"+id, bob.token, nil)
	decode[gameView](t, res, http.StatusOK)
	wantNull(t, res.body, "winner", "next_turn")
}

func TestMoveErrors(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice, bob, carol := c.signUp(t, "alice"), c.signUp(t, "bob"), c.signUp(t, "carol")
	id := c.createGame(t, alice).ID
	path := "/v1/games/" + id + "/moves"

	wantError(t, c.do(t, http.MethodPost, path, alice.token, moveAt(0, 0)),
		http.StatusConflict, "GAME_NOT_IN_PROGRESS") // nobody has joined yet
	c.join(t, bob, id)

	tests := []struct {
		name   string
		p      player
		body   any
		status int
		code   string
	}{
		{"stranger", carol, moveAt(0, 0), http.StatusForbidden, "NOT_A_PLAYER"},
		{"O moves first", bob, moveAt(0, 0), http.StatusConflict, "NOT_YOUR_TURN"},
		{"row 3", alice, moveAt(3, 0), http.StatusBadRequest, "OUT_OF_BOUNDS"},
		{"negative col", alice, moveAt(0, -1), http.StatusBadRequest, "OUT_OF_BOUNDS"},
		{"no col", alice, map[string]int{"row": 0}, http.StatusBadRequest, "INVALID_REQUEST"},
		{"no row", alice, map[string]int{"col": 0}, http.StatusBadRequest, "INVALID_REQUEST"},
		{"null row", alice, `{"row":null,"col":0}`, http.StatusBadRequest, "INVALID_REQUEST"},
		{"empty object", alice, `{}`, http.StatusBadRequest, "INVALID_REQUEST"},
		{"empty body", alice, nil, http.StatusBadRequest, "INVALID_JSON"},
		{"row as a string", alice, `{"row":"0","col":0}`, http.StatusBadRequest, "INVALID_JSON"},
		{"fractional row", alice, `{"row":0.5,"col":0}`, http.StatusBadRequest, "INVALID_JSON"},
		{"player in the body", alice, `{"row":0,"col":0,"player_id":"` + bob.id + `"}`, http.StatusBadRequest, "INVALID_JSON"},
		{"malformed JSON", alice, `{"row":0,"col":`, http.StatusBadRequest, "INVALID_JSON"},
		{"two objects", alice, `{"row":0,"col":0}{"row":1,"col":1}`, http.StatusBadRequest, "INVALID_JSON"},
		{"stale expected_version", alice, map[string]int{"row": 0, "col": 0, "expected_version": 1}, http.StatusConflict, "VERSION_MISMATCH"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			wantError(t, c.do(t, http.MethodPost, path, tc.p.token, tc.body), tc.status, tc.code)
		})
	}

	// None of that changed the game, so the current version is accepted.
	res := c.do(t, http.MethodPost, path, alice.token, map[string]int{"row": 0, "col": 0, "expected_version": 2})
	if g := decode[playedView](t, res, http.StatusCreated).Game; g.Version != 3 {
		t.Errorf("version after the first move %d, want 3", g.Version)
	}
	wantError(t, c.do(t, http.MethodPost, path, bob.token, moveAt(0, 0)), http.StatusConflict, "CELL_OCCUPIED")

	// Anyone logged in may watch, but only the players move.
	if g := c.game(t, carol, id); g.Version != 3 || board(t, g) != "X../.../..." {
		t.Errorf("game seen by carol: version %d, board %s; want 3, X../.../...", g.Version, board(t, g))
	}
	if moves := c.moves(t, carol, id); len(moves) != 1 {
		t.Errorf("carol sees %d moves, want 1", len(moves))
	}
}

func TestJoin(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice, bob, carol := c.signUp(t, "alice"), c.signUp(t, "bob"), c.signUp(t, "carol")
	id := c.createGame(t, alice).ID
	path := "/v1/games/" + id + "/join"

	wantError(t, c.do(t, http.MethodPost, path, alice.token, nil), http.StatusConflict, "CANNOT_JOIN_OWN_GAME")

	// A new game has no moves yet: an empty list, not null.
	res := c.do(t, http.MethodGet, "/v1/games/"+id+"/moves", carol.token, nil)
	if body := strings.TrimSpace(string(res.body)); res.status != http.StatusOK || body != `{"moves":[]}` {
		t.Errorf("moves of a new game: %d %s, want 200 {\"moves\":[]}", res.status, body)
	}

	joined := c.join(t, bob, id)
	// Joining again is a harmless retry.
	if again := c.join(t, bob, id); !reflect.DeepEqual(again, joined) {
		t.Errorf("second join = %+v, want unchanged %+v", again, joined)
	}
	wantError(t, c.do(t, http.MethodPost, path, carol.token, nil), http.StatusConflict, "GAME_FULL")
	wantError(t, c.do(t, http.MethodPost, path, alice.token, nil), http.StatusConflict, "CANNOT_JOIN_OWN_GAME")
}

func TestUnknownGame(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice := c.signUp(t, "alice")

	for _, id := range []string{"6f1c1c35-8e8e-4b8e-9a6e-3c9b7e7a5d10", "not-a-uuid"} {
		for _, r := range []struct {
			method, path string
			body         any
		}{
			{http.MethodGet, "/v1/games/" + id, nil},
			{http.MethodPost, "/v1/games/" + id + "/join", nil},
			{http.MethodPost, "/v1/games/" + id + "/moves", moveAt(0, 0)},
			{http.MethodGet, "/v1/games/" + id + "/moves", nil},
		} {
			msg := wantError(t, c.do(t, r.method, r.path, alice.token, r.body), http.StatusNotFound, "NOT_FOUND")
			if msg != "game not found" {
				t.Errorf("%s %s: message %q, want %q", r.method, r.path, msg, "game not found")
			}
		}
	}
}

func TestUnroutedRequestsGetJSON(t *testing.T) {
	t.Parallel()
	c := newServer(t)

	wantError(t, c.do(t, http.MethodGet, "/", "", nil), http.StatusNotFound, "NOT_FOUND")
	wantError(t, c.do(t, http.MethodGet, "/v1/players", "", nil), http.StatusNotFound, "NOT_FOUND")
	wantError(t, c.do(t, http.MethodPost, "/v1/games/", "", nil), http.StatusNotFound, "NOT_FOUND")

	for _, tc := range []struct{ method, path, allow string }{
		{http.MethodDelete, "/v1/games/42", "GET, HEAD"},
		{http.MethodPut, "/v1/games/42/moves", "POST, GET, HEAD"},
		{http.MethodGet, "/v1/auth/login", "POST"},
		{http.MethodPost, "/healthz", "GET, HEAD"},
	} {
		res := c.do(t, tc.method, tc.path, "", nil)
		wantError(t, res, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED")
		if got := res.header.Get("Allow"); got != tc.allow {
			t.Errorf("%s %s: Allow %q, want %q", tc.method, tc.path, got, tc.allow)
		}
	}
}

func TestHealthz(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	if h := decode[healthView](t, c.do(t, http.MethodGet, "/healthz", "", nil), http.StatusOK); h.Status != "ok" {
		t.Errorf("status %q, want ok", h.Status)
	}
}

// TestDatabaseDown checks what clients see when the database is unreachable:
// an unhealthy health check, and a generic 500 that leaves the details to
// the server log.
func TestDatabaseDown(t *testing.T) {
	t.Parallel()
	db := newDB(t)
	alice := startServer(t, db.Pool).signUp(t, "alice")

	pool := db.NewPool(t)
	c := startServer(t, pool)
	pool.Close()

	res := c.do(t, http.MethodGet, "/healthz", "", nil)
	if h := decode[healthView](t, res, http.StatusServiceUnavailable); h.Status != "unavailable" {
		t.Errorf("health status %q, want unavailable", h.Status)
	}

	res = c.do(t, http.MethodPost, "/v1/games", alice.token, nil)
	if msg := wantError(t, res, http.StatusInternalServerError, "INTERNAL"); msg != "internal server error" {
		t.Errorf("500 message %q, want the generic one", msg)
	}
	if logs := c.logs.String(); !strings.Contains(logs, `level=ERROR msg="request failed"`) {
		t.Errorf("the failure was not logged:\n%s", logs)
	}
}

func TestNewValidatesConfig(t *testing.T) {
	t.Parallel()
	tokens, err := auth.NewTokens([]byte(testSecret), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	st := new(store.Store) // never used: New must reject the config first

	for _, tc := range []struct {
		name string
		cfg  api.Config
	}{
		{"no store", api.Config{Tokens: tokens}},
		{"no tokens", api.Config{Store: st}},
		{"bcrypt cost below the minimum", api.Config{Store: st, Tokens: tokens, BcryptCost: 3}},
		{"bcrypt cost above the maximum", api.Config{Store: st, Tokens: tokens, BcryptCost: 32}},
		{"negative bcrypt cost", api.Config{Store: st, Tokens: tokens, BcryptCost: -1}},
	} {
		if h, err := api.New(tc.cfg); err == nil || h != nil {
			t.Errorf("%s: New = %v, %v; want an error", tc.name, h, err)
		}
	}

	// A zero cost means bcrypt's default, and a nil logger slog's default.
	if _, err := api.New(api.Config{Store: st, Tokens: tokens}); err != nil {
		t.Errorf("New with defaults: %v", err)
	}
}
