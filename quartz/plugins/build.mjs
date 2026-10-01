// Build script for the local Quartz plugins (sqlite-index + sqlite-search).
// Run with: node quartz/plugins/build.mjs
import { build } from "esbuild"
import { copyFileSync, mkdirSync, cpSync, rmSync, symlinkSync, existsSync } from "fs"
import path from "path"
import { fileURLToPath } from "url"

const root = path.dirname(fileURLToPath(import.meta.url))

async function main() {
  // --- Emitter (Node): slim contentIndex.json + build FTS5 sqlite ---
  // Built as CommonJS because sql.js (CJS) calls require("fs") and uses __dirname.
  await build({
    entryPoints: [path.join(root, "sqlite-index/src/index.ts")],
    outfile: path.join(root, "sqlite-index/dist/index.js"),
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node20",
    external: ["@quartz-community/types", "@quartz-community/utils"],
    logLevel: "info",
  })

  // --- Component (Browser): on-demand SQLite search ---
  await build({
    entryPoints: [path.join(root, "sqlite-search/src/components/index.ts")],
    outfile: path.join(root, "sqlite-search/dist/components/index.js"),
    bundle: true,
    platform: "browser",
    format: "esm",
    target: "es2020",
    external: ["preact", "@quartz-community/types", "@quartz-community/utils"],
    loader: { ".tsx": "tsx", ".ts": "ts" },
    logLevel: "info",
  })

  // --- Copy sqlite worker + wasm into quartz/static so they are served at /static ---
  const staticDir = path.join(root, "..", "static")
  mkdirSync(staticDir, { recursive: true })
  const httpvfs = path.join(root, "..", "..", "node_modules", "sql.js-httpvfs", "dist")
  copyFileSync(path.join(httpvfs, "sqlite.worker.js"), path.join(staticDir, "sqlite.worker.js"))
  copyFileSync(path.join(httpvfs, "sql-wasm.wasm"), path.join(staticDir, "sql-wasm.wasm"))

  // --- Link built plugins into .quartz/plugins so the Quartz loader skips its
  //     own symlink step (which needs admin/Developer-Mode on Windows and fails
  //     with EPERM). We create a *junction* (Windows) / normal symlink (Linux),
  //     which the loader recognizes as "already linked" and leaves alone.
  //     The loader only re-symlinks when the target is NOT already a symlink to
  //     the right place, so a junction satisfies it on every platform. ---
  const quartzPlugins = path.join(root, "..", "..", ".quartz", "plugins")
  mkdirSync(quartzPlugins, { recursive: true })
  for (const name of ["sqlite-index", "sqlite-search"]) {
    const dest = path.join(quartzPlugins, name)
    const src = path.join(root, name)
    if (existsSync(dest)) rmSync(dest, { recursive: true, force: true })
    try {
      // junction: works on Windows without admin; ignored-type -> normal symlink on Linux
      symlinkSync(src, dest, "junction")
    } catch {
      try {
        symlinkSync(src, dest, "dir")
      } catch {
        // absolute last resort (loader will re-symlink, but keeps a usable copy)
        cpSync(src, dest, { recursive: true })
      }
    }
  }

  console.log("Built sqlite-index + sqlite-search, copied worker/wasm to quartz/static, and installed into .quartz/plugins.")
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
