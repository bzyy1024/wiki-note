import path from "path"
import fs from "fs/promises"
import { statSync } from "fs"

// sql.js default build has no FTS5; we use a plain `LIKE` substring search which
// works for any language (including CJK of any length) and needs no extra engine.
import initSqlJs from "sql.js"

interface SqliteIndexOptions {
  enableSiteMap?: boolean
  enableRSS?: boolean
  rssLimit?: number
  rssFullHtml?: boolean
  rssSlug?: string
  rssRecentNotesText?: string
  rssLastFewNotesText?: string | ((count: number) => string)
}

interface Entry {
  slug: string
  filePath: string
  title: string
  links: string[]
  tags: string[]
  content: string
  date: string
  description: string
}

async function writeFileToOutput(
  output: string,
  slug: string,
  ext: string,
  content: string | Uint8Array,
): Promise<string> {
  const target = path.join(output, slug + ext)
  await fs.mkdir(path.dirname(target), { recursive: true })
  await fs.writeFile(target, content)
  return target
}

function getDate(data: any): Date | undefined {
  const defaultDateType = data.defaultDateType
  if (!defaultDateType) return undefined
  const dates = data.dates
  return dates?.[defaultDateType]
}

function escapeHTML(unsafe: string): string {
  return unsafe
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;")
}

function joinSegments(...parts: string[]): string {
  return parts
    .map((p) => p.replace(/^\/+|\/+$/g, ""))
    .filter(Boolean)
    .join("/")
}

function simplifySlug(slug: string): string {
  return slug.replace(/\/index$/, "") || "/"
}

function generateSiteMap(base: string, entries: Entry[]): string {
  const urls = entries
    .map(
      (e) => `<url>
  <loc>https://${joinSegments(base, encodeURI(simplifySlug(e.slug)))}</loc>
</url>`,
    )
    .join("")
  return `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">${urls}</urlset>`
}

function generateRSSFeed(
  cfg: any,
  entries: Entry[],
  options: Required<SqliteIndexOptions>,
): string {
  const base = cfg.baseUrl ?? ""
  const pageTitle = cfg.pageTitle ?? ""
  const recentNotesText = options.rssRecentNotesText
  const lastFewNotesText =
    typeof options.rssLastFewNotesText === "function"
      ? options.rssLastFewNotesText(options.rssLimit)
      : options.rssLastFewNotesText.replace("${count}", String(options.rssLimit))

  const items = entries
    .slice()
    .sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
    .slice(0, options.rssLimit)
    .map(
      (e) => `<item>
    <title>${escapeHTML(e.title)}</title>
    <link>https://${joinSegments(base, encodeURI(simplifySlug(e.slug)))}</link>
    <guid>https://${joinSegments(base, encodeURI(simplifySlug(e.slug)))}</guid>
    <description><![CDATA[ ${e.description} ]]></description>
    <pubDate>${new Date(e.date).toUTCString()}</pubDate>
  </item>`,
    )
    .join("")

  const description = options.rssLimit
    ? `${lastFewNotesText} on ${escapeHTML(pageTitle)}`
    : `${recentNotesText} on ${escapeHTML(pageTitle)}`

  return `<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
  <channel>
    <title>${escapeHTML(pageTitle)}</title>
    <link>https://${base}</link>
    <description>${description}</description>
    <generator>Quartz -- quartz.jzhao.xyz</generator>
    ${items}
  </channel>
</rss>`
}

export const SqliteIndex: QuartzEmitterPlugin = (opts?: SqliteIndexOptions) => {
  const options: Required<SqliteIndexOptions> = {
    enableSiteMap: true,
    enableRSS: true,
    rssLimit: 10,
    rssFullHtml: false,
    rssSlug: "index",
    rssRecentNotesText: "Recent notes",
    rssLastFewNotesText: (count: number) => `Last ${count} notes`,
    ...opts,
  }

  return {
    name: "SqliteIndex",
    async emit(ctx, content: ProcessedContent[]) {
      const output = ctx.argv.output
      const cfg = (ctx.cfg as any)?.configuration ?? {}
      const entries: Entry[] = []

      for (const [, file] of content) {
        const data: any = file.data ?? {}
        if (data.unlisted === true) continue
        const slug = data.slug
        if (!slug) continue

        const frontmatter = data.frontmatter ?? {}
        const text: string = data.text ?? ""
        entries.push({
          slug,
          filePath: data.relativePath ?? "",
          title: frontmatter.title ?? "",
          links: data.links ?? [],
          tags: frontmatter.tags ?? [],
          content: text,
          date: (getDate(data) ?? new Date()).toISOString(),
          description: data.description ?? "",
        })
      }

      const emitted: string[] = []

      // 1) Slim contentIndex.json — only metadata needed by Graph / Explorer / Backlinks.
      const slim = Object.fromEntries(
        entries.map((e) => [
          e.slug,
          {
            slug: e.slug,
            filePath: e.filePath,
            title: e.title,
            links: e.links,
            tags: e.tags,
          },
        ]),
      )
      const jsonPath = await writeFileToOutput(
        output,
        "static/contentIndex",
        ".json",
        JSON.stringify(slim),
      )
      emitted.push(jsonPath)

      // 2) Build contentIndex.sqlite holding the full text for on-demand search.
      //    The browser reads this file via HTTP Range requests (sql.js-httpvfs),
      //    so it is only fetched when the user actually searches.
      const SQL = await initSqlJs({
        locateFile: () => path.resolve(process.cwd(), "node_modules/sql.js/dist/sql-wasm.wasm"),
      })
      const db = new SQL.Database()
      db.run(
        `CREATE TABLE pages (
           id INTEGER PRIMARY KEY,
           slug TEXT,
           title TEXT,
           tags TEXT,
           content TEXT,
           date TEXT,
           description TEXT
         );`,
      )
      const ins = db.prepare(
        "INSERT INTO pages (id, slug, title, tags, content, date, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
      )
      db.run("BEGIN TRANSACTION")
      let id = 1
      for (const e of entries) {
        ins.run([id, e.slug, e.title, e.tags.join(","), e.content, e.date, e.description])
        id++
      }
      db.run("COMMIT")
      ins.free()

      const sqlitePath = await writeFileToOutput(
        output,
        "static/contentIndex",
        ".sqlite",
        db.export() as Uint8Array,
      )
      db.close()
      emitted.push(sqlitePath)

      // 3) Sitemap — replaces the default ContentIndex emitter.
      if (options.enableSiteMap) {
        const siteMapPath = await writeFileToOutput(
          output,
          "sitemap",
          ".xml",
          generateSiteMap(cfg.baseUrl ?? "", entries),
        )
        emitted.push(siteMapPath)
      }

      // 4) RSS feed — replaces the default ContentIndex emitter.
      if (options.enableRSS) {
        const rssPath = await writeFileToOutput(
          output,
          options.rssSlug,
          ".xml",
          generateRSSFeed(cfg, entries, options),
        )
        emitted.push(rssPath)
      }

      console.log(
        `[sqlite-index] wrote ${entries.length} pages → slim JSON (${slimSize(jsonPath)}) + sqlite (${slimSize(sqlitePath)})`,
      )

      return emitted
    },
  }
}

function slimSize(p: string): string {
  try {
    const s = statSync(p).size
    return (s / 1024 / 1024).toFixed(2) + " MB"
  } catch {
    return "?"
  }
}

export default SqliteIndex
