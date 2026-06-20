// Shared JS — toast notifications
function showToast(message, type = 'info') {
  const colors = {
    success: 'bg-emerald-600',
    error:   'bg-rose-600',
    info:    'bg-slate-700',
  };
  const toast = document.createElement('div');
  toast.className = [
    'pointer-events-auto px-4 py-3 rounded-xl text-white text-sm font-medium shadow-lg',
    'flex items-center gap-3 max-w-sm transition-all duration-300 opacity-0 translate-y-2',
    colors[type] || colors.info,
  ].join(' ');

  const icons = {
    success: '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>',
    error:   '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>',
    info:    '<svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  };

  toast.innerHTML = (icons[type] || '') + `<span>${message}</span>`;
  document.getElementById('toasts').appendChild(toast);

  // Animate in
  requestAnimationFrame(() => {
    toast.classList.remove('opacity-0', 'translate-y-2');
  });

  // Auto-remove after 4s
  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
