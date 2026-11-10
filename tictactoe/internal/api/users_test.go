package api_test

import (
	"encoding/base64"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/krishamb/goExchange/tictactoe/internal/auth"
)

func TestRegister(t *testing.T) {
	t.Parallel()
	c := newServer(t)

	alice := c.register(t, "alice")
	if alice.ID == "" || alice.Username != "alice" {
		t.Errorf("register alice = %+v", alice)
	}
	// Usernames are trimmed and lower-cased before they are checked or stored.
	res := c.do(t, http.MethodPost, "/v1/auth/register", "", credentials("  Bob_99\t", password))
	if u := decode[userView](t, res, http.StatusCreated); u.Username != "bob_99" {
		t.Errorf("registered username %q, want bob_99", u.Username)
	}
	for _, name := range []string{"abc", strings.Repeat("z", 32)} {
		c.register(t, name) // the shortest and longest names allowed
	}

	tests := []struct {
		name   string
		body   any
		status int
		code   string
	}{
		{"taken", credentials("alice", password), http.StatusConflict, "USERNAME_TAKEN"},
		{"taken in another case", credentials("Alice", password), http.StatusConflict, "USERNAME_TAKEN"},
		{"taken with spaces", credentials(" ALICE ", password), http.StatusConflict, "USERNAME_TAKEN"},
		{"username too short", credentials("ab", password), http.StatusBadRequest, "INVALID_USERNAME"},
		{"username too long", credentials(strings.Repeat("a", 33), password), http.StatusBadRequest, "INVALID_USERNAME"},
		{"space in username", credentials("al ice", password), http.StatusBadRequest, "INVALID_USERNAME"},
		{"hyphen in username", credentials("al-ice", password), http.StatusBadRequest, "INVALID_USERNAME"},
		{"non-ASCII username", credentials("zoë", password), http.StatusBadRequest, "INVALID_USERNAME"},
		{"no username", map[string]string{"password": password}, http.StatusBadRequest, "INVALID_USERNAME"},
		{"password too short", credentials("carol", "1234567"), http.StatusBadRequest, "INVALID_PASSWORD"},
		{"password too long", credentials("carol", strings.Repeat("p", 73)), http.StatusBadRequest, "INVALID_PASSWORD"},
		{"no password", map[string]string{"username": "carol"}, http.StatusBadRequest, "INVALID_PASSWORD"},
		{"malformed JSON", `{"username":"carol",`, http.StatusBadRequest, "INVALID_JSON"},
		{"syntax error", `{"username":"carol" "password":"x"}`, http.StatusBadRequest, "INVALID_JSON"},
		{"unknown field", `{"username":"carol","password":"long enough","admin":true}`, http.StatusBadRequest, "INVALID_JSON"},
		{"trailing data", `{"username":"carol","password":"long enough"} {}`, http.StatusBadRequest, "INVALID_JSON"},
		{"trailing garbage", `{"username":"carol","password":"long enough"}]`, http.StatusBadRequest, "INVALID_JSON"},
		{"wrong type", `{"username":42,"password":"long enough"}`, http.StatusBadRequest, "INVALID_JSON"},
		{"not an object", `["carol","long enough"]`, http.StatusBadRequest, "INVALID_JSON"},
		{"empty body", nil, http.StatusBadRequest, "INVALID_JSON"},
		{
			"body over 64 KiB",
			`{"username":"carol","password":"` + strings.Repeat("p", 64<<10) + `"}`,
			http.StatusRequestEntityTooLarge, "BODY_TOO_LARGE",
		},
		{
			"over 64 KiB only with trailing whitespace",
			`{"username":"carol","password":"long enough"}` + strings.Repeat(" ", 64<<10),
			http.StatusRequestEntityTooLarge, "BODY_TOO_LARGE",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			wantError(t, c.do(t, http.MethodPost, "/v1/auth/register", "", tc.body), tc.status, tc.code)
		})
	}

	// None of the failures created carol.
	res = c.do(t, http.MethodPost, "/v1/auth/login", "", credentials("carol", "long enough"))
	wantError(t, res, http.StatusUnauthorized, "INVALID_CREDENTIALS")
}

func TestLogin(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice := c.register(t, "alice")

	// Login normalizes the username the same way registration does.
	res := c.do(t, http.MethodPost, "/v1/auth/login", "", credentials(" ALICE ", password))
	l := decode[loginView](t, res, http.StatusOK)
	if l.Token == "" || l.TokenType != "Bearer" || l.User != alice {
		t.Errorf("login = %+v, want a Bearer token for %+v", l, alice)
	}
	// The test servers issue tokens valid for an hour.
	if left := time.Until(l.ExpiresAt); left < 59*time.Minute || left > time.Hour {
		t.Errorf("expires_at %v is %v away, want about an hour", l.ExpiresAt, left)
	}
	// The token works.
	c.createGame(t, player{id: l.User.ID, name: l.User.Username, token: l.Token})

	// A wrong password and an unknown user are indistinguishable.
	wrong := wantError(t,
		c.do(t, http.MethodPost, "/v1/auth/login", "", credentials("alice", "not the password")),
		http.StatusUnauthorized, "INVALID_CREDENTIALS")
	unknown := wantError(t,
		c.do(t, http.MethodPost, "/v1/auth/login", "", credentials("mallory", password)),
		http.StatusUnauthorized, "INVALID_CREDENTIALS")
	if wrong != unknown {
		t.Errorf("wrong-password message %q differs from unknown-user message %q", wrong, unknown)
	}

	wantError(t, c.do(t, http.MethodPost, "/v1/auth/login", "", `{"username":"alice"`),
		http.StatusBadRequest, "INVALID_JSON")
	wantError(t, c.do(t, http.MethodPost, "/v1/auth/login", "", `{"username":"alice","password":"x","totp":1}`),
		http.StatusBadRequest, "INVALID_JSON")
}

func TestGameRoutesRequireBearerToken(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice := c.signUp(t, "alice")
	id := c.createGame(t, alice).ID

	otherSecret, err := auth.NewTokens([]byte("some-other-deployments-secret-0123456789"), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	forged, _, err := otherSecret.Issue(alice.id, alice.name)
	if err != nil {
		t.Fatal(err)
	}
	instant, err := auth.NewTokens([]byte(testSecret), time.Nanosecond)
	if err != nil {
		t.Fatal(err)
	}
	expired, _, err := instant.Issue(alice.id, alice.name)
	if err != nil {
		t.Fatal(err)
	}

	authorizations := []struct{ name, header string }{
		{"no header", ""},
		{"garbage token", "Bearer not-a-token"},
		{"empty token", "Bearer "},
		{"token signed with another secret", "Bearer " + forged},
		{"expired token", "Bearer " + expired},
		{"token without a scheme", alice.token},
		{"basic scheme", "Basic " + base64.StdEncoding.EncodeToString([]byte("alice:"+password))},
		{"other scheme with a valid token", "Token " + alice.token},
	}
	routes := []struct {
		method, path string
		body         any
	}{
		{http.MethodPost, "/v1/games", nil},
		{http.MethodGet, "/v1/games/" + id, nil},
		{http.MethodPost, "/v1/games/" + id + "/join", nil},
		{http.MethodPost, "/v1/games/" + id + "/moves", moveAt(0, 0)},
		{http.MethodGet, "/v1/games/" + id + "/moves", nil},
	}
	for _, a := range authorizations {
		t.Run(a.name, func(t *testing.T) {
			for _, r := range routes {
				res, err := c.send(r.method, r.path, a.header, r.body)
				if err != nil {
					t.Fatalf("%s %s: %v", r.method, r.path, err)
				}
				wantError(t, res, http.StatusUnauthorized, "UNAUTHORIZED")
				if got := res.header.Get("WWW-Authenticate"); got != "Bearer" {
					t.Errorf("%s %s: WWW-Authenticate %q, want Bearer", r.method, r.path, got)
				}
			}
		})
	}

	// The scheme is case-insensitive.
	for _, scheme := range []string{"bearer", "BEARER"} {
		res, err := c.send(http.MethodGet, "/v1/games/"+id, scheme+" "+alice.token, nil)
		if err != nil {
			t.Fatal(err)
		}
		decode[gameView](t, res, http.StatusOK)
	}

	// A genuine token for a user the database doesn't have: no game was
	// looked up, so this is a credentials problem rather than a 404.
	tokens, err := auth.NewTokens([]byte(testSecret), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	ghost, _, err := tokens.Issue("00000000-0000-4000-8000-000000000000", "ghost")
	if err != nil {
		t.Fatal(err)
	}
	res := c.do(t, http.MethodPost, "/v1/games", ghost, nil)
	wantError(t, res, http.StatusUnauthorized, "UNAUTHORIZED")
	if got := res.header.Get("WWW-Authenticate"); got != "Bearer" {
		t.Errorf("WWW-Authenticate %q, want Bearer", got)
	}
}
