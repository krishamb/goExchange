-- Players, games and moves.
--
-- games holds each game's current state (one-row reads); moves is the
-- append-only history. Both are written in the same transaction. The
-- constraints below are a backstop: even if application code had a bug, the
-- database refuses two moves for one turn, two marks in one cell, or a move
-- by the wrong symbol.

CREATE TABLE users (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT        NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_]{3,32}$'),
    password_hash TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE games (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    player_x_id UUID        NOT NULL REFERENCES users (id),
    player_o_id UUID        REFERENCES users (id),
    -- 9 cells, row-major: 'X', 'O' or '.' for empty.
    board       TEXT        NOT NULL DEFAULT '.........' CHECK (board ~ '^[XO.]{9}$'),
    status      TEXT        NOT NULL DEFAULT 'waiting'
                            CHECK (status IN ('waiting', 'in_progress', 'x_won', 'o_won', 'draw')),
    -- 1 at creation; +1 on join and on every move.
    version     INTEGER     NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT games_players_differ CHECK (player_o_id <> player_x_id),
    CONSTRAINT games_waiting_iff_no_opponent CHECK ((status = 'waiting') = (player_o_id IS NULL))
);

CREATE TABLE moves (
    game_id     UUID        NOT NULL REFERENCES games (id) ON DELETE CASCADE,
    move_number SMALLINT    NOT NULL CHECK (move_number BETWEEN 1 AND 9),
    player_id   UUID        NOT NULL REFERENCES users (id),
    symbol      TEXT        NOT NULL CHECK (symbol IN ('X', 'O')),
    row         SMALLINT    NOT NULL CHECK (row BETWEEN 0 AND 2),
    col         SMALLINT    NOT NULL CHECK (col BETWEEN 0 AND 2),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One move per turn.
    CONSTRAINT moves_pkey PRIMARY KEY (game_id, move_number),
    -- Each cell can be taken once per game.
    CONSTRAINT moves_one_mark_per_cell UNIQUE (game_id, row, col),
    -- X plays the odd-numbered moves, O the even ones.
    CONSTRAINT moves_symbol_matches_turn
        CHECK (symbol = CASE WHEN move_number % 2 = 1 THEN 'X' ELSE 'O' END)
);
