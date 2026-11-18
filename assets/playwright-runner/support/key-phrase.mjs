const KEY_NAMES = {
  enter: 'Enter', return: 'Enter', 回车: 'Enter', tab: 'Tab', escape: 'Escape', esc: 'Escape',
  arrowdown: 'ArrowDown', arrowup: 'ArrowUp', arrowleft: 'ArrowLeft', arrowright: 'ArrowRight',
  space: 'Space', 空格: 'Space', backspace: 'Backspace', delete: 'Delete',
};

/** A press phrase is a key command. A control whose visible name is Enter stays a click. */
export function keyFromPhrase(text) {
  const raw = String(text ?? '').trim().replace(/\s+/gu, ' ')
    .replace(/^(?:click:text=|text=)/iu, '').replace(/^[?？]/u, '');
  if (/^(?:按回车键|按回车|按下回车键|按下回车)$/u.test(raw)) return 'Enter';
  const match = /^(?:please\s+)?(?:press|hit|tap|按下|按|敲)(?:\s*(?:一下|the|键))?\s*(enter|return|回车|tab|escape|esc|arrow\s*down|arrow\s*up|arrow\s*left|arrow\s*right|space|空格|backspace|delete)(?:\s*键)?$/iu.exec(raw);
  if (!match) return null;
  return KEY_NAMES[match[1].replace(/\s+/gu, '').toLowerCase()] ?? null;
}
