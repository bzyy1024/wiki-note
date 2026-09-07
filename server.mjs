// 纯静态服务器：serve 镜像内预构建好的 public/，启动即就绪（无任何构建逻辑）。
// 路由行为与 Quartz 自带 serve 保持一致：
//   /foo       -> 若存在 foo.html 则返回；若存在 foo/index.html 则 302 到 /foo/
//   /foo/      -> 若存在 foo/index.html 则返回；否则退回 foo.html（302 到 /foo）
//   其他静态资源按文件直接返回；找不到时返回 404.html（若有）
import { createServer } from "node:http"
import { promises as fs } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const PUBLIC_DIR = path.join(HERE, "public")
const PORT = Number(process.env.PORT || 8080)

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".avif": "image/avif",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".xml": "text/xml; charset=utf-8",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
  ".eot": "application/vnd.ms-fontobject",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".mp3": "audio/mpeg",
  ".pdf": "application/pdf",
  ".epub": "application/epub+zip",
  ".zip": "application/zip",
  ".wasm": "application/wasm",
}

async function statOrNull(abs) {
  try {
    return await fs.stat(abs)
  } catch {
    return null
  }
}

// 返回 { file } | { redirect } | null
async function resolveTarget(rel) {
  const join = (p) => path.join(PUBLIC_DIR, p)

  if (rel === "") {
    // 站点根目录
    if (await statOrNull(join("index.html"))) return { file: "index.html" }
    return null
  }

  const trailing = rel.endsWith("/")
  const base = rel.replace(/\/+$/, "")

  if (trailing) {
    // /foo/ 目录式请求
    const idx = `${base}/index.html`
    if (await statOrNull(join(idx))) return { file: idx }
    if (path.extname(base) === "") {
      const html = `${base}.html`
      if (await statOrNull(join(html))) return { redirect: `/${base}` }
    }
    return null
  }

  // 无扩展名的路径：先试 foo.html，再试 foo/index.html（转成目录式）
  if (path.extname(rel) === "") {
    const html = `${rel}.html`
    if (await statOrNull(join(html))) return { file: html }
    const idx = `${rel}/index.html`
    if (await statOrNull(join(idx))) return { redirect: `/${rel}/` }
    return null
  }

  // 带扩展名的静态资源（css/js/图片等）：按文件直接返回
  const st = await statOrNull(join(rel))
  if (st && st.isFile()) return { file: rel }
  return null
}

function absSafe(rel) {
  const abs = path.resolve(PUBLIC_DIR, rel)
  if (abs !== PUBLIC_DIR && !abs.startsWith(PUBLIC_DIR + path.sep)) return null
  return abs
}

async function sendFile(res, rel, status, headOnly) {
  const abs = absSafe(rel)
  if (!abs) {
    res.writeHead(403).end("Forbidden")
    return
  }
  const ext = path.extname(abs).toLowerCase()
  const htmlLike = ext === ".html" || ext === ""
  res.writeHead(status, {
    "Content-Type": MIME[ext] || "application/octet-stream",
    // 页面实时性优先；带 hash 的构建产物/图片可长缓存
    "Cache-Control": htmlLike ? "no-cache" : "public, max-age=604800",
  })
  if (headOnly) {
    res.end()
    return
  }
  try {
    const data = await fs.readFile(abs)
    res.end(data)
  } catch {
    res.writeHead(404).end("Not Found")
  }
}

const server = createServer(async (req, res) => {
  try {
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.writeHead(405, { Allow: "GET, HEAD" }).end()
      return
    }
    const headOnly = req.method === "HEAD"

    let pathname
    try {
      pathname = decodeURIComponent(new URL(req.url, "http://localhost").pathname)
    } catch {
      res.writeHead(400).end("Bad Request")
      return
    }
    if (pathname.includes("\\")) {
      res.writeHead(400).end("Bad Request")
      return
    }

    // 防目录穿越：任何路径段不允许出现 ".."
    const segments = pathname.split("/")
    if (segments.some((s) => s === "..")) {
      res.writeHead(403).end("Forbidden")
      return
    }

    const rel = pathname.replace(/^\/+/, "")
    const hit = await resolveTarget(rel)
    if (hit?.file) {
      await sendFile(res, hit.file, 200, headOnly)
      return
    }
    if (hit?.redirect) {
      res.writeHead(302, { Location: hit.redirect }).end()
      return
    }

    // 未命中 -> 404.html（Quartz 生成的错误页），否则纯 404
    if (await statOrNull(path.join(PUBLIC_DIR, "404.html"))) {
      await sendFile(res, "404.html", 404, headOnly)
    } else {
      res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" }).end("Not Found")
    }
  } catch (err) {
    console.error("[server]", err)
    if (!res.headersSent) res.writeHead(500).end("Internal Server Error")
    else res.destroy()
  }
})

server.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    console.error(`Port ${PORT} is already in use.`)
  } else {
    console.error(err)
  }
  process.exit(1)
})

server.listen(PORT, () => {
  console.log(`Static server serving ${PUBLIC_DIR} at http://0.0.0.0:${PORT}`)
})

// 优雅退出：容器收到 SIGTERM（docker stop）后立即关闭，避免拖满 stop_grace_period
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    server.close(() => process.exit(0))
    setTimeout(() => process.exit(0), 3000).unref()
  })
}
