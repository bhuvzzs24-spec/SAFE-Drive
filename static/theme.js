/* Apply the saved preference before CSS paints; storage can be disabled by the browser. */
(() => {
  let theme = 'dark';
  try { if (localStorage.getItem('safe-drive.theme') === 'light') theme = 'light'; } catch (_) {}
  document.documentElement.dataset.theme = theme;
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('theme-toggle');
    const update = () => {
      const light = document.documentElement.dataset.theme === 'light';
      button.setAttribute('aria-pressed', String(light));
      button.setAttribute('aria-label', light ? 'Use dark theme' : 'Use light theme');
      button.querySelector('span').textContent = light ? 'Dark theme' : 'Light theme';
    };
    button.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem('safe-drive.theme', next); } catch (_) {}
      update();
    });
    update();
  });
})();
