/**
 * core/api.js —— 后端接口封装
 * 统一处理后端约定的 {code, message, data} 响应包裹：
 * code === 0 视为成功返回 data，否则抛出带错误信息的异常。
 */

import { log } from "./log.js";

const BASE = "";

/**
 * 发起请求并解包统一响应。
 * @param {string} path 接口路径
 * @param {Object} [options] 选项：method、body、query
 * @returns {Promise<any>} 成功时的 data
 */
async function request(path, { method = "GET", body, query } = {}) {
  const url = new URL(path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined && value !== "") {
        url.searchParams.set(key, value);
      }
    }
  }

  log.debug("请求 →", method, url.pathname + url.search);
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    // 网络层失败（基站离线/断网）
    log.error("请求失败（网络层）:", method, path, err);
    const error = new Error("无法连接处理基站，请检查网络或服务状态");
    error.code = -1;
    throw error;
  }

  let payload;
  try {
    payload = await response.json();
  } catch (err) {
    payload = { code: 1000, message: `响应解析失败(${response.status})`, data: null };
  }

  if (!response.ok || payload.code !== 0) {
    const error = new Error(payload.message || `请求失败(${response.status})`);
    error.code = payload.code;
    error.status = response.status;
    log.error("响应错误:", response.status, method, path, payload.message);
    throw error;
  }

  log.debug("响应 ←", response.status, method, path);
  return payload.data;
}

/**
 * 流式请求：POST 后逐块解析 SSE，回调每个事件。
 * @param {string} path 接口路径
 * @param {Object} body 请求体
 * @param {Function} onEvent 事件回调（收到一个已解析的事件对象）
 */
async function streamRequest(path, body, onEvent) {
  log.debug("流式请求 →", path);
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    log.error("流式请求失败（网络层）:", path, err);
    const error = new Error("无法连接处理基站，请检查网络或服务状态");
    error.code = -1;
    throw error;
  }

  if (!response.ok || !response.body) {
    let message = `请求失败(${response.status})`;
    try {
      const payload = await response.json();
      if (payload && payload.message) message = payload.message;
    } catch (err) {
      /* 忽略解析失败，沿用默认信息 */
    }
    log.error("流式响应错误:", response.status, path, message);
    throw new Error(message);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 以空行分隔事件块
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop();
    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data:")) continue;
      let event;
      try {
        event = JSON.parse(line.slice(5).trim());
      } catch (err) {
        continue;
      }
      onEvent(event);
    }
  }
  log.debug("流式请求结束 ←", path);
}

/** 业务接口集合。 */
export const api = {
  // ---- 元数据 ----
  listTypes: () => request("/api/v1/profile/types"),
  dimensions: () => request("/api/v1/evaluation/dimensions"),
  evidenceSources: () => request("/api/v1/evaluation/evidence-sources"),
  resourceTypes: () => request("/api/v1/forge/resource-types"),

  // ---- 学生档案 ----
  listStudents: (query) => request("/api/v1/students", { query }),
  createStudent: (body) => request("/api/v1/students", { method: "POST", body }),
  getStudent: (id) => request(`/api/v1/students/${encodeURIComponent(id)}`),
  deleteStudent: (id) =>
    request(`/api/v1/students/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // ---- 证据管理 ----
  listEvidence: (query) => request("/api/v1/evidence", { query }),
  evidenceSummary: (query) => request("/api/v1/evidence/summary", { query }),
  getEvidence: (id) => request(`/api/v1/evidence/${encodeURIComponent(id)}`),
  createEvidence: (body) => request("/api/v1/evidence", { method: "POST", body }),
  reviewEvidence: (id, body) =>
    request(`/api/v1/evidence/${encodeURIComponent(id)}/review`, {
      method: "POST",
      body,
    }),
  deleteEvidence: (id) =>
    request(`/api/v1/evidence/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // ---- 评价框架预览 ----
  previewFramework: (body) =>
    request("/api/v1/evaluation/framework", { method: "POST", body }),

  // ---- 资源生成与资源库 ----
  generate: (body) => request("/api/v1/forge/generate", { method: "POST", body }),
  generateStream: (body, onEvent) =>
    streamRequest("/api/v1/forge/generate/stream", body, onEvent),
  listResources: (query) => request("/api/v1/forge/resources", { query }),
  getResource: (id) =>
    request(`/api/v1/forge/resources/${encodeURIComponent(id)}`),
  updateResourceStatus: (id, status) =>
    request(`/api/v1/forge/resources/${encodeURIComponent(id)}/status`, {
      method: "POST",
      body: { status },
    }),
  deleteResource: (id) =>
    request(`/api/v1/forge/resources/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // ---- 异步任务 ----
  taskTypes: () => request("/api/v1/tasks/types"),
  listTasks: (query) => request("/api/v1/tasks", { query }),
  createTask: (body) => request("/api/v1/tasks", { method: "POST", body }),
  getTask: (id) => request(`/api/v1/tasks/${encodeURIComponent(id)}`),
  cancelTask: (id) =>
    request(`/api/v1/tasks/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
