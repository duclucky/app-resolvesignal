/* Native adaptation of the React Bits Spotlight Card pointer light.
 * (c) 2026 David Haz. MIT + Commons Clause; see ../../THIRD_PARTY_NOTICES.md.
 * No global pointer listeners or continuous animation loop. */
(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  for (const card of document.querySelectorAll('.spotlight-card')) {
    card.addEventListener('pointermove', event => {
      if (reduced.matches || event.pointerType !== 'mouse') return;
      const box = card.getBoundingClientRect();
      card.style.setProperty('--light-x', `${event.clientX-box.left}px`);
      card.style.setProperty('--light-y', `${event.clientY-box.top}px`);
    }, {passive:true});
    card.addEventListener('pointerleave', () => {
      card.style.removeProperty('--light-x'); card.style.removeProperty('--light-y');
    });
  }
})();
