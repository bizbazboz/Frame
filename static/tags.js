document.querySelectorAll('.tag-dropdown').forEach(dropdown => {
  const update = () => {
    const checked = [...dropdown.querySelectorAll('input[name="tag"]:checked')];
    dropdown.querySelector('.tag-summary').textContent = checked.length ? `${checked.length} selected` : 'Choose tags';
  };
  dropdown.addEventListener('change', update);
  dropdown.querySelector('.clear-tags')?.addEventListener('click', () => {
    dropdown.querySelectorAll('input[name="tag"]').forEach(input => { input.checked = false; }); update();
  });
  dropdown.querySelector('.tag-search')?.addEventListener('input', event => {
    const value = event.target.value.toLowerCase();
    dropdown.querySelectorAll('[data-tag-option]').forEach(option => { option.hidden = !option.textContent.toLowerCase().includes(value); });
  });
  dropdown.addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.classList.contains('tag-search')) event.preventDefault(); if (event.key === 'Escape') { dropdown.open = false; dropdown.querySelector('summary').focus(); } });
});
document.addEventListener('click', event => {
  document.querySelectorAll('.tag-dropdown[open]').forEach(dropdown => { if (!dropdown.contains(event.target)) dropdown.open = false; });
});
document.querySelectorAll('[data-preview]').forEach(button => button.addEventListener('click', () => {
  const preview = document.querySelector('#version-preview'); preview.src = button.dataset.preview; preview.alt = button.dataset.alt;
  const caption = document.querySelector('[data-preview-label]'); if (caption) caption.textContent = button.dataset.label || button.textContent.trim();
  document.querySelectorAll('[data-preview]').forEach(tile => { const selected = tile === button; tile.classList.toggle('selected', selected); tile.setAttribute('aria-pressed', selected); });
}));
document.querySelectorAll('[data-destination]').forEach(destination => {
  const checkbox = destination.querySelector('input[name="accounts"]');
  const status = destination.querySelector('[data-post-status]');
  const update = () => {
    destination.querySelector('.destination-fields').hidden = !checkbox.checked;
    destination.querySelectorAll('.destination-fields input,.destination-fields select').forEach(field => { field.disabled = !checkbox.checked; });
    destination.querySelector('.publication-fields').hidden = status.value !== 'published';
  };
  checkbox.addEventListener('change', update); status.addEventListener('change', update); update();
});
document.querySelector('[data-version-select]')?.addEventListener('change', event => {
  document.querySelector('[data-campaign-preview]').src = event.target.selectedOptions[0].dataset.image;
});
document.querySelectorAll('[data-upload-control]').forEach(control => {
  const input = control.querySelector('[data-file-picker]');
  const selection = control.querySelector('[data-upload-selection]');
  const clear = control.querySelector('[data-upload-clear]');
  const update = () => {
    const files = [...input.files];
    const bytes = files.reduce((total, file) => total + file.size, 0);
    const size = bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    const folder = files[0]?.webkitRelativePath?.split('/')[0];
    selection.textContent = files.length ? `${folder ? folder + ' · ' : ''}${files.length} ${files.length === 1 ? 'file' : 'files'} selected · ${size}` : (input.hasAttribute('webkitdirectory') ? 'No folder selected' : 'No files selected');
    if (files.length) {
      const names = document.createElement('small');
      names.textContent = files.slice(0, 3).map(file => file.name).join(', ') + (files.length > 3 ? ` +${files.length - 3} more` : '');
      selection.append(names);
    }
    clear.hidden = !files.length;
    control.classList.toggle('has-files', files.length > 0);
    const form = input.closest('form');
    const total = form.querySelector('.upload-count');
    if (total) {
      const all = [...form.querySelectorAll('[data-file-picker]')].flatMap(picker => [...picker.files]);
      const totalBytes = all.reduce((sum, file) => sum + file.size, 0);
      const totalSize = totalBytes < 1024 * 1024 ? `${(totalBytes / 1024).toFixed(1)} KB` : `${(totalBytes / 1024 / 1024).toFixed(1)} MB`;
      total.textContent = all.length ? `${all.length} ${all.length === 1 ? 'file' : 'files'} ready to import · ${totalSize}` : 'No files selected';
    }
  };
  input.addEventListener('change', update);
  clear.addEventListener('click', () => { input.value = ''; update(); input.focus(); });
});
document.querySelector('[data-upload-form]')?.addEventListener('submit', event => {
  if (![...document.querySelectorAll('[data-file-picker]')].some(input => input.files.length)) { event.preventDefault(); document.querySelector('.upload-count').textContent = 'Choose at least one image or folder first.'; return; }
  const button = document.querySelector('[data-upload-button]'); button.disabled = true; button.textContent = 'Importing…';
});
const menuToggle = document.querySelector('[data-menu-toggle]');
const sidebar = document.querySelector('#app-navigation');
const appBody = document.querySelector('.app-body');
function closeMenu() {
  document.body.classList.remove('menu-open');
  appBody.inert = false;
  menuToggle?.setAttribute('aria-expanded', 'false');
  menuToggle?.focus();
}
menuToggle?.addEventListener('click', () => {
  document.body.classList.add('menu-open');
  menuToggle.setAttribute('aria-expanded', 'true');
  appBody.inert = true;
  sidebar.querySelector('[data-menu-close]').focus();
});
document.querySelectorAll('[data-menu-close]').forEach(button => button.addEventListener('click', closeMenu));
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('menu-open')) return;
  if (event.key === 'Escape') { event.preventDefault(); closeMenu(); }
  if (event.key === 'Tab') {
    const items = [...sidebar.querySelectorAll('a[href],button:not([disabled])')].filter(el => el.getClientRects().length);
    const first = items[0], last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
window.matchMedia('(min-width:768px)').addEventListener('change', event => {
  if (event.matches && document.body.classList.contains('menu-open')) closeMenu();
});
document.querySelector('[data-admin-search]')?.addEventListener('input', event => {
  const query = event.target.value.toLowerCase().trim();
  const items = [...document.querySelectorAll('[data-admin-item]')];
  items.forEach(item => { item.hidden = !item.querySelector('summary').textContent.toLowerCase().includes(query); });
  document.querySelector('[data-admin-empty]').hidden = !query || items.some(item => !item.hidden);
});
const reviewForm = document.querySelector('[data-review-form]');
if (reviewForm) {
  reviewForm.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.target.tagName !== 'INPUT') return;
    if (event.target.classList.contains('tag-search')) event.preventDefault();
  });
  reviewForm.addEventListener('submit', event => {
    if (reviewForm.classList.contains('is-submitting')) { event.preventDefault(); return; }
    const action = document.createElement('input');
    action.type = 'hidden'; action.name = 'action'; action.value = event.submitter?.value || 'save';
    action.dataset.reviewAction = '';
    reviewForm.append(action);
    reviewForm.querySelectorAll('button[type="submit"]:not(:disabled)').forEach(button => { button.dataset.reviewBusy = ''; button.disabled = true; });
    reviewForm.classList.add('is-submitting');
    reviewForm.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    reviewForm.querySelectorAll('[data-review-action]').forEach(input => input.remove());
    reviewForm.querySelectorAll('[data-review-busy]').forEach(button => { button.disabled = false; delete button.dataset.reviewBusy; });
    reviewForm.classList.remove('is-submitting'); reviewForm.removeAttribute('aria-busy');
  });
}
const bulkSelection = document.querySelector('#bulk-selection');
if (bulkSelection) {
  const boxes = [...document.querySelectorAll('[data-photo-select]')];
  const selectAll = bulkSelection.querySelector('[data-select-all]');
  const update = () => {
    const count = boxes.filter(box => box.checked).length;
    const returnFocus = count === 0 && bulkSelection.contains(document.activeElement);
    bulkSelection.hidden = count === 0;
    bulkSelection.querySelector('.bulk-count').textContent = `${count} selected`;
    if (returnFocus) boxes[0]?.focus({preventScroll: true});
    selectAll.checked = count > 0 && count === boxes.length;
    selectAll.indeterminate = count > 0 && count < boxes.length;
    bulkSelection.querySelectorAll('[data-bulk-action],[data-clear-selection]').forEach(button => { button.disabled = count === 0; });
    boxes.forEach(box => box.closest('.selectable-photo').classList.toggle('is-selected', box.checked));
  };
  boxes.forEach(box => box.addEventListener('change', update));
  selectAll.addEventListener('change', () => { boxes.forEach(box => { box.checked = selectAll.checked; }); update(); });
  bulkSelection.querySelector('[data-clear-selection]').addEventListener('click', () => { boxes.forEach(box => { box.checked = false; }); update(); });
  window.addEventListener('pageshow', update);
  update();
}
document.querySelectorAll('[data-user-avatar]').forEach(avatar => {
  const fallback = () => { avatar.hidden = true; };
  avatar.addEventListener('error', fallback);
  if (avatar.complete && !avatar.naturalWidth) fallback();
});
