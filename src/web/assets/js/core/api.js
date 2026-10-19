/**
 * core/api.js —— 后端接口封装
 * 统一处理后端约定的 {code, message, data} 响应包裹：
 * code === 0 视为成功返回 data，否则抛出带错误信息的异常。
 */

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

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    // 网络层失败（基站离线/断网）
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
    throw error;
  }

  return payload.data;
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

  // ---- 评价框架预览 ----
  previewFramework: (body) =>
    request("/api/v1/evaluation/framework", { method: "POST", body }),

  // ---- 资源生成与资源库 ----
  generate: (body) => request("/api/v1/forge/generate", { method: "POST", body }),
  listResources: (query) => request("/api/v1/forge/resources", { query }),
  getResource: (id) =>
    request(`/api/v1/forge/resources/${encodeURIComponent(id)}`),

  // ---- 异步任务 ----
  taskTypes: () => request("/api/v1/tasks/types"),
  listTasks: (query) => request("/api/v1/tasks", { query }),
  createTask: (body) => request("/api/v1/tasks", { method: "POST", body }),
  getTask: (id) => request(`/api/v1/tasks/${encodeURIComponent(id)}`),
  cancelTask: (id) =>
    request(`/api/v1/tasks/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
