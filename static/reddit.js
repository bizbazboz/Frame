const redditSync = document.querySelector('[data-reddit-sync]');
if (redditSync) {
  const status = document.querySelector('[data-sync-status]');
  const pause = redditSync.querySelector('[data-sync-pause]');
  const submit = redditSync.querySelector('button[type="submit"], button:not([type])');
  let running = false;
  let paused = false;
  pause.addEventListener('click', () => {
    paused = true;
    pause.disabled = true;
    status.textContent = 'Pausing after this page…';
  });
  redditSync.addEventListener('submit', async event => {
    event.preventDefault();
    if (running) return;
    running = true;
    paused = false;
    submit.disabled = true;
    pause.disabled = false;
    pause.hidden = false;
    let reset = redditSync.dataset.complete === 'true';
    try {
      while (true) {
        status.textContent = 'Fetching archived posts…';
        const body = new FormData(redditSync);
        if (reset) body.set('reset', '1');
        const response = await fetch(redditSync.action, {method: 'POST', body, credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
        if (response.redirected) throw new Error('Sign in again to continue syncing.');
        if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Sync failed. Reload this page and try again.');
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Sync failed. Saved progress is retained.');
        reset = false;
        redditSync.dataset.complete = 'false';
        status.textContent = `${result.count.toLocaleString()} posts saved${result.complete ? ' · Complete' : ''}`;
        if (result.complete || paused) {
          location.reload();
          return;
        }
        await new Promise(resolve => setTimeout(resolve, 1100));
        if (paused) { location.reload(); return; }
      }
    } catch (error) {
      status.textContent = error.message;
    } finally {
      running = false;
      submit.disabled = false;
      submit.textContent = 'Resume sync';
      pause.hidden = true;
    }
  });
}
