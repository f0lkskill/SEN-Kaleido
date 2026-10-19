/**
 * core/dom.js —— 轻量 DOM 构建工具
 * 用函数式方式创建元素，避免在各视图里拼接 HTML 字符串（更安全、可维护）。
 */

/**
 * 创建元素。
 * @param {string} tag 标签名
 * @param {Object} [attrs] 属性，特殊键：class、text、html、dataset、on（事件）
 * @param {Array<Node|string>} [children] 子节点
 * @returns {HTMLElement}
 */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);

  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;

    if (key === "class") {
      node.className = value;
    } else if (key === "text") {
      node.textContent = value;
    } else if (key === "dataset") {
      Object.assign(node.dataset, value);
    } else if (key === "on") {
      // on 为 { 事件名: 处理函数 } 映射
      for (const [event, handler] of Object.entries(value)) {
        node.addEventListener(event, handler);
      }
    } else if (key in node) {
      node[key] = value;
    } else {
      node.setAttribute(key, value);
    }
  }

  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }

  return node;
}

/** 清空节点全部子元素。 */
export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

/** querySelector 简写。 */
export function qs(selector, root = document) {
  return root.querySelector(selector);
}

/** 生成一个空态/加载态占位元素。 */
export function placeholder(text, kind = "empty") {
  return el("div", { class: kind, text });
}
