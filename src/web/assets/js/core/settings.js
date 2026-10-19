/**
 * core/settings.js —— 无障碍显示设置
 * 字号档位与高对比度偏好保存在 localStorage，刷新后仍生效。
 */

const STORAGE_KEY = "sen-kaleido.display";
const FONT_SIZES = ["normal", "large", "xlarge"];
const CONTRASTS = ["normal", "high"];

const state = {
  fontsize: "normal",
  contrast: "normal",
};

/** 从本地存储读取偏好并应用。 */
export function loadSettings() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch (err) {
    saved = {};
  }
  if (FONT_SIZES.includes(saved.fontsize)) state.fontsize = saved.fontsize;
  if (CONTRASTS.includes(saved.contrast)) state.contrast = saved.contrast;
  apply();
}

/** 把当前偏好写到 <html> 的属性上，由 CSS 变量接管。 */
function apply() {
  document.documentElement.dataset.fontsize = state.fontsize;
  document.documentElement.dataset.contrast = state.contrast;
}

/** 保存偏好。 */
function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (err) {
    // 隐私模式下可能失败，忽略即可
  }
}

/** 设置字号档位。 */
export function setFontSize(value) {
  if (!FONT_SIZES.includes(value)) return;
  state.fontsize = value;
  apply();
  persist();
}

/** 设置对比度模式。 */
export function setContrast(value) {
  if (!CONTRASTS.includes(value)) return;
  state.contrast = value;
  apply();
  persist();
}

/** 读取当前状态（供界面按钮回显）。 */
export function getSettings() {
  return { ...state };
}

/**
 * 把显示设置控件绑定到事件。
 * @param {HTMLElement} root 设置区容器
 */
export function bindSettingsControls(root) {
  root.querySelectorAll("[data-fontsize]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setFontSize(btn.dataset.fontsize);
      syncSettingsControls(root);
    });
  });
  root.querySelectorAll("[data-contrast]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setContrast(btn.dataset.contrast);
      syncSettingsControls(root);
    });
  });
  syncSettingsControls(root);
}

/** 同步按钮的按下态与当前设置。 */
export function syncSettingsControls(root) {
  const current = getSettings();
  root.querySelectorAll("[data-fontsize]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.fontsize === current.fontsize));
  });
  root.querySelectorAll("[data-contrast]").forEach((btn) => {
    btn.setAttribute("aria-pressed", String(btn.dataset.contrast === current.contrast));
  });
}
