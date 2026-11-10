// Package auth hashes passwords and issues and verifies the signed tokens that
// identify players. It keeps no server-side session state: any server
// instance holding the same secret can verify any token.
package auth

import (
	"errors"
	"time"
)

const (
	// MinPasswordLen and MaxPasswordLen bound password length in bytes.
	// bcrypt ignores input past 72 bytes, so longer passwords are rejected
	// rather than silently truncated.
	MinPasswordLen = 8
	MaxPasswordLen = 72

	// MinSecretLen is the shortest HMAC secret NewTokens accepts.
	MinSecretLen = 32

	// Issuer is the "iss" claim on every token; Verify requires it.
	Issuer = "tictactoe"
)

var (
	// ErrInvalidToken is wrapped by every error Verify returns.
	ErrInvalidToken = errors.New("invalid or expired token")
	// ErrPasswordLength is returned by HashPassword for a password outside
	// [MinPasswordLen, MaxPasswordLen] bytes.
	ErrPasswordLength = errors.New("password must be between 8 and 72 bytes")
	// ErrWeakSecret is returned by NewTokens for a secret shorter than MinSecretLen.
	ErrWeakSecret = errors.New("token secret must be at least 32 bytes")
)

// HashPassword returns a bcrypt hash of password at the given cost. It
// returns ErrPasswordLength (before doing any hashing) if the password is
// outside [MinPasswordLen, MaxPasswordLen] bytes.
func HashPassword(password string, cost int) (string, error) {
	panic("not implemented") // TODO(auth agent)
}

// CheckPassword reports whether password matches the bcrypt hash.
func CheckPassword(hash, password string) bool {
	panic("not implemented") // TODO(auth agent)
}

// Claims identifies the player a verified token was issued to.
type Claims struct {
	UserID    string
	Username  string
	ExpiresAt time.Time
}

// Tokens issues and verifies HS256-signed JWTs. It is safe for concurrent use.
type Tokens struct {
	secret []byte
	ttl    time.Duration
	now    func() time.Time // time source; tests may replace it
}

// NewTokens returns a Tokens that signs with secret and issues tokens valid
// for ttl. The secret must be at least MinSecretLen bytes (else
// ErrWeakSecret) and ttl must be positive.
func NewTokens(secret []byte, ttl time.Duration) (*Tokens, error) {
	panic("not implemented") // TODO(auth agent)
}

// Issue returns a signed token for the user and the time it expires.
func (t *Tokens) Issue(userID, username string) (token string, expiresAt time.Time, err error) {
	panic("not implemented") // TODO(auth agent)
}

// Verify checks the token's signature (HS256 only), expiry and issuer and
// returns its claims. Every failure returns an error wrapping ErrInvalidToken.
func (t *Tokens) Verify(token string) (Claims, error) {
	panic("not implemented") // TODO(auth agent)
}
