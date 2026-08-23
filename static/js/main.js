// Shared helpers: toasts + a small fetch wrapper. Page-specific logic lives
// in inline <script> blocks in each template to keep things easy to follow
// for a student project.

function toast(message, type = 'ok') {
  const root = document.getElementById('toast-root');
  if (!root) return;
  const el = document.createElement('div');
  el.className = `toast ${type === 'error' ? 'error' : ''}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

const THEME_KEY = 'verascan-theme';
const DEVICE_KEY = 'verascan-device-id';

function getDeviceId() {
  let deviceId = localStorage.getItem(DEVICE_KEY);
  if (!deviceId) {
    if (window.crypto && window.crypto.randomUUID) {
      deviceId = window.crypto.randomUUID();
    } else {
      deviceId = `dev-${Math.random().toString(36).substring(2, 10)}-${Date.now()}`;
    }
    localStorage.setItem(DEVICE_KEY, deviceId);
  }
  return deviceId;
}

function getDeviceName() {
  const ua = navigator.userAgent;
  let browser = "Browser";
  if (ua.includes("Firefox")) browser = "Firefox";
  else if (ua.includes("Edg")) browser = "Edge";
  else if (ua.includes("Chrome")) browser = "Chrome";
  else if (ua.includes("Safari")) browser = "Safari";

  let os = "Device";
  if (ua.includes("Win")) os = "Windows";
  else if (ua.includes("Android")) os = "Android";
  else if (ua.includes("iPhone") || ua.includes("iPad")) os = "iOS";
  else if (ua.includes("Mac")) os = "Macintosh";
  else if (ua.includes("Linux")) os = "Linux";

  return `${browser} on ${os}`;
}


function getSavedTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === 'dark' || stored === 'light') return stored;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
  const btn = document.getElementById('theme-toggle');
  const mobileBtn = document.getElementById('theme-toggle-mobile');
  const label = theme === 'dark' ? 'Light mode' : 'Dark mode';
  if (btn) btn.textContent = label;
  if (mobileBtn) mobileBtn.textContent = label;
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme || getSavedTheme();
  applyTheme(current === 'dark' ? 'light' : 'dark');
}

window.addEventListener('DOMContentLoaded', () => {
  applyTheme(getSavedTheme());
  const themeButtons = document.querySelectorAll('[data-theme-toggle], #theme-toggle-panel');
  themeButtons.forEach((btn) => btn.addEventListener('click', toggleTheme));

  const settingsPanel = document.getElementById('settings-panel');
  const settingsTriggers = document.querySelectorAll('[data-settings-trigger]');
  const settingsClose = document.getElementById('settings-close');

  const openSettings = () => {
    if (settingsPanel) {
      settingsPanel.hidden = false;
      requestAnimationFrame(() => settingsPanel.classList.add('is-open'));
    }
  };
  const closeSettings = () => {
    if (settingsPanel) {
      settingsPanel.classList.remove('is-open');
      setTimeout(() => {
        settingsPanel.hidden = true;
      }, 220);
    }
  };

  settingsTriggers.forEach((trigger) => trigger.addEventListener('click', openSettings));
  if (settingsClose) settingsClose.addEventListener('click', closeSettings);
  if (settingsPanel) {
    settingsPanel.addEventListener('click', (event) => {
      if (event.target === settingsPanel) closeSettings();
    });
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSettings();
  });
});

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const msg = (data && data.error) ? data.error : `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return data;
}

// Starts the webcam on a given <video> element, returns the MediaStream.
async function startCamera(videoEl, facingMode = 'user') {
  if (videoEl.srcObject) {
    const tracks = videoEl.srcObject.getTracks();
    tracks.forEach(track => track.stop());
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: facingMode },
    audio: false,
  });
  videoEl.srcObject = stream;
  await videoEl.play();
  return stream;
}

// Grabs the current video frame as a base64 JPEG data-url.
function grabFrame(videoEl) {
  const canvas = document.createElement('canvas');
  canvas.width = videoEl.videoWidth || 640;
  canvas.height = videoEl.videoHeight || 480;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85);
}
