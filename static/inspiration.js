(() => {
  const frames = [...document.querySelectorAll('[data-inspiration-embed="reddit"]')];
  window.addEventListener('message', event => {
    if (event.origin !== 'https://embed.reddit.com') return;
    const frame = frames.find(candidate => candidate.contentWindow === event.source);
    if (!frame) return;
    let message = event.data;
    if (typeof message === 'string') {
      try { message = JSON.parse(message); } catch { return; }
    }
    if (message?.type !== 'resize.embed') return;
    const height = Number(message.data);
    if (Number.isFinite(height) && height > 0) {
      frame.style.height = `${Math.min(1600, Math.max(180, height))}px`;
    }
  });
})();
