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

/** 认知等级（细化到年级）。 */
export const COGNITIVE_LEVEL = {
  preschool: "学前",
  primary_1: "小学一年级",
  primary_2: "小学二年级",
  primary_3: "小学三年级",
  primary_4: "小学四年级",
  primary_5: "小学五年级",
  primary_6: "小学六年级",
  junior_1: "初中一年级",
  junior_2: "初中二年级",
  junior_3: "初中三年级",
  senior_1: "高中一年级",
  senior_2: "高中二年级",
  senior_3: "高中三年级",
  vocational: "职教",
  // 兼容历史数据键（旧版枚举），迁移后可移除
  primary_low: "小学低段",
  primary_high: "小学高段",
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

/** 评价维度（当前阶段仅两个公共维度）。 */
export const DIMENSION = {
  participation: "课堂参与",
  practice: "练习质量",
};

/** 评价方式。 */
export const METHOD = {
  quantitative: "量化",
  qualitative: "质性",
};

/** 观测频率。 */
export const FREQUENCY = {
  per_lesson: "每课",
  weekly: "每周",
  phase: "阶段性",
};

/**
 * 证据来源静态兜底映射。
 * 运行时可经 setEvidenceSources() 用后端元数据覆盖，保持与配置同源。
 */
export const EVIDENCE_SOURCE = {
  item_response: "试题作答",
  classroom_observation: "课堂观察",
  video_event: "视频事件",
  work_sample: "作品/作业样本",
  teacher_rating: "教师评分",
  parent_feedback: "家长反馈",
  rehab_record: "康复师记录",
  system_log: "系统埋点",
};

/** 当前生效的证据来源映射（静态兜底 + 后端元数据）。 */
let evidenceSourceMap = { ...EVIDENCE_SOURCE };

/**
 * 用后端返回的证据来源定义更新映射。
 * @param {Object} map 形如 { key: { name } } 的定义表
 */
export function setEvidenceSources(map) {
  if (!map || typeof map !== "object") return;
  const merged = {};
  for (const [key, value] of Object.entries(map)) {
    merged[key] = value && value.name ? value.name : String(value);
  }
  evidenceSourceMap = { ...EVIDENCE_SOURCE, ...merged };
}

/** 证据来源键转中文名。 */
export function evidenceLabel(key) {
  return evidenceSourceMap[key] || String(key);
}

/** 证据来源键数组转中文顿号串。 */
export function evidenceLabels(keys) {
  if (!Array.isArray(keys) || keys.length === 0) return "无";
  return keys.map(evidenceLabel).join("、");
}

/** 证据审核状态。 */
export const EVIDENCE_STATUS = {
  draft: "待审核",
  verified: "已通过",
  rejected: "已拒绝",
};

/** 证据审核状态对应的徽章样式类。 */
export const EVIDENCE_STATUS_CLASS = {
  draft: "badge-warning",
  verified: "badge-success",
  rejected: "badge-danger",
};

/** 当前公共评价框架的观测点中文名。 */
export const OBSERVATION = {
  class_engagement: "课堂参与程度",
  practice_completion: "练习完成质量",
};

/** 证据来源的媒体形态。 */
export const EVIDENCE_MODALITY = {
  structured: "结构化",
  raw_media: "原始媒体",
  artifact: "作品样本",
  text: "文本",
};

/** 证据来源的加工方式。 */
export const EVIDENCE_PROCESSED_BY = {
  auto: "自动",
  human: "人工",
  auto_or_human: "自动/人工",
  human_or_llm: "人工/LLM",
};

/** 证据来源的采集成本。 */
export const EVIDENCE_COST = {
  low: "低",
  medium: "中",
  high: "高",
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
