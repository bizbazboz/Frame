(() => {
  const form = document.querySelector('[data-import-form]');
  if (!form || typeof DataTransfer === 'undefined') return;
  const payload = form.querySelector('[data-import-payload]');
  const photos = form.querySelector('[data-import-photos]');
  const folders = form.querySelector('[data-import-folder]');
  const dropzone = form.querySelector('[data-import-dropzone]');
  const list = form.querySelector('[data-import-list]');
  const empty = form.querySelector('[data-import-empty]');
  const clear = form.querySelector('[data-import-clear]');
  const submit = form.querySelector('[data-import-submit]');
  const total = form.querySelector('[data-import-total]');
  const feedback = form.querySelector('[data-import-feedback]');
  const previewCount = form.querySelector('[data-import-preview-count]');
  const template = document.querySelector('#import-file-template');
  const limit = 512 * 1024 * 1024;
  let queue = [], busy = false, reading = false, dragDepth = 0;
  payload.disabled = false;
  photos.removeAttribute('name');
  folders.removeAttribute('name');

  const formatSize = bytes => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${bytes} B`;
  const message = value => { feedback.textContent = value; feedback.hidden = !value; };
  const revoke = entry => { if (entry.url) URL.revokeObjectURL(entry.url); };
  function render() {
    const transfer = new DataTransfer();
    queue.forEach(entry => transfer.items.add(entry.file));
    payload.files = transfer.files;
    const bytes = queue.reduce((sum, entry) => sum + entry.file.size, 0);
    total.textContent = `${queue.length} ${queue.length === 1 ? 'file' : 'files'}${queue.length ? ' · ' + formatSize(bytes) : ''}`;
    submit.disabled = busy || reading || !queue.length || bytes > limit;
    clear.disabled = busy || reading || !queue.length;
    empty.hidden = queue.length > 0;
    list.hidden = !queue.length;
    list.replaceChildren();
    const fragment = document.createDocumentFragment();
    queue.slice(0, 50).forEach(entry => {
      const row = template.content.firstElementChild.cloneNode(true);
      const image = row.querySelector('img');
      if (!entry.url) entry.url = URL.createObjectURL(entry.file);
      image.addEventListener('error', () => { image.hidden = true; });
      image.src = entry.url;
      row.querySelector('.import-file-name strong').textContent = entry.file.name;
      row.querySelector('.import-file-name strong').title = entry.path;
      const path = row.querySelector('.import-file-name span');
      path.textContent = `${entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) + ' · ' : ''}${formatSize(entry.file.size)}`;
      const remove = row.querySelector('button');
      remove.setAttribute('aria-label', `Remove ${entry.file.name}`);
      remove.disabled = busy || reading;
      remove.addEventListener('click', () => {
        const index = queue.indexOf(entry);
        revoke(entry);
        queue.splice(index, 1);
        message(''); render();
        const next = list.querySelectorAll('button')[Math.min(index, 49)] || list.querySelector('button');
        if (next) next.focus({preventScroll:true}); else photos.focus({preventScroll:true});
      });
      fragment.append(row);
    });
    list.append(fragment);
    previewCount.hidden = queue.length <= 50;
    previewCount.textContent = `50 of ${queue.length} files shown`;
    form.classList.toggle('has-selection', queue.length > 0);
    form.classList.toggle('over-limit', bytes > limit);
    if (bytes > limit) message('Selection exceeds the 512 MB upload limit.');
  }
  async function sameContents(left, right) {
    if (left.size !== right.size) return false;
    const chunkSize = 1024 * 1024;
    for (let offset = 0; offset < left.size; offset += chunkSize) {
      const [a, b] = await Promise.all([
        left.slice(offset, offset + chunkSize).arrayBuffer(),
        right.slice(offset, offset + chunkSize).arrayBuffer()
      ]);
      const first = new Uint8Array(a), second = new Uint8Array(b);
      if (first.some((value, index) => value !== second[index])) return false;
    }
    return true;
  }
  async function addFiles(entries) {
    let skipped = 0, duplicates = 0, unreadable = 0;
    reading = true; photos.disabled = folders.disabled = true;
    form.setAttribute('aria-busy', 'true'); message('Checking files�'); render();
    try {
      for (const item of entries) {
        const file = item.file || item;
        if (!/\.(jpe?g|png|gif|webp|avif)$/i.test(file.name)) { skipped++; continue; }
        try {
          let duplicate = false;
          for (const entry of queue) {
            if (await sameContents(entry.file, file)) { duplicate = true; break; }
          }
          if (duplicate) { duplicates++; continue; }
          const path = item.path || file.webkitRelativePath || file.name;
          queue.push({file, path});
        } catch { unreadable++; }
      }
    } finally {
      reading = false; photos.disabled = folders.disabled = false;
      form.removeAttribute('aria-busy');
      message([
        duplicates ? `${duplicates} duplicate ${duplicates === 1 ? 'file' : 'files'} skipped.` : '',
        skipped ? `${skipped} unsupported ${skipped === 1 ? 'file' : 'files'} skipped.` : '',
        unreadable ? `${unreadable} files could not be read.` : ''
      ].filter(Boolean).join(' '));
      render();
    }
  }
  [photos, folders].forEach(input => input.addEventListener('change', async () => {
    const files = [...input.files]; input.value = '';
    if (!busy && !reading) await addFiles(files);
  }));
  clear.addEventListener('click', () => { queue.forEach(revoke); queue = []; message(''); render(); photos.focus({preventScroll:true}); });
  const isFileDrag = event => [...(event.dataTransfer?.types || [])].includes('Files');
  dropzone.addEventListener('dragenter', event => {
    if (!isFileDrag(event) || busy || reading) return;
    event.preventDefault(); dragDepth++; dropzone.classList.add('is-dragover');
  });
  dropzone.addEventListener('dragover', event => {
    if (!isFileDrag(event)) return;
    event.preventDefault(); event.dataTransfer.dropEffect = busy || reading ? 'none' : 'copy';
  });
  dropzone.addEventListener('dragleave', event => {
    if (!isFileDrag(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) dropzone.classList.remove('is-dragover');
  });
  async function readEntry(entry, prefix, output) {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      output.push({file, path: prefix + file.name});
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      while (true) {
        const children = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
        if (!children.length) break;
        for (const child of children) await readEntry(child, prefix + entry.name + '/', output);
      }
    }
  }
  dropzone.addEventListener('drop', async event => {
    event.preventDefault(); dragDepth = 0; dropzone.classList.remove('is-dragover');
    if (busy || reading) return;
    const transfer = event.dataTransfer;
    const roots = [...(transfer.items || [])].filter(item => item.kind === 'file').map(item => ({entry:item.webkitGetAsEntry?.() || item.getAsEntry?.(), file:item.getAsFile()}));
    const fallback = [...transfer.files];
    reading = true; photos.disabled = folders.disabled = true;
    form.setAttribute('aria-busy', 'true'); message('Reading files…'); render();
    const entries = []; let errors = 0;
    try {
      if (roots.length) {
        for (const root of roots) {
          try {
            if (root.entry) await readEntry(root.entry, '', entries);
            else if (root.file) entries.push(root.file);
          } catch { errors++; }
        }
      } else entries.push(...fallback);
    } finally {
      reading = false; photos.disabled = folders.disabled = false;
      form.removeAttribute('aria-busy'); await addFiles(entries);
      if (errors) message(`${feedback.textContent} ${errors} dropped items could not be read.`.trim());
    }
  });
  window.addEventListener('dragover', event => { if (isFileDrag(event)) event.preventDefault(); });
  window.addEventListener('drop', event => { if (isFileDrag(event)) event.preventDefault(); });
  const idleLabel = submit.innerHTML;
  form.addEventListener('submit', event => {
    const bytes = queue.reduce((sum, entry) => sum + entry.file.size, 0);
    if (busy || reading || !queue.length || bytes > limit) {
      event.preventDefault();
      if (!queue.length) message('No photos selected.');
      return;
    }
    busy = true; form.setAttribute('aria-busy', 'true');
    submit.textContent = 'Importing…'; submit.disabled = clear.disabled = true;
    photos.disabled = folders.disabled = true;
    list.querySelectorAll('button').forEach(button => { button.disabled = true; });
  });
  window.addEventListener('pageshow', () => {
    busy = false; photos.disabled = folders.disabled = false;
    submit.innerHTML = idleLabel; form.removeAttribute('aria-busy'); render();
  });
  render();
})();
