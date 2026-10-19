/**
 * core/log.js —— 前端日志
 * 统一在浏览器控制台输出带 [kaleido] 前缀的调试信息，并捕获全局错误，
 * 便于在教室机上排查前端问题（打开开发者工具即可看到）。
 */

const PREFIX = "[kaleido]";

/** 带前缀的日志方法集合。 */
export const log = {
  debug: (...args) => console.debug(PREFIX, ...args),
  info: (...args) => console.info(PREFIX, ...args),
  warn: (...args) => console.warn(PREFIX, ...args),
  error: (...args) => console.error(PREFIX, ...args),
};

/** 注册全局错误与未处理 Promise 拒绝的捕获。 */
export function initErrorCapture() {
  window.addEventListener("error", (event) => {
    log.error("未捕获错误:", event.message, `${event.filename}:${event.lineno}`);
  });
  window.addEventListener("unhandledrejection", (event) => {
    log.error("未处理的 Promise 拒绝:", event.reason);
  });
}
