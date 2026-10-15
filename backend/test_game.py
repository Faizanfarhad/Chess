import unittest

from backend.game import GameError, GameState


class GameStateTests(unittest.TestCase):
    def test_pawn_has_two_opening_moves(self):
        game = GameState()

        self.assertEqual(len(game.legal_moves(6, 4)), 2)

    def test_wrong_turn_is_rejected(self):
        game = GameState()
        game.apply_move("w", {"row": 6, "column": 4}, {"row": 4, "column": 4}, 0)

        with self.assertRaises(GameError):
            game.apply_move("w", {"row": 1, "column": 4}, {"row": 3, "column": 4}, 1)

    def test_outdated_version_is_rejected(self):
        game = GameState()

        with self.assertRaises(GameError):
            game.apply_move("w", {"row": 6, "column": 4}, {"row": 4, "column": 4}, 1)

    def test_outdated_reset_is_rejected(self):
        game = GameState()

        with self.assertRaises(GameError):
            game.reset(1)

    def test_outdated_undo_is_rejected(self):
        game = GameState()
        game.apply_move("w", {"row": 6, "column": 4}, {"row": 4, "column": 4}, 0)

        with self.assertRaises(GameError):
            game.undo("w", 0)

    def test_fools_mate_is_checkmate(self):
        # 1. f3 e5 2. g4 Qh4#
        game = GameState()
        game.apply_move("w", {"row": 6, "column": 5}, {"row": 5, "column": 5}, 0)
        game.apply_move("b", {"row": 1, "column": 4}, {"row": 3, "column": 4}, 1)
        game.apply_move("w", {"row": 6, "column": 6}, {"row": 4, "column": 6}, 2)
        game.apply_move("b", {"row": 0, "column": 3}, {"row": 4, "column": 7}, 3)

        self.assertEqual(game.status, "checkmate")
        self.assertEqual(game.winner, "b")

    def test_undo_restores_the_previous_position(self):
        game = GameState()
        game.apply_move("w", {"row": 6, "column": 4}, {"row": 4, "column": 4}, 0)
        game.undo("w", 1)

        self.assertEqual(game.board[6][4], "wp")
        self.assertIsNone(game.board[4][4])
        self.assertEqual(game.current_turn, "w")

    def test_kingside_castling_moves_the_rook(self):
        game = GameState()
        game.board = [[None] * 8 for _ in range(8)]
        game.board[7][4] = "wk"
        game.board[7][7] = "wr"
        game.board[0][4] = "bk"
        game.castling_rights = {"wK": True, "wQ": False, "bK": False, "bQ": False}

        self.assertIn({"row": 7, "column": 6}, game.legal_moves(7, 4))
        game.apply_move("w", {"row": 7, "column": 4}, {"row": 7, "column": 6}, 0)

        self.assertEqual(game.board[7][6], "wk")
        self.assertEqual(game.board[7][5], "wr")
        self.assertIsNone(game.board[7][7])

    def test_en_passant_captures_the_pawn(self):
        game = GameState()
        game.apply_move("w", "e2", "e4", 0)
        game.apply_move("b", "a7", "a6", 1)
        game.apply_move("w", "e4", "e5", 2)
        game.apply_move("b", "d7", "d5", 3)

        self.assertIn({"row": 2, "column": 3}, game.legal_moves(3, 4))
        game.apply_move("w", "e5", "d6", 4)

        self.assertEqual(game.board[2][3], "wp")
        self.assertIsNone(game.board[3][3])

    def test_pawn_promotion_requires_and_applies_a_piece(self):
        game = GameState()
        game.board = [[None] * 8 for _ in range(8)]
        game.board[7][4] = "wk"
        game.board[0][4] = "bk"
        game.board[1][0] = "wp"

        with self.assertRaises(GameError):
            game.apply_move("w", "a7", "a8", 0)

        game.apply_move("w", "a7", "a8", 0, "q")
        self.assertEqual(game.board[0][0], "wq")

    def test_insufficient_material_is_a_draw(self):
        game = GameState()
        game.board = [[None] * 8 for _ in range(8)]
        game.board[7][4] = "wk"
        game.board[0][4] = "bk"
        game.board[5][2] = "wb"
        game._update_status()

        self.assertEqual(game.status, "draw_insufficient")

    def test_public_state_repairs_a_stale_checkmate_status(self):
        game = GameState()
        game.board = [[None] * 8 for _ in range(8)]
        game.board[0][6] = "bk"
        game.board[0][7] = "br"
        game.board[1][4] = "wq"
        game.board[4][2] = "wb"
        game.board[7][4] = "wk"
        game.current_turn = "b"
        game.status = "playing"

        state = game.public_state()

        self.assertEqual(state["status"], "checkmate")
        self.assertTrue(state["gameOver"])


if __name__ == "__main__":
    unittest.main()
