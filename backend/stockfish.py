"""Optional Stockfish adapter. The chess rules still validate its move."""

import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from config import * 




def _configured_move_time() -> int:
    try:
        return max(300, int(os.getenv("STOCKFISH_MOVE_TIME_MS", "3000")))
    except ValueError:
        return 3000


def best_move(fen: str, move_time_ms: int | None = None) -> tuple[str, str, str | None]:
    if not ENGINE_PATH.exists():
        raise RuntimeError("Stockfish is not available in engine/stockfish/stockfish.")
    if move_time_ms is None:
        move_time_ms = _configured_move_time()

    process = subprocess.Popen(
        [str(ENGINE_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    output_queue: queue.Queue[str] = queue.Queue()

    def read_output() -> None:
        for raw_line in iter(process.stdout.readline, ""):
            output_queue.put(raw_line.strip())

    threading.Thread(target=read_output, daemon=True).start()

    try:
        def wait_for_line(expected: str, timeout: float) -> None:
            """Wait for a UCI handshake response without sending commands early."""

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    line = output_queue.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty as error:
                    raise RuntimeError(f"Stockfish did not send {expected}.") from error
                if line == expected:
                    return
            raise RuntimeError(f"Stockfish did not send {expected}.")

        # Complete the UCI handshake before starting the search. Sending all
        # commands at once can make Stockfish stop at depth 1 and play a3.
        process.stdin.write("uci\n")
        process.stdin.flush()
        wait_for_line("uciok", 5)

        process.stdin.write(
            "setoption name Threads value 2\n"
            "setoption name Hash value 128\n"
            "isready\n"
        )
        process.stdin.flush()
        wait_for_line("readyok", 10)

        process.stdin.write(
            f"position fen {fen}\n"
            f"go movetime {move_time_ms}\n"
        )
        process.stdin.flush()

        # Read until Stockfish has completed the requested search.
        deadline = time.monotonic() + max(20, move_time_ms / 1000 + 10)
        while time.monotonic() < deadline:
            try:
                line = output_queue.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as error:
                raise RuntimeError("Stockfish did not return a best move.") from error
            if not line.startswith("bestmove "):
                continue

            move_parts = line.split()
            move = move_parts[1] if len(move_parts) > 1 else "(none)"
            if move != "(none)" and len(move) >= 4:
                return move[:2], move[2:4], move[4:5] or None
    finally:
        # Stop the engine only after the best move has been read.
        try:
            process.stdin.write("quit\n")
            process.stdin.flush()
            process.wait(timeout=2)
        except (BrokenPipeError, subprocess.TimeoutExpired):
            process.kill()

    raise RuntimeError("Stockfish did not return a legal move.")
