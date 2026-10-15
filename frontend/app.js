

const files = ["a", "b", "c", "d", "e", "f", "g", "h"];
const pieceSymbols = {
  white: { king: "♔", queen: "♕", rook: "♖", bishop: "♗", knight: "♘", pawn: "♙" },
  black: { king: "♚", queen: "♛", rook: "♜", bishop: "♝", knight: "♞", pawn: "♟" },
};

const startingBoard = [
  ["br", "bn", "bb", "bq", "bk", "bb", "bn", "br"],
  ["bp", "bp", "bp", "bp", "bp", "bp", "bp", "bp"],
  [null, null, null, null, null, null, null, null],
  [null, null, null, null, null, null, null, null],
  [null, null, null, null, null, null, null, null],
  [null, null, null, null, null, null, null, null],
  ["wp", "wp", "wp", "wp", "wp", "wp", "wp", "wp"],
  ["wr", "wn", "wb", "wq", "wk", "wb", "wn", "wr"],
];

const boardElement = document.querySelector("#board");
const moveListElement = document.querySelector("#move-list");
const moveCountElement = document.querySelector("#move-count");
const turnLabelElement = document.querySelector("#turn-label");
const statusTitleElement = document.querySelector("#status-title");
const statusMessageElement = document.querySelector("#status-message");
const currentPlayerNameElement = document.querySelector("#current-player-name");
const currentPlayerSubtitleElement = document.querySelector("#current-player-subtitle");
const opponentNameElement = document.querySelector("#opponent-name");
const opponentSubtitleElement = document.querySelector("#opponent-subtitle");
const undoButton = document.querySelector("#undo-move");
const startGameButton = document.querySelector("#start-game");
const newGameButton = document.querySelector("#new-game");
const createRoomButton = document.querySelector("#create-room");
const joinRoomButton = document.querySelector("#join-room");
const roomInput = document.querySelector("#room-id");
const copyRoomLinkButton = document.querySelector("#copy-room-link");
const roomHelperElement = document.querySelector("#room-helper");
const usernameInput = document.querySelector("#username");
const passwordInput = document.querySelector("#password");
const loginButton = document.querySelector("#login");
const registerButton = document.querySelector("#register");
const authHelperElement = document.querySelector("#auth-helper");
const timeControlElement = document.querySelector("#time-control");
const createAiRoomButton = document.querySelector("#create-ai-room");
const rankedMatchButton = document.querySelector("#ranked-match");
const offerDrawButton = document.querySelector("#offer-draw");
const resignButton = document.querySelector("#resign-game");
const resultOverlay = document.querySelector("#result-overlay");
const resultTitleElement = document.querySelector("#result-title");
const resultMessageElement = document.querySelector("#result-message");
const whiteResultScoreElement = document.querySelector("#white-result-score");
const blackResultScoreElement = document.querySelector("#black-result-score");
const whiteResultPlayerElement = document.querySelector("#white-result-player");
const blackResultPlayerElement = document.querySelector("#black-result-player");
const whiteResultRatingElement = document.querySelector("#white-result-rating");
const blackResultRatingElement = document.querySelector("#black-result-rating");
const whiteRatingChangeElement = document.querySelector("#white-rating-change");
const blackRatingChangeElement = document.querySelector("#black-rating-change");
const whiteCapturedPiecesElement = document.querySelector("#white-captured-pieces");
const blackCapturedPiecesElement = document.querySelector("#black-captured-pieces");
const resultNewGameButton = document.querySelector("#result-new-game");
const resultCloseButton = document.querySelector("#result-close");
const promotionPicker = document.querySelector("#promotion-picker");
const promotionButtons = [...document.querySelectorAll("[data-promotion]")];
const cancelPromotionButton = document.querySelector("#cancel-promotion");

let board = copyBoard(startingBoard);
let selectedSquare = null;
let legalMoves = [];
let currentTurn = "w";
let currentStatus = "playing";
let moveHistory = [];
let lastMove = null;
let pendingPromotion = null;
// The first player must wait until the second player joins.
let gameStarted = false;
// No pieces can move after checkmate or stalemate.
let gameOver = false;
// The backend assigns this when the player joins a room.
let playerColor = null;
let currentUserProfile = null;
// Keep the latest complete server state so clicks after game end can still
// show the actual result instead of replacing it with a generic message.
let lastServerState = null;
// The server increases this after every accepted state change.
let gameVersion = 0;
let castlingRights = {};
let enPassantTarget = null;
let clockValues = { w: 0, b: 0 };
let hasServerClockState = false;
let authToken = localStorage.getItem("chess_token");
let matchmakingTimer = null;
let lastSeenDrawOffer = null;
let requestInFlight = false;
let aiThinking = false;

function copyBoard(boardToCopy) {
  return boardToCopy.map((row) => [...row]);
}

function pieceDetails(piece) {
  if (!piece) return null;
  return { color: piece[0], type: piece[1] };
}

function squareName(row, column) {
  return `${files[column]}${8 - row}`;
}

function renderBoard() {
  boardElement.innerHTML = "";
  const isFlipped = playerColor === "b";

  // Render the board from the joined player's point of view. The internal
  // board coordinates never change; only their visual order changes.
  for (let visualRow = 0; visualRow < 8; visualRow += 1) {
    const actualRow = isFlipped ? 7 - visualRow : visualRow;
    for (let visualColumn = 0; visualColumn < 8; visualColumn += 1) {
      const actualColumn = isFlipped ? 7 - visualColumn : visualColumn;
      const piece = board[actualRow][actualColumn];
      const square = document.createElement("button");
      const isLight = (actualRow + actualColumn) % 2 === 1;
      const isSelected = selectedSquare?.row === actualRow && selectedSquare?.column === actualColumn;
      const isLegal = legalMoves.some((move) => move.row === actualRow && move.column === actualColumn);
      const isLastMove = lastMove?.some((move) => move.row === actualRow && move.column === actualColumn);
      // Use both sources: the server is authoritative, while the local check
      // also lets the highlight appear immediately with a fresh board state.
      const serverSaysCheck =
        piece?.[1] === "k" &&
        ["check", "checkmate"].includes(currentStatus) &&
        piece[0] === currentTurn;
      const boardSaysCheck = piece?.[1] === "k" && isKingInCheck(board, piece[0]);
      const isCheckedKing = serverSaysCheck || boardSaysCheck;
      const location = squareName(actualRow, actualColumn);

      square.className = `square ${isLight ? "light" : "dark"}`;
      if (isSelected) square.classList.add("selected");
      if (isLegal) square.classList.add("legal");
      if (piece) square.classList.add("has-piece");
      if (isLastMove) square.classList.add("last-move");
      if (isCheckedKing) {
        square.classList.add("king-in-check");
        // Keep the visual state explicit as well as class-based. This makes
        // the check highlight visible even if a cached stylesheet is present.
        square.style.setProperty("background", "#e05252", "important");
        square.style.setProperty(
          "background-image",
          "radial-gradient(circle, #f47b7b 0%, #e05252 68%, #bd3030 100%)",
          "important"
        );
        square.style.setProperty(
          "box-shadow",
          "inset 0 0 0 5px #a91f1f, inset 0 0 22px rgba(255, 224, 224, 0.75), 0 0 12px rgba(211, 47, 47, 0.8)",
          "important"
        );
      }
      square.setAttribute("role", "gridcell");
      square.setAttribute("aria-label", `${location}${piece ? `, ${describePiece(piece)}` : ""}`);
      square.addEventListener("click", () => handleSquareClick(actualRow, actualColumn));
      
      if (visualRow === 7) {
        const fileLabel = document.createElement("span");
        fileLabel.className = "file-label";
        fileLabel.textContent = files[actualColumn];
        square.appendChild(fileLabel);
      }

      if (visualColumn === 0) {
        const rankLabel = document.createElement("span");
        rankLabel.className = "rank-label";
        rankLabel.textContent = 8 - actualRow;
        square.appendChild(rankLabel);
      }

      if (piece) {
        const pieceElement = document.createElement("span");
        const details = pieceDetails(piece);
        pieceElement.className = `piece ${details.color === "w" ? "white" : "black"}`;
        pieceElement.textContent = pieceSymbols[details.color === "w" ? "white" : "black"][pieceTypeName(details.type)];
        pieceElement.setAttribute("aria-hidden", "true");
        square.appendChild(pieceElement);
      }

      boardElement.appendChild(square);
    }
  }
}

function handleSquareClick(row, column) {
  // Keep the promotion choice open until the player chooses a piece or
  // explicitly cancels it.
  if (pendingPromotion) return;

  // Do not allow a move while the room only has one player.
  if (!gameStarted) {
    updateStatus("Waiting for opponent", "Another player must join before you can move.");
    return;
  }

  if (requestInFlight || aiThinking) {
    updateStatus("Please wait", aiThinking ? "Stockfish is choosing its move." : "Waiting for the server.");
    return;
  }

  // The game ends when there are no legal moves left.
  if (gameOver) {
    if (lastServerState) {
      updateServerStatus(lastServerState);
    } else {
      updateStatus("Game complete", "This game has ended.");
    }
    return;
  }

  const clickedPiece = board[row][column];
  const clickedLegalMove = legalMoves.find((move) => move.row === row && move.column === column);

  if (selectedSquare) {
    if (clickedLegalMove) {
      makeMove(selectedSquare, { row, column });
      return;
    }


    // Highlights are only a convenience. The backend is authoritative, so
    // send a destination click even if the browser's local list is stale.
    // This also lets the server handle castling, en passant, and promotion.
    if (!clickedPiece || clickedPiece[0] !== playerColor) {
      makeMove(selectedSquare, { row, column });
      return;
    }
  }

  // A player can only select pieces that belong to their assigned color.
  if (clickedPiece && clickedPiece[0] !== playerColor) {
    selectedSquare = null;
    legalMoves = [];
    updateStatus("Not your piece", "You can only move your own pieces.");
  } else if (clickedPiece && clickedPiece[0] !== currentTurn) {
    selectedSquare = null;
    legalMoves = [];
    updateStatus("Opponent's turn", "Wait for your opponent to move.");
  } else if (clickedPiece && clickedPiece[0] === playerColor) {
    selectedSquare = { row, column };
    legalMoves = getLegalMoves(row, column);
    updateStatus(
      `${currentTurn === "w" ? "White" : "Black"} selected`,
      legalMoves.length ? "Choose a highlighted square." : "This piece has no available moves."
    );
  } else {
    selectedSquare = null;
    legalMoves = [];
    updateStatus(
      `${currentTurn === "w" ? "White" : "Black"} to move`,
      "Choose one of your pieces to see its possible moves."
    );
  }

  renderBoard();
}

function getLegalMoves(row, column) {
  return getLegalMovesOnBoard(board, row, column);
}

// A legal move is a normal piece move that does not leave that player's king
// under attack. This is what prevents moving a pinned piece or ignoring check.
function getLegalMovesOnBoard(boardState, row, column) {
  const piece = pieceDetails(boardState[row][column]);
  if (!piece) return [];

  const possibleMoves = getPseudoLegalMoves(boardState, row, column, piece.color, piece.type);

  return possibleMoves.filter((move) => {
    const targetPiece = boardState[move.row][move.column];

    // Kings are never captured. Checkmate ends the game before that happens.
    if (targetPiece && targetPiece[0] !== piece.color && targetPiece[1] === "k") {
      return false;
    }

    // Copy the board, apply the candidate move, and test the king's safety.
    const simulatedBoard = copyBoard(boardState);
    applyLocalMove(simulatedBoard, row, column, move.row, move.column);

    return !isKingInCheck(simulatedBoard, piece.color);
  });
}



    
// The server remains authoritative. This helper only makes special moves
// visible as selectable squares before the request is sent.
function applyLocalMove(boardState, fromRow, fromColumn, toRow, toColumn) {
  const piece = boardState[fromRow][fromColumn];
  boardState[toRow][toColumn] = piece;
  boardState[fromRow][fromColumn] = null;

  if (piece?.[1] === "k" && Math.abs(toColumn - fromColumn) === 2) {
    const rookFrom = toColumn > fromColumn ? 7 : 0;
    const rookTo = toColumn > fromColumn ? 5 : 3;
    boardState[toRow][rookTo] = boardState[toRow][rookFrom];
    boardState[toRow][rookFrom] = null;
  }

  if (piece?.[1] === "p" && fromColumn !== toColumn && !boardState[toRow][toColumn]) {
    if (enPassantTarget?.row === toRow && enPassantTarget?.column === toColumn) {
      boardState[fromRow][toColumn] = null;
    }
  }
}

function getPseudoLegalMoves(boardState, row, column, color, type) {
  if (type === "p") return getPawnMoves(row, column, color, boardState);
  if (type === "n") return getKnightMoves(row, column, color, boardState);
  if (type === "k") return getKingMoves(row, column, color, boardState);

  const directions = [];
  if (type === "r" || type === "q") {
    directions.push([-1, 0], [1, 0], [0, -1], [0, 1]);
  }
  if (type === "b" || type === "q") {
    directions.push([-1, -1], [-1, 1], [1, -1], [1, 1]);
  }

  return getSlidingMoves(row, column, color, directions, boardState);
}




function getPawnMoves(row, column, color, boardState = board) {
  const moves = [];
  const direction = color === "w" ? -1 : 1;
  const startingRow = color === "w" ? 6 : 1;
  const nextRow = row + direction;

  if (isInsideBoard(nextRow, column) && !boardState[nextRow][column]) {
    moves.push({ row: nextRow, column });
    const doubleRow = row + direction * 2;
    if (row === startingRow && !boardState[doubleRow][column]) moves.push({ row: doubleRow, column });
  }

  [-1, 1].forEach((columnOffset) => {
    const captureColumn = column + columnOffset;
    if (isInsideBoard(nextRow, captureColumn) && isOpponent(boardState[nextRow][captureColumn], color)) {
      moves.push({ row: nextRow, column: captureColumn });
    } else if (enPassantTarget?.row === nextRow && enPassantTarget?.column === captureColumn) {
      moves.push({ row: nextRow, column: captureColumn });
    }
  });

  return moves;
}

function getKnightMoves(row, column, color, boardState = board) {
  const moves = [];
  const offsets = [[-2, -1], [-2, 1], [-1, -2], [-1, 2], [1, -2], [1, 2], [2, -1], [2, 1]];
  offsets.forEach(([rowOffset, columnOffset]) => {
    const targetRow = row + rowOffset;
    const targetColumn = column + columnOffset;
    if (isInsideBoard(targetRow, targetColumn) && !isFriendly(boardState[targetRow][targetColumn], color)) {
      moves.push({ row: targetRow, column: targetColumn });
    }
  });
  return moves;
}

function getKingMoves(row, column, color, boardState = board) {
  const moves = [];
  for (let rowOffset = -1; rowOffset <= 1; rowOffset += 1) {
    for (let columnOffset = -1; columnOffset <= 1; columnOffset += 1) {
      if (rowOffset === 0 && columnOffset === 0) continue;
      const targetRow = row + rowOffset;
      const targetColumn = column + columnOffset;
      if (isInsideBoard(targetRow, targetColumn) && !isFriendly(boardState[targetRow][targetColumn], color)) {
        moves.push({ row: targetRow, column: targetColumn });
      }
    }
  }

  const homeRow = color === "w" ? 7 : 0;
  if (row === homeRow && column === 4 && !isKingInCheck(boardState, color)) {
    const enemy = color === "w" ? "b" : "w";
    if (castlingRights[`${color}K`] && boardState[homeRow][7] === `${color}r`
      && !boardState[homeRow][5] && !boardState[homeRow][6]
      && !isSquareAttacked(boardState, homeRow, 5, enemy)
      && !isSquareAttacked(boardState, homeRow, 6, enemy)) {
      moves.push({ row: homeRow, column: 6 });
    }
    if (castlingRights[`${color}Q`] && boardState[homeRow][0] === `${color}r`
      && !boardState[homeRow][1] && !boardState[homeRow][2] && !boardState[homeRow][3]
      && !isSquareAttacked(boardState, homeRow, 3, enemy)
      && !isSquareAttacked(boardState, homeRow, 2, enemy)) {
      moves.push({ row: homeRow, column: 2 });
    }
  }
  return moves;
}

function getSlidingMoves(row, column, color, directions, boardState = board) {
  const moves = [];
  directions.forEach(([rowDirection, columnDirection]) => {
    let targetRow = row + rowDirection;
    let targetColumn = column + columnDirection;
    while (isInsideBoard(targetRow, targetColumn)) {
      const targetPiece = boardState[targetRow][targetColumn];
      if (!targetPiece) {
        moves.push({ row: targetRow, column: targetColumn });
      } else {
        if (isOpponent(targetPiece, color)) moves.push({ row: targetRow, column: targetColumn });
        break;
      }
      targetRow += rowDirection;
      targetColumn += columnDirection;
    }
  });
  return moves;
}

function isInsideBoard(row, column) {
  return row >= 0 && row < 8 && column >= 0 && column < 8;
}

function isFriendly(piece, color) {
  return Boolean(piece) && piece[0] === color;
}

function isOpponent(piece, color) {
  return Boolean(piece) && piece[0] !== color;
}

// Find the king of one color on a board.
function findKing(boardState, color) {
  for (let row = 0; row < 8; row += 1) {
    for (let column = 0; column < 8; column += 1) {
      if (boardState[row][column] === `${color}k`) {
        return { row, column };
      }
    }
  }

  return null;
}

// Check whether a square is attacked by any piece of attackingColor.
function isSquareAttacked(boardState, row, column, attackingColor) {
  // A pawn attacks diagonally forward. Reverse the direction to find attackers.
  const pawnRow = row + (attackingColor === "w" ? 1 : -1);
  for (const pawnColumn of [column - 1, column + 1]) {
    if (isInsideBoard(pawnRow, pawnColumn) && boardState[pawnRow][pawnColumn] === `${attackingColor}p`) {
      return true;
    }
  }

  // Knights can attack from any of these eight positions.
  const knightOffsets = [[-2, -1], [-2, 1], [-1, -2], [-1, 2], [1, -2], [1, 2], [2, -1], [2, 1]];
  for (const [rowOffset, columnOffset] of knightOffsets) {
    const attackerRow = row + rowOffset;
    const attackerColumn = column + columnOffset;
    if (isInsideBoard(attackerRow, attackerColumn) && boardState[attackerRow][attackerColumn] === `${attackingColor}n`) {
      return true;
    }
  }

  // Kings attack the squares immediately next to them.
  for (let rowOffset = -1; rowOffset <= 1; rowOffset += 1) {
    for (let columnOffset = -1; columnOffset <= 1; columnOffset += 1) {
      if (rowOffset === 0 && columnOffset === 0) continue;
      const attackerRow = row + rowOffset;
      const attackerColumn = column + columnOffset;
      if (isInsideBoard(attackerRow, attackerColumn) && boardState[attackerRow][attackerColumn] === `${attackingColor}k`) {
        return true;
      }
    }
  }

  // Rooks and queens attack in straight lines.
  const straightDirections = [[-1, 0], [1, 0], [0, -1], [0, 1]];
  if (isAttackedAlongDirections(boardState, row, column, attackingColor, straightDirections, ["r", "q"])) {
    return true;
  }

  // Bishops and queens attack in diagonal lines.
  const diagonalDirections = [[-1, -1], [-1, 1], [1, -1], [1, 1]];
  return isAttackedAlongDirections(boardState, row, column, attackingColor, diagonalDirections, ["b", "q"]);
}

function isAttackedAlongDirections(boardState, row, column, attackingColor, directions, attackingPieces) {
  for (const [rowDirection, columnDirection] of directions) {
    let attackerRow = row + rowDirection;
    let attackerColumn = column + columnDirection;

    while (isInsideBoard(attackerRow, attackerColumn)) {
      const piece = boardState[attackerRow][attackerColumn];

      if (piece) {
        if (piece[0] === attackingColor && attackingPieces.includes(piece[1])) {
          return true;
        }
        // A different piece blocks this direction, so check the next direction.
        break;
      }

      attackerRow += rowDirection;
      attackerColumn += columnDirection;
    }
  }

  return false;
}

function isKingInCheck(boardState, color) {
  const king = findKing(boardState, color);
  if (!king) return true;

  const attackingColor = color === "w" ? "b" : "w";
  return isSquareAttacked(boardState, king.row, king.column, attackingColor);
}

function makeMove(from, to) {
  const movingPiece = board[from.row][from.column];
  if (movingPiece?.[1] === "p" && (to.row === 0 || to.row === 7)) {
    showPromotionPicker(from, to);
    return;
  }

  sendMove(from, to, null);
}

function sendMove(from, to, promotion) {
  // The browser asks the server to make the move. It does not change the
  // official board until the server sends back an accepted game_state.
  const sent = sendServerRequest({
    type: "move",
    from,
    to,
    promotion,
    version: gameVersion,
  });

  if (!sent) return;
  requestInFlight = true;

  selectedSquare = null;
  legalMoves = [];
  updateStatus("Move sent", "Waiting for the server to validate the move.");
  renderBoard();
}

function updatePromotionSymbols() {
  const colorName = playerColor === "b" ? "black" : "white";
  promotionPicker.dataset.color = playerColor === "b" ? "b" : "w";
  promotionButtons.forEach((button) => {
    const pieceType = button.dataset.promotion;
    button.querySelector(".promotion-piece").textContent = pieceSymbols[colorName][pieceTypeName(pieceType)];
  });
}

function showPromotionPicker(from, to) {
  pendingPromotion = { from, to };
  updatePromotionSymbols();
  promotionPicker.hidden = false;

  // Place the picker beside the pawn's destination square. If there is no
  // room on the right, place it on the left while keeping it in the viewport.
  const isFlipped = playerColor === "b";
  const visualRow = isFlipped ? 7 - to.row : to.row;
  const visualColumn = isFlipped ? 7 - to.column : to.column;
  const targetSquare = boardElement.children[visualRow * 8 + visualColumn];
  const targetRect = targetSquare.getBoundingClientRect();
  const pickerRect = promotionPicker.getBoundingClientRect();
  let left = targetRect.right + 4;
  if (left + pickerRect.width > window.innerWidth - 8) {
    left = targetRect.left - pickerRect.width - 4;
  }
  const top = Math.max(8, Math.min(targetRect.top, window.innerHeight - pickerRect.height - 8));

  promotionPicker.style.left = `${Math.max(8, left)}px`;
  promotionPicker.style.top = `${top}px`;
  updateStatus("Choose promotion", "Select a queen, rook, bishop, or knight.");
}

function hidePromotionPicker() {
  pendingPromotion = null;
  promotionPicker.hidden = true;
}

function choosePromotion(piece) {
  if (!pendingPromotion) return;
  const move = pendingPromotion;
  hidePromotionPicker();
  sendMove(move.from, move.to, piece);
}

function updateMoveList() {
  moveCountElement.textContent = `${moveHistory.length} ${moveHistory.length === 1 ? "move" : "moves"}`;
  undoButton.disabled = moveHistory.length === 0;

  if (!moveHistory.length) {
    moveListElement.innerHTML = '<p class="empty-moves">The game has just begun.</p>';
    return;
  }

  moveListElement.innerHTML = "";
  for (let index = 0; index < moveHistory.length; index += 2) {
    const pair = document.createElement("div");
    pair.className = "move-pair";
    pair.innerHTML = `
      <span class="move-number">${index / 2 + 1}.</span>
      <span class="move-name">${moveHistory[index]?.notation ?? ""}</span>
      <span class="move-name">${moveHistory[index + 1]?.notation ?? ""}</span>
    `;
    moveListElement.appendChild(pair);
  }

  moveListElement.scrollTop = moveListElement.scrollHeight;
}

const pieceValues = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };

function capturedMaterial(history) {
  const capturedBy = { w: [], b: [] };
  const points = { w: 0, b: 0 };

  history.forEach((move) => {
    if (!move.capturedPiece) return;
    capturedBy[move.color].push(move.capturedPiece);
    points[move.color] += pieceValues[move.capturedPiece[1]] || 0;
  });

  return { capturedBy, points };
}

function materialText(pieces) {
  if (!pieces.length) return "No captures";
  return pieces.map((piece) => {
    const colorName = piece[0] === "w" ? "white" : "black";
    return pieceSymbols[colorName][pieceTypeName(piece[1])];
  }).join(" ");
}

function profileName(profile, fallback) {
  if (!profile?.username) return fallback;
  return profile.rating === null || profile.rating === undefined
    ? profile.username
    : `${profile.username} (${profile.rating})`;
}

function profileRating(profile, fallback = "") {
  return profile?.rating === null || profile?.rating === undefined
    ? fallback
    : `Rating: ${profile.rating}`;
}

function updatePlayerNames(state) {
  const opponentColor = playerColor === "w" ? "b" : "w";
  const profiles = state.playerProfiles || {};
  const ownProfile = profiles[playerColor] || currentUserProfile;
  const opponentProfile = profiles[opponentColor];
  const opponentName = opponentProfile?.username || state.players?.[opponentColor];

  if (currentPlayerNameElement) {
    currentPlayerNameElement.textContent = profileName(ownProfile, "You");
  }
  if (currentPlayerSubtitleElement) {
    currentPlayerSubtitleElement.textContent = `${playerColor === "b" ? "Black" : "White"}${ownProfile?.rating ? ` · ${ownProfile.rating}` : ""}`;
  }

  if (!opponentName) {
    opponentNameElement.textContent = "Opponent";
    opponentSubtitleElement.innerHTML = '<span class="online-dot"></span> Waiting to join';
    return;
  }

  opponentNameElement.textContent = profileName(opponentProfile, opponentName);
  opponentSubtitleElement.innerHTML = opponentName === "AI"
    ? '<span class="online-dot"></span> Computer opponent'
    : '<span class="online-dot"></span> Playing online';
}

function updateResultOverlay(state) {
  if (!state?.gameOver) {
    resultOverlay.hidden = true;
    return;
  }

  const isDraw = !state.winner;
  const won = state.winner && state.winner === playerColor;
  const profiles = state.playerProfiles || {};
  resultTitleElement.textContent = isDraw ? "Draw" : won ? "You win" : "You lose";

  whiteResultPlayerElement.textContent = profileName(profiles.w, "White");
  blackResultPlayerElement.textContent = profileName(profiles.b, "Black");
  whiteResultRatingElement.textContent = profileRating(profiles.w, "Rating unavailable");
  blackResultRatingElement.textContent = profileRating(profiles.b, "Rating unavailable");

  const ratingChanges = state.ratingChanges || {};
  const ratingChangeText = (color) => {
    const change = ratingChanges[color]?.change;
    if (!Number.isFinite(change) || change === 0) return "No rating change";
    return `${change > 0 ? "+" : ""}${change} rating points`;
  };
  whiteRatingChangeElement.textContent = ratingChangeText("w");
  blackRatingChangeElement.textContent = ratingChangeText("b");

  if (state.status === "timeout") {
    resultMessageElement.textContent = `${state.winner === "w" ? "White" : "Black"} wins on time.`;
  } else if (state.status === "resignation") {
    resultMessageElement.textContent = `${state.winner === "w" ? "White" : "Black"} wins by resignation.`;
  } else if (state.status === "checkmate") {
    resultMessageElement.textContent = `${state.winner === "w" ? "White" : "Black"} wins by checkmate.`;
  } else if (state.status === "stalemate") {
    resultMessageElement.textContent = "The game ended in stalemate.";
  } else if (state.status === "draw_agreement") {
    resultMessageElement.textContent = "Both players agreed to a draw.";
  } else if (state.drawReason === "threefold_repetition") {
    resultMessageElement.textContent = "Draw by threefold repetition.";
  } else if (state.drawReason === "fifty_move_rule") {
    resultMessageElement.textContent = "Draw by the fifty-move rule.";
  } else if (state.drawReason === "insufficient_material") {
    resultMessageElement.textContent = "Draw by insufficient material.";
  } else {
    resultMessageElement.textContent = "The game ended in a draw.";
  }

  if (state.winner && ratingChanges[state.winner]) {
    const winnerProfile = profiles[state.winner];
    const winnerName = winnerProfile?.username || (state.winner === "w" ? "White" : "Black");
    const winnerChange = ratingChanges[state.winner].change;
    resultMessageElement.textContent += ` ${winnerName} gained ${winnerChange >= 0 ? "+" : ""}${winnerChange} rating points.`;
  }

  const material = capturedMaterial(moveHistory);
  whiteResultScoreElement.textContent = `+${material.points.w}`;
  blackResultScoreElement.textContent = `+${material.points.b}`;
  whiteCapturedPiecesElement.textContent = materialText(material.capturedBy.w);
  blackCapturedPiecesElement.textContent = materialText(material.capturedBy.b);
  resultOverlay.hidden = false;
}

function undoLastMove() {
  sendServerRequest({
    type: "undo",
    version: gameVersion,
  });
}


function resetGame() {
  sendServerRequest({ type: "reset", version: gameVersion });
}

function startGame() {
  sendServerRequest({ type: "start_game", version: gameVersion });
}

function offerDraw() {
  sendServerRequest({ type: "offer_draw", version: gameVersion });
}

function resignGame() {
  if (window.confirm("Resign this game?")) {
    sendServerRequest({ type: "resign", version: gameVersion });
  }
}

function updateStatus(title, message) {
  statusTitleElement.textContent = title;
  statusMessageElement.textContent = message;
  const isYourTurn = playerColor && currentTurn === playerColor;
  const turnText = playerColor ? (isYourTurn ? "Your turn" : "Opponent's turn") : "Waiting";
  turnLabelElement.innerHTML = `<span class="turn-dot"></span> ${turnText}`;
}

function updateStartButton(playersReady = false) {
  if (!startGameButton) return;
  startGameButton.disabled = gameStarted || gameOver || !playersReady;
  startGameButton.innerHTML = gameStarted ? "Game started" : "Start game <span>↗</span>";
}

function describePiece(piece) {
  const details = pieceDetails(piece);
  return `${details.color === "w" ? "White" : "Black"} ${pieceTypeName(details.type)}`;
}

function pieceTypeName(type) {
  return { k: "king", q: "queen", r: "rook", b: "bishop", n: "knight", p: "pawn" }[type];
}

function pieceNotation(piece) {
  if (piece[1] === "p") return "";
  return { k: "K", q: "Q", r: "R", b: "B", n: "N" }[piece[1]];
}

function renderClocks() {
  const format = (milliseconds) => {
    const totalSeconds = Math.max(0, Math.ceil(milliseconds / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = String(totalSeconds % 60).padStart(2, "0");
    return `${minutes}:${seconds}`;
  };
  const ownColor = playerColor || "w";
  const opponentColor = ownColor === "w" ? "b" : "w";
  const playerClockElement = document.querySelector("#player-clock");
  const opponentClockElement = document.querySelector("#opponent-clock");
  playerClockElement.textContent = format(clockValues[ownColor]);
  opponentClockElement.textContent = format(clockValues[opponentColor]);

  // The server clock belongs to the side whose turn it is. Highlight only
  // that clock so the player's clock visibly stops during the opponent turn.
  const clockIsRunning = gameStarted && !gameOver;
  playerClockElement.classList.toggle("active-clock", clockIsRunning && currentTurn === ownColor);
  opponentClockElement.classList.toggle("active-clock", clockIsRunning && currentTurn === opponentColor);
}

function applyClockUpdate(message) {
  if (!message || message.version < gameVersion || !message.clocks) return;
  if (!hasServerClockState || message.currentTurn !== currentTurn) {
    clockValues = { ...message.clocks };
    hasServerClockState = true;
  } else {
    // Never let a delayed clock packet make a visible clock increase.
    clockValues = {
      w: Math.min(clockValues.w, message.clocks.w),
      b: Math.min(clockValues.b, message.clocks.b),
    };
  }
  currentTurn = message.currentTurn;
  renderClocks();
}

undoButton.addEventListener("click", undoLastMove);
if (startGameButton) startGameButton.addEventListener("click", startGame);
newGameButton.addEventListener("click", resetGame);
renderBoard();

const gameIdFromUrl = new URLSearchParams(window.location.search).get("game_id");
let gameid = gameIdFromUrl;
const socketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
let socket = null;

function sendServerRequest(request) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(request));
    return true;
  } else {
    updateStatus("Not connected", "Join a room before sending a request.");
    return false;
  }
}

function connectToRoom(roomId) {
  if (!authToken) {
    updateStatus("Log in required", "Create an account or log in before joining a game.");
    return;
  }
  gameid = roomId.trim().toUpperCase();
  if (!gameid) return;

  gameStarted = false;
  gameOver = false;
  updateStartButton(false);
  currentStatus = "playing";
  hidePromotionPicker();
  lastServerState = null;
  playerColor = null;
  renderBoard();
  requestInFlight = false;
  aiThinking = false;
  selectedSquare = null;
  legalMoves = [];
  gameVersion = 0;
  hasServerClockState = false;
  clockValues = { w: 0, b: 0 };

  roomInput.value = gameid;
  roomHelperElement.textContent = `Room ${gameid} is connecting...`;
  const roomUrl = new URL(window.location.href);
  roomUrl.searchParams.set("game_id", gameid);
  window.history.replaceState({}, "", roomUrl);

  socket = new WebSocket(`${socketProtocol}://${window.location.host}/ws/game/${gameid}?token=${encodeURIComponent(authToken)}`);
  socket.addEventListener("message", handleSocketMessage);
  
  socket.addEventListener("close", () => {
    gameStarted = false;
    requestInFlight = false;
    aiThinking = false;
    roomHelperElement.textContent = "This room is no longer connected.";
  });

}

async function createRoom() {
  if (!authToken) {
    authHelperElement.textContent = "Log in before creating a room.";
    return;
  }
  createRoomButton.disabled = true;
  roomHelperElement.textContent = "Creating a room...";

  try {
    const response = await fetch("/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
      body: JSON.stringify({ mode: "human", time_control: Number(timeControlElement.value) }),
    });
    if (!response.ok) throw new Error("Room creation failed");

    const room = await response.json();
    copyRoomLinkButton.hidden = false;
    roomHelperElement.textContent = `Share this page with your friend: room ${room.game_id}`;
    connectToRoom(room.game_id);
  } catch (error) {
    roomHelperElement.textContent = "Could not create a room. Please try again.";
  } finally {
    createRoomButton.disabled = false;
  }
}

async function createAiRoom() {
  if (!authToken) {
    authHelperElement.textContent = "Log in before starting an AI game.";
    return;
  }
  const response = await fetch("/rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
    body: JSON.stringify({ mode: "ai", time_control: Number(timeControlElement.value) }),
  });
  if (!response.ok) {
    roomHelperElement.textContent = "Could not start an AI game.";
    return;
  }
  const room = await response.json();
  roomHelperElement.textContent = "Starting your AI game...";
  connectToRoom(room.game_id);
}

async function joinRankedMatch() {
  if (!authToken) {
    authHelperElement.textContent = "Log in before joining ranked matchmaking.";
    return;
  }
  const response = await fetch("/matchmaking/join", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${authToken}` },
    body: JSON.stringify({ time_control: Number(timeControlElement.value) }),
  });
  const result = await response.json();
  if (result.status === "matched") {
    connectToRoom(result.game_id);
    return;
  }
  roomHelperElement.textContent = "Waiting for a similarly rated player...";
  clearInterval(matchmakingTimer);
  matchmakingTimer = setInterval(checkMatchmakingStatus, 2000);
}

async function checkMatchmakingStatus() {
  const response = await fetch("/matchmaking/status", { headers: { Authorization: `Bearer ${authToken}` } });
  if (!response.ok) return;
  const result = await response.json();
  if (result.status === "matched") {
    clearInterval(matchmakingTimer);
    roomHelperElement.textContent = "Opponent found.";
    connectToRoom(result.game_id);
  }
}

async function authenticate(path) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: usernameInput.value, password: passwordInput.value }),
  });
  const result = await response.json();
  if (!response.ok) {
    authHelperElement.textContent = result.detail || "Authentication failed.";
    return;
  }
  authToken = result.token;
  currentUserProfile = result.user;
  localStorage.setItem("chess_token", authToken);
  authHelperElement.textContent = `Signed in as ${result.user.username} · rating ${result.user.rating}`;
}

function joinRoom() {
  const roomId = roomInput.value.trim();
  if (!roomId) {
    roomHelperElement.textContent = "Enter a room code first.";
    return;
  }
  
  // The backend decides whether the room is valid or full.
  connectToRoom(roomId);
}

// Apply a board state received from the backend and redraw the board.
function applyBackendState(state) {
  if (!state || !Array.isArray(state.board)) return;
  if (Number.isInteger(state.version) && state.version < gameVersion) return;

  lastServerState = state;
  updatePlayerNames(state);

  const previousVersion = gameVersion;
  const previousTurn = currentTurn;
  const previousStatus = currentStatus;
  const boardChanged = state.version !== previousVersion;
  const turnChanged = state.currentTurn !== previousTurn;
  const statusChanged = state.status !== previousStatus;

  board = state.board.map((row) => [...row]);
  currentTurn = state.currentTurn;
  currentStatus = state.status || "playing";
  if (typeof state.started === "boolean") {
    gameStarted = state.started;
  }
  moveHistory = Array.isArray(state.moveHistory) ? state.moveHistory : [];
  lastMove = Array.isArray(state.lastMove) ? state.lastMove : null;
  gameVersion = state.version;
  castlingRights = state.castlingRights || {};
  enPassantTarget = state.enPassantTarget || null;
  if (state.clocks) {
    if (!hasServerClockState || boardChanged || turnChanged) {
      clockValues = { ...state.clocks };
      hasServerClockState = true;
    } else {
      // A delayed WebSocket snapshot must never make a visible clock increase.
      clockValues = {
        w: Math.min(clockValues.w, state.clocks.w),
        b: Math.min(clockValues.b, state.clocks.b),
      };
    }
  }
  gameOver = Boolean(state.gameOver);
  if (boardChanged) {
    selectedSquare = null;
    legalMoves = [];
    requestInFlight = false;
  }
  if (Object.prototype.hasOwnProperty.call(state, "aiThinking")) {
    aiThinking = Boolean(state.aiThinking);
  } else if (!aiThinking || state.currentTurn === playerColor) {
    aiThinking = false;
  }

  updateMoveList();
  if (gameStarted) {
    updateServerStatus(state);
  } else if (Object.keys(state.players || {}).length >= 2) {
    updateStatus("Ready to start", "Press Start game when both players are ready.");
  } else {
    updateStatus("Waiting for opponent", "The board is ready when another player joins.");
  }
  updateResultOverlay(state);
  updateStartButton(Object.keys(state.players || {}).length >= 2);
  if (boardChanged || statusChanged) renderBoard();
  renderClocks();
}

function updateServerStatus(state) {
  const sideName = state.currentTurn === "w" ? "White" : "Black";
  const winnerName = state.winner === "w" ? "White" : "Black";
  const resultLabel = !state.winner
    ? "Draw"
    : state.winner === playerColor
      ? "You win"
      : "You lose";

  // The status card contains the exact reason. The turn pill contains the
  // result from this player's point of view after the game has ended.
  const showFinishedResult = () => {
    turnLabelElement.innerHTML = `<span class="turn-dot"></span> ${resultLabel}`;
  };

  if (state.status === "checkmate") {
    updateStatus("Checkmate", `${sideName} is checkmated. ${winnerName} wins.`);
    showFinishedResult();
  } else if (state.status === "stalemate") {
    updateStatus("Stalemate", "There are no legal moves. The game is a draw.");
    showFinishedResult();
  } else if (state.status === "check") {
    updateStatus("Check", `${sideName} is in check. Protect the king.`);
  } else if (state.status.startsWith("draw_")) {
    updateStatus("Draw", state.drawReason || "The game is drawn.");
    showFinishedResult();
  } else if (state.status === "timeout") {
    updateStatus("Time expired", `${winnerName} wins on time.`);
    showFinishedResult();
  } else if (state.status === "resignation") {
    updateStatus("Resignation", `${winnerName} wins.`);
    showFinishedResult();
  } else if (state.status === "draw_agreement") {
    updateStatus("Draw agreed", "Both players accepted a draw.");
    showFinishedResult();
  } else {
    updateStatus(`${sideName} to move`, "Choose a piece to see its possible moves.");
  }
}

function handleSocketMessage(event) {
  const message = JSON.parse(event.data);

  // Save the color assigned by the backend before the game starts.
  if (message.type === "player_color") {
    playerColor = message.color;
    renderBoard();
    roomHelperElement.textContent = message.message;
  }

  // The first player receives this message while waiting for player two.
  if (message.type === "waiting") {
    gameStarted = false;
    updateStartButton(false);
    updateStatus("Waiting for opponent", message.message);
    turnLabelElement.innerHTML = '<span class="turn-dot"></span> Waiting';
    roomHelperElement.textContent = `Room ${message.game_id} is waiting for a second player.`;
  }

  if (message.type === "game_ready") {
    gameStarted = false;
    if (startGameButton) startGameButton.disabled = false;
    updateStatus("Ready to start", message.message);
    turnLabelElement.innerHTML = '<span class="turn-dot"></span> Ready';
    roomHelperElement.textContent = `Room ${message.game_id} is ready.`;
  }

  // Both players receive this message when the room is ready.
  if (message.type === "game_started") {
    gameStarted = true;
    updateStartButton(true);
    updateStatus("Game started", message.message);
    turnLabelElement.innerHTML = '<span class="turn-dot"></span> Ready';
    roomHelperElement.textContent = `Room ${message.game_id} is ready.`;
  }

  // A player's move arrives here and updates this browser's board.
  if (message.type === "game_state") {
    applyBackendState(message.state);
    if (!message.state.drawOffer) lastSeenDrawOffer = null;
    if (message.state.drawOffer && message.state.drawOffer !== playerColor && message.state.drawOffer !== lastSeenDrawOffer) {
      lastSeenDrawOffer = message.state.drawOffer;
      const accepted = window.confirm("Your opponent offered a draw. Accept?");
      sendServerRequest({ type: "answer_draw", accept: accepted, version: gameVersion });
    }
  }

  if (message.type === "clock_update") {
    applyClockUpdate(message);
  }

  if (message.type === "draw_offer") {
    const accepted = window.confirm("Your opponent offered a draw. Accept?");
    sendServerRequest({ type: "answer_draw", accept: accepted, version: gameVersion });
  }

  if (message.type === "ai_error") {
    aiThinking = false;
    updateStatus("AI unavailable", message.message);
  }

  if (message.type === "ai_warning") {
    aiThinking = false;
    updateStatus("AI move completed", message.message);
  }

  if (message.type === "request_rejected") {
    requestInFlight = false;
    selectedSquare = null;
    legalMoves = [];
    if (message.state) applyBackendState(message.state);
    updateStatus("Request rejected", message.reason);
    renderBoard();
  }

  if (message.type === "ai_thinking") {
    aiThinking = true;
    selectedSquare = null;
    legalMoves = [];
    updateStatus("AI is thinking", "Stockfish is choosing a move.");
    renderBoard();
  }

  // Stop allowing moves if the other player disconnects.
  if (message.type === "player_left") {
    gameStarted = false;
    updateStartButton(false);
    updateStatus("Opponent disconnected", "Waiting for the other player to reconnect.");
    turnLabelElement.innerHTML = '<span class="turn-dot"></span> Waiting';
  }
}

createRoomButton.addEventListener("click", createRoom);
joinRoomButton.addEventListener("click", joinRoom);
createAiRoomButton.addEventListener("click", createAiRoom);
rankedMatchButton.addEventListener("click", joinRankedMatch);
loginButton.addEventListener("click", () => authenticate("/auth/login"));
registerButton.addEventListener("click", () => authenticate("/auth/register"));
offerDrawButton.addEventListener("click", offerDraw);
resignButton.addEventListener("click", resignGame);
resultNewGameButton.addEventListener("click", () => {
  resultOverlay.hidden = true;
  resetGame();
});
resultCloseButton.addEventListener("click", () => {
  resultOverlay.hidden = true;
});
promotionButtons.forEach((button) => {
  button.addEventListener("click", () => choosePromotion(button.dataset.promotion));
});
cancelPromotionButton.addEventListener("click", () => {
  hidePromotionPicker();
  selectedSquare = null;
  legalMoves = [];
  updateStatus("Promotion cancelled", "Choose a piece to continue.");
  renderBoard();
});

copyRoomLinkButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(window.location.href);
  roomHelperElement.textContent = "Invite link copied.";
});

// If somebody opens an invite link, join that room automatically.
if (gameIdFromUrl) {
  roomInput.value = gameIdFromUrl;
  connectToRoom(gameIdFromUrl);
}

if (authToken) {
  fetch("/auth/me", { headers: { Authorization: `Bearer ${authToken}` } })
    .then((response) => response.ok ? response.json() : Promise.reject(new Error("expired")))
    .then((user) => {
      currentUserProfile = user;
      authHelperElement.textContent = `Signed in as ${user.username} · rating ${user.rating}`;
    })
    .catch(() => {
      localStorage.removeItem("chess_token");
      authToken = null;
      authHelperElement.textContent = "Your session expired. Please log in again.";
    });
}
