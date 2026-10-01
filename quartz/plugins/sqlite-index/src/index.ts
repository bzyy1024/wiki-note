import path from "path"
import fs from "fs/promises"
import { statSync } from "fs"
// sql.js default build has no FTS5; we use a plain `LIKE` substring search which
// works for any language (including CJK of any length) and needs no extra engine.
import initSqlJs from "sql.js"

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

export const SqliteIndex: QuartzEmitterPlugin = () => {
  return {
    name: "SqliteIndex",
    async emit(ctx, content: ProcessedContent[]) {
      const output = ctx.argv.output
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

      // 1) Slim contentIndex.json — drop the heavy `content`/`description`/`date`
      //    fields. Graph / Explorer / Backlinks only need slug/title/links/tags.
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

      console.log(
        `[sqlite-index] wrote ${entries.length} pages → slim JSON (${slimSize(jsonPath)}) + sqlite (${slimSize(sqlitePath)})`,
      )

      return [jsonPath, sqlitePath]
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
