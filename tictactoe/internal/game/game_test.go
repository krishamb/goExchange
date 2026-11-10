package game

import (
	"errors"
	"fmt"
	"maps"
	"math"
	"slices"
	"strings"
	"testing"
)

// Player IDs used throughout. Real IDs are UUIDs, but the rules only compare
// them for equality, and short IDs keep failure messages readable.
const (
	idX      = "x"
	idO      = "o"
	stranger = "z"
)

// cell is a (row, col) pair, for tables of moves and coordinates.
type cell struct{ row, col int }

// seated returns a game that both players have joined, with the given board
// and the Version it would have reached by then.
func seated(t *testing.T, status Status, board string) Game {
	t.Helper()
	b := mustParse(t, board)
	// Version is 1 at creation and goes up on the join and on every move.
	return Game{ID: "g1", PlayerX: idX, PlayerO: idO, Board: b, Status: status, Version: 2 + b.Count()}
}

// waitingGame returns a freshly created game that nobody has joined yet.
func waitingGame() Game {
	return Game{ID: "g1", PlayerX: idX, Board: NewBoard(), Status: StatusWaiting, Version: 1}
}

func mustParse(t *testing.T, board string) Board {
	t.Helper()
	b, err := ParseBoard(board)
	if err != nil {
		t.Fatalf("ParseBoard(%q): %v", board, err)
	}
	return b
}

func intPtr(v int) *int { return &v }

// lines lists the eight winning lines as board indexes. They are written out
// by hand, not derived from Size or At, so referenceStatus shares no code
// with the implementation it checks.
var lines = [8][3]int{
	{0, 1, 2}, {3, 4, 5}, {6, 7, 8}, // rows
	{0, 3, 6}, {1, 4, 7}, {2, 5, 8}, // columns
	{0, 4, 8}, {2, 4, 6}, // diagonals
}

// referenceStatus works out from scratch which status a seated game with
// board b should have. Play only looks at the lines through the last move;
// this scans all eight, so the two cannot share a blind spot.
func referenceStatus(b Board) Status {
	var xLine, oLine bool
	for _, l := range lines {
		m := b[l[0]]
		if m == Empty || b[l[1]] != m || b[l[2]] != m {
			continue
		}
		switch m {
		case X:
			xLine = true
		case O:
			oLine = true
		}
	}
	switch {
	case xLine && oLine:
		// No legal game gets here. A status that matches nothing makes the
		// caller's comparison fail if Play ever lets one through.
		return "both players have a line"
	case xLine:
		return StatusXWon
	case oLine:
		return StatusOWon
	}
	for _, m := range b {
		if m == Empty {
			return StatusInProgress
		}
	}
	return StatusDraw
}

// TestPlayEveryGame plays out every legal game through Play, checking each
// move against referenceStatus and, in every position reached, checking that
// the moves the rules forbid there are rejected.
func TestPlayEveryGame(t *testing.T) {
	finished := map[Status]int{}
	positions := map[Board]Game{} // the first state seen with each board
	var history [Cells]Move       // the moves leading to the position being visited

	var visit func(g Game, depth int)
	visit = func(g Game, depth int) {
		// Everything in Game follows from the board, so every move order that
		// reaches a board must produce the same state. That is also why the
		// rejections need checking only once per position.
		if first, ok := positions[g.Board]; !ok {
			positions[g.Board] = g
			checkRejections(t, g, history[:depth])
		} else if g != first {
			t.Fatalf("after %s: state %+v, but another move order reached this board as %+v",
				describe(history[:depth]), g, first)
		}
		if g.Status.Over() {
			finished[g.Status]++
			return
		}

		// X moves first and the players alternate. The turn is tracked here
		// rather than taken from NextMark, which is part of what is under test.
		player, mark := idX, X
		if depth%2 == 1 {
			player, mark = idO, O
		}
		for i := range Cells {
			if g.Board[i] != Empty {
				continue
			}
			row, col := i/Size, i%Size
			next := g
			move, err := next.Play(player, row, col, nil)
			if err != nil {
				t.Fatalf("after %s: %v at (%d,%d) rejected: %v", describe(history[:depth]), mark, row, col, err)
			}
			wantMove := Move{Number: depth + 1, PlayerID: player, Mark: mark, Row: row, Col: col}
			if move != wantMove {
				t.Fatalf("after %s: Play returned %+v, want %+v", describe(history[:depth]), move, wantMove)
			}
			want := g
			want.Board[i] = mark
			want.Status = referenceStatus(want.Board)
			want.Version++
			if next != want {
				t.Fatalf("after %s, then %v at (%d,%d):\n got %+v\nwant %+v",
					describe(history[:depth]), mark, row, col, next, want)
			}
			history[depth] = move
			visit(next, depth+1)
		}
	}
	visit(seated(t, StatusInProgress, "........."), 0)

	// The well-known totals for tic-tac-toe played until someone wins.
	wantFinished := map[Status]int{StatusXWon: 131_184, StatusOWon: 77_904, StatusDraw: 46_080} // 255,168 games
	if !maps.Equal(finished, wantFinished) {
		t.Errorf("finished games by outcome = %v, want %v", finished, wantFinished)
	}
	if len(positions) != 5_478 {
		t.Errorf("distinct positions reached = %d, want 5,478", len(positions))
	}
}

// checkRejections tries in g every move the rules forbid there and checks
// that each one fails with the documented error and leaves g unchanged.
func checkRejections(t *testing.T, g Game, history []Move) {
	t.Helper()
	onTurn, offTurn := idX, idO
	if len(history)%2 == 1 {
		onTurn, offTurn = idO, idX
	}
	reject := func(player string, row, col int, want error) {
		t.Helper()
		got := g
		move, err := got.Play(player, row, col, nil)
		if !errors.Is(err, want) || move != (Move{}) || got != g {
			t.Fatalf("after %s: Play(%q, %d, %d) = %+v, %v, leaving %+v; want error %v and the game unchanged",
				describe(history), player, row, col, move, err, got, want)
		}
	}
	for i := range Cells {
		row, col := i/Size, i%Size
		reject(stranger, row, col, ErrNotAPlayer)
		if g.Status.Over() {
			reject(idX, row, col, ErrGameOver)
			reject(idO, row, col, ErrGameOver)
			continue
		}
		reject(offTurn, row, col, ErrNotYourTurn)
		if g.Board[i] != Empty {
			reject(onTurn, row, col, ErrCellOccupied)
		}
	}
}

// describe lists moves for failure messages, e.g. "X(0,0) O(1,1)".
func describe(history []Move) string {
	if len(history) == 0 {
		return "no moves"
	}
	parts := make([]string, len(history))
	for i, m := range history {
		parts[i] = fmt.Sprintf("%v(%d,%d)", m.Mark, m.Row, m.Col)
	}
	return strings.Join(parts, " ")
}

// TestPlayScenarios replays whole games, X moving first, and checks how
// each one ends.
func TestPlayScenarios(t *testing.T) {
	tests := []struct {
		name  string
		moves []cell
		want  Status
		board [Size]string // after the last move, one string per row
	}{
		{
			name:  "X wins along the top row",
			moves: []cell{{0, 0}, {1, 1}, {0, 1}, {2, 2}, {0, 2}},
			want:  StatusXWon,
			board: [Size]string{
				"XXX",
				".O.",
				"..O",
			},
		},
		{
			name:  "X wins down the left column",
			moves: []cell{{0, 0}, {0, 1}, {1, 0}, {1, 1}, {2, 0}},
			want:  StatusXWon,
			board: [Size]string{
				"XO.",
				"XO.",
				"X..",
			},
		},
		{
			name:  "X wins on the main diagonal",
			moves: []cell{{0, 0}, {0, 1}, {1, 1}, {0, 2}, {2, 2}},
			want:  StatusXWon,
			board: [Size]string{
				"XOO",
				".X.",
				"..X",
			},
		},
		{
			name:  "X wins on the anti-diagonal",
			moves: []cell{{0, 2}, {0, 0}, {1, 1}, {0, 1}, {2, 0}},
			want:  StatusXWon,
			board: [Size]string{
				"OOX",
				".X.",
				"X..",
			},
		},
		{
			name:  "O wins across the middle row",
			moves: []cell{{0, 0}, {1, 0}, {0, 1}, {1, 1}, {2, 2}, {1, 2}},
			want:  StatusOWon,
			board: [Size]string{
				"XX.",
				"OOO",
				"..X",
			},
		},
		{
			name:  "draw",
			moves: []cell{{0, 0}, {0, 1}, {0, 2}, {1, 1}, {2, 1}, {2, 0}, {1, 0}, {1, 2}, {2, 2}},
			want:  StatusDraw,
			board: [Size]string{
				"XOX",
				"XOO",
				"OXX",
			},
		},
		{
			// The board is full too, but a completed line beats a draw.
			name:  "X wins with the ninth move",
			moves: []cell{{0, 0}, {0, 1}, {0, 2}, {1, 0}, {1, 1}, {1, 2}, {2, 1}, {2, 0}, {2, 2}},
			want:  StatusXWon,
			board: [Size]string{
				"XOX",
				"OXO",
				"OXX",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			g := seated(t, StatusInProgress, ".........")
			for i, c := range tt.moves {
				if g.Status != StatusInProgress {
					t.Fatalf("game ended (%s) before move %d", g.Status, i+1)
				}
				player := idX
				if i%2 == 1 {
					player = idO
				}
				if _, err := g.Play(player, c.row, c.col, nil); err != nil {
					t.Fatalf("move %d, %q at (%d,%d): %v", i+1, player, c.row, c.col, err)
				}
			}
			if g.Status != tt.want {
				t.Errorf("Status = %s, want %s", g.Status, tt.want)
			}
			if got, want := g.Board.String(), strings.Join(tt.board[:], ""); got != want {
				t.Errorf("Board = %s, want %s", got, want)
			}
			if got, want := g.Version, 2+len(tt.moves); got != want {
				t.Errorf("Version = %d, want %d", got, want)
			}
		})
	}
}

// TestPlayRejects covers each rule violation, and which error wins when a
// move breaks several rules at once.
func TestPlayRejects(t *testing.T) {
	fresh := seated(t, StatusInProgress, ".........")
	oToMove := seated(t, StatusInProgress, "X........")
	xWon := seated(t, StatusXWon, "XXXOO....")
	waiting := waitingGame()

	tests := []struct {
		name     string
		game     Game
		player   string
		row, col int
		version  *int
		want     error
	}{
		{"row above the board", fresh, idX, -1, 0, nil, ErrOutOfBounds},
		{"column left of the board", fresh, idX, 0, -1, nil, ErrOutOfBounds},
		{"row below the board", fresh, idX, 3, 0, nil, ErrOutOfBounds},
		{"column right of the board", fresh, idX, 0, 3, nil, ErrOutOfBounds},
		{"far off the board", fresh, idX, math.MaxInt, math.MinInt, nil, ErrOutOfBounds},
		{"stranger", fresh, stranger, 0, 0, nil, ErrNotAPlayer},
		{"empty player ID", fresh, "", 0, 0, nil, ErrNotAPlayer},
		{"empty player ID while seat O is empty", waiting, "", 0, 0, nil, ErrNotAPlayer},
		{"waiting for an opponent", waiting, idX, 0, 0, nil, ErrGameNotStarted},
		{"game over", xWon, idO, 2, 2, nil, ErrGameOver},
		{"O moves first", fresh, idO, 0, 0, nil, ErrNotYourTurn},
		{"X moves twice", oToMove, idX, 1, 1, nil, ErrNotYourTurn},
		{"cell occupied", oToMove, idO, 0, 0, nil, ErrCellOccupied},

		// When a move breaks several rules, the check that runs first decides.
		{"stranger off the board", fresh, stranger, 3, 0, nil, ErrOutOfBounds},
		{"off the board with a stale version", fresh, idX, 0, 3, intPtr(1), ErrOutOfBounds},
		{"stranger with a stale version", fresh, stranger, 0, 0, intPtr(1), ErrNotAPlayer},
		{"stranger on a finished game", xWon, stranger, 2, 2, nil, ErrNotAPlayer},
		{"stale version on a waiting game", waiting, idX, 0, 0, intPtr(0), ErrVersionMismatch},
		{"stale version on a finished game", xWon, idO, 2, 2, intPtr(xWon.Version - 1), ErrVersionMismatch},
		{"stale version when it is not your turn", fresh, idO, 0, 0, intPtr(1), ErrVersionMismatch},
		{"not your turn on a finished game", xWon, idX, 2, 2, nil, ErrGameOver},
		{"occupied cell on a finished game", xWon, idO, 0, 0, nil, ErrGameOver},
		{"occupied cell when it is not your turn", oToMove, idX, 0, 0, nil, ErrNotYourTurn},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			g := tt.game
			move, err := g.Play(tt.player, tt.row, tt.col, tt.version)
			if !errors.Is(err, tt.want) {
				t.Errorf("Play error = %v, want %v", err, tt.want)
			}
			if move != (Move{}) {
				t.Errorf("Play returned move %+v, want the zero Move", move)
			}
			if g != tt.game {
				t.Errorf("rejected Play changed the game:\n got %+v\nwant %+v", g, tt.game)
			}
		})
	}
}

// TestPlayExpectedVersion checks the optimistic-concurrency guard: a move
// goes through only if expectedVersion is nil or matches the game's Version.
func TestPlayExpectedVersion(t *testing.T) {
	before := seated(t, StatusInProgress, "X........") // O to move
	current := before.Version

	tests := []struct {
		name    string
		version *int
		want    error
	}{
		{"nil skips the check", nil, nil},
		{"current version", intPtr(current), nil},
		{"stale version", intPtr(current - 1), ErrVersionMismatch},
		{"version from the future", intPtr(current + 1), ErrVersionMismatch},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			g := before
			_, err := g.Play(idO, 1, 1, tt.version)
			if !errors.Is(err, tt.want) {
				t.Fatalf("Play error = %v, want %v", err, tt.want)
			}
			want := before
			if tt.want == nil {
				want.Board = mustParse(t, "X...O....")
				want.Version = current + 1
			}
			if g != want {
				t.Errorf("after Play:\n got %+v\nwant %+v", g, want)
			}
		})
	}
}

// TestPlayUnknownStatus checks that a status Play does not recognize, which
// only corrupt data could produce, is an error rather than a playable game,
// and not one of the rule violations callers report to players.
func TestPlayUnknownStatus(t *testing.T) {
	before := seated(t, "paused", ".........")
	g := before
	_, err := g.Play(idX, 0, 0, nil)
	if err == nil {
		t.Fatal("Play accepted a move in a game with an unknown status")
	}
	ruleViolations := []error{
		ErrOutOfBounds, ErrNotAPlayer, ErrVersionMismatch, ErrGameNotStarted,
		ErrGameOver, ErrNotYourTurn, ErrCellOccupied, ErrOwnGame, ErrGameFull,
	}
	for _, target := range ruleViolations {
		if errors.Is(err, target) {
			t.Errorf("Play error %q is the rule violation %q", err, target)
		}
	}
	if !strings.Contains(err.Error(), "paused") {
		t.Errorf("Play error %q does not name the unknown status", err)
	}
	if g != before {
		t.Errorf("rejected Play changed the game:\n got %+v\nwant %+v", g, before)
	}
}

func TestJoin(t *testing.T) {
	g := waitingGame()
	if err := g.Join(idO); err != nil {
		t.Fatalf("Join: %v", err)
	}
	want := waitingGame()
	want.PlayerO = idO
	want.Status = StatusInProgress
	want.Version = 2
	if g != want {
		t.Errorf("after Join:\n got %+v\nwant %+v", g, want)
	}
}

// TestJoinLeavesGameUnchanged covers the joins that must not change the
// game: refused ones, and a retried join by the player already seated as O.
func TestJoinLeavesGameUnchanged(t *testing.T) {
	waiting := waitingGame()
	inProgress := seated(t, StatusInProgress, "X...O....")
	finished := seated(t, StatusXWon, "XXXOO....")
	// The schema forbids a waiting game with an O, but if one ever turned up,
	// Join must not hand the taken seat to someone else.
	waitingWithO := waitingGame()
	waitingWithO.PlayerO = idO

	tests := []struct {
		name   string
		game   Game
		player string
		want   error
	}{
		{"empty player ID", waiting, "", ErrNotAPlayer},
		{"X joins own waiting game", waiting, idX, ErrOwnGame},
		{"X joins own game in progress", inProgress, idX, ErrOwnGame},
		{"third player, game in progress", inProgress, stranger, ErrGameFull},
		{"third player, game over", finished, stranger, ErrGameFull},
		{"third player, waiting game whose O seat is taken", waitingWithO, stranger, ErrGameFull},
		{"O joins again, game in progress", inProgress, idO, nil},
		{"O joins again, game over", finished, idO, nil},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			g := tt.game
			if err := g.Join(tt.player); !errors.Is(err, tt.want) {
				t.Errorf("Join error = %v, want %v", err, tt.want)
			}
			if g != tt.game {
				t.Errorf("Join changed the game:\n got %+v\nwant %+v", g, tt.game)
			}
		})
	}
}

// everyBoard yields all 3^9 ways of filling the board, most of which no game
// can reach, so the board helpers are checked on every input they accept.
func everyBoard(yield func(Board) bool) {
	marks := [...]Mark{Empty, X, O}
	total := 1
	for range Cells {
		total *= len(marks)
	}
	for n := range total {
		// Read n in base 3, one digit per cell.
		var b Board
		digits := n
		for i := range b {
			b[i] = marks[digits%len(marks)]
			digits /= len(marks)
		}
		if !yield(b) {
			return
		}
	}
}

// TestWinsThrough checks winsThrough against the hand-written line table for
// every cell of every possible board, including boards no game can reach and
// empty cells, which Play never asks about.
func TestWinsThrough(t *testing.T) {
	for b := range everyBoard {
		for i, m := range b {
			want := false
			for _, l := range lines {
				if m != Empty && slices.Contains(l[:], i) && b[l[0]] == m && b[l[1]] == m && b[l[2]] == m {
					want = true
				}
			}
			if got := b.winsThrough(i/Size, i%Size); got != want {
				t.Fatalf("board %s: winsThrough(%d, %d) = %t, want %t", b, i/Size, i%Size, got, want)
			}
		}
	}
}

func TestParseBoardRoundTrip(t *testing.T) {
	n := 0
	for b := range everyBoard {
		s := b.String()
		got, err := ParseBoard(s)
		if err != nil || got != b {
			t.Fatalf("ParseBoard(%q) = %v, %v; want %v, nil", s, got, err, b)
		}
		n++
	}
	if n != 19_683 {
		t.Errorf("round-tripped %d boards, want all 3^9 = 19,683", n)
	}
}

func TestParseBoardRejects(t *testing.T) {
	for _, s := range []string{
		// Wrong length.
		"",
		"........",
		"..........",
		"X...O....\n",
		// Nine bytes, exactly one of which is not a mark, so each case
		// fails for one reason only.
		"x...O....", // marks are upper case
		"X...o....",
		"X...O...0",
		"X...O... ",
		"\x00...O....",
		"é.......", // é takes two bytes
	} {
		if b, err := ParseBoard(s); err == nil {
			t.Errorf("ParseBoard(%q) = %v, want an error", s, b)
		}
	}
}

func TestNewBoard(t *testing.T) {
	b := NewBoard()
	for i, m := range b {
		if m != Empty {
			t.Errorf("cell %d = %q, want Empty", i, byte(m))
		}
	}
	if got := b.String(); got != "........." {
		t.Errorf("String() = %q, want %q", got, ".........")
	}
	if got := b.Count(); got != 0 {
		t.Errorf("Count() = %d, want 0", got)
	}
}

// TestBoardAt pins the row-major layout the database and the API share.
func TestBoardAt(t *testing.T) {
	b := mustParse(t, "XO...XO..")
	want := [Size][Size]Mark{
		{X, O, Empty},
		{Empty, Empty, X},
		{O, Empty, Empty},
	}
	for row := range Size {
		for col := range Size {
			if got := b.At(row, col); got != want[row][col] {
				t.Errorf("At(%d, %d) = %q, want %q", row, col, byte(got), byte(want[row][col]))
			}
		}
	}
}

func TestBoardCount(t *testing.T) {
	tests := []struct {
		board string
		want  int
	}{
		{".........", 0},
		{"X........", 1},
		{"X...O....", 2},
		{"XXXOO....", 5},
		{"XOXXOOOXX", 9},
	}
	for _, tt := range tests {
		if got := mustParse(t, tt.board).Count(); got != tt.want {
			t.Errorf("ParseBoard(%q).Count() = %d, want %d", tt.board, got, tt.want)
		}
	}
}

func TestBoardNextMark(t *testing.T) {
	// Fill the board cell by cell, placing whichever mark is due each time.
	b := NewBoard()
	for n := range Cells {
		want := X
		if n%2 == 1 {
			want = O
		}
		if got := b.NextMark(); got != want {
			t.Errorf("with %d marks on %s: NextMark() = %v, want %v", n, b, got, want)
		}
		b[n] = want
	}
}

func TestMarkOf(t *testing.T) {
	inProgress := seated(t, StatusInProgress, ".........")
	waiting := waitingGame()

	tests := []struct {
		name   string
		game   Game
		player string
		want   Mark
	}{
		{"X", inProgress, idX, X},
		{"O", inProgress, idO, O},
		{"stranger", inProgress, stranger, Empty},
		{"empty player ID", inProgress, "", Empty},
		{"X while waiting", waiting, idX, X},
		// Seat O is "" while waiting, and an empty ID must not match it.
		{"empty player ID while seat O is empty", waiting, "", Empty},
	}
	for _, tt := range tests {
		if got := tt.game.MarkOf(tt.player); got != tt.want {
			t.Errorf("%s: MarkOf(%q) = %q, want %q", tt.name, tt.player, byte(got), byte(tt.want))
		}
	}
}

func TestNextTurn(t *testing.T) {
	tests := []struct {
		name string
		game Game
		want Mark
	}{
		{"waiting", waitingGame(), Empty},
		{"X to move", seated(t, StatusInProgress, "........."), X},
		{"O to move", seated(t, StatusInProgress, "X........"), O},
		{"X won", seated(t, StatusXWon, "XXXOO...."), Empty},
		{"O won", seated(t, StatusOWon, "XX.OOOX.."), Empty},
		{"draw", seated(t, StatusDraw, "XOXXOOOXX"), Empty},
		{"unknown status", seated(t, "paused", "X........"), Empty},
	}
	for _, tt := range tests {
		if got := tt.game.NextTurn(); got != tt.want {
			t.Errorf("%s: NextTurn() = %q, want %q", tt.name, byte(got), byte(tt.want))
		}
	}
}

func TestWinner(t *testing.T) {
	tests := []struct {
		status Status
		want   Mark
	}{
		{StatusWaiting, Empty},
		{StatusInProgress, Empty},
		{StatusXWon, X},
		{StatusOWon, O},
		{StatusDraw, Empty},
	}
	for _, tt := range tests {
		g := Game{Status: tt.status}
		if got := g.Winner(); got != tt.want {
			t.Errorf("Winner() with status %s = %q, want %q", tt.status, byte(got), byte(tt.want))
		}
	}
}

func TestStatusValidAndOver(t *testing.T) {
	// Literal strings rather than the constants, so this also pins the values
	// the database CHECK constraint and API clients depend on.
	tests := []struct {
		status      Status
		valid, over bool
	}{
		{"waiting", true, false},
		{"in_progress", true, false},
		{"x_won", true, true},
		{"o_won", true, true},
		{"draw", true, true},
		{"", false, false},
		{"X_WON", false, false},
		{"won", false, false},
	}
	for _, tt := range tests {
		if got := tt.status.Valid(); got != tt.valid {
			t.Errorf("Status(%q).Valid() = %t, want %t", tt.status, got, tt.valid)
		}
		if got := tt.status.Over(); got != tt.over {
			t.Errorf("Status(%q).Over() = %t, want %t", tt.status, got, tt.over)
		}
	}
}

func TestMarkString(t *testing.T) {
	tests := []struct {
		mark Mark
		want string
	}{
		{X, "X"},
		{O, "O"},
		{Empty, ""},
		{Mark(0), ""},
		{Mark('x'), ""},
	}
	for _, tt := range tests {
		if got := tt.mark.String(); got != tt.want {
			t.Errorf("Mark(%q).String() = %q, want %q", byte(tt.mark), got, tt.want)
		}
	}
}

func TestInBounds(t *testing.T) {
	for row := range Size {
		for col := range Size {
			if !InBounds(row, col) {
				t.Errorf("InBounds(%d, %d) = false, want true", row, col)
			}
		}
	}
	for _, c := range []cell{
		{-1, 0}, {0, -1}, {3, 0}, {0, 3}, {-1, -1}, {3, 3}, {-1, 2}, {2, 3},
		{math.MinInt, 0}, {0, math.MaxInt},
	} {
		if InBounds(c.row, c.col) {
			t.Errorf("InBounds(%d, %d) = true, want false", c.row, c.col)
		}
	}
}
