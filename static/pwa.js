(() => {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'})
      .catch(error => console.warn('Frame service worker registration failed:', error));
  });
  const button = document.querySelector('[data-pwa-install]');
  if (!button) return;
  let installPrompt;
  const standalone = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    button.hidden = Boolean(standalone());
  });
  button.addEventListener('click', async () => {
    if (!installPrompt) return;
    const prompt = installPrompt;
    installPrompt = null;
    button.hidden = true;
    try {
      await prompt.prompt();
      await prompt.userChoice;
    } catch (error) {
      console.warn('Frame install prompt failed:', error);
    }
  });
  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    button.hidden = true;
  });
})();
