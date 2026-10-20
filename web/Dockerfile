# 知识治理专家（KGE）前端镜像：pnpm 构建 + nginx 托管。
# 宿主端口约定 8080（与生产 deploy/intranet/nginx-kge.conf 一致），容器内 80。
FROM node:24-alpine AS build
WORKDIR /app
# vitepress 产品手册构建需要 git（last-updated/dead-link 检测），alpine 基础镜像默认不带
RUN corepack enable && corepack prepare pnpm@11.17.0 --activate && apk add --no-cache git
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# 容器内无 .git，给 vitepress 一个临时仓库以便 last-updated 检测（构建层随多阶段丢弃，不影响产物）
RUN git init -q . && git add -A && git -c user.email=build@local -c user.name=build commit -qm "docker build"
# 覆盖 portal 入口默认值（留空则组件回退主机默认端口）：如部署独立域名用构建参数传入
ARG VITE_PORTAL_URL=
ENV VITE_PORTAL_URL=$VITE_PORTAL_URL
RUN pnpm build

FROM nginx:1.28-alpine
# 默认面向 compose 容器网络；本机后端联调可用 -e 覆盖为 http://host.docker.internal:8000/8004
ENV KB_API_UPSTREAM=http://kb-api:8000 FAQ_API_UPSTREAM=http://faq-service:8004
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
