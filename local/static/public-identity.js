function mountPublicIdentity(panel, {manual = false} = {}) {
  const source = panel.querySelector('.public-identity-value');
  const status = panel.querySelector('.public-identity-status');
  const form = source.form;
  if (source.name !== 'identification') {
    const group = document.createElement('div');
    group.className = 'public-identity-digits';
    group.setAttribute('role', 'group');
    const label = source.labels[0];
    const caption = label.querySelector('span[id]');
    if (caption) group.setAttribute('aria-labelledby', caption.id);
    else group.setAttribute('aria-label', label.textContent.trim());
    const slots = Array.from({length: 4}, (_, index) => {
      const slot = document.createElement('input');
      slot.type = 'text';
      slot.inputMode = 'numeric';
      slot.autocomplete = 'off';
      slot.pattern = '[0-9]';
      slot.required = source.required;
      slot.setAttribute('aria-label', 'Dígito ' + (index + 1));
      group.append(slot);
      return slot;
    });
    const sync = () => {
      source.value = slots.map(slot => slot.value).join('');
      if (manual) source.dispatchEvent(new Event('input', {bubbles: true}));
    };
    const fill = (value, index) => {
      const digits = value.replace(/[^0-9]/g, '').slice(0, 4);
      if (!digits) return;
      const start = digits.length === 4 ? 0 : index;
      [...digits].slice(0, 4 - start).forEach((digit, offset) => {
        slots[start + offset].value = digit;
      });
      sync();
      slots[Math.min(start + digits.length, 3)].focus();
    };
    slots.forEach((slot, index) => {
      slot.addEventListener('focus', () => slot.select());
      slot.addEventListener('input', () => {
        const value = slot.value;
        slot.value = '';
        fill(value, index);
        sync();
      });
      slot.addEventListener('paste', event => {
        event.preventDefault();
        fill(event.clipboardData.getData('text'), index);
      });
      slot.addEventListener('keydown', event => {
        const previous = event.key === 'ArrowLeft' || (event.key === 'Backspace' && !slot.value);
        if (previous && index > 0) {
          event.preventDefault();
          if (event.key === 'Backspace') slots[index - 1].value = '';
          slots[index - 1].focus();
          sync();
        }
        if (event.key === 'ArrowRight' && index < 3) {
          event.preventDefault();
          slots[index + 1].focus();
        }
      });
    });
    source.type = 'hidden';
    label.after(group);
    form?.addEventListener('reset', () => {
      slots.forEach(slot => { slot.value = ''; });
      source.value = '';
    });
  }
  if (manual) return;
  form.addEventListener('submit', event => {
    if (panel.dataset.busy) {
      event.preventDefault();
      return;
    }
    panel.dataset.busy = 'true';
    form.setAttribute('aria-busy', 'true');
    status.textContent = 'Verificando tu identidad de forma segura…';
  });
  window.addEventListener('pageshow', () => {
    delete panel.dataset.busy;
    form.removeAttribute('aria-busy');
    status.textContent = '';
  });
}

window.mountPublicIdentity = mountPublicIdentity;
document.querySelectorAll('[data-public-identity]').forEach(panel => mountPublicIdentity(panel));
