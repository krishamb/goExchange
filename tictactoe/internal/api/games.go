package api

import (
	"errors"
	"net/http"
	"time"

	"github.com/krishamb/goExchange/tictactoe/internal/game"
	"github.com/krishamb/goExchange/tictactoe/internal/store"
)

type gameJSON struct {
	ID        string                       `json:"id"`
	Status    game.Status                  `json:"status"`
	Board     [game.Size][game.Size]string `json:"board"` // rows of "X", "O" or ""
	Players   playersJSON                  `json:"players"`
	NextTurn  *string                      `json:"next_turn"` // null unless in progress
	Winner    *string                      `json:"winner"`
	Version   int                          `json:"version"`
	CreatedAt time.Time                    `json:"created_at"`
	UpdatedAt time.Time                    `json:"updated_at"`
}

type playersJSON struct {
	X userJSON  `json:"X"`
	O *userJSON `json:"O"` // null while waiting for an opponent
}

type moveJSON struct {
	MoveNumber int       `json:"move_number"`
	Symbol     string    `json:"symbol"`
	Row        int       `json:"row"`
	Col        int       `json:"col"`
	Player     userJSON  `json:"player"`
	CreatedAt  time.Time `json:"created_at"`
}

func newGameJSON(g store.GameView) gameJSON {
	out := gameJSON{
		ID:        g.ID,
		Status:    g.Status,
		Players:   playersJSON{X: userJSON{ID: g.PlayerX, Username: g.PlayerXName}},
		NextTurn:  markJSON(g.NextTurn()),
		Winner:    markJSON(g.Winner()),
		Version:   g.Version,
		CreatedAt: g.CreatedAt.UTC(),
		UpdatedAt: g.UpdatedAt.UTC(),
	}
	if g.PlayerO != "" {
		out.Players.O = &userJSON{ID: g.PlayerO, Username: g.PlayerOName}
	}
	for row := range game.Size {
		for col := range game.Size {
			out.Board[row][col] = g.Board.At(row, col).String()
		}
	}
	return out
}

func newMoveJSON(m store.MoveView) moveJSON {
	return moveJSON{
		MoveNumber: m.Number,
		Symbol:     m.Mark.String(),
		Row:        m.Row,
		Col:        m.Col,
		Player:     userJSON{ID: m.PlayerID, Username: m.Username},
		CreatedAt:  m.CreatedAt.UTC(),
	}
}

// markJSON returns "X" or "O", or nil (JSON null) for game.Empty.
func markJSON(m game.Mark) *string {
	if m == game.Empty {
		return nil
	}
	s := m.String()
	return &s
}

func (s *server) createGame(w http.ResponseWriter, r *http.Request) {
	g, err := s.store.CreateGame(r.Context(), caller(r).UserID)
	if errors.Is(err, store.ErrNotFound) {
		// The token is genuine but names a user the database doesn't have
		// (say, it was reset). No game was looked up, so a 404 would mislead.
		unauthorized(w, "the token's user does not exist")
		return
	}
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	w.Header().Set("Location", "/v1/games/"+g.ID)
	writeJSON(w, http.StatusCreated, newGameJSON(g))
}

func (s *server) getGame(w http.ResponseWriter, r *http.Request) {
	g, err := s.store.GetGame(r.Context(), r.PathValue("id"))
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, newGameJSON(g))
}

func (s *server) joinGame(w http.ResponseWriter, r *http.Request) {
	g, err := s.store.JoinGame(r.Context(), r.PathValue("id"), caller(r).UserID)
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	writeJSON(w, http.StatusOK, newGameJSON(g))
}

// moveRequest has pointer fields so that a missing row or col can be told
// apart from 0.
type moveRequest struct {
	Row             *int `json:"row"`
	Col             *int `json:"col"`
	ExpectedVersion *int `json:"expected_version"` // optional optimistic-concurrency check
}

type moveResponse struct {
	Move moveJSON `json:"move"`
	Game gameJSON `json:"game"`
}

func (s *server) playMove(w http.ResponseWriter, r *http.Request) {
	var req moveRequest
	if !decodeJSON(w, r, &req) {
		return
	}
	if req.Row == nil || req.Col == nil {
		writeError(w, http.StatusBadRequest, "INVALID_REQUEST", "row and col are required")
		return
	}
	// The rules check this too, but a move off the board can be refused
	// without a database round trip.
	if !game.InBounds(*req.Row, *req.Col) {
		writeError(w, http.StatusBadRequest, "OUT_OF_BOUNDS", game.ErrOutOfBounds.Error())
		return
	}
	g, m, err := s.store.PlayMove(r.Context(), r.PathValue("id"), caller(r).UserID,
		*req.Row, *req.Col, req.ExpectedVersion)
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	writeJSON(w, http.StatusCreated, moveResponse{Move: newMoveJSON(m), Game: newGameJSON(g)})
}

type movesResponse struct {
	Moves []moveJSON `json:"moves"`
}

func (s *server) listMoves(w http.ResponseWriter, r *http.Request) {
	moves, err := s.store.ListMoves(r.Context(), r.PathValue("id"))
	if err != nil {
		s.respondError(w, r, err)
		return
	}
	// Non-nil even when empty, so the JSON is [] rather than null.
	out := make([]moveJSON, 0, len(moves))
	for _, m := range moves {
		out = append(out, newMoveJSON(m))
	}
	writeJSON(w, http.StatusOK, movesResponse{Moves: out})
}
