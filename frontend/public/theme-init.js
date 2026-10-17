// Apply the saved appearance before the app and its styles render.
(() => {
  let saved
  try { saved = localStorage.getItem('geekexam:theme') } catch { /* Storage may be unavailable. */ }
  const dark = saved === 'dark' || (saved !== 'light' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.bsTheme = dark ? 'dark' : 'light'
})()
