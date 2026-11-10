package api

import (
	"errors"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/krishamb/goExchange/tictactoe/internal/auth"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
)

// usernamePattern is the rule for normalized usernames. The users table
// enforces the same one.
var usernamePattern = regexp.MustCompile(`^[a-z0-9_]{3,32}$`)

// normalizeUsername makes usernames case-insensitive and forgiving of stray
// whitespace. Register and login must agree on it, or users could create
// accounts they can't log in to.
func normalizeUsername(s string) string {
	return strings.ToLower(strings.TrimSpace(s))
}

// invalidCredentialsMessage is the same for an unknown username and a wrong
// password, so that a failed login doesn't reveal which usernames exist.
const invalidCredentialsMessage = "invalid username or password"

type credentials struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

type userJSON struct {
	ID       string `json:"id"`
	Username string `json:"username"`
}

type loginResponse struct {
	Token     string    `json:"token"`
	TokenType string    `json:"token_type"`
	ExpiresAt time.Time `json:"expires_at"`
	User      userJSON  `json:"user"`
}

func (s *server) register(w http.ResponseWriter, r *http.Request) {
	var req credentials
	if !decodeJSON(w, r, &req) {
		return
	}
	username := normalizeUsername(req.Username)
	if !usernamePattern.MatchString(username) {
		writeError(w, http.StatusBadRequest, "INVALID_USERNAME",
			"username must be 3 to 32 characters long and use only letters, digits and underscores")
		return
	}
	hash, err := auth.HashPassword(req.Password, s.bcryptCost)
	if errors.Is(err, auth.ErrPasswordLength) {
		writeError(w, http.StatusBadRequest, "INVALID_PASSWORD", err.Error())
		return
	}
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	// No check that the name is free first: the unique constraint is the
	// only check that holds when two people register it at once.
	user, err := s.store.CreateUser(r.Context(), username, hash)
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, userJSON{ID: user.ID, Username: user.Username})
}

func (s *server) login(w http.ResponseWriter, r *http.Request) {
	var req credentials
	if !decodeJSON(w, r, &req) {
		return
	}
	user, err := s.store.GetUserByUsername(r.Context(), normalizeUsername(req.Username))
	if errors.Is(err, store.ErrNotFound) {
		// Do a real user's bcrypt work anyway (see server.dummyHash).
		auth.CheckPassword(s.dummyHash, req.Password)
		writeError(w, http.StatusUnauthorized, "INVALID_CREDENTIALS", invalidCredentialsMessage)
		return
	}
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	if !auth.CheckPassword(user.PasswordHash, req.Password) {
		writeError(w, http.StatusUnauthorized, "INVALID_CREDENTIALS", invalidCredentialsMessage)
		return
	}
	token, expiresAt, err := s.tokens.Issue(user.ID, user.Username)
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, loginResponse{
		Token:     token,
		TokenType: "Bearer",
		ExpiresAt: expiresAt.UTC(),
		User:      userJSON{ID: user.ID, Username: user.Username},
	})
}
