package api_test

import (
	"bytes"
	"fmt"
	"net/http"
	"testing"
)

// wantOneWinner checks that exactly one of responses has status win and that
// every other is a 409 with one of the loseCodes. It returns the winner's index.
func wantOneWinner(t *testing.T, responses []response, win int, loseCodes ...string) int {
	t.Helper()
	winner := -1
	for i, res := range responses {
		switch res.status {
		case win:
			if winner >= 0 {
				t.Errorf("requests %d and %d both got %d", winner, i, win)
			}
			winner = i
		case http.StatusConflict:
			code := errorCode(t, res)
			ok := false
			for _, c := range loseCodes {
				ok = ok || code == c
			}
			if !ok {
				t.Errorf("request %d: 409 %s, want one of %v", i, code, loseCodes)
			}
		default:
			t.Errorf("request %d: status %d; body: %s", i, res.status, res.body)
		}
	}
	if winner < 0 {
		t.Fatalf("no request got %d", win)
	}
	return winner
}

func TestConcurrentMovesOnlyOneWins(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	alice, bob := c.signUp(t, "alice"), c.signUp(t, "bob")
	id := c.createGame(t, alice).ID
	c.join(t, bob, id)

	// It is X's turn and X tries 20 moves at once, some of them for the
	// same cell.
	const n = 20
	c.warmUp(t, n)
	responses := concurrently(t, n, func(i int) (response, error) {
		return c.send(http.MethodPost, "/v1/games/"+id+"/moves", bearer(alice.token), moveAt(i%3, i/3%3))
	})
	wantOneWinner(t, responses, http.StatusCreated, "NOT_YOUR_TURN", "CELL_OCCUPIED")

	if moves := c.moves(t, bob, id); len(moves) != 1 {
		t.Errorf("got %d moves, want 1: %+v", len(moves), moves)
	}
	if g := c.game(t, bob, id); g.Version != 3 || orNull(g.NextTurn) != "O" {
		t.Errorf("game: version %d, next_turn %s; want 3, O", g.Version, orNull(g.NextTurn))
	}
}

func TestConcurrentJoinsOnlyOneWins(t *testing.T) {
	t.Parallel()
	c := newServer(t)
	owner := c.signUp(t, "owner")
	id := c.createGame(t, owner).ID
	const n = 10
	joiners := make([]player, n)
	for i := range joiners {
		joiners[i] = c.signUp(t, fmt.Sprintf("joiner_%d", i))
	}

	c.warmUp(t, n)
	responses := concurrently(t, n, func(i int) (response, error) {
		return c.send(http.MethodPost, "/v1/games/"+id+"/join", bearer(joiners[i].token), nil)
	})
	winner := joiners[wantOneWinner(t, responses, http.StatusOK, "GAME_FULL")]

	g := c.game(t, owner, id)
	wantUser(t, "players.O", g.Players.O, winner)
	if g.Status != "in_progress" || g.Version != 2 {
		t.Errorf("game: status %s, version %d; want in_progress, 2", g.Status, g.Version)
	}
}

// TestInstancesShareOnlyTheDatabase plays a game across two API instances,
// each with its own connection pool, store and token verifier, as separate
// server processes would be.
func TestInstancesShareOnlyTheDatabase(t *testing.T) {
	t.Parallel()
	db := newDB(t)
	a := startServer(t, db.Pool)
	b := startServer(t, db.NewPool(t))

	// Accounts and tokens work on either instance.
	a.register(t, "alice")
	alice := b.login(t, "alice")
	b.register(t, "bob")
	bob := a.login(t, "bob")

	id := a.createGame(t, alice).ID
	b.join(t, bob, id)

	// Alternate instances move by move until X completes the diagonal.
	instances := []*client{a, b}
	for i, m := range []struct {
		p        player
		row, col int
	}{
		{alice, 0, 0}, {bob, 0, 1}, {alice, 1, 1}, {bob, 0, 2}, {alice, 2, 2},
	} {
		instances[i%2].move(t, m.p, id, m.row, m.col)
	}

	// Both instances report the same final game and history.
	gameA := a.do(t, http.MethodGet, "/v1/games/"+id, bob.token, nil)
	gameB := b.do(t, http.MethodGet, "/v1/games/"+id, alice.token, nil)
	if g := decode[gameView](t, gameA, http.StatusOK); g.Status != "x_won" || board(t, g) != "XOO/.X./..X" {
		t.Errorf("final game: status %s, board %s; want x_won, XOO/.X./..X", g.Status, board(t, g))
	}
	if !bytes.Equal(gameA.body, gameB.body) {
		t.Errorf("instances disagree on the game:\nA: %s\nB: %s", gameA.body, gameB.body)
	}
	movesA := a.do(t, http.MethodGet, "/v1/games/"+id+"/moves", alice.token, nil)
	movesB := b.do(t, http.MethodGet, "/v1/games/"+id+"/moves", bob.token, nil)
	if n := len(decode[movesView](t, movesA, http.StatusOK).Moves); n != 5 {
		t.Errorf("got %d moves, want 5", n)
	}
	if !bytes.Equal(movesA.body, movesB.body) {
		t.Errorf("instances disagree on the moves:\nA: %s\nB: %s", movesA.body, movesB.body)
	}
}

// TestInstancesRaceForTheSameTurn sends the same player's move for one turn
// to two instances at once: the database must accept exactly one of them.
func TestInstancesRaceForTheSameTurn(t *testing.T) {
	t.Parallel()
	db := newDB(t)
	a := startServer(t, db.Pool)
	b := startServer(t, db.NewPool(t))
	alice, bob := a.signUp(t, "alice"), b.signUp(t, "bob")
	id := a.createGame(t, alice).ID
	b.join(t, bob, id)

	// Nobody can win within four moves, so every round races for a turn in
	// a game that is still in progress.
	instances := []*client{a, b}
	const rounds = 4
	for round := range rounds {
		p := []player{alice, bob}[round%2]
		free := freeCells(a.game(t, p, id))
		responses := concurrently(t, len(instances), func(i int) (response, error) {
			return instances[i].send(http.MethodPost, "/v1/games/"+id+"/moves", bearer(p.token), free[i])
		})
		wantOneWinner(t, responses, http.StatusCreated, "NOT_YOUR_TURN", "CELL_OCCUPIED")
	}

	for name, c := range map[string]*client{"A": a, "B": b} {
		if moves := c.moves(t, alice, id); len(moves) != rounds {
			t.Errorf("instance %s lists %d moves, want %d", name, len(moves), rounds)
		}
		if g := c.game(t, bob, id); g.Version != 2+rounds {
			t.Errorf("instance %s: version %d, want %d", name, g.Version, 2+rounds)
		}
	}
}

// freeCells returns move bodies for g's empty cells, in row-major order.
func freeCells(g gameView) []map[string]int {
	var free []map[string]int
	for row, cells := range g.Board {
		for col, mark := range cells {
			if mark == "" {
				free = append(free, moveAt(row, col))
			}
		}
	}
	return free
}
