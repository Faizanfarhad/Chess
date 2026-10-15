"""Server-authoritative chess rules and serializable game state."""

from copy import deepcopy
import time


class GameError(Exception):
    """An understandable error that can be shown to a player."""


def copy_board(board: list[list[str | None]]) -> list[list[str | None]]:
    return [row[:] for row in board]


def starting_board() -> list[list[str | None]]:
    return [
        ["br", "bn", "bb", "bq", "bk", "bb", "bn", "br"],
        ["bp"] * 8,
        [None] * 8,
        [None] * 8,
        [None] * 8,
        [None] * 8,
        ["wp"] * 8,
        ["wr", "wn", "wb", "wq", "wk", "wb", "wn", "wr"],
    ]


def inside_board(row: int, column: int) -> bool:
    return 0 <= row < 8 and 0 <= column < 8


def parse_square(value: object) -> tuple[int, int]:
    """Accept {row, column} and readable e2-style squares."""

    if isinstance(value, dict):
        row = value.get("row")
        column = value.get("column")
        if isinstance(row, int) and isinstance(column, int) and inside_board(row, column):
            return row, column

    if isinstance(value, str) and len(value) == 2:
        file_name, rank_name = value[0].lower(), value[1]
        if file_name in "abcdefgh" and rank_name in "12345678":
            return 8 - int(rank_name), ord(file_name) - ord("a")

    raise GameError("The move contains an invalid square.")


def square_data(row: int, column: int) -> dict[str, int]:
    return {"row": row, "column": column}


class GameState:
    """The complete official state for one chess game."""

    DRAW_STATUSES = {"draw_threefold", "draw_fifty_move", "draw_insufficient"}
    GAME_OVER_STATUSES = {"checkmate", "stalemate", "timeout", "resignation", "draw_agreement"} | DRAW_STATUSES

    def __init__(self, time_control_minutes: int = 10) -> None:
        if time_control_minutes not in {2, 3, 5, 10, 15}:
            raise ValueError("time_control_minutes must be 2, 3, 5, 10, or 15")

        self.board = starting_board()
        self.current_turn = "w"
        self.move_history: list[dict] = []
        self.last_move: list[dict[str, int]] | None = None
        self.status = "playing"
        self.winner: str | None = None
        self.draw_reason: str | None = None
        # Filled after a ranked game finishes so reconnecting players can
        # still see the rating change in the result screen.
        self.rating_changes: dict = {}
        self.version = 0
        self.castling_rights = {"wK": True, "wQ": True, "bK": True, "bQ": True}
        self.en_passant_target: tuple[int, int] | None = None
        self.halfmove_clock = 0
        self.position_counts: dict[str, int] = {self._position_key(): 1}

        self.time_control_minutes = time_control_minutes
        self.clocks = {"w": time_control_minutes * 60_000, "b": time_control_minutes * 60_000}
        self.clock_running = False
        self.last_clock_update = time.time()
        self.draw_offer: str | None = None
        self._snapshots: list[dict] = []

    @classmethod
    def from_dict(cls, saved: dict) -> "GameState":
        """Rebuild a game from PostgreSQL after a server restart."""

        state = cls(int(saved.get("timeControlMinutes", 10)))
        state.board = saved.get("board", starting_board())
        state.current_turn = saved.get("currentTurn", "w")
        state.move_history = saved.get("moveHistory", [])
        state.last_move = saved.get("lastMove")
        state.status = saved.get("status", "playing")
        state.winner = saved.get("winner")
        state.draw_reason = saved.get("drawReason")
        state.rating_changes = saved.get("ratingChanges", {})
        state.version = int(saved.get("version", 0))
        state.castling_rights = saved.get("castlingRights", state.castling_rights)
        target = saved.get("enPassantTarget")
        state.en_passant_target = tuple(target) if target else None
        state.halfmove_clock = int(saved.get("halfmoveClock", 0))
        state.position_counts = saved.get("positionCounts", {state._position_key(): 1})
        state.clocks = saved.get("clocks", state.clocks)
        state.clock_running = bool(saved.get("clockRunning", False))
        state.draw_offer = saved.get("drawOffer")
        state.last_clock_update = time.time()
        state._snapshots = []
        return state

    def to_dict(self) -> dict:
        self._update_clock()
        data = {
            "board": copy_board(self.board),
            "currentTurn": self.current_turn,
            "moveHistory": deepcopy(self.move_history),
            "lastMove": deepcopy(self.last_move),
            "status": self.status,
            "winner": self.winner,
            "drawReason": self.draw_reason,
            "ratingChanges": deepcopy(self.rating_changes),
            "version": self.version,
            "castlingRights": dict(self.castling_rights),
            "enPassantTarget": list(self.en_passant_target) if self.en_passant_target else None,
            "halfmoveClock": self.halfmove_clock,
            "positionCounts": dict(self.position_counts),
            "timeControlMinutes": self.time_control_minutes,
            "clocks": dict(self.clocks),
            "clockRunning": self.clock_running,
            "drawOffer": self.draw_offer,
        }
        return data

    def public_state(self) -> dict:
        """Return JSON-friendly state used by the frontend."""

        self._update_clock()
        self.refresh_status()
        return {
            "board": copy_board(self.board),
            "currentTurn": self.current_turn,
            "moveHistory": deepcopy(self.move_history),
            "lastMove": deepcopy(self.last_move),
            "status": self.status,
            "winner": self.winner,
            "drawReason": self.draw_reason,
            "ratingChanges": deepcopy(self.rating_changes),
            "version": self.version,
            "started": self.clock_running,
            "gameOver": self.status in self.GAME_OVER_STATUSES,
            "castlingRights": dict(self.castling_rights),
            "enPassantTarget": square_data(*self.en_passant_target) if self.en_passant_target else None,
            "clocks": dict(self.clocks),
            "timeControlMinutes": self.time_control_minutes,
            "drawOffer": self.draw_offer,
        }

    def refresh_status(self) -> None:
        """Repair a stale saved status without reopening finished non-chess results."""

        if self.status not in {"timeout", "resignation", "draw_agreement"}:
            self._update_status()

    def start_clock(self) -> None:
        self.clock_running = True
        self.last_clock_update = time.time()

    def stop_clock(self) -> None:
        self._update_clock()
        self.clock_running = False

    def apply_move(self, player_color, from_value, to_value, expected_version, promotion=None) -> None:
        """Validate and apply one move from a player or AI request."""

        self._check_version(expected_version)
        self._update_clock()
        self._reject_if_game_over()
        if self.clocks[self.current_turn] <= 0:
            self._finish_timeout()
            raise GameError("Time has expired.")
        if player_color != self.current_turn:
            raise GameError("It is not your turn.")

        from_row, from_column = parse_square(from_value)
        to_row, to_column = parse_square(to_value)
        piece = self.board[from_row][from_column]
        if not piece:
            raise GameError("There is no piece on the starting square.")
        if piece[0] != player_color:
            raise GameError("You can only move your own pieces.")

        target = square_data(to_row, to_column)
        if target not in self.legal_moves(from_row, from_column):
            raise GameError("That move is not legal.")

        promotion_piece = self._validated_promotion(piece, to_row, promotion)
        snapshot = self._snapshot()
        captured_piece = self._captured_piece(from_row, from_column, to_row, to_column)
        self._apply_move_to_board(from_row, from_column, to_row, to_column, promotion_piece)
        self._update_metadata_after_move(piece, from_row, from_column, to_row, to_column, captured_piece)
        self.move_history.append({
            "from": square_data(from_row, from_column),
            "to": square_data(to_row, to_column),
            "notation": self._notation(piece, to_row, to_column, promotion_piece),
            "capturedPiece": captured_piece,
            "color": player_color,
            "promotion": promotion_piece[1] if promotion_piece else None,
        })
        self.last_move = [square_data(from_row, from_column), square_data(to_row, to_column)]
        self.current_turn = "b" if self.current_turn == "w" else "w"
        self.draw_offer = None
        self.version += 1
        self.position_counts[self._position_key()] = self.position_counts.get(self._position_key(), 0) + 1
        self._update_status()
        self._snapshots.append(snapshot)
        self.last_clock_update = time.time()

    def resign(self, player_color, expected_version) -> None:
        self._check_version(expected_version)
        self._update_clock()
        self._reject_if_game_over()
        self._snapshots.append(self._snapshot())
        self.status = "resignation"
        self.winner = "b" if player_color == "w" else "w"
        self.clock_running = False
        self.version += 1

    def offer_draw(self, player_color, expected_version) -> None:
        self._check_version(expected_version)
        self._update_clock()
        self._reject_if_game_over()
        if self.draw_offer and self.draw_offer != player_color:
            raise GameError("There is already a draw offer waiting for you.")
        self.draw_offer = player_color
        self.version += 1

    def answer_draw(self, player_color, accept, expected_version) -> None:
        self._check_version(expected_version)
        self._update_clock()
        self._reject_if_game_over()
        opponent = "b" if player_color == "w" else "w"
        if self.draw_offer != opponent:
            raise GameError("There is no draw offer from your opponent.")
        self.draw_offer = None
        if accept:
            self.status = "draw_agreement"
            self.winner = None
            self.draw_reason = "agreement"
            self.clock_running = False
        self.version += 1

    def undo(self, player_color, expected_version) -> None:
        self._check_version(expected_version)
        self._update_clock()
        if not self._snapshots:
            raise GameError("There is no move to undo.")
        if not self.move_history or self.move_history[-1]["color"] != player_color:
            raise GameError("Only the player who made the last move can undo it.")
        snapshot = self._snapshots.pop()
        self._restore_snapshot(snapshot)
        self.version += 1

    def reset(self, expected_version) -> None:
        self._check_version(expected_version)
        time_control = self.time_control_minutes
        self.__init__(time_control)
        self.version = int(expected_version) + 1

    def legal_moves(self, row, column):
        piece = self.board[row][column]
        if not piece:
            return []
        possible_moves = self._pseudo_legal_moves(row, column, piece[0], piece[1])
        legal_moves = []
        for move in possible_moves:
            target_piece = self.board[move["row"]][move["column"]]
            if target_piece and target_piece[0] != piece[0] and target_piece[1] == "k":
                continue
            simulated_board = copy_board(self.board)
            self._apply_move_to_board(row, column, move["row"], move["column"], None, simulated_board)
            if not self._king_in_check(simulated_board, piece[0]):
                legal_moves.append(move)
        return legal_moves

    def all_legal_moves(self, color):
        moves = []
        for row in range(8):
            for column in range(8):
                piece = self.board[row][column]
                if piece and piece[0] == color:
                    for move in self.legal_moves(row, column):
                        moves.append({"from": square_data(row, column), "to": move})
        return moves

    def to_fen(self):
        rows = []
        for row in self.board:
            empty = 0
            encoded = ""
            for piece in row:
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        encoded += str(empty)
                        empty = 0
                    encoded += piece[1].upper() if piece[0] == "w" else piece[1]
            if empty:
                encoded += str(empty)
            rows.append(encoded)
        rights = "".join(
            letter
            for key, letter in (("wK", "K"), ("wQ", "Q"), ("bK", "k"), ("bQ", "q"))
            if self.castling_rights[key]
        ) or "-"
        target = self._square_name(*self.en_passant_target) if self.en_passant_target else "-"
        return f"{'/'.join(rows)} {self.current_turn} {rights} {target} {self.halfmove_clock} {len(self.move_history) // 2 + 1}"

    def _pseudo_legal_moves(self, row, column, color, piece_type):
        if piece_type == "p":
            return self._pawn_moves(row, column, color)
        if piece_type == "n":
            return self._knight_moves(row, column, color)
        if piece_type == "k":
            return self._king_moves(row, column, color)
        directions = []
        if piece_type in {"r", "q"}:
            directions.extend([(-1, 0), (1, 0), (0, -1), (0, 1)])
        if piece_type in {"b", "q"}:
            directions.extend([(-1, -1), (-1, 1), (1, -1), (1, 1)])
        return self._sliding_moves(row, column, color, directions)

    def _pawn_moves(self, row, column, color):
        moves = []
        direction = -1 if color == "w" else 1
        starting_row = 6 if color == "w" else 1
        next_row = row + direction
        if inside_board(next_row, column) and not self.board[next_row][column]:
            moves.append(square_data(next_row, column))
            double_row = row + direction * 2
            if row == starting_row and not self.board[double_row][column]:
                moves.append(square_data(double_row, column))
        for column_offset in (-1, 1):
            capture_column = column + column_offset
            if not inside_board(next_row, capture_column):
                continue
            target = self.board[next_row][capture_column]
            if target and target[0] != color:
                moves.append(square_data(next_row, capture_column))
            elif self.en_passant_target == (next_row, capture_column):
                moves.append(square_data(next_row, capture_column))
        return moves

    def _knight_moves(self, row, column, color):
        moves = []
        offsets = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
        for row_offset, column_offset in offsets:
            target_row, target_column = row + row_offset, column + column_offset
            if inside_board(target_row, target_column) and not self._friendly(target_row, target_column, color):
                moves.append(square_data(target_row, target_column))
        return moves

    def _king_moves(self, row, column, color):
        moves = []
        for row_offset in (-1, 0, 1):
            for column_offset in (-1, 0, 1):
                if row_offset == 0 and column_offset == 0:
                    continue
                target_row, target_column = row + row_offset, column + column_offset
                if inside_board(target_row, target_column) and not self._friendly(target_row, target_column, color):
                    moves.append(square_data(target_row, target_column))

        home_row = 7 if color == "w" else 0
        if row == home_row and column == 4 and not self._king_in_check(self.board, color):
            enemy = "b" if color == "w" else "w"
            if self.castling_rights[f"{color}K"] and self.board[home_row][7] == f"{color}r":
                if not any(self.board[home_row][c] for c in (5, 6)) and not self._square_attacked(self.board, home_row, 5, enemy) and not self._square_attacked(self.board, home_row, 6, enemy):
                    moves.append(square_data(home_row, 6))
            if self.castling_rights[f"{color}Q"] and self.board[home_row][0] == f"{color}r":
                if not any(self.board[home_row][c] for c in (1, 2, 3)) and not self._square_attacked(self.board, home_row, 3, enemy) and not self._square_attacked(self.board, home_row, 2, enemy):
                    moves.append(square_data(home_row, 2))
        return moves

    def _sliding_moves(self, row, column, color, directions):
        moves = []
        for row_direction, column_direction in directions:
            target_row, target_column = row + row_direction, column + column_direction
            while inside_board(target_row, target_column):
                target_piece = self.board[target_row][target_column]
                if not target_piece:
                    moves.append(square_data(target_row, target_column))
                else:
                    if target_piece[0] != color:
                        moves.append(square_data(target_row, target_column))
                    break
                target_row += row_direction
                target_column += column_direction
        return moves

    def _apply_move_to_board(self, from_row, from_column, to_row, to_column, promotion_piece, board=None):
        board = self.board if board is None else board
        piece = board[from_row][from_column]
        board[to_row][to_column] = piece
        board[from_row][from_column] = None
        if piece and piece[1] == "k" and abs(to_column - from_column) == 2:
            rook_from = 7 if to_column > from_column else 0
            rook_to = 5 if to_column > from_column else 3
            board[to_row][rook_to] = board[to_row][rook_from]
            board[to_row][rook_from] = None
        if piece and piece[1] == "p" and from_column != to_column and board[to_row][to_column] == piece:
            if self.en_passant_target == (to_row, to_column):
                board[from_row][to_column] = None
        if promotion_piece:
            board[to_row][to_column] = promotion_piece

    def _update_metadata_after_move(self, piece, from_row, from_column, to_row, to_column, captured_piece):
        color = piece[0]
        self.halfmove_clock = 0 if piece[1] == "p" or captured_piece else self.halfmove_clock + 1
        self.en_passant_target = None
        if piece[1] == "p" and abs(to_row - from_row) == 2:
            self.en_passant_target = ((from_row + to_row) // 2, from_column)
        if piece[1] == "k":
            self.castling_rights[f"{color}K"] = False
            self.castling_rights[f"{color}Q"] = False
        if piece[1] == "r":
            self._remove_rook_right(color, from_row, from_column)
        if captured_piece and captured_piece[1] == "r":
            self._remove_rook_right(captured_piece[0], to_row, to_column)

    def _remove_rook_right(self, color, row, column):
        home_row = 7 if color == "w" else 0
        if row == home_row and column == 0:
            self.castling_rights[f"{color}Q"] = False
        if row == home_row and column == 7:
            self.castling_rights[f"{color}K"] = False

    def _captured_piece(self, from_row, from_column, to_row, to_column):
        target = self.board[to_row][to_column]
        piece = self.board[from_row][from_column]
        if piece and piece[1] == "p" and from_column != to_column and target is None and self.en_passant_target == (to_row, to_column):
            return self.board[from_row][to_column]
        return target

    def _validated_promotion(self, piece, to_row, promotion):
        reaches_last_rank = piece[1] == "p" and to_row in {0, 7}
        if not reaches_last_rank:
            if promotion is not None:
                raise GameError("Only a pawn reaching the last rank can promote.")
            return None
        if not isinstance(promotion, str) or promotion.lower() not in {"q", "r", "b", "n"}:
            raise GameError("Choose a promotion piece: queen, rook, bishop, or knight.")
        return f"{piece[0]}{promotion.lower()}"

    def _snapshot(self):
        return {
            "board": copy_board(self.board),
            "current_turn": self.current_turn,
            "move_history": deepcopy(self.move_history),
            "last_move": deepcopy(self.last_move),
            "status": self.status,
            "winner": self.winner,
            "draw_reason": self.draw_reason,
            "castling_rights": dict(self.castling_rights),
            "en_passant_target": self.en_passant_target,
            "halfmove_clock": self.halfmove_clock,
            "position_counts": dict(self.position_counts),
            "clocks": dict(self.clocks),
            "clock_running": self.clock_running,
            "draw_offer": self.draw_offer,
        }

    def _restore_snapshot(self, snapshot):
        self.board = snapshot["board"]
        self.current_turn = snapshot["current_turn"]
        self.move_history = snapshot["move_history"]
        self.last_move = snapshot["last_move"]
        self.status = snapshot["status"]
        self.winner = snapshot["winner"]
        self.draw_reason = snapshot["draw_reason"]
        self.castling_rights = snapshot["castling_rights"]
        self.en_passant_target = snapshot["en_passant_target"]
        self.halfmove_clock = snapshot["halfmove_clock"]
        self.position_counts = snapshot["position_counts"]
        self.clocks = snapshot["clocks"]
        self.clock_running = snapshot["clock_running"]
        self.draw_offer = snapshot["draw_offer"]
        self.last_clock_update = time.time()

    def _check_version(self, expected_version):
        if not isinstance(expected_version, int) or expected_version != self.version:
            raise GameError("This request is based on an outdated board.")

    def _reject_if_game_over(self):
        if self.status in self.GAME_OVER_STATUSES:
            raise GameError("The game is already over.")

    def _update_clock(self):
        now = time.time()
        if self.clock_running and self.status not in self.GAME_OVER_STATUSES:
            elapsed = max(0, int((now - self.last_clock_update) * 1000))
            if elapsed:
                self.clocks[self.current_turn] = max(0, self.clocks[self.current_turn] - elapsed)
                self.last_clock_update = now
                if self.clocks[self.current_turn] == 0:
                    self._finish_timeout()
        else:
            self.last_clock_update = now

    def _finish_timeout(self):
        self.status = "timeout"
        self.winner = "b" if self.current_turn == "w" else "w"
        self.clock_running = False

    def _update_status(self):
        in_check = self._king_in_check(self.board, self.current_turn)
        moves = self.all_legal_moves(self.current_turn)
        self.draw_reason = None
        if not moves and in_check:
            self.status = "checkmate"
            self.winner = "b" if self.current_turn == "w" else "w"
        elif not moves:
            self.status = "stalemate"
            self.winner = None
        elif self.halfmove_clock >= 100:
            self.status = "draw_fifty_move"
            self.draw_reason = "fifty_move_rule"
            self.winner = None
        elif self.position_counts.get(self._position_key(), 0) >= 3:
            self.status = "draw_threefold"
            self.draw_reason = "threefold_repetition"
            self.winner = None
        elif self._insufficient_material():
            self.status = "draw_insufficient"
            self.draw_reason = "insufficient_material"
            self.winner = None
        elif in_check:
            self.status = "check"
            self.winner = None
        else:
            self.status = "playing"
            self.winner = None

    def _insufficient_material(self):
        pieces = [piece for row in self.board for piece in row if piece and piece[1] != "k"]
        if not pieces:
            return True
        if any(piece[1] in {"p", "q", "r"} for piece in pieces):
            return False
        if len(pieces) == 1 and pieces[0][1] in {"b", "n"}:
            return True
        if all(piece[1] == "b" for piece in pieces):
            bishops = []
            for row in range(8):
                for column in range(8):
                    if self.board[row][column] and self.board[row][column][1] == "b":
                        bishops.append((row + column) % 2)
            return len(set(bishops)) == 1
        return False

    def _position_key(self):
        board_key = "/".join("".join(piece or "--" for piece in row) for row in self.board)
        rights = "".join(key for key, allowed in self.castling_rights.items() if allowed)
        return f"{board_key}|{self.current_turn}|{rights}|{self.en_passant_target}"

    def _friendly(self, row, column, color):
        piece = self.board[row][column]
        return bool(piece) and piece[0] == color

    def _find_king(self, board, color):
        for row in range(8):
            for column in range(8):
                if board[row][column] == f"{color}k":
                    return row, column
        return None

    def _king_in_check(self, board, color):
        king = self._find_king(board, color)
        if king is None:
            return True
        attacking_color = "b" if color == "w" else "w"
        return self._square_attacked(board, king[0], king[1], attacking_color)

    def _square_attacked(self, board, row, column, attacking_color):
        pawn_row = row + (1 if attacking_color == "w" else -1)
        for pawn_column in (column - 1, column + 1):
            if inside_board(pawn_row, pawn_column) and board[pawn_row][pawn_column] == f"{attacking_color}p":
                return True
        knight_offsets = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
        for row_offset, column_offset in knight_offsets:
            attacker_row, attacker_column = row + row_offset, column + column_offset
            if inside_board(attacker_row, attacker_column) and board[attacker_row][attacker_column] == f"{attacking_color}n":
                return True
        for row_offset in (-1, 0, 1):
            for column_offset in (-1, 0, 1):
                if (row_offset or column_offset) and inside_board(row + row_offset, column + column_offset) and board[row + row_offset][column + column_offset] == f"{attacking_color}k":
                    return True
        if self._attacked_in_directions(board, row, column, attacking_color, [(-1, 0), (1, 0), (0, -1), (0, 1)], {"r", "q"}):
            return True
        return self._attacked_in_directions(board, row, column, attacking_color, [(-1, -1), (-1, 1), (1, -1), (1, 1)], {"b", "q"})

    def _attacked_in_directions(self, board, row, column, attacking_color, directions, attacking_pieces):
        for row_direction, column_direction in directions:
            attacker_row, attacker_column = row + row_direction, column + column_direction
            while inside_board(attacker_row, attacker_column):
                piece = board[attacker_row][attacker_column]
                if piece:
                    if piece[0] == attacking_color and piece[1] in attacking_pieces:
                        return True
                    break
                attacker_row += row_direction
                attacker_column += column_direction
        return False

    def _notation(self, piece, row, column, promotion_piece=None):
        names = {"k": "K", "q": "Q", "r": "R", "b": "B", "n": "N", "p": ""}
        suffix = f"={promotion_piece[1].upper()}" if promotion_piece else ""
        return f"{names[piece[1]]}{self._square_name(row, column)}{suffix}"

    @staticmethod
    def _square_name(row, column):
        return f"{chr(ord('a') + column)}{8 - row}"
