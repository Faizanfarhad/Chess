"""FastAPI backend for authenticated, server-authoritative chess games."""

import asyncio
from pathlib import Path
import secrets

from fastapi import Body, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from backend import database
from backend.game import GameError, GameState
from backend.stockfish import best_move
from config import * 



VALID_CLOCKS = {2, 3, 5, 10, 15}

app = FastAPI(title="Chess")

# Live sockets are kept in memory. Games themselves are persisted in PostgreSQL.
rooms: dict[str, set[WebSocket]] = {}
games: dict[str, GameState] = {}
room_meta: dict[str, dict] = {}
player_info: dict[str, dict[WebSocket, dict]] = {}
room_state_locks: dict[str, asyncio.Lock] = {}
ai_rooms_running: set[str] = set()
clock_task: asyncio.Task | None = None


def _token_from_header(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _require_user(authorization: str | None) -> dict:
    user = database.get_user_by_token(_token_from_header(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Log in before using this feature.")
    return user


def _validate_clock(value) -> int:
    try:
        clock = int(value)
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="Choose a 2, 3, 5, 10, or 15 minute clock.") from error
    if clock not in VALID_CLOCKS:
        raise HTTPException(status_code=400, detail="Choose a 2, 3, 5, 10, or 15 minute clock.")
    return clock


def _new_room_id() -> str:
    while True:
        room_id = secrets.token_hex(3).upper()
        if room_id not in games and not database.load_game(room_id):
            return room_id


def _ensure_loaded(room_id: str) -> bool:
    if room_id in games:
        return True
    saved = database.load_game(room_id)
    if not saved:
        return False
    games[room_id] = GameState.from_dict(saved["state"])
    room_state_locks.setdefault(room_id, asyncio.Lock())
    room_meta[room_id] = {
        "mode": saved["mode"],
        "time_control": saved["time_control"],
        "white_user_id": saved["white_user_id"],
        "black_user_id": saved["black_user_id"],
    }
    return True


def _persist(room_id: str) -> None:
    metadata = room_meta[room_id]
    game = games[room_id]
    database.save_game(
        room_id,
        metadata["mode"],
        metadata["time_control"],
        game.to_dict(),
        metadata.get("white_user_id"),
        metadata.get("black_user_id"),
    )


def _player_names(room_id: str) -> dict[str, str]:
    """Build the backwards-compatible public color-to-name map."""

    return {
        color: profile["username"]
        for color, profile in _player_profiles(room_id).items()
    }


def _player_profiles(room_id: str) -> dict[str, dict]:
    """Build public player profiles without exposing account credentials."""

    metadata = room_meta[room_id]
    profiles = {"b": {"username": "AI", "rating": None}} if metadata["mode"] == "ai" else {}

    # Read the current database rating so a finished ranked game shows the
    # post-game rating, not the rating from when the socket was opened.
    for color, user_id in (
        ("w", metadata.get("white_user_id")),
        ("b", metadata.get("black_user_id")),
    ):
        if color == "b" and metadata["mode"] == "ai":
            continue
        if user_id is not None:
            user = database.get_user_by_id(user_id)
            if user:
                profiles[color] = {"username": user["username"], "rating": user["rating"]}

    # Fall back to the active socket while a newly created room is being
    # persisted or if the account lookup is temporarily unavailable.
    for info in player_info.get(room_id, {}).values():
        profiles.setdefault(info["color"], {
            "username": info["username"],
            "rating": info.get("rating"),
        })

    return profiles


async def broadcast(room_id: str, message: dict) -> None:
    for player in rooms.get(room_id, set()).copy():
        try:
            await player.send_json(message)
        except Exception:
            rooms.get(room_id, set()).discard(player)


async def broadcast_game_state(room_id: str) -> None:
    if room_id not in games:
        return
    lock = room_state_locks.setdefault(room_id, asyncio.Lock())
    async with lock:
        game = games[room_id]
        state = game.public_state()
        if game.status in {"checkmate", "timeout", "resignation"} and room_meta[room_id]["mode"] == "ranked":
            rating_changes = database.record_ranked_result(room_id, game.winner)
            if rating_changes:
                game.rating_changes = rating_changes
        state = game.public_state()
        state["players"] = _player_names(room_id)
        state["playerProfiles"] = _player_profiles(room_id)
        _persist(room_id)
        state["aiThinking"] = room_meta[room_id]["mode"] == "ai" and game.current_turn == "b" and not state["gameOver"]
        await broadcast(room_id, {
            "type": "game_state",
            "game_id": room_id,
            "state": state,
        })


@app.on_event("startup")
async def startup() -> None:
    global clock_task
    database.init_database()
    clock_task = asyncio.create_task(clock_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    if clock_task:
        clock_task.cancel()


async def clock_loop() -> None:
    """Broadcast ticking clocks and persist a timeout without trusting the browser."""

    while True:
        await asyncio.sleep(1)
        for room_id, game in list(games.items()):
            if not game.clock_running:
                continue
            before = game.status
            state = game.public_state()
            _persist(room_id)
            if not rooms.get(room_id):
                continue
            if before != game.status:
                await broadcast_game_state(room_id)
            else:
                # Clock ticks are deliberately separate from board snapshots.
                # They must never clear a selected piece or redraw the board.
                await broadcast(room_id, {
                    "type": "clock_update",
                    "version": game.version,
                    "currentTurn": game.current_turn,
                    "clocks": state["clocks"],
                })


@app.post("/auth/register")
async def register(body: dict = Body(...)) -> dict:
    try:
        user = database.create_user(str(body.get("username", "")), str(body.get("password", "")))
        token = database.create_session(user["id"])
        return {"token": token, "user": user}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/auth/login")
async def login(body: dict = Body(...)) -> dict:
    user = database.authenticate_user(str(body.get("username", "")), str(body.get("password", "")))
    if not user:
        raise HTTPException(status_code=401, detail="Username or password is incorrect.")
    return {"token": database.create_session(user["id"]), "user": user}


@app.get("/auth/me")
async def current_user(authorization: str | None = Header(default=None)) -> dict:
    return _require_user(authorization)


@app.post("/rooms")
async def create_room(body: dict = Body(default={}), authorization: str | None = Header(default=None)) -> dict:
    user = _require_user(authorization)
    mode = body.get("mode", "human")
    if mode not in {"human", "ai"}:
        raise HTTPException(status_code=400, detail="Mode must be human or ai.")
    time_control = _validate_clock(body.get("time_control", 10))
    room_id = _new_room_id()
    games[room_id] = GameState(time_control)
    room_state_locks[room_id] = asyncio.Lock()
    room_meta[room_id] = {
        "mode": mode,
        "time_control": time_control,
        "white_user_id": user["id"],
        "black_user_id": None,
    }
    _persist(room_id)
    return {"game_id": room_id, "mode": mode, "time_control": time_control}


@app.post("/matchmaking/join")
async def join_matchmaking(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    user = _require_user(authorization)
    time_control = _validate_clock(body.get("time_control", 10))
    match = database.find_match(user, time_control)
    if match:
        room_id = _new_room_id()
        games[room_id] = GameState(time_control)
        # The player who completes the match receives White; the queued player gets Black.
        room_meta[room_id] = {
            "mode": "ranked",
            "time_control": time_control,
            "white_user_id": user["id"],
            "black_user_id": match["user_id"],
        }
        _persist(room_id)
        database.mark_match(user["id"], room_id)
        database.mark_match(match["user_id"], room_id)
        return {"status": "matched", "game_id": room_id}

    database.enqueue_match(user, time_control)
    return {"status": "waiting", "time_control": time_control}


@app.get("/matchmaking/status")
async def matchmaking_status(authorization: str | None = Header(default=None)) -> dict:
    user = _require_user(authorization)
    row = database.matchmaking_status(user["id"])
    if not row:
        return {"status": "idle"}
    if row["matched_game_id"]:
        return {"status": "matched", "game_id": row["matched_game_id"]}
    return {"status": "waiting", "time_control": row["time_control"]}


@app.post("/matchmaking/leave")
async def leave_matchmaking(authorization: str | None = Header(default=None)) -> dict:
    user = _require_user(authorization)
    database.leave_matchmaking(user["id"])
    return {"status": "idle"}


async def run_ai_move(room_id: str) -> None:
    if room_id in ai_rooms_running:
        return
    metadata = room_meta[room_id]
    game = games[room_id]
    game.refresh_status()
    if metadata["mode"] != "ai" or not game.clock_running or game.current_turn != "b" or game.status in GameState.GAME_OVER_STATUSES:
        if metadata["mode"] == "ai" and game.status in GameState.GAME_OVER_STATUSES:
            await broadcast_game_state(room_id)
        return
    ai_rooms_running.add(room_id)
    try:
        from_value, to_value, promotion = await asyncio.to_thread(best_move, game.to_fen())
        game.apply_move("b", from_value, to_value, game.version, promotion)
        await broadcast_game_state(room_id)
    except (GameError, RuntimeError) as error:
        # Keep the game playable if the optional Stockfish process fails.
        # The fallback is still validated by the same server-side rules.
        legal_moves = game.all_legal_moves("b")
        if legal_moves and game.current_turn == "b" and game.status not in GameState.GAME_OVER_STATUSES:
            fallback = legal_moves[0]
            from_row = fallback["from"]["row"]
            to_row = fallback["to"]["row"]
            piece = game.board[from_row][fallback["from"]["column"]]
            promotion = "q" if piece and piece[1] == "p" and to_row in {0, 7} else None
            game.apply_move("b", fallback["from"], fallback["to"], game.version, promotion)
            await broadcast_game_state(room_id)
            await broadcast(room_id, {"type": "ai_warning", "message": f"Stockfish failed ({error}); a legal fallback move was played."})
        else:
            await broadcast(room_id, {"type": "ai_error", "message": str(error)})
    finally:
        ai_rooms_running.discard(room_id)


@app.websocket("/ws/game/{game_id}")
async def game_socket(websocket: WebSocket, game_id: str, token: str | None = None) -> None:
    await websocket.accept()
    user = database.get_user_by_token(token)
    if not user or not _ensure_loaded(game_id):
        await websocket.close(code=1008)
        return

    metadata = room_meta[game_id]
    game = games[game_id]
    if metadata["mode"] == "ai" and user["id"] != metadata["white_user_id"]:
        await websocket.close(code=1008)
        return

    existing_color = None
    for info in player_info.get(game_id, {}).values():
        if info["user_id"] == user["id"]:
            existing_color = info["color"]
            break

    if existing_color:
        color = existing_color
    elif user["id"] == metadata.get("white_user_id"):
        color = "w"
    elif user["id"] == metadata.get("black_user_id"):
        color = "b"
    elif metadata.get("black_user_id") is None and metadata["mode"] == "human":
        color = "b"
        metadata["black_user_id"] = user["id"]
        _persist(game_id)
    else:
        await websocket.close(code=1008)
        return

    rooms.setdefault(game_id, set()).add(websocket)
    player_info.setdefault(game_id, {})[websocket] = {
        "user_id": user["id"],
        "color": color,
        "username": user["username"],
        "rating": user["rating"],
    }
    player_count = len(rooms[game_id])

    await websocket.send_json({
        "type": "player_color",
        "color": color,
        "username": user["username"],
        "message": f"You are playing {'White' if color == 'w' else 'Black'}.",
    })
    if game.clock_running:
        await websocket.send_json({"type": "game_started", "game_id": game_id, "players": 2, "message": "The game is already in progress."})
    elif metadata["mode"] == "ai":
        await websocket.send_json({"type": "game_ready", "game_id": game_id, "players": 2, "message": "AI game ready. Press Start game."})
    elif player_count == 1:
        await websocket.send_json({"type": "waiting", "game_id": game_id, "players": 1, "message": "Waiting for another player to join."})
    else:
        await broadcast(game_id, {"type": "game_ready", "game_id": game_id, "players": 2, "message": "Both players are ready. Press Start game."})
    _persist(game_id)
    initial_state = game.public_state()
    initial_state["players"] = _player_names(game_id)
    initial_state["playerProfiles"] = _player_profiles(game_id)
    initial_state["aiThinking"] = metadata["mode"] == "ai" and game.clock_running and game.current_turn == "b" and not initial_state["gameOver"]
    await websocket.send_json({"type": "game_state", "game_id": game_id, "state": initial_state})

    # Resume a saved AI turn after a browser/server reconnect.
    if metadata["mode"] == "ai" and game.clock_running and game.current_turn == "b" and not game.public_state()["gameOver"]:
        asyncio.create_task(run_ai_move(game_id))

    try:
        while True:
            request = await websocket.receive_json()
            request_type = request.get("type")
            try:
                if request_type == "start_game":
                    if game.clock_running:
                        raise GameError("The game has already started.")
                    if metadata["mode"] == "human" and len(rooms.get(game_id, set())) < 2:
                        raise GameError("Wait for the second player before starting the game.")
                    if game.status in GameState.GAME_OVER_STATUSES:
                        raise GameError("Create a new game before starting again.")
                    game.start_clock()
                    await broadcast(game_id, {
                        "type": "game_started",
                        "game_id": game_id,
                        "players": 2,
                        "message": "The game has started.",
                    })
                    await broadcast_game_state(game_id)
                    if metadata["mode"] == "ai":
                        await run_ai_move(game_id)
                elif request_type == "move":
                    game.apply_move(color, request.get("from"), request.get("to"), request.get("version"), request.get("promotion"))
                    await broadcast_game_state(game_id)
                    if metadata["mode"] == "ai":
                        await broadcast(game_id, {"type": "ai_thinking"})
                    await run_ai_move(game_id)
                elif request_type == "undo":
                    game.undo(color, request.get("version"))
                    await broadcast_game_state(game_id)
                elif request_type == "reset":
                    game.reset(request.get("version"))
                    await broadcast_game_state(game_id)
                elif request_type == "resign":
                    game.resign(color, request.get("version"))
                    await broadcast_game_state(game_id)
                elif request_type == "offer_draw":
                    game.offer_draw(color, request.get("version"))
                    await broadcast_game_state(game_id)
                elif request_type == "answer_draw":
                    game.answer_draw(color, bool(request.get("accept")), request.get("version"))
                    await broadcast_game_state(game_id)
                else:
                    raise GameError("Unknown request type.")
            except GameError as error:
                await websocket.send_json({
                    "type": "request_rejected",
                    "reason": str(error),
                    "version": game.version,
                    "state": {
                        **game.public_state(),
                        "players": _player_names(game_id),
                        "playerProfiles": _player_profiles(game_id),
                    },
                })
    except WebSocketDisconnect:
        rooms.get(game_id, set()).discard(websocket)
        player_info.get(game_id, {}).pop(websocket, None)
        if rooms.get(game_id):
            await broadcast(game_id, {"type": "player_left", "players": len(rooms[game_id])})


app.mount("/", StaticFiles(directory=str(FRONTEND_DIRECTORY), html=True), name="frontend")
