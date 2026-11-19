(() => {
  const delay = (ms, signal) => new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {clearTimeout(timer); reject(new DOMException('Paused', 'AbortError'));}, {once:true});
  });
  async function request(url, options, csrf, signal) {
    for (let attempt = 0; ; attempt++) {
      try {
        const response = await fetch(url, {...options, credentials:'same-origin', cache:'no-store', redirect:'error', signal,
          headers:{'Accept':'application/json', 'X-CSRF-Token':csrf, ...(options.headers || {})}});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const error = new Error(data.error || `Upload failed (HTTP ${response.status}).`);
          error.status = response.status;
          throw error;
        }
        return data;
      } catch (error) {
        if (error.name === 'AbortError' || attempt >= 3 || (error.status && ![408,429,500,502,503,504,524].includes(error.status))) throw error;
        await delay(800 * 2 ** attempt, signal);
      }
    }
  }
  function address(start, id, action = '') {
    const url = new URL(start, location.href);
    url.pathname = url.pathname.replace(/\/$/, '') + '/' + id + (action ? '/' + action : '');
    return url;
  }
  const token = () => [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2,'0')).join('');
  async function upload(entry, {start, csrf, signal, groupId=null, label='Original', onProgress=()=>{}}) {
    entry.ticket ||= token();
    let state = await request(start, {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id:entry.ticket,filename:entry.file.name,size:entry.file.size,group_id:groupId,label})}, csrf, signal);
    if (state.status === 'cancelled') {entry.ticket=null; throw new Error('Upload cancelled. Select Import again to restart.');}
    while (state.status === 'active' && state.offset < entry.file.size) {
      onProgress(state.offset, entry.file.size);
      const body = entry.file.slice(state.offset, Math.min(entry.file.size, state.offset + state.chunk_size));
      state = await request(address(start, entry.ticket, 'chunks'), {method:'POST',
        headers:{'Content-Type':'application/octet-stream','Upload-Offset':String(state.offset)},body}, csrf, signal);
    }
    onProgress(entry.file.size, entry.file.size, true);
    return await request(address(start, entry.ticket, 'finish'), {method:'POST'}, csrf, signal);
  }
  async function cancel(entry, {start,csrf}) {
    if (!entry.ticket) return;
    await request(address(start,entry.ticket,'cancel'), {method:'POST'}, csrf);
    entry.ticket=null;
  }
  window.FrameUploads = {upload,cancel};

  document.querySelectorAll('[data-version-upload]').forEach(form => {
    const picker=form.querySelector('input[type="file"]'), label=form.querySelector('[name="label"]');
    const button=form.querySelector('button:not([type]),button[type="submit"]');
    const progress=document.createElement('progress'); progress.max=100; progress.hidden=true; progress.setAttribute('aria-label','Upload progress');
    const feedback=document.createElement('p'); feedback.className='muted'; feedback.setAttribute('role','status');
    const pause=document.createElement('button'); pause.type='button'; pause.className='secondary'; pause.textContent='Pause'; pause.hidden=true;
    const controls=document.createElement('div'); controls.className='upload-transfer'; controls.append(progress,pause);
    form.append(controls,feedback);
    let entry, controller, busy=false;
    pause.addEventListener('click',()=>controller?.abort());
    form.addEventListener('submit',async event=>{
      event.preventDefault();
      if (busy || !picker.files.length) return;
      const csrf=form.querySelector('[name="csrf_token"]').value, start=form.dataset.uploadStart;
      busy=true; controller=new AbortController(); button.disabled=true; picker.disabled=label.disabled=true;
      pause.hidden=false; progress.hidden=false; form.setAttribute('aria-busy','true');
      try {
        if (entry && entry.file!==picker.files[0]) { await cancel(entry,{start,csrf}).catch(()=>{}); entry=null; }
        entry ||= {file:picker.files[0]};
        const result=await upload(entry,{start,csrf,signal:controller.signal,groupId:Number(form.dataset.groupId),label:label.value,
          onProgress:(sent,size,finishing)=>{progress.value=sent/size*100; feedback.textContent=finishing?'Checking image…':`Uploading · ${Math.floor(sent/size*100)}%`;}});
        if (result.status==='duplicate') {feedback.textContent=result.message; entry=null;}
        else if (result.status==='complete') {location.assign(result.redirect); return;}
      } catch(error) {feedback.textContent=error.name==='AbortError'?'Paused':error.message;}
      busy=false; button.disabled=false; picker.disabled=label.disabled=false; pause.hidden=true; form.removeAttribute('aria-busy');
      button.textContent=entry?.ticket?'Resume upload':'Upload version';
    });
  });
})();
