package auth

import (
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
)

// testSecret is exactly MinSecretLen bytes.
var testSecret = []byte("0123456789abcdef0123456789abcdef")

// start is the clock reading tests issue tokens at. It is half a second past
// the second, so the expiry Issue reports must be truncated to match the
// whole-second exp claim.
var start = time.Date(2026, time.January, 2, 15, 4, 5, 500_000_000, time.UTC)

// newTestTokens returns Tokens with a one-hour TTL whose clock reads *now, so a
// test can move time by assigning to it.
func newTestTokens(t *testing.T, secret []byte, now *time.Time) *Tokens {
	t.Helper()
	tk, err := NewTokens(secret, time.Hour)
	if err != nil {
		t.Fatalf("NewTokens: %v", err)
	}
	tk.now = func() time.Time { return *now }
	return tk
}

// sign builds a token directly with the jwt library, for shapes Issue never
// produces.
func sign(t *testing.T, method jwt.SigningMethod, key any, claims jwt.MapClaims) string {
	t.Helper()
	token, err := jwt.NewWithClaims(method, claims).SignedString(key)
	if err != nil {
		t.Fatalf("signing test token: %v", err)
	}
	return token
}

func TestHashAndCheckPassword(t *testing.T) {
	const password = "correct horse battery staple"
	// Two costs, so a hard-coded cost could not pass.
	for _, cost := range []int{bcrypt.MinCost, bcrypt.MinCost + 1} {
		hash, err := HashPassword(password, cost)
		if err != nil {
			t.Fatalf("HashPassword(cost %d): %v", cost, err)
		}
		if got, err := bcrypt.Cost([]byte(hash)); err != nil || got != cost {
			t.Errorf("bcrypt.Cost(hash) = %d, %v; want %d", got, err, cost)
		}
		if !CheckPassword(hash, password) {
			t.Errorf("cost %d: CheckPassword rejected the password the hash was made from", cost)
		}
		if CheckPassword(hash, "correct horse battery stapler") {
			t.Errorf("cost %d: CheckPassword accepted a wrong password", cost)
		}
	}
}

func TestHashPasswordSalts(t *testing.T) {
	a, errA := HashPassword("same password", bcrypt.MinCost)
	b, errB := HashPassword("same password", bcrypt.MinCost)
	if errA != nil || errB != nil {
		t.Fatalf("HashPassword: %v, %v", errA, errB)
	}
	if a == b {
		t.Errorf("two hashes of the same password are identical (%q); want distinct salts", a)
	}
}

func TestHashPasswordLength(t *testing.T) {
	tests := []struct {
		name     string
		password string
		wantErr  error
	}{
		{"empty", "", ErrPasswordLength},
		{"7 bytes", strings.Repeat("a", 7), ErrPasswordLength},
		{"8 bytes", strings.Repeat("a", 8), nil},
		{"72 bytes", strings.Repeat("a", 72), nil},
		{"73 bytes", strings.Repeat("a", 73), ErrPasswordLength},
		// "€" is one rune but three bytes, so these cases would flip if
		// length were counted in runes.
		{"8 bytes in 4 runes", "€€ab", nil},
		{"72 bytes in 24 runes", strings.Repeat("€", 24), nil},
		{"73 bytes in 25 runes", strings.Repeat("€", 24) + "a", ErrPasswordLength},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			hash, err := HashPassword(tc.password, bcrypt.MinCost)
			if !errors.Is(err, tc.wantErr) {
				t.Fatalf("HashPassword(%d bytes) err = %v, want %v", len(tc.password), err, tc.wantErr)
			}
			if tc.wantErr == nil && !CheckPassword(hash, tc.password) {
				t.Error("CheckPassword rejected the password the hash was made from")
			}
		})
	}
}

func TestHashPasswordInvalidCost(t *testing.T) {
	_, err := HashPassword("long enough", bcrypt.MaxCost+1)
	var costErr bcrypt.InvalidCostError
	if !errors.As(err, &costErr) {
		t.Fatalf("HashPassword(cost %d) err = %v, want a bcrypt.InvalidCostError", bcrypt.MaxCost+1, err)
	}
}

func TestCheckPasswordRejects(t *testing.T) {
	stored := strings.Repeat("a", MaxPasswordLen)
	hash, err := HashPassword(stored, bcrypt.MinCost)
	if err != nil {
		t.Fatalf("HashPassword: %v", err)
	}
	tests := []struct{ name, hash, password string }{
		// bcrypt compares only the first 72 bytes, so this matches unless
		// CheckPassword enforces the length limit itself.
		{"stored password plus a suffix", hash, stored + "b"},
		{"empty hash", "", stored},
		{"malformed hash", "not a bcrypt hash", stored},
	}
	for _, tc := range tests {
		if CheckPassword(tc.hash, tc.password) {
			t.Errorf("%s: CheckPassword = true, want false", tc.name)
		}
	}
}

func TestNewTokensSecretLength(t *testing.T) {
	for _, n := range []int{0, MinSecretLen - 1} {
		if _, err := NewTokens(make([]byte, n), time.Hour); !errors.Is(err, ErrWeakSecret) {
			t.Errorf("NewTokens(%d-byte secret) err = %v, want ErrWeakSecret", n, err)
		}
	}
	if _, err := NewTokens(make([]byte, MinSecretLen), time.Hour); err != nil {
		t.Errorf("NewTokens(%d-byte secret): %v", MinSecretLen, err)
	}
}

func TestNewTokensTTL(t *testing.T) {
	for _, ttl := range []time.Duration{0, -time.Minute} {
		if _, err := NewTokens(testSecret, ttl); err == nil {
			t.Errorf("NewTokens(ttl %v) succeeded, want an error", ttl)
		}
	}
}

func TestNewTokensCopiesSecret(t *testing.T) {
	secret := bytes.Clone(testSecret)
	tk, err := NewTokens(secret, time.Hour)
	if err != nil {
		t.Fatalf("NewTokens: %v", err)
	}
	token, _, err := tk.Issue("user-1", "alice")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	clear(secret) // as a caller might, to wipe the key from its own memory
	if _, err := tk.Verify(token); err != nil {
		t.Errorf("Verify after the caller cleared its secret slice: %v", err)
	}
}

func TestIssueVerifyRoundTrip(t *testing.T) {
	now := start
	tk := newTestTokens(t, testSecret, &now)

	token, exp, err := tk.Issue("user-1", "alice")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	// An hour after start, truncated to the second like the exp claim.
	wantExp := time.Date(2026, time.January, 2, 16, 4, 5, 0, time.UTC)
	if !exp.Equal(wantExp) {
		t.Errorf("Issue expiry = %v, want %v", exp, wantExp)
	}

	got, err := tk.Verify(token)
	if err != nil {
		t.Fatalf("Verify: %v", err)
	}
	if got.UserID != "user-1" || got.Username != "alice" || !got.ExpiresAt.Equal(exp) {
		t.Errorf("Verify = %+v, want user-1/alice expiring at %v", got, exp)
	}

	// Verify does not expose the header, iss or iat, so check the encoded
	// token directly.
	raw := jwt.MapClaims{}
	parsed, _, err := jwt.NewParser().ParseUnverified(token, raw)
	if err != nil {
		t.Fatalf("ParseUnverified: %v", err)
	}
	wantHeader := map[string]any{"alg": "HS256", "typ": "JWT"}
	if !reflect.DeepEqual(parsed.Header, wantHeader) {
		t.Errorf("header = %v, want %v", parsed.Header, wantHeader)
	}
	wantClaims := jwt.MapClaims{
		"sub":      "user-1",
		"username": "alice",
		"iss":      Issuer,
		"iat":      float64(start.Unix()), // JSON numbers decode as float64
		"exp":      float64(wantExp.Unix()),
	}
	if !reflect.DeepEqual(raw, wantClaims) {
		t.Errorf("claims = %v, want %v", raw, wantClaims)
	}
}

func TestIssueRequiresUserID(t *testing.T) {
	now := start
	tk := newTestTokens(t, testSecret, &now)
	if _, _, err := tk.Issue("", "alice"); err == nil {
		t.Error("Issue with an empty user ID succeeded, want an error")
	}
}

func TestVerifyExpiry(t *testing.T) {
	now := start
	tk := newTestTokens(t, testSecret, &now)
	token, exp, err := tk.Issue("user-1", "alice")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}

	now = exp.Add(-time.Nanosecond)
	if _, err := tk.Verify(token); err != nil {
		t.Fatalf("Verify just before expiry: %v", err)
	}
	for _, at := range []time.Time{exp, exp.Add(time.Hour)} {
		now = at
		if _, err := tk.Verify(token); !errors.Is(err, ErrInvalidToken) {
			t.Errorf("Verify at %v of a token expiring at %v: err = %v, want ErrInvalidToken", at, exp, err)
		}
	}
}

func TestVerifyRejects(t *testing.T) {
	now := start
	tk := newTestTokens(t, testSecret, &now)

	good, _, err := tk.Issue("user-1", "alice")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	other, _, err := tk.Issue("user-2", "bob")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}
	foreign, _, err := newTestTokens(t, []byte(strings.Repeat("x", MinSecretLen)), &now).Issue("user-1", "alice")
	if err != nil {
		t.Fatalf("Issue: %v", err)
	}

	parts := strings.Split(good, ".") // header, payload, signature
	otherPayload := strings.Split(other, ".")[1]
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		t.Fatalf("decoding signature: %v", err)
	}
	// Flip a bit of the decoded signature: editing its last base64 character
	// may change only padding bits, which decode to the same signature.
	sig[0] ^= 1
	flipped := parts[0] + "." + parts[1] + "." + base64.RawURLEncoding.EncodeToString(sig)

	// valid returns claims tk accepts; each hand-built case breaks one thing.
	valid := func() jwt.MapClaims {
		return jwt.MapClaims{
			"sub": "user-1", "username": "alice", "iss": Issuer,
			"iat": now.Unix(), "exp": now.Add(time.Hour).Unix(),
		}
	}
	with := func(claim string, value any) jwt.MapClaims {
		c := valid()
		c[claim] = value
		return c
	}
	without := func(claim string) jwt.MapClaims {
		c := valid()
		delete(c, claim)
		return c
	}
	hs256 := func(c jwt.MapClaims) string { return sign(t, jwt.SigningMethodHS256, testSecret, c) }

	// If the unbroken hand-built token failed, the cases below could pass
	// for the wrong reason.
	if _, err := tk.Verify(hs256(valid())); err != nil {
		t.Fatalf("Verify(hand-built valid token): %v", err)
	}

	tests := []struct {
		name  string
		token string
	}{
		{"empty", ""},
		{"garbage", "garbage"},
		{"garbage segments", "a.b.c"},
		{"signed with another secret", foreign},
		{"payload swapped for another user's", parts[0] + "." + otherPayload + "." + parts[2]},
		{"signature bit flipped", flipped},
		{"signature removed", parts[0] + "." + parts[1] + "."},
		{"alg none", sign(t, jwt.SigningMethodNone, jwt.UnsafeAllowNoneSignatureType, valid())},
		{"HS512 with the same secret", sign(t, jwt.SigningMethodHS512, testSecret, valid())},
		{"wrong issuer", hs256(with("iss", "someone-else"))},
		{"no issuer", hs256(without("iss"))},
		{"no exp", hs256(without("exp"))},
		{"no sub", hs256(without("sub"))},
		{"empty sub", hs256(with("sub", ""))},
		{"non-string sub", hs256(with("sub", 42))},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := tk.Verify(tc.token)
			if !errors.Is(err, ErrInvalidToken) {
				t.Fatalf("Verify err = %v, want one wrapping ErrInvalidToken", err)
			}
			if got != (Claims{}) {
				t.Errorf("Verify claims = %+v, want the zero value alongside an error", got)
			}
		})
	}
}

func TestTokensConcurrentUse(t *testing.T) {
	tk, err := NewTokens(testSecret, time.Hour) // real clock
	if err != nil {
		t.Fatalf("NewTokens: %v", err)
	}
	const goroutines, rounds = 16, 50
	var wg sync.WaitGroup
	for g := range goroutines {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range rounds {
				id := fmt.Sprintf("user-%d-%d", g, i)
				token, _, err := tk.Issue(id, "player")
				if err != nil {
					t.Errorf("Issue(%s): %v", id, err)
					return
				}
				claims, err := tk.Verify(token)
				if err != nil {
					t.Errorf("Verify(token for %s): %v", id, err)
					return
				}
				if claims.UserID != id {
					t.Errorf("Verify(token for %s).UserID = %q", id, claims.UserID)
					return
				}
			}
		}()
	}
	wg.Wait()
}
