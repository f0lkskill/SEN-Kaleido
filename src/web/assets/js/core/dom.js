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

/**
 * 生成一个"板块"容器：可选小标题 + 内容。
 * 用于把表单/详情按语义分区，样式克制（细分隔线 + 小标题）。
 * @param {string|null} title 板块小标题
 * @param {Node|Node[]} body 内容
 * @param {Object} [options] 选项：className
 * @returns {HTMLElement}
 */
export function panel(title, body, { className = "" } = {}) {
  const node = el("section", { class: `panel ${className}`.trim() });
  if (title) node.append(el("h3", { class: "panel-title", text: title }));
  const content = el("div", { class: "panel-body" });
  for (const child of [].concat(body)) {
    if (child) content.append(child);
  }
  node.append(content);
  return node;
}

/**
 * 窄屏（学生档案/证据/资源库的 master-detail 堆叠）时，
 * 把详情面板滚动到视口，避免用户点击后以为没有反应。
 * @param {HTMLElement} detailBox 详情容器
 */
export function revealDetail(detailBox) {
  if (!detailBox) return;
  if (window.matchMedia("(max-width: 899px)").matches) {
    detailBox.scrollIntoView({ block: "start" });
  }
}

/**
 * 让原生 <details> 支持平滑的展开 / 收起高度过渡。
 * 原理：把 summary 之后的内容包进高度过渡容器，拦截点击手动控制 open 时机，
 * 收起时先播放过渡、结束再关闭，避免内容瞬间消失。
 * @param {HTMLDetailsElement} details 目标元素
 * @returns {HTMLDetailsElement}
 */
export function enhanceDisclosure(details) {
  const summary = details.querySelector("summary");
  if (!summary) return details;

  // 把 summary 之后的所有内容移入动画容器
  const body = document.createElement("div");
  body.className = "disclosure-body";
  while (summary.nextSibling) body.append(summary.nextSibling);
  details.append(body);

  // 尊重初始 open：默认展开的板块（如学生画像）保持展开
  body.style.height = details.open ? "auto" : "0px";

  summary.addEventListener("click", (event) => {
    event.preventDefault();
    if (details.dataset.danim === "1") return;
    details.dataset.danim = "1";

    const expanding = !details.open;
    let settled = false;
    const settle = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      body.removeEventListener("transitionend", onEnd);
      body.style.height = expanding ? "auto" : "0px";
      details.open = expanding;
      details.dataset.danim = "0";
    };
    const onEnd = (e) => {
      if (e.target === body) settle();
    };
    body.addEventListener("transitionend", onEnd);
    // 兜底：过渡事件未回调（内容为空或动效被禁用）时也要落定
    const timer = window.setTimeout(settle, 400);

    if (expanding) {
      // 展开：先置 0 再过渡到内容高度
      details.open = true;
      body.style.height = "0px";
      requestAnimationFrame(() => {
        body.style.height = `${body.scrollHeight}px`;
      });
    } else {
      // 收起：先固定当前高度，再过渡到 0，结束后真正关闭
      body.style.height = `${body.scrollHeight}px`;
      requestAnimationFrame(() => {
        body.style.height = "0px";
      });
    }
  });
  return details;
}
