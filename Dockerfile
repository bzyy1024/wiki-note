FROM node:22-slim AS builder

# install git to install plugins
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app
COPY package.json .
COPY package-lock.json* .
COPY .npmrc* .
COPY quartz/ ./quartz/
COPY quartz.lock.json* .
RUN npm install; npx quartz plugin install

FROM node:22-slim
WORKDIR /usr/src/app
COPY --from=builder /usr/src/app/ /usr/src/app/
COPY . .

# 2 核小内存服务器加固：
# 1) 限制 V8 堆内存，防止全量构建吃光内存触发 OOM（可按服务器内存调 1024~2048）
# 2) 构建并发固定为 2，避免 worker 线程抢占 CPU
ENV NODE_OPTIONS=--max-old-space-size=1588
# --serve 会先构建 public/ 再用自带 serve-handler 监听 8080
EXPOSE 8080
CMD ["npx", "quartz", "build", "--serve", "--port", "8080", "--wsPort", "3001", "--concurrency", "2"]
