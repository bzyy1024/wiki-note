/**
 * 第三方前端资源自托管。
 *
 * 部分插件默认从公共 CDN（jsdelivr / cdnjs 等）加载 JS、CSS，这会让浏览器
 * 向第三方站点发起请求。这里把这些 URL 统一改写为本站 `static/vendor/**`
 * 下的本地副本：资源文件存放在 `quartz/static/vendor/`，构建时由 Static
 * emitter 原样拷贝到 `/static/vendor/**`，从而实现「只在本站请求前端资源」。
 *
 * 注意：新增映射时，必须同步把对应文件下载到 `quartz/static/vendor/` 对应路径，
 * 否则浏览器会出现 404。
 */
export const SELF_HOSTED_ASSETS: Readonly<Record<string, string>> = {
  // KaTeX —— 由 @quartz-community/latex 插件引入（CSS 会相对引用同目录 fonts/）
  "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css":
    "/static/vendor/katex/katex.min.css",
  "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/copy-tex.min.js":
    "/static/vendor/katex/contrib/copy-tex.min.js",
  // d3 / PixiJS —— 由 @quartz-community/graph 插件在运行时引入
  "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js": "/static/vendor/d3/d3.min.js",
  "https://cdn.jsdelivr.net/npm/pixi.js@8/dist/pixi.js": "/static/vendor/pixi/pixi.js",
  // Mermaid —— 由 @quartz-community/obsidian-flavored-markdown 插件在运行时引入
  // （同目录 chunks/ 为其代码分包，需一并下载）
  "https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.4.0/mermaid.esm.min.mjs":
    "/static/vendor/mermaid/mermaid.esm.min.mjs",
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

const externalAssetPattern = new RegExp(
  Object.keys(SELF_HOSTED_ASSETS)
    .map(escapeRegExp)
    .join("|"),
  "g",
)

/** 把单个外部资源 URL 改写为本站静态路径（未命中时原样返回）。 */
export function rewriteExternalAssetUrl(url: string): string {
  return SELF_HOSTED_ASSETS[url] ?? url
}

/** 把文本中出现的所有外部资源 URL 批量改写为本站静态路径。 */
export function rewriteExternalAssets(text: string): string {
  if (!text) {
    return text
  }
  return text.replace(externalAssetPattern, (match) => SELF_HOSTED_ASSETS[match] ?? match)
}
