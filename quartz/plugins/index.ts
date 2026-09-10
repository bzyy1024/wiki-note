import { StaticResources } from "../util/resources"
import { BuildCtx } from "../util/ctx"
import { rewriteExternalAssets } from "../util/selfHostedAssets"

export function getStaticResourcesFromPlugins(ctx: BuildCtx) {
  const staticResources: StaticResources = {
    css: [],
    js: [],
    additionalHead: [],
  }

  for (const transformer of [...ctx.cfg.plugins.transformers, ...ctx.cfg.plugins.emitters]) {
    const res = transformer.externalResources ? transformer.externalResources(ctx) : {}
    if (res?.js) {
      staticResources.js.push(...res.js)
    }
    if (res?.css) {
      staticResources.css.push(...res.css)
    }
    if (res?.additionalHead) {
      staticResources.additionalHead.push(...res.additionalHead)
    }
  }

  // if serving locally, listen for rebuilds and reload the page
  if (ctx.argv.serve) {
    const wsUrl = ctx.argv.remoteDevHost
      ? `wss://${ctx.argv.remoteDevHost}:${ctx.argv.wsPort}`
      : `ws://localhost:${ctx.argv.wsPort}`

    staticResources.js.push({
      loadTime: "afterDOMReady",
      contentType: "inline",
      script: `
        const socket = new WebSocket('${wsUrl}')
        // reload(true) ensures resources like images and scripts are fetched again in firefox
        socket.addEventListener('message', () => document.location.reload(true))
      `,
    })
  }

  // 插件默认可能从公共 CDN 加载前端资源（例如 KaTeX），这里统一改写为本站
  // `static/vendor/**` 的本地副本，保证浏览器只向本站发起请求。
  staticResources.css = staticResources.css.map((resource) => ({
    ...resource,
    content: rewriteExternalAssets(resource.content),
  }))
  staticResources.js = staticResources.js.map((resource) =>
    resource.contentType === "external"
      ? { ...resource, src: rewriteExternalAssets(resource.src) }
      : { ...resource, script: rewriteExternalAssets(resource.script) },
  )

  return staticResources
}

export * from "./transformers"
export * from "./filters"
export * from "./emitters"
export * from "./types"
export * from "./config"
export * as PageTypes from "./pageTypes"
export * as PluginLoader from "./loader"
