const campaignImages = document.querySelector('[data-campaign-images]');
if (campaignImages) {
  const preview = document.querySelector('[data-campaign-preview]');
  const update = () => {
    const rows = [...campaignImages.querySelectorAll('[data-campaign-image]')];
    campaignImages.closest('form').querySelector('.form-footer button').disabled = rows.length === 0;
    rows.forEach((row, index) => {
      row.querySelector('[data-image-number]').textContent = index + 1;
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
      select.setCustomValidity(select.value && selectedIds.filter(id => id === select.value).length > 1 ? 'Choose each image only once.' : '');
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
    update(); campaignImages.lastElementChild.querySelector('select').focus();
  });
  if (!campaignImages.children.length) document.querySelector('[data-add-campaign-image]').click();
  update();
}
