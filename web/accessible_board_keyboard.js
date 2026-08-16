(function (global) {
  'use strict';

  const SQUARE_RE = /^[a-h][1-8]$/;
  const NAVIGATION_KEYS = new Set([
    'ArrowLeft',
    'ArrowRight',
    'ArrowUp',
    'ArrowDown',
    'Home',
    'End',
  ]);

  function normalizeSquare(value) {
    const square = String(value || '').replace(/\s/g, '').toLowerCase();
    return SQUARE_RE.test(square) ? square : null;
  }

  function squareName(square) {
    const normalized = normalizeSquare(square);
    return normalized ? normalized[0] + ' ' + normalized[1] : '';
  }

  function squareIndex(square) {
    const normalized = normalizeSquare(square);
    if (!normalized) return null;
    return {
      file: normalized.charCodeAt(0) - 97,
      rank: Number(normalized[1]) - 1,
    };
  }

  function indexSquare(file, rank) {
    if (file < 0 || file > 7 || rank < 0 || rank > 7) return null;
    return String.fromCharCode(97 + file) + String(rank + 1);
  }

  function moveSquare(square, key) {
    const index = squareIndex(square);
    if (!index) return null;
    let { file, rank } = index;
    if (key === 'ArrowLeft') file = Math.max(0, file - 1);
    else if (key === 'ArrowRight') file = Math.min(7, file + 1);
    else if (key === 'ArrowUp') rank = Math.min(7, rank + 1);
    else if (key === 'ArrowDown') rank = Math.max(0, rank - 1);
    else if (key === 'Home') return 'a1';
    else if (key === 'End') return 'h8';
    else return normalizeSquare(square);
    return indexSquare(file, rank);
  }

  function create(options) {
    const board = options && options.board;
    if (!board || typeof board.querySelectorAll !== 'function') {
      throw new Error('Accessible board requires a board element.');
    }
    const onActivate = options && typeof options.onActivate === 'function'
      ? options.onActivate
      : null;
    let currentSquare = normalizeSquare(options && options.initialSquare) || 'a1';

    function cells() {
      return Array.from(board.querySelectorAll('[role="gridcell"][data-square]'));
    }

    function cellFor(square) {
      const normalized = normalizeSquare(square);
      return normalized ? board.querySelector(`[data-square="${normalized}"]`) : null;
    }

    function syncRovingTabindex() {
      const available = cells();
      if (!available.length) return null;
      if (!cellFor(currentSquare)) {
        currentSquare = normalizeSquare(available[0].dataset.square) || 'a1';
      }
      available.forEach((cell) => {
        cell.tabIndex = cell.dataset.square === currentSquare ? 0 : -1;
      });
      return cellFor(currentSquare);
    }

    function focus(square) {
      const normalized = normalizeSquare(square);
      if (!normalized) return false;
      currentSquare = normalized;
      const cell = syncRovingTabindex();
      if (!cell || typeof cell.focus !== 'function') return false;
      cell.focus();
      return true;
    }

    async function onKeyDown(event) {
      const target = event.target && event.target.closest
        ? event.target.closest('[role="gridcell"][data-square]')
        : null;
      if (!target || !board.contains(target)) return;
      const square = normalizeSquare(target.dataset.square);
      if (!square) return;
      currentSquare = square;

      if (NAVIGATION_KEYS.has(event.key)) {
        event.preventDefault();
        focus(moveSquare(square, event.key));
        return;
      }

      if ((event.key === 'Enter' || event.key === ' ') && onActivate) {
        event.preventDefault();
        await onActivate(square, event);
      }
    }

    function onFocusIn(event) {
      const target = event.target && event.target.closest
        ? event.target.closest('[role="gridcell"][data-square]')
        : null;
      if (!target || !board.contains(target)) return;
      const square = normalizeSquare(target.dataset.square);
      if (!square) return;
      currentSquare = square;
      syncRovingTabindex();
    }

    board.addEventListener('keydown', onKeyDown);
    board.addEventListener('focusin', onFocusIn);

    return {
      normalizeSquare,
      squareName,
      moveSquare,
      get currentSquare() { return currentSquare; },
      setCurrentSquare(square) {
        const normalized = normalizeSquare(square);
        if (!normalized) return false;
        currentSquare = normalized;
        syncRovingTabindex();
        return true;
      },
      syncRovingTabindex,
      focus,
      destroy() {
        board.removeEventListener('keydown', onKeyDown);
        board.removeEventListener('focusin', onFocusIn);
      },
    };
  }

  global.AccessibleChessBoardKeyboard = {
    normalizeSquare,
    squareName,
    moveSquare,
    create,
  };
})(window);
