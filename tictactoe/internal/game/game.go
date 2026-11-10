// Package game holds the tic-tac-toe rules. It is pure: no I/O, clocks or
// randomness, so every rule can be tested exhaustively and the same code
// decides every move no matter which server instance handles the request.
package game

import (
	"errors"
	"fmt"
)

// Size is the board's width and height.
const Size = 3

// Cells is the number of cells on the board.
const Cells = Size * Size

// Mark is the content of one cell.
type Mark byte

const (
	Empty Mark = '.'
	X     Mark = 'X'
	O     Mark = 'O'
)

// String returns "X", "O", or "" for an empty cell.
func (m Mark) String() string {
	switch m {
	case X:
		return "X"
	case O:
		return "O"
	default:
		return ""
	}
}

// Status is where a game is in its lifecycle.
type Status string

const (
	StatusWaiting    Status = "waiting"     // created; waiting for player O to join
	StatusInProgress Status = "in_progress" // both players seated; moves allowed
	StatusXWon       Status = "x_won"
	StatusOWon       Status = "o_won"
	StatusDraw       Status = "draw"
)

// Valid reports whether s is a known status.
func (s Status) Valid() bool {
	switch s {
	case StatusWaiting, StatusInProgress, StatusXWon, StatusOWon, StatusDraw:
		return true
	}
	return false
}

// Over reports whether the game has finished.
func (s Status) Over() bool {
	return s == StatusXWon || s == StatusOWon || s == StatusDraw
}

// Board is stored row-major: cell (row, col) is at index row*Size+col.
type Board [Cells]Mark

// NewBoard returns an empty board.
func NewBoard() Board {
	var b Board
	for i := range b {
		b[i] = Empty
	}
	return b
}

// ParseBoard parses the 9-character form stored in the database, e.g. "X...O....".
func ParseBoard(s string) (Board, error) {
	var b Board
	if len(s) != Cells {
		return b, fmt.Errorf("board must have %d cells, got %d", Cells, len(s))
	}
	for i := 0; i < Cells; i++ {
		m := Mark(s[i])
		if m != Empty && m != X && m != O {
			return b, fmt.Errorf("invalid cell %q at index %d", s[i], i)
		}
		b[i] = m
	}
	return b, nil
}

// String is the inverse of ParseBoard.
func (b Board) String() string {
	buf := make([]byte, Cells)
	for i, m := range b {
		buf[i] = byte(m)
	}
	return string(buf)
}

// InBounds reports whether (row, col) is on the board.
func InBounds(row, col int) bool {
	return row >= 0 && row < Size && col >= 0 && col < Size
}

// At returns the mark at (row, col). The caller must ensure InBounds(row, col).
func (b Board) At(row, col int) Mark { return b[row*Size+col] }

// Count returns how many marks have been placed.
func (b Board) Count() int {
	n := 0
	for _, m := range b {
		if m != Empty {
			n++
		}
	}
	return n
}

// NextMark returns whose turn it is on this board. X moves first and the
// players alternate, so it is X's turn whenever an even number of marks have
// been placed. Turn order is derived from the board, so it can never drift
// out of sync with it.
func (b Board) NextMark() Mark {
	if b.Count()%2 == 0 {
		return X
	}
	return O
}

// winsThrough reports whether the mark at (row, col) completes its row, its
// column, or a diagonal running through that cell. Only those lines can have
// changed with the last move, so this is all that needs checking after each
// move: O(Size) instead of scanning the whole board.
func (b Board) winsThrough(row, col int) bool {
	m := b.At(row, col)
	if m == Empty {
		return false
	}
	rowWin, colWin := true, true
	diagWin, antiWin := row == col, row+col == Size-1
	for i := 0; i < Size; i++ {
		rowWin = rowWin && b.At(row, i) == m
		colWin = colWin && b.At(i, col) == m
		diagWin = diagWin && b.At(i, i) == m
		antiWin = antiWin && b.At(i, Size-1-i) == m
	}
	return rowWin || colWin || diagWin || antiWin
}

// Rule violations. Callers map these to API responses.
var (
	ErrOutOfBounds     = errors.New("cell is outside the 3x3 board")
	ErrNotAPlayer      = errors.New("you are not a player in this game")
	ErrVersionMismatch = errors.New("the game has changed since the version you sent")
	ErrGameNotStarted  = errors.New("the game is waiting for an opponent to join")
	ErrGameOver        = errors.New("the game is already over")
	ErrNotYourTurn     = errors.New("it is not your turn")
	ErrCellOccupied    = errors.New("that cell is already taken")
	ErrOwnGame         = errors.New("you cannot join your own game")
	ErrGameFull        = errors.New("the game already has two players")
)

// Game is the rules-level state of one game. Player IDs are opaque strings
// (UUIDs in the database).
type Game struct {
	ID      string
	PlayerX string // user ID of X; always set
	PlayerO string // user ID of O; "" while waiting
	Board   Board
	Status  Status
	Version int // 1 at creation; +1 on join and on every move
}

// Move is one accepted move.
type Move struct {
	Number   int // 1-based: move n is the n-th mark placed, so X plays odd numbers
	PlayerID string
	Mark     Mark
	Row, Col int
}

// MarkOf returns the mark playerID plays in g, or Empty if they hold no seat.
func (g *Game) MarkOf(playerID string) Mark {
	switch {
	case playerID == "":
		return Empty
	case playerID == g.PlayerX:
		return X
	case playerID == g.PlayerO:
		return O
	}
	return Empty
}

// NextTurn returns the mark due to move, or Empty when the game is not in progress.
func (g *Game) NextTurn() Mark {
	if g.Status != StatusInProgress {
		return Empty
	}
	return g.Board.NextMark()
}

// Winner returns the winning mark, or Empty if nobody has won (yet).
func (g *Game) Winner() Mark {
	switch g.Status {
	case StatusXWon:
		return X
	case StatusOWon:
		return O
	}
	return Empty
}

// Join seats playerID as O and starts the game. If playerID already holds
// seat O it returns nil without changing g, so a retried join is harmless.
func (g *Game) Join(playerID string) error {
	switch {
	case playerID == "":
		return ErrNotAPlayer
	case playerID == g.PlayerX:
		return ErrOwnGame
	case playerID == g.PlayerO:
		return nil
	case g.Status != StatusWaiting || g.PlayerO != "":
		return ErrGameFull
	}
	g.PlayerO = playerID
	g.Status = StatusInProgress
	g.Version++
	return nil
}

// Play validates a move by playerID at (row, col) and applies it to g.
//
// Checks run in this order and the first failure is returned with g
// unchanged: ErrOutOfBounds, ErrNotAPlayer, ErrVersionMismatch (only when
// expectedVersion is non-nil), ErrGameNotStarted or ErrGameOver,
// ErrNotYourTurn, ErrCellOccupied.
//
// On success the mark is placed; Status becomes x_won or o_won if the move
// completed a line, or draw if it filled the board without one (so a win on
// the last cell is a win); and Version is incremented.
func (g *Game) Play(playerID string, row, col int, expectedVersion *int) (Move, error) {
	if !InBounds(row, col) {
		return Move{}, ErrOutOfBounds
	}
	mark := g.MarkOf(playerID)
	if mark == Empty {
		return Move{}, ErrNotAPlayer
	}
	if expectedVersion != nil && *expectedVersion != g.Version {
		return Move{}, ErrVersionMismatch
	}
	switch {
	case g.Status == StatusWaiting:
		return Move{}, ErrGameNotStarted
	case g.Status.Over():
		return Move{}, ErrGameOver
	case g.Status != StatusInProgress:
		return Move{}, fmt.Errorf("game %s has unknown status %q", g.ID, g.Status)
	}
	if g.Board.NextMark() != mark {
		return Move{}, ErrNotYourTurn
	}
	if g.Board.At(row, col) != Empty {
		return Move{}, ErrCellOccupied
	}

	g.Board[row*Size+col] = mark
	switch {
	case g.Board.winsThrough(row, col) && mark == X:
		g.Status = StatusXWon
	case g.Board.winsThrough(row, col):
		g.Status = StatusOWon
	case g.Board.Count() == Cells:
		g.Status = StatusDraw
	}
	g.Version++
	return Move{Number: g.Board.Count(), PlayerID: playerID, Mark: mark, Row: row, Col: col}, nil
}
