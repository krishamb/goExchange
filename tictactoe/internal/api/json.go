package api

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/krishamb/goExchange/tictactoe/internal/game"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
)

// maxBodyBytes caps request bodies. Valid bodies are tiny; the cap stops a
// client from making the server read and parse arbitrarily large input.
const maxBodyBytes = 64 << 10

// internalErrorMessage is all a client learns about an unexpected failure.
// The real error goes to the log.
const internalErrorMessage = "internal server error"

type errorResponse struct {
	Error errorDetail `json:"error"`
}

type errorDetail struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

// writeJSON sends v as the response body with the given status.
func writeJSON(w http.ResponseWriter, status int, v any) {
	// Encoding before writing anything keeps a failure here from leaving a
	// half-written response behind.
	body, err := json.Marshal(v)
	if err != nil {
		// Every response type is a plain struct, so this is a programming
		// error. recoverPanics logs it and sends a 500.
		panic(fmt.Sprintf("api: encode %T response: %v", v, err))
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	// An error here means the client has gone; there is no one to tell.
	_, _ = w.Write(append(body, '\n'))
}

// writeError sends the API's error body.
func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, errorResponse{Error: errorDetail{Code: code, Message: message}})
}

// respondError sends the response for an error from the store, the game rules
// or auth. Errors that aren't a client's fault become a generic 500, and
// only the log sees what went wrong.
func (s *server) respondError(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(err, store.ErrUnknownPlayer) {
		// The token is genuine but names a user the database doesn't have
		// (say, it was reset). That's a credentials problem, not a missing game.
		unauthorized(w, "the token's user does not exist")
		return
	}
	if status, code, message, ok := clientError(err); ok {
		writeError(w, status, code, message)
		return
	}
	s.log.ErrorContext(r.Context(), "request failed",
		"method", r.Method, "path", r.URL.Path, "err", err)
	writeError(w, http.StatusInternalServerError, "INTERNAL", internalErrorMessage)
}

// clientError maps the errors that describe a problem with the request to
// their responses. The message is the matched error's own text rather than
// err.Error(), so context the store wraps around it never reaches clients.
func clientError(err error) (status int, code, message string, ok bool) {
	for _, e := range [...]struct {
		target  error
		status  int
		code    string
		message string // "" means target's own text
	}{
		// Only game routes reach here with ErrNotFound: login handles an
		// unknown username itself.
		{store.ErrNotFound, http.StatusNotFound, "NOT_FOUND", "game not found"},
		{game.ErrOutOfBounds, http.StatusBadRequest, "OUT_OF_BOUNDS", ""},
		{game.ErrNotAPlayer, http.StatusForbidden, "NOT_A_PLAYER", ""},
		{game.ErrVersionMismatch, http.StatusConflict, "VERSION_MISMATCH", ""},
		{game.ErrGameNotStarted, http.StatusConflict, "GAME_NOT_IN_PROGRESS", ""},
		{game.ErrGameOver, http.StatusConflict, "GAME_NOT_IN_PROGRESS", ""},
		{game.ErrNotYourTurn, http.StatusConflict, "NOT_YOUR_TURN", ""},
		{game.ErrCellOccupied, http.StatusConflict, "CELL_OCCUPIED", ""},
		{game.ErrOwnGame, http.StatusConflict, "CANNOT_JOIN_OWN_GAME", ""},
		{game.ErrGameFull, http.StatusConflict, "GAME_FULL", ""},
		{store.ErrConflict, http.StatusConflict, "CONFLICT", ""},
		{store.ErrUsernameTaken, http.StatusConflict, "USERNAME_TAKEN", ""},
	} {
		if errors.Is(err, e.target) {
			if e.message == "" {
				e.message = e.target.Error()
			}
			return e.status, e.code, e.message, true
		}
	}
	return 0, "", "", false
}

// decodeJSON decodes the request body into dst. The body must hold a single
// JSON object with no fields that dst lacks. On failure decodeJSON sends the
// error response and returns false.
func decodeJSON(w http.ResponseWriter, r *http.Request, dst any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBodyBytes))
	dec.DisallowUnknownFields()
	err := dec.Decode(dst)
	if err == nil {
		err = expectEOF(dec)
	}
	if err == nil {
		return true
	}

	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		writeError(w, http.StatusRequestEntityTooLarge, "BODY_TOO_LARGE",
			fmt.Sprintf("request body must not exceed %d bytes", tooLarge.Limit))
		return false
	}
	writeError(w, http.StatusBadRequest, "INVALID_JSON", jsonErrorMessage(err))
	return false
}

var errTrailingData = errors.New("request body must contain a single JSON object")

// expectEOF checks that nothing but whitespace follows the value dec has just
// decoded: Decode stops after one value and would silently ignore the rest.
func expectEOF(dec *json.Decoder) error {
	_, err := dec.Token()
	switch {
	case err == io.EOF:
		return nil
	case errors.As(err, new(*http.MaxBytesError)):
		return err // the trailing data alone took the body over the limit
	}
	return errTrailingData
}

// jsonErrorMessage explains a decoding failure in terms of the JSON the
// client sent rather than the Go types it was decoded into.
func jsonErrorMessage(err error) string {
	var syntaxErr *json.SyntaxError
	var typeErr *json.UnmarshalTypeError
	switch {
	case errors.Is(err, errTrailingData):
		return err.Error()
	case errors.As(err, &syntaxErr):
		return fmt.Sprintf("malformed JSON at byte %d", syntaxErr.Offset)
	case errors.Is(err, io.ErrUnexpectedEOF):
		return "malformed JSON: unexpected end of input"
	case errors.Is(err, io.EOF):
		return "request body must be a JSON object"
	case errors.As(err, &typeErr) && typeErr.Field != "":
		return fmt.Sprintf("field %q has the wrong type", typeErr.Field)
	case errors.As(err, &typeErr):
		return "request body must be a JSON object"
	case strings.HasPrefix(err.Error(), "json: unknown field "):
		// encoding/json has no error type for this (golang/go#29035).
		return strings.TrimPrefix(err.Error(), "json: ")
	}
	return "request body is not valid JSON"
}
