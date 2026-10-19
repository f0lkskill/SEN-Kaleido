/**
 * core/format.js —— 枚举值到中文标签的映射与格式化工具
 * 后端返回的是稳定英文键，界面统一展示中文，避免教师理解成本。
 */

/** 障碍类型。 */
export const DISABILITY = {
  visual: "视力障碍",
  hearing: "听力障碍",
  intellectual: "智力障碍",
  autism: "自闭症",
};

/** 障碍程度。 */
export const SEVERITY = {
  mild: "轻度",
  moderate: "中度",
  severe: "重度",
};

/** 认知等级。 */
export const COGNITIVE_LEVEL = {
  preschool: "学前",
  primary_low: "小学低段",
  primary_high: "小学高段",
  vocational: "职教",
};

/** 感官偏好。 */
export const SENSORY = {
  visual_first: "视觉优先",
  audio_first: "听觉优先",
  tactile_aided: "触觉辅助",
  mixed: "综合",
};

/** 康复目标。 */
export const REHAB_GOAL = {
  language: "语言",
  sensory_integration: "感知统合",
  social: "社交",
  cognitive: "认知",
};

/** 学习节奏。 */
export const LEARNING_PACE = {
  fast: "较快",
  medium: "适中",
  slow: "较慢",
};

/** 评价维度。 */
export const DIMENSION = {
  knowledge: "知识掌握",
  participation: "课堂参与",
  behavior: "行为改善",
  rehabilitation: "身心康复",
};

/** 任务状态。 */
export const TASK_STATUS = {
  pending: "排队中",
  running: "执行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

/** 任务状态对应的徽章样式类。 */
export const TASK_STATUS_CLASS = {
  pending: "status-pending",
  running: "status-running",
  succeeded: "status-succeeded",
  failed: "status-failed",
  cancelled: "status-cancelled",
};

/** 资源状态。 */
export const RESOURCE_STATUS = {
  draft: "草稿",
  approved: "已通过",
  rejected: "已退回",
};

/**
 * 通用取标签：找不到时回退为原值。
 * @param {Object} map 映射表
 * @param {string} key 键
 */
export function label(map, key) {
  if (key === null || key === undefined || key === "") return "-";
  return map[key] || String(key);
}

/** 把多值数组格式化为中文顿号分隔。 */
export function labels(map, keys) {
  if (!Array.isArray(keys) || keys.length === 0) return "无";
  return keys.map((key) => label(map, key)).join("、");
}

/** 把 ISO 时间格式化为本地可读文本。 */
export function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}
