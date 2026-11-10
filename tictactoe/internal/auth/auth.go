// Package auth hashes passwords and issues and verifies the signed tokens that
// identify players. It keeps no server-side session state: any server
// instance holding the same secret can verify any token.
package auth

import (
	"bytes"
	"errors"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
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
	if len(password) < MinPasswordLen || len(password) > MaxPasswordLen {
		return "", ErrPasswordLength
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), cost)
	if err != nil {
		return "", err
	}
	return string(hash), nil
}

// CheckPassword reports whether password matches the bcrypt hash.
func CheckPassword(hash, password string) bool {
	// bcrypt compares only the first 72 bytes, so without the length check a
	// stored password followed by any suffix would match too. HashPassword
	// never hashes a longer password, so a longer one is always wrong.
	return len(password) <= MaxPasswordLen &&
		bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
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

// tokenClaims is the token payload: the registered claims plus the username,
// so that Verify can return a player's full Claims without a store lookup.
type tokenClaims struct {
	jwt.RegisteredClaims
	Username string `json:"username"`
}

// NewTokens returns a Tokens that signs with secret and issues tokens valid
// for ttl. The secret must be at least MinSecretLen bytes (else
// ErrWeakSecret) and ttl must be positive.
func NewTokens(secret []byte, ttl time.Duration) (*Tokens, error) {
	if len(secret) < MinSecretLen {
		return nil, ErrWeakSecret
	}
	if ttl <= 0 {
		return nil, fmt.Errorf("token ttl must be positive, got %v", ttl)
	}
	// Copy the secret so a caller that later reuses or zeroes its slice
	// cannot change the key out from under tokens already issued.
	return &Tokens{secret: bytes.Clone(secret), ttl: ttl, now: time.Now}, nil
}

// Issue returns a signed token for the user and the time it expires.
func (t *Tokens) Issue(userID, username string) (token string, expiresAt time.Time, err error) {
	// Verify rejects tokens without a subject, so fail here rather than hand
	// out a token that can never be used.
	if userID == "" {
		return "", time.Time{}, errors.New("cannot issue a token without a user ID")
	}
	now := t.now()
	// The exp claim has whole-second precision; returning the truncated
	// value tells the caller exactly when Verify will start rejecting it.
	exp := jwt.NewNumericDate(now.Add(t.ttl))
	claims := tokenClaims{
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			Issuer:    Issuer,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: exp,
		},
		Username: username,
	}
	token, err = jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(t.secret)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("sign token: %w", err)
	}
	return token, exp.Time, nil
}

// Verify checks the token's signature (HS256 only), expiry and issuer and
// returns its claims. Every failure returns an error wrapping ErrInvalidToken.
func (t *Tokens) Verify(token string) (Claims, error) {
	var c tokenClaims
	_, err := jwt.ParseWithClaims(token, &c, t.key,
		// Pinning the algorithm stops a token from choosing how it is
		// checked, e.g. "none" or another hash under the same secret.
		jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}),
		jwt.WithIssuer(Issuer),
		jwt.WithExpirationRequired(), // the library treats exp as optional
		jwt.WithTimeFunc(t.now),
	)
	if err != nil {
		// %v rather than %w: callers should match ErrInvalidToken, not
		// depend on the jwt library's error types.
		return Claims{}, fmt.Errorf("%w: %v", ErrInvalidToken, err)
	}
	// The library treats sub as optional too, but a token without one
	// identifies no player.
	if c.Subject == "" {
		return Claims{}, fmt.Errorf("%w: missing subject", ErrInvalidToken)
	}
	// WithExpirationRequired guarantees ExpiresAt is non-nil here.
	return Claims{UserID: c.Subject, Username: c.Username, ExpiresAt: c.ExpiresAt.Time}, nil
}

// key supplies the HMAC secret to the parser. The parser checks the token's
// alg against WithValidMethods before calling it, so the secret is only ever
// used to verify HS256 signatures.
func (t *Tokens) key(*jwt.Token) (any, error) {
	return t.secret, nil
}
