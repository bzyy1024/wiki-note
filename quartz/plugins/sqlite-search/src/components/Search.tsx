import { h } from "preact"
import { createDbWorker } from "sql.js-httpvfs"
import type {
  QuartzComponentConstructor,
  QuartzComponentProps,
} from "@quartz-community/types"

// Expose the worker factory globally so the inline bootstrap (which runs in the
// global scope) can reach the module-scoped import.
;(globalThis as any).__createDbWorker = createDbWorker

function SearchComponent(_props: QuartzComponentProps) {
  return h("div", { class: "search" }, [
    h(
      "button",
      {
        class: "search-button",
        id: "search-button",
        "aria-label": "Search",
        type: "button",
      },
      [
        h(
          "svg",
          {
            xmlns: "http://www.w3.org/2000/svg",
            width: "18",
            height: "18",
            viewBox: "0 0 24 24",
            fill: "none",
            stroke: "currentColor",
            "stroke-width": "2",
            "stroke-linecap": "round",
            "stroke-linejoin": "round",
          },
          [
            h("circle", { cx: "11", cy: "11", r: "8" }),
            h("line", { x1: "21", y1: "21", x2: "16.65", y2: "16.65" }),
          ],
        ),
        h("p", null, "Search"),
      ],
    ),
    h("div", { class: "search-container", id: "search-container" }, [
      h("div", { class: "search-space" }, [
        h("div", { class: "search-bar" }, [
          h("input", {
            type: "text",
            id: "search-input",
            class: "search-input",
            placeholder: "Search",
            "aria-label": "Search query",
            autocomplete: "off",
            spellcheck: false,
          }),
          h(
            "button",
            { class: "search-close", id: "search-close", "aria-label": "Close search", type: "button" },
            "✕",
          ),
        ]),
        h("div", { class: "search-results", id: "search-results" }),
      ]),
    ]),
  ])
}

SearchComponent.css = `
.search {
  min-width: fit-content;
  max-width: 14rem;
}
@media all and (max-width: 800px) {
  .search { flex-grow: 0.3; }
}
.search > .search-button {
  background-color: transparent;
  border: 1px var(--lightgray) solid;
  border-radius: 4px;
  font-family: inherit;
  font-size: inherit;
  height: 2rem;
  padding: 0 1rem 0 0;
  display: flex;
  align-items: center;
  text-align: inherit;
  cursor: pointer;
  white-space: nowrap;
  width: 100%;
  color: var(--darkgray);
}
.search > .search-button:hover { border-color: var(--gray); }
.search > .search-button > p {
  display: inline;
  color: var(--gray);
  text-wrap: unset;
}
.search > .search-button svg {
  cursor: pointer;
  width: 18px;
  min-width: 18px;
  margin: 0 0.5rem;
}
.search > .search-container {
  position: fixed;
  contain: layout;
  z-index: var(--search-z-index, 999);
  left: 0;
  top: 0;
  width: 100vw;
  height: 100vh;
  background: var(--light);
  display: none;
}
.search > .search-container > .search-space {
  width: 100%;
  max-width: 48rem;
  margin: 0 auto;
  padding: 6rem 1rem 1rem;
  display: flex;
  flex-direction: column;
  height: 100%;
}
.dark .search > .search-container { background: var(--dark); }
.search-bar {
  display: flex;
  gap: 0.5rem;
  border-bottom: 2px solid var(--lightgray);
  padding-bottom: 0.5rem;
}
.search-input {
  flex: 1 1 auto;
  font-size: 1.4rem;
  font-family: inherit;
  background: transparent;
  border: none;
  outline: none;
  color: var(--dark);
}
.dark .search-input { color: var(--light); }
.search-close {
  background: transparent;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  color: var(--gray);
}
.search-results {
  margin-top: 1rem;
  overflow-y: auto;
  flex: 1 1 auto;
}
.search-result {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.6rem 0.2rem;
  border-bottom: 1px solid var(--lightgray);
  text-decoration: none;
  color: var(--dark);
}
.dark .search-result { color: var(--light); }
.search-result-title { font-weight: 600; }
.search-result-snippet {
  font-size: 0.85rem;
  color: var(--gray);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.search-result mark { background: var(--tertiary); color: inherit; border-radius: 2px; }
.search-noresult { color: var(--gray); padding: 1rem 0.2rem; }
`

// --- Browser-side search logic (real TS, bundled; runs only in the browser) ---
function initSearch() {
  const button = document.getElementById("search-button")
  const container = document.getElementById("search-container")
  const input = document.getElementById("search-input") as HTMLInputElement | null
  const results = document.getElementById("search-results")
  const closeBtn = document.getElementById("search-close")
  if (!button || !container || !input || !results) return

  let dbPromise: Promise<any> | null = null
  function getDb() {
    if (dbPromise) return dbPromise
    const factory = (globalThis as any).__createDbWorker
    if (!factory) {
      dbPromise = Promise.reject(new Error("search worker not loaded"))
      return dbPromise
    }
    dbPromise = factory(
      [{ virtualFilename: "db", from: "inline", config: { serverMode: "full", url: "/static/contentIndex.sqlite" } }],
      "/static/sqlite.worker.js",
      "/static/sql-wasm.wasm",
    )
      .then((r: any) => r.db)
      .catch((e: any) => {
        dbPromise = null
        throw e
      })
    return dbPromise
  }

  function openSearch() {
    ;(container as HTMLElement).style.display = "block"
    setTimeout(() => input!.focus(), 0)
    document.addEventListener("keydown", onKey)
  }
  function closeSearch() {
    ;(container as HTMLElement).style.display = "none"
    results!.innerHTML = ""
    input!.value = ""
    document.removeEventListener("keydown", onKey)
  }
  function onKey(e: KeyboardEvent) {
    if (e.key === "Escape") closeSearch()
  }

  button.addEventListener("click", openSearch)
  closeBtn?.addEventListener("click", closeSearch)
  container.addEventListener("click", (e) => {
    if (e.target === container) closeSearch()
  })

  let timer: any = null
  input.addEventListener("input", () => {
    const q = input!.value.trim()
    clearTimeout(timer)
    if (q.length < 1) {
      results!.innerHTML = ""
      return
    }
    timer = setTimeout(() => runSearch(q), 200)
  })

  const escapeHtml = (s: string) =>
    s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!)

  function makeSnippet(content: string, words: string[]): string {
    const lower = content.toLowerCase()
    let idx = -1
    for (const w of words) {
      const p = lower.indexOf(w.toLowerCase())
      if (p >= 0 && (idx < 0 || p < idx)) idx = p
    }
    if (idx < 0) idx = 0
    const start = Math.max(0, idx - 50)
    const end = Math.min(content.length, idx + 80)
    let piece = content.slice(start, end)
    if (start > 0) piece = "…" + piece
    if (end < content.length) piece = piece + "…"
    let esc = escapeHtml(piece)
    for (const w of words) {
      if (!w) continue
      try {
        const re = new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi")
        esc = esc.replace(re, (m) => "<mark>" + m + "</mark>")
      } catch {
        /* ignore invalid regex */
      }
    }
    return esc
  }

  async function runSearch(q: string) {
    try {
      const db = await getDb()
      // Tokenize the query with the same word segmenter used at build time, so a
      // query word matches an independent word in `seg`, not a substring.
      const seg = new Intl.Segmenter("zh", { granularity: "word" })
      const words: string[] = []
      for (const { segment, isWordLike } of seg.segment(q)) {
        const w = segment.trim()
        if (isWordLike && w) words.push(w)
      }
      if (!words.length) {
        results!.innerHTML = ""
        return
      }
      // `seg` is padded with spaces, so a leading/trailing space turns a LIKE
      // into a word-boundary match (e.g. "% 程序 %" won't hit "程序员").
      const patternFor = (w: string) => "% " + w.replace(/[%~_]/g, (c) => "\\" + c) + " %"
      const conds = words
        .map(() => "(seg LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\')")
        .join(" AND ")
      const params: string[] = []
      words.forEach((w) => {
        const p = patternFor(w)
        params.push(p, p)
      })
      const sql = "SELECT slug, title, content FROM pages WHERE " + conds + " LIMIT 60"
      const rows: any[] = await (db as any).query(sql, ...params)
      if (!rows || !rows.length) {
        results!.innerHTML = '<p class="search-noresult">无结果。</p>'
        return
      }
      const max = Math.min(rows.length, 30)
      let html = ""
      for (let i = 0; i < max; i++) {
        const r = rows[i]
        const snip = makeSnippet(r.content || "", words)
        const title = escapeHtml(r.title || r.slug)
        html +=
          '<a class="search-result" href="' +
          escapeHtml(r.slug) +
          '">' +
          '<span class="search-result-title">' +
          title +
          '</span>' +
          '<span class="search-result-snippet">' +
          snip +
          "</span></a>"
      }
      results!.innerHTML = html
    } catch (e: any) {
      results!.innerHTML =
        '<p class="search-noresult">搜索不可用：' + escapeHtml(String(e?.message || e)) + "</p>"
    }
  }
}

;(globalThis as any).__initSqliteSearch = initSearch

// After the page DOM is ready, wire up the browser-side search UI.
// NOTE: afterDOMLoaded must be a string (StringResource), not a function.
SearchComponent.afterDOMLoaded = `window.__initSqliteSearch && window.__initSqliteSearch();`

// Quartz expects a constructor: (options) => QuartzComponent.
// The loader calls this with the plugin's YAML options and uses the returned
// component (body function) for rendering.
const Search: QuartzComponentConstructor = () => SearchComponent

export default Search
export { Search }
