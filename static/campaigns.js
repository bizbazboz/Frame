const campaignImages = document.querySelector('[data-campaign-images]');
if (campaignImages) {
  const preview = document.querySelector('[data-campaign-preview]');
  let pickerId = 0;
  const enhancePicker = select => {
    if (select.dataset.searchReady) return;
    select.dataset.searchReady = 'true';
    const picker = document.createElement('div');
    picker.className = 'campaign-image-picker';
    const input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.required = true;
    input.placeholder = 'Search by filename…';
    input.dataset.imageSearch = '';
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-haspopup', 'listbox');
    const list = document.createElement('div');
    list.className = 'campaign-image-results';
    list.id = `campaign-image-results-${++pickerId}`;
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Images');
    list.hidden = true;
    input.setAttribute('aria-controls', list.id);
    select.after(picker);
    picker.append(input, list);
    select.hidden = true;
    select.required = false;
    let active = -1;
    let matches = [];
    const options = [...select.options].filter(option => option.value);
    const close = () => {
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    };
    const highlight = index => {
      active = index;
      [...list.querySelectorAll('[role="option"]')].forEach((option, i) => {
        option.classList.toggle('is-active', i === active);
        if (i === active) {
          input.setAttribute('aria-activedescendant', option.id);
          option.scrollIntoView({block: 'nearest'});
        }
      });
    };
    const choose = option => {
      select.value = option.value;
      input.value = option.textContent;
      select.dispatchEvent(new Event('change', {bubbles: true}));
      close();
    };
    const render = query => {
      matches = options.filter(option => (option.dataset.filename || option.textContent).toLocaleLowerCase().includes(query.toLocaleLowerCase().trim()));
      list.replaceChildren();
      active = -1;
      input.removeAttribute('aria-activedescendant');
      matches.forEach((option, index) => {
        const result = document.createElement('div');
        result.id = `${list.id}-${index}`;
        result.setAttribute('role', 'option');
        result.setAttribute('aria-selected', String(option.value === select.value));
        result.textContent = option.textContent;
        result.addEventListener('pointerdown', event => event.preventDefault());
        result.addEventListener('click', () => choose(option));
        list.append(result);
      });
      if (!matches.length) {
        const empty = document.createElement('div');
        empty.className = 'campaign-image-no-results';
        empty.setAttribute('role', 'status');
        empty.textContent = 'No matching images';
        list.append(empty);
      }
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    };
    input.value = select.value ? select.selectedOptions[0].textContent : '';
    input.addEventListener('focus', () => { render(''); input.select(); });
    input.addEventListener('click', () => { if (list.hidden) render(''); });
    input.addEventListener('input', () => {
      select.value = '';
      select.dispatchEvent(new Event('change', {bubbles: true}));
      render(input.value);
    });
    input.addEventListener('blur', close);
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (list.hidden) render('');
        if (matches.length) highlight(active < 0 ? (event.key === 'ArrowDown' ? 0 : matches.length - 1) : (active + (event.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length);
      } else if (event.key === 'Enter' && !list.hidden) {
        event.preventDefault();
        if (matches.length) choose(matches[active < 0 ? 0 : active]);
      }
    });
    select.addEventListener('change', () => {
      if (select.value) input.value = select.selectedOptions[0].textContent;
    });
  };
  const update = () => {
    const rows = [...campaignImages.querySelectorAll('[data-campaign-image]')];
    campaignImages.closest('form').querySelector('.form-footer button').disabled = rows.length === 0;
    rows.forEach((row, index) => {
      enhancePicker(row.querySelector('select'));
      row.querySelector('[data-image-number]').textContent = index + 1;
      row.querySelector('[data-image-search]').setAttribute('aria-label', `Image ${index + 1}`);
      row.querySelector('[data-image-up]').disabled = index === 0;
      row.querySelector('[data-image-down]').disabled = index === rows.length - 1;
      const selected = row.querySelector('select').selectedOptions[0];
      const thumb = row.querySelector('img');
      thumb.hidden = !selected?.value;
      if (selected?.value) thumb.src = selected.dataset.thumb;
    });
    const selectedIds = rows.map(row => row.querySelector('select').value).filter(Boolean);
    rows.forEach(row => {
      const select = row.querySelector('select');
      const input = row.querySelector('[data-image-search]');
      const duplicate = select.value && selectedIds.filter(id => id === select.value).length > 1;
      select.setCustomValidity('');
      input.setCustomValidity(duplicate ? 'Choose each image only once.' : (!select.value && input.value ? 'Choose an image from the results.' : ''));
    });
    if (!rows.length) { preview.hidden = true; preview.removeAttribute('src'); }
  };
  const show = row => {
    const selected = row.querySelector('select').selectedOptions[0];
    if (selected?.value) { preview.src = selected.dataset.full; preview.hidden = false; }
  };
  campaignImages.addEventListener('change', event => { update(); show(event.target.closest('[data-campaign-image]')); });
  campaignImages.addEventListener('click', event => {
    const row = event.target.closest('[data-campaign-image]');
    if (!row) return;
    if (event.target.closest('[data-image-remove]')) { row.remove(); update(); if (campaignImages.firstElementChild) show(campaignImages.firstElementChild); }
    else if (event.target.closest('[data-image-up]') && row.previousElementSibling) { campaignImages.insertBefore(row, row.previousElementSibling); update(); }
    else if (event.target.closest('[data-image-down]') && row.nextElementSibling) { campaignImages.insertBefore(row.nextElementSibling, row); update(); }
    else show(row);
  });
  document.querySelector('[data-add-campaign-image]').addEventListener('click', () => {
    campaignImages.append(document.querySelector('[data-campaign-image-template]').content.cloneNode(true));
    update(); campaignImages.lastElementChild.querySelector('[data-image-search]').focus();
  });
  if (!campaignImages.children.length) document.querySelector('[data-add-campaign-image]').click();
  update();
}
