/**
 * core/markdown.js —— 极简 Markdown → HTML
 * 支持标题、粗体/斜体、行内代码、代码块、有序/无序列表、引用、链接与分隔线。
 * 先对文本做 HTML 转义以避免 XSS；不追求完整规范，足以呈现模型输出。
 */

/** HTML 转义，防止注入。 */
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** 行内标记解析（代码、粗体、斜体、链接）。 */
function inline(text) {
  let out = escapeHtml(text);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, "$1<em>$2</em>");
  out = out.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  return out;
}

/**
 * 把 Markdown 文本渲染为 HTML 字符串。
 * @param {string} source 原始 Markdown
 * @returns {string} HTML 字符串
 */
export function renderMarkdown(source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n");
  const html = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  };
  const openList = (type) => {
    if (listType !== type) {
      closeList();
      html.push(`<${type}>`);
      listType = type;
    }
  };

  for (const line of lines) {
    // 代码块围栏
    if (/^\s*```/.test(line)) {
      if (inCode) {
        html.push(`<pre class="md-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        closeList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (/^\s*$/.test(line)) {
      closeList();
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeList();
      const level = heading[1].length;
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }

    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      closeList();
      html.push("<hr />");
      continue;
    }

    const quote = line.match(/^\s*>\s?(.*)$/);
    if (quote) {
      closeList();
      html.push(`<blockquote>${inline(quote[1])}</blockquote>`);
      continue;
    }

    const ul = line.match(/^\s*[-*+]\s+(.*)$/);
    if (ul) {
      openList("ul");
      html.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }

    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ol) {
      openList("ol");
      html.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }

    closeList();
    html.push(`<p>${inline(line)}</p>`);
  }

  if (inCode) {
    html.push(`<pre class="md-code"><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }
  closeList();
  return html.join("\n");
}
