# syntax=docker/dockerfile:1

# ---------- 阶段 1：安装依赖（层缓存稳定，仅依赖/quartz 框架变更时重建） ----------
FROM node:22-slim AS deps
# git 供 @quartz-community/created-modified-date 读取文章创建/修改时间
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /usr/src/app
COPY package.json package-lock.json* .npmrc* ./
COPY quartz/ ./quartz/
COPY quartz.lock.json* ./
RUN npm install; npx quartz plugin install

# ---------- 阶段 2：镜像构建期内完成全站构建（bake），产物生成 public/ ----------
FROM deps AS builder
WORKDIR /usr/src/app
# content 与 .git 需进构建上下文：content 是站点源，.git 供 created-modified-date 读历史
COPY . .
# 2 核小内存加固：限制 V8 堆 + 固定并发，防止 docker build 期间 OOM / CPU 抢占
ENV NODE_OPTIONS=--max-old-space-size=1536
RUN npx quartz build --output public --concurrency 2

# ---------- 阶段 3：运行时纯静态服务，启动即秒级可用，不再有任何构建 ----------
FROM node:22-slim
WORKDIR /usr/src/app
COPY --from=builder /usr/src/app/public ./public
COPY server.mjs .
EXPOSE 8080
CMD ["node", "server.mjs"]
