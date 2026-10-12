FROM node:24-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.17.0 --activate
ARG VITE_KNOWLEDGE_URL=/kge/chat
ARG VITE_EVALUATION_URL=/evaluation/datasets
ARG VITE_SKILLHUB_URL=/skillhub/
ENV VITE_KNOWLEDGE_URL=$VITE_KNOWLEDGE_URL \
    VITE_EVALUATION_URL=$VITE_EVALUATION_URL \
    VITE_SKILLHUB_URL=$VITE_SKILLHUB_URL
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.28-alpine
ENV PORTAL_API_TARGET=http://host.docker.internal:8080
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
