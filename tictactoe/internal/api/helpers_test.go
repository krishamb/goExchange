package api_test

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"

	"github.com/krishamb/goExchange/tictactoe/internal/api"
	"github.com/krishamb/goExchange/tictactoe/internal/auth"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
	"github.com/krishamb/goExchange/tictactoe/internal/testdb"
)

// testSecret signs every test server's tokens so that, like production
// instances sharing JWT_SECRET, each server accepts the others' tokens.
const testSecret = "test-only-hmac-secret-0123456789abcdef"

const password = "correct horse battery staple"

// newDB returns a migrated, empty database private to the test.
func newDB(t *testing.T) *testdb.DB {
	t.Helper()
	db := testdb.New(t)
	if err := store.Migrate(t.Context(), db.Pool); err != nil {
		t.Fatalf("store.Migrate: %v", err)
	}
	return db
}

// newServer starts an API server on a fresh database.
func newServer(t *testing.T) *client {
	t.Helper()
	return startServer(t, newDB(t).Pool)
}

// startServer starts an API instance on pool. It gets its own store, token
// verifier and HTTP server, so it shares nothing with other instances except
// what is in the database.
func startServer(t *testing.T, pool *pgxpool.Pool) *client {
	t.Helper()
	tokens, err := auth.NewTokens([]byte(testSecret), time.Hour)
	if err != nil {
		t.Fatalf("auth.NewTokens: %v", err)
	}
	logs := new(syncBuffer)
	h, err := api.New(api.Config{
		Store:      store.New(pool),
		Tokens:     tokens,
		BcryptCost: bcrypt.MinCost,
		Logger:     slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug})),
	})
	if err != nil {
		t.Fatalf("api.New: %v", err)
	}
	// Registered before srv.Close, so it runs after it, when no request can
	// still be writing to the log.
	t.Cleanup(func() {
		if t.Failed() {
			t.Logf("server log:\n%s", logs)
		}
	})
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)

	hc := srv.Client()
	hc.Timeout = 30 * time.Second
	return &client{url: srv.URL, http: hc, logs: logs}
}

// syncBuffer is a bytes.Buffer that server goroutines can log to while the
// test reads it.
type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// client talks to one test server.
type client struct {
	url  string
	http *http.Client
	logs *syncBuffer // the server's log
}

// response is a received response with its body read.
type response struct {
	status int
	header http.Header
	body   []byte
}

// send makes a request without failing the test, so any goroutine may call
// it. authorization is the verbatim Authorization header, "" for none. body
// is nil for no body, a string to send verbatim, or a value to send as JSON.
func (c *client) send(method, path, authorization string, body any) (response, error) {
	var rd io.Reader
	switch b := body.(type) {
	case nil:
	case string:
		rd = strings.NewReader(b)
	default:
		data, err := json.Marshal(b)
		if err != nil {
			return response{}, err
		}
		rd = bytes.NewReader(data)
	}
	req, err := http.NewRequest(method, c.url+path, rd)
	if err != nil {
		return response{}, err
	}
	if authorization != "" {
		req.Header.Set("Authorization", authorization)
	}
	if rd != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := c.http.Do(req)
	if err != nil {
		return response{}, err
	}
	defer res.Body.Close()
	data, err := io.ReadAll(res.Body)
	if err != nil {
		return response{}, err
	}
	return response{status: res.StatusCode, header: res.Header, body: data}, nil
}

// do sends a request authenticated with token ("" for none).
func (c *client) do(t testing.TB, method, path, token string, body any) response {
	t.Helper()
	res, err := c.send(method, path, bearer(token), body)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	return res
}

func bearer(token string) string {
	if token == "" {
		return ""
	}
	return "Bearer " + token
}

// Request bodies.

func credentials(username, password string) map[string]string {
	return map[string]string{"username": username, "password": password}
}

func moveAt(row, col int) map[string]int {
	return map[string]int{"row": row, "col": col}
}

// Response bodies, mirroring the API's JSON. decode rejects fields these
// don't have, so a response growing an undocumented field fails the tests.

type userView struct {
	ID       string `json:"id"`
	Username string `json:"username"`
}

type loginView struct {
	Token     string    `json:"token"`
	TokenType string    `json:"token_type"`
	ExpiresAt time.Time `json:"expires_at"`
	User      userView  `json:"user"`
}

type gameView struct {
	ID      string     `json:"id"`
	Status  string     `json:"status"`
	Board   [][]string `json:"board"`
	Players struct {
		X *userView `json:"X"`
		O *userView `json:"O"`
	} `json:"players"`
	NextTurn  *string   `json:"next_turn"`
	Winner    *string   `json:"winner"`
	Version   int       `json:"version"`
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}

type moveView struct {
	MoveNumber int       `json:"move_number"`
	Symbol     string    `json:"symbol"`
	Row        int       `json:"row"`
	Col        int       `json:"col"`
	Player     userView  `json:"player"`
	CreatedAt  time.Time `json:"created_at"`
}

type playedView struct {
	Move moveView `json:"move"`
	Game gameView `json:"game"`
}

type movesView struct {
	Moves []moveView `json:"moves"`
}

type healthView struct {
	Status string `json:"status"`
}

type errorView struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

// decode checks that res has the given status and a JSON body, and decodes
// the body into a T.
func decode[T any](t testing.TB, res response, status int) T {
	t.Helper()
	if res.status != status {
		t.Fatalf("status %d, want %d; body: %s", res.status, status, res.body)
	}
	if ct := res.header.Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type %q, want application/json", ct)
	}
	var v T
	dec := json.NewDecoder(bytes.NewReader(res.body))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&v); err != nil {
		t.Fatalf("decode %T: %v; body: %s", v, err, res.body)
	}
	return v
}

// wantError checks that res is an error with the given status and code, and
// returns its message.
func wantError(t testing.TB, res response, status int, code string) string {
	t.Helper()
	e := decode[errorView](t, res, status)
	if e.Error.Code != code {
		t.Errorf("error code %q, want %q (message %q)", e.Error.Code, code, e.Error.Message)
	}
	if e.Error.Message == "" {
		t.Errorf("error %s has no message", e.Error.Code)
	}
	return e.Error.Message
}

// errorCode returns the code of an error response of any status.
func errorCode(t testing.TB, res response) string {
	t.Helper()
	return decode[errorView](t, res, res.status).Error.Code
}

// wantNull checks that each dotted path, such as "players.O", is present in
// the JSON body with the value null. Decoding into a pointer can't tell null
// from absent, but the API promises null.
func wantNull(t testing.TB, body []byte, paths ...string) {
	t.Helper()
	var doc any
	if err := json.Unmarshal(body, &doc); err != nil {
		t.Fatalf("unmarshal: %v; body: %s", err, body)
	}
paths:
	for _, path := range paths {
		v := doc
		for _, key := range strings.Split(path, ".") {
			obj, ok := v.(map[string]any)
			if !ok {
				t.Errorf("%s: not inside an object; body: %s", path, body)
				continue paths
			}
			if v, ok = obj[key]; !ok {
				t.Errorf("%s is missing, want null; body: %s", path, body)
				continue paths
			}
		}
		if v != nil {
			t.Errorf("%s = %v, want null", path, v)
		}
	}
}

// player is a registered, logged-in user.
type player struct {
	id, name, token string
}

func (c *client) register(t testing.TB, username string) userView {
	t.Helper()
	res := c.do(t, http.MethodPost, "/v1/auth/register", "", credentials(username, password))
	return decode[userView](t, res, http.StatusCreated)
}

func (c *client) login(t testing.TB, username string) player {
	t.Helper()
	res := c.do(t, http.MethodPost, "/v1/auth/login", "", credentials(username, password))
	l := decode[loginView](t, res, http.StatusOK)
	return player{id: l.User.ID, name: l.User.Username, token: l.Token}
}

// signUp registers username and logs in.
func (c *client) signUp(t testing.TB, username string) player {
	t.Helper()
	c.register(t, username)
	return c.login(t, username)
}

func (c *client) createGame(t testing.TB, p player) gameView {
	t.Helper()
	return decode[gameView](t, c.do(t, http.MethodPost, "/v1/games", p.token, nil), http.StatusCreated)
}

func (c *client) game(t testing.TB, p player, id string) gameView {
	t.Helper()
	return decode[gameView](t, c.do(t, http.MethodGet, "/v1/games/"+id, p.token, nil), http.StatusOK)
}

func (c *client) join(t testing.TB, p player, id string) gameView {
	t.Helper()
	return decode[gameView](t, c.do(t, http.MethodPost, "/v1/games/"+id+"/join", p.token, nil), http.StatusOK)
}

func (c *client) move(t testing.TB, p player, id string, row, col int) playedView {
	t.Helper()
	res := c.do(t, http.MethodPost, "/v1/games/"+id+"/moves", p.token, moveAt(row, col))
	return decode[playedView](t, res, http.StatusCreated)
}

func (c *client) moves(t testing.TB, p player, id string) []moveView {
	t.Helper()
	return decode[movesView](t, c.do(t, http.MethodGet, "/v1/games/"+id+"/moves", p.token, nil), http.StatusOK).Moves
}

// board renders g's board as rows such as "XO./.X./..O", after checking that
// it is 3x3 and every cell is "X", "O" or "".
func board(t testing.TB, g gameView) string {
	t.Helper()
	if len(g.Board) != 3 {
		t.Fatalf("board has %d rows, want 3: %v", len(g.Board), g.Board)
	}
	rows := make([]string, 0, 3)
	for _, row := range g.Board {
		if len(row) != 3 {
			t.Fatalf("board row has %d cells, want 3: %v", len(row), g.Board)
		}
		var sb strings.Builder
		for _, cell := range row {
			switch cell {
			case "X", "O":
				sb.WriteString(cell)
			case "":
				sb.WriteByte('.')
			default:
				t.Fatalf(`board cell %q, want "X", "O" or ""`, cell)
			}
		}
		rows = append(rows, sb.String())
	}
	return strings.Join(rows, "/")
}

// orNull formats a nullable mark for messages and comparisons.
func orNull(s *string) string {
	if s == nil {
		return "null"
	}
	return *s
}

// wantUser checks that a player slot holds p.
func wantUser(t testing.TB, slot string, got *userView, p player) {
	t.Helper()
	if got == nil || got.ID != p.id || got.Username != p.name {
		t.Errorf("%s = %+v, want {ID:%s Username:%s}", slot, got, p.id, p.name)
	}
}

// concurrently sends n requests at once and returns their responses in
// order. Every goroutine is started and waiting on a barrier before any is
// released, so the requests really race.
func concurrently(t *testing.T, n int, send func(i int) (response, error)) []response {
	t.Helper()
	var ready, done sync.WaitGroup
	ready.Add(n)
	done.Add(n)
	start := make(chan struct{})
	responses := make([]response, n)
	errs := make([]error, n)
	for i := range n {
		go func() {
			defer done.Done()
			ready.Done()
			<-start
			responses[i], errs[i] = send(i)
		}()
	}
	ready.Wait()
	close(start)
	done.Wait()
	for i, err := range errs {
		if err != nil {
			t.Fatalf("request %d: %v", i, err)
		}
	}
	return responses
}
