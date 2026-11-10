# Tic-tac-toe service (MVP)

A small REST API for two-player tic-tac-toe, written in Go and backed by
PostgreSQL. Players register and log in, one player creates a game, a second
player joins it, and they take turns until someone wins or the board fills.

The MVP focuses on four things:

1. **Creating games:** create a game, then a second player joins it.
2. **Detecting the winner:** the server decides every result.
3. **Preventing conflicting moves:** simultaneous or out-of-turn moves can't corrupt a game.
4. **Statelessness:** any number of server copies can run against one database.

## Quick start

You need Go 1.24+ and either Docker or a local PostgreSQL 13+.

```bash
make db    # start PostgreSQL 16 in Docker (docker-compose.yml)
make run   # start the API on :8080; migrations run on startup
```

Without `make`:

```bash
export DATABASE_URL='postgres://tictactoe:tictactoe@localhost:5432/tictactoe?sslmode=disable'
export JWT_SECRET='dev-only-secret-change-me-0123456789abcdef'
go run ./cmd/server
```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `DATABASE_URL` | yes | – | PostgreSQL connection URL |
| `JWT_SECRET` | yes | – | HMAC key for signing tokens, at least 32 bytes; every server copy must share it |
| `PORT` | no | `8080` | Listen port |
| `TOKEN_TTL` | no | `24h` | How long a login token stays valid (Go duration) |

## Play a game with curl

The examples use `curl --json` (curl 7.82 or newer) and `jq`.

```bash
BASE=http://localhost:8080

# Register two players.
curl -s --json '{"username":"alice","password":"alice-password"}' $BASE/v1/auth/register
curl -s --json '{"username":"bob","password":"bob-password"}' $BASE/v1/auth/register

# Log in and keep the tokens.
ALICE=$(curl -s --json '{"username":"alice","password":"alice-password"}' $BASE/v1/auth/login | jq -r .token)
BOB=$(curl -s --json '{"username":"bob","password":"bob-password"}' $BASE/v1/auth/login | jq -r .token)

# Alice creates a game and plays X; Bob joins and plays O.
GAME=$(curl -s -X POST -H "Authorization: Bearer $ALICE" $BASE/v1/games | jq -r .id)
curl -s -X POST -H "Authorization: Bearer $BOB" $BASE/v1/games/$GAME/join | jq

# Take turns. X always moves first.
curl -s -H "Authorization: Bearer $ALICE" --json '{"row":0,"col":0}' $BASE/v1/games/$GAME/moves | jq .game.board
curl -s -H "Authorization: Bearer $BOB"   --json '{"row":1,"col":1}' $BASE/v1/games/$GAME/moves | jq .game.board
curl -s -H "Authorization: Bearer $ALICE" --json '{"row":0,"col":1}' $BASE/v1/games/$GAME/moves | jq .game.board
curl -s -H "Authorization: Bearer $BOB"   --json '{"row":2,"col":2}' $BASE/v1/games/$GAME/moves | jq .game.board
curl -s -H "Authorization: Bearer $ALICE" --json '{"row":0,"col":2}' $BASE/v1/games/$GAME/moves | jq .game.status   # "x_won"

# Read the game and its move history.
curl -s -H "Authorization: Bearer $BOB" $BASE/v1/games/$GAME | jq
curl -s -H "Authorization: Bearer $BOB" $BASE/v1/games/$GAME/moves | jq
```

## API

Every request and response body is JSON. Game routes need an
`Authorization: Bearer <token>` header from `/v1/auth/login`.

| Method | Path | Auth | Purpose | Success |
|---|---|---|---|---|
| POST | `/v1/auth/register` | – | Create a player: `{"username","password"}` | 201 `{"id","username"}` |
| POST | `/v1/auth/login` | – | Get a token: `{"username","password"}` | 200 `{"token","token_type","expires_at","user"}` |
| POST | `/v1/games` | ✓ | Create a game; the caller plays X | 201 game (and a `Location` header) |
| GET | `/v1/games/{id}` | ✓ | Read a game (any logged-in player) | 200 game |
| POST | `/v1/games/{id}/join` | ✓ | Take seat O; the game starts | 200 game |
| POST | `/v1/games/{id}/moves` | ✓ | Play `{"row","col"}` (0–2), optionally with `"expected_version"` | 201 `{"move","game"}` |
| GET | `/v1/games/{id}/moves` | ✓ | Move history, in order | 200 `{"moves":[…]}` |
| GET | `/healthz` | – | Liveness plus a database ping | 200 / 503 |

A game looks like this:

```json
{
  "id": "6f1c2d1e-8a4b-4c1e-9a55-2f0d9a7c3b10",
  "status": "in_progress",
  "board": [["X", "", ""], ["", "O", ""], ["", "", ""]],
  "players": {
    "X": {"id": "…", "username": "alice"},
    "O": {"id": "…", "username": "bob"}
  },
  "next_turn": "X",
  "winner": null,
  "version": 4,
  "created_at": "2026-11-10T22:00:00Z",
  "updated_at": "2026-11-10T22:01:30Z"
}
```

- `status` is one of `waiting`, `in_progress`, `x_won`, `o_won` or `draw`.
- `next_turn` is `null` unless the game is in progress.
- `winner` is `"X"`, `"O"` or `null`.
- `version` goes up by one on every join and every move.

Errors look like `{"error": {"code": "NOT_YOUR_TURN", "message": "it is not your turn"}}`:

| Status | Codes |
|---|---|
| 400 | `INVALID_JSON`, `INVALID_REQUEST`, `INVALID_USERNAME`, `INVALID_PASSWORD`, `OUT_OF_BOUNDS` |
| 401 | `UNAUTHORIZED`: missing, invalid or expired token, or a token whose user no longer exists. `INVALID_CREDENTIALS`: failed login |
| 403 | `NOT_A_PLAYER`: you're not seated in this game |
| 404 | `NOT_FOUND`: no such game or endpoint |
| 405 | `METHOD_NOT_ALLOWED`, with an `Allow` header |
| 409 | `NOT_YOUR_TURN`, `CELL_OCCUPIED`, `GAME_NOT_IN_PROGRESS`, `VERSION_MISMATCH`, `GAME_FULL`, `CANNOT_JOIN_OWN_GAME`, `USERNAME_TAKEN`, `CONFLICT` |
| 413 | `BODY_TOO_LARGE` |
| 500 | `INTERNAL`: details go to the server log, never to the client |

## How it works

### Creating a game

`POST /v1/games` creates a `waiting` game with the caller as X.
`POST /v1/games/{id}/join` seats the caller as O with one conditional update:

```sql
UPDATE games SET player_o_id = $2, status = 'in_progress', ...
WHERE id = $1 AND status = 'waiting' AND player_o_id IS NULL AND player_x_id <> $2
```

If several players try to join at the same moment, exactly one of them gets the
seat; the rest get `409 GAME_FULL`. Joining your own game is rejected, and
joining again as the current O is a harmless no-op.

### Detecting the winner

The rules live in `internal/game`, a pure package with no database or HTTP
code. After each move it checks only the lines through the cell just played:
its row, its column, and a diagonal if the cell is on one. Only those lines can
have changed. A full board with no line is a draw, and a win on the ninth move
counts as a win. A test plays out every one of the 255,168 possible games and
checks each position against an independent full-board scan.

### Preventing conflicting moves

There are three layers, all enforced by PostgreSQL, so they hold however many
server copies are running:

1. **One move at a time per game.** A move is a single transaction that starts
   with `SELECT … FROM games WHERE id = $1 FOR UPDATE`. Moves on the same game
   wait for each other, and each one sees the previous one's result.
2. **Rule checks while holding the lock:**
   - the caller is seated in this game
   - the game is in progress
   - it's the caller's turn (derived from the board, so it can't drift)
   - the cell is on the board and empty

   A client can also send `expected_version`. If the game has changed since
   that version, the move is rejected, which makes blind retries safe.
3. **Database constraints as a safety net.** These hold even if application
   code had a bug:
   - `moves` has `PRIMARY KEY (game_id, move_number)`, so there is one move per turn.
   - `moves` has `UNIQUE (game_id, row, col)`, so each cell is taken once.
   - A `CHECK` makes X play the odd-numbered moves and O the even ones.
   - `games` has `CHECK`s on the board format and on status.

The player making a move is always taken from their token, never from the
request body, so nobody can move for their opponent.

### Stateless servers

- **No sessions.** Login returns an HS256-signed JWT. Any server copy with the
  same `JWT_SECRET` can verify it, and only HS256-signed tokens are accepted.
- **No game state in memory.** Every request reads and writes PostgreSQL, the
  single source of truth. Concurrency is enforced by the database, not by Go
  locks, so requests can go to any copy and a restart loses nothing.
- **Safe concurrent startup.** Migrations run inside a transaction-scoped
  advisory lock, so several copies can start at once.

A test runs two server instances, each with its own memory and connection pool,
against one database. It plays a full game by alternating requests between
them and races moves across both.

### Authentication

- Players are stored in `users` with bcrypt password hashes.
- Usernames are case-insensitive: 3–32 characters of `a-z`, `0-9` and `_`.
- Passwords are 8–72 bytes.
- A failed login gives the same response whether the username or the password
  was wrong.
- Tokens can't be revoked before they expire, so the MVP has no real logout.

## Data model

```
users  (id, username UNIQUE, password_hash, created_at)
games  (id, player_x_id, player_o_id NULL, board 'X...O....', status, version, created_at, updated_at)
moves  (game_id, move_number, player_id, symbol, row, col, created_at)
        PRIMARY KEY (game_id, move_number), UNIQUE (game_id, row, col)
```

`games` holds each game's current state, so reading a game is a single row.
`moves` is the full history, and it only ever grows. Each move writes both in
the same transaction. The schema is in
`internal/store/migrations/0001_init.sql`.

## Tests

```bash
make db
make test   # go test -race ./... against TEST_DATABASE_URL
```

Each database test gets its own throwaway schema. Tests that need PostgreSQL
are skipped if `TEST_DATABASE_URL` isn't set. The suite covers:

- **Rules:** every possible game, every invalid move, and the order in which rule errors are reported.
- **Auth:** password hashing, plus expired, tampered, wrong-algorithm and `alg: none` tokens.
- **Store and HTTP:** full games, every error response, and the database constraints.
- **Concurrency:** 20 simultaneous moves for one turn give exactly one success; 10 simultaneous joins give exactly one seat.
- **Statelessness:** the two-instance test described above.

## Layout

```
cmd/server/        main: config from env, migrations, HTTP server, graceful shutdown
internal/game/     rules and winner detection (pure, no I/O)
internal/auth/     bcrypt password hashing, JWT issue and verify
internal/store/    PostgreSQL queries and transactions, embedded SQL migrations
internal/api/      HTTP handlers, auth middleware, error mapping
internal/testdb/   per-test PostgreSQL schemas for tests
```

## Not in the MVP yet

- **In-memory read cache:** it will sit in front of `GET /v1/games/{id}` behind
  an interface, so Redis can replace it once several copies run. Memory will
  only ever be a cache, never the source of truth.
- **Infrastructure:** API gateway, load balancer, rate limiting and TLS.
- **Real-time updates:** clients poll `GET /v1/games/{id}`.
- **Lobby:** there's no listing of open games; players share the game ID.
- **Accounts:** logout and refresh tokens.
- **Gameplay extras:** turn timers, forfeits, rematches and leaderboards.
