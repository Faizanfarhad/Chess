# Chess Web Application

An authenticated, server-authoritative chess application built with FastAPI, PostgreSQL, WebSockets, vanilla JavaScript, and a bundled Stockfish engine.

The browser renders the board and provides fast move highlights. The backend owns the official board, validates every move, controls clocks, persists games, and broadcasts accepted state to connected players.

For the complete implementation architecture and Mermaid diagrams, read [architecture.md](architecture.md).

## Features currently implemented

- Username/password registration and login.
- PostgreSQL storage for users, sessions, saved games, and ranked matchmaking.
- Human room creation with a six-character room ID.
- A waiting room: the first human player waits until the second player joins.
- Authenticated WebSocket game connections.
- Server-assigned white and black colors.
- Server-authoritative move validation.
- Pawn, knight, bishop, rook, queen, and king movement.
- Captures and king-safety validation.
- Castling, en passant, and promotion to queen, rook, bishop, or knight.
- Check, checkmate, stalemate, and game-over handling.
- Threefold repetition, fifty-move, and insufficient-material draw detection.
- Draw offers, resignation, undo, and reset.
- Server-side clocks: 2, 3, 5, 10, and 15 minutes.
- Timeout results.
- Human-versus-Stockfish mode.
- Ranked matchmaking with a simple Elo update after a decisive ranked game.
- Result overlay with winner/draw status and captured-material points.

## Project structure

```text
chess/
├── backend/
│   ├── main.py          FastAPI routes, WebSockets, rooms, clocks, AI orchestration
│   ├── game.py          Server-authoritative chess rules and serializable game state
│   ├── database.py      PostgreSQL queries, authentication, sessions, saved games
│   ├── stockfish.py     UCI adapter for the bundled Stockfish process
│   └── test_game.py     Unit tests for the chess rules
├── frontend/
│   ├── index.html       Board and game-panel markup
│   ├── app.js           Rendering, click handling, WebSocket client, UI state
│   └── styles.css       Layout, board, result, promotion, and responsive styles
├── engine/stockfish/    Local Stockfish executable and source tree when available
├── requirements.txt     Python dependencies
├── .env.example         Environment-variable example
└── architecture.md      Detailed architecture and Mermaid diagrams
```

## Requirements

- Python 3.10 or newer.
- PostgreSQL.
- A runnable Stockfish executable at `engine/stockfish/stockfish` for AI mode.
- A shell that can provide environment variables.

The Stockfish directory is ignored by Git in this project. A fresh checkout therefore needs the executable copied or built locally before AI mode can work.

## Setup

Create a PostgreSQL database and user, then configure the connection string. URL-encode special characters in the password. For example, a password containing `@` must use `%40` in the URL:

```bash
export DATABASE_URL="postgresql://chess_user:change_me@localhost:5432/chess"
```

Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The application creates its required tables during FastAPI startup through `database.init_database()`. It does not currently use a migration tool.

Optional Stockfish search time:

```bash
export STOCKFISH_MOVE_TIME_MS=5000
```

If the variable is not set, the adapter uses a 3-second search time. The checked-in `.env.example` currently shows 2 seconds, which takes precedence when that value is loaded into the environment.

## Run the application

From the project root:

```bash
uvicorn backend.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/
```

Register or log in before creating a room, joining a room, starting an AI game, or entering ranked matchmaking.

## How to play

1. Register or log in.
2. Select a clock.
3. Choose one of the modes:
   - `Create room`: create a human room and share its room code.
   - `Join`: connect to an existing human room.
   - `Play AI`: create a room where the logged-in user is White and Stockfish is Black.
   - `Ranked match`: enter the PostgreSQL-backed matchmaking queue.
4. Click a piece, then click a destination square.
5. If a pawn reaches the final rank, choose a promotion piece from the visual picker.

The browser sends a move request containing the source square, destination square, promotion choice when needed, and the current state version. It does not send a complete board as the authority.

## API and WebSocket surface

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/register` | Create an account and return a session token |
| `POST` | `/auth/login` | Authenticate and return a session token |
| `GET` | `/auth/me` | Return the authenticated user |
| `POST` | `/rooms` | Create a human or AI room |
| `POST` | `/matchmaking/join` | Join ranked matchmaking |
| `GET` | `/matchmaking/status` | Read matchmaking status |
| `POST` | `/matchmaking/leave` | Leave the matchmaking queue |
| `WebSocket` | `/ws/game/{game_id}?token=...` | Join a game and exchange game messages |

WebSocket action messages include `move`, `undo`, `reset`, `resign`, `offer_draw`, and `answer_draw`. Server messages include `player_color`, `waiting`, `game_started`, `game_state`, `clock_update`, `ai_thinking`, `ai_warning`, `ai_error`, `request_rejected`, and `player_left`.

## Run tests

```bash
python -m unittest backend.test_game
python -m py_compile backend/*.py
node --check frontend/app.js
```

The current rule test suite covers opening pawn movement, turn ownership, stale versions, checkmate, undo, castling, en passant, promotion, insufficient-material draw, and stale checkmate repair.

## Important implementation boundaries

- `backend/game.py` is the final authority for legal moves and game status.
- The frontend's legal-move code is for highlights and interaction feedback; it is not a security boundary.
- Live sockets, rooms, and in-memory `GameState` objects are process-local. PostgreSQL restores saved games after a restart, but a multi-process deployment would need shared room coordination.
- Stockfish runs as a subprocess. If it fails, the backend currently plays the first legal fallback move and sends an AI warning.
- User passwords are stored as PBKDF2 hashes with per-user salts; raw passwords are not stored.
- The project has no database migration history, automated browser tests, spectator mode, chat, rematch endpoint, or production deployment configuration yet.

