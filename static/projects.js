(() => {
  const project = document.body.dataset.projectContext;
  if (project) {
    const url = new URL(window.location.href);
    if (!url.searchParams.has('project')) {
      url.searchParams.set('project', project);
      window.history.replaceState(window.history.state, '', url);
    }
  }
  const form = document.querySelector('[data-project-switch-form]');
  if (!form) return;
  const select = form.querySelector('[data-project-switch]');
  form.classList.add('is-enhanced');
  select.addEventListener('change', () => form.requestSubmit());
})();
