/**
 * core/icons.js —— Font Awesome 图标映射
 * 统一资源类型与证据媒体类型的图标，避免各视图继续使用文字占位。
 */

import { el } from "./dom.js";

/** 资源类型键 -> Font Awesome 图标类。 */
export const RESOURCE_TYPE_ICONS = {
  courseware: "fa-layer-group",
  exercise: "fa-list-check",
  rehabilitation: "fa-hand-holding-heart",
  interaction: "fa-comments",
  iep: "fa-route",
};

/** 学生档案默认图标。 */
export const STUDENT_ICON = "fa-user";

/** 证据媒体类型 -> Font Awesome 图标类。 */
export const MEDIA_ICONS = {
  text: "fa-file-lines",
  image: "fa-image",
  video: "fa-video",
};

/** 创建 Font Awesome 实心图标。 */
export function faIcon(name, { className = "" } = {}) {
  return el("i", {
    class: `fa-solid ${name} ${className}`.trim(),
    "aria-hidden": "true",
  });
}

/** 资源类型图标；未知类型回退为通用文件图标。 */
export function resourceIcon(type) {
  return RESOURCE_TYPE_ICONS[type] || "fa-file-lines";
}

/** 证据媒体图标；未知类型回退为文本文件图标。 */
export function mediaIcon(media) {
  return MEDIA_ICONS[media] || "fa-file-lines";
}
