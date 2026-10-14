# 杰克科技 AIGC 门户

独立的 Vue 3 + TypeScript + Element Plus 应用。首页为「小杰」智能助手，左侧整合知识治理专家、智能体测评与 SkillHub。可单独构建和部署，不修改现有知识治理系统。

## 本地启动

```bash
cd portal
pnpm install
cp .env.example .env
pnpm dev
```

访问 http://localhost （默认端口 80 归门户，本地与生产口径一致）。需要能访问 10.10.166.2 的内网环境。

```bash
pnpm type-check
pnpm test:run
pnpm build
```

## 统一账号与身份

门户与知识治理专家共享同一后端认证配置（`GET /api/v1/auth/config`）。

- `AUTH_PROVIDER=keycloak`：门户与知识治理专家使用同一个 Realm，采用授权码 + PKCE S256；登录一次后，另一应用复用身份中心会话。
- `AUTH_PROVIDER=local`：兼容知识治理专家原有账号，由真实后端校验；门户不再有独立账号或前端口令校验。此模式只共享账号数据，不提供跨应用 SSO。
- 小杰使用本次登录的访问令牌调用企业问答，无需二次登录。令牌仅存于内存，刷新通过身份中心恢复会话；过期前自动刷新。
- 门户底部「企业账号」可进入个人账号中心（自助改密等）；管理员可在门户「系统管理 → 账号管理」页直接新增/停用/删除账号、分配知识治理角色、重置初始密码，无需访问身份中心控制台。
- 生产入口在网关层使用 OAuth2 Proxy 验证 Keycloak 会话；门户、知识治理专家、测评和 SkillHub 的页面、API、下载及 WebSocket 均必须经过网关。

部署、角色映射、账号迁移和验证步骤见 [统一身份中心说明](../deploy/keycloak/README.md)。模型和知识权限仍由知识治理专家后端执行。

## 应用入口

| 应用 | 默认地址 | 构建环境变量 |
| --- | --- | --- |
| 知识治理专家 | `/kge/chat`（开发默认） | `VITE_KNOWLEDGE_URL` |
| 智能体测评 | `/evaluation/datasets`（开发默认） | `VITE_EVALUATION_URL` |
| SkillHub | `/skillhub/`（开发默认） | `VITE_SKILLHUB_URL` |

生产环境建议为门户和三个应用配置同一受控域下的 HTTPS 主机名，由单一入口反向代理转发；所有主机共享 Keycloak 登录会话。门户 iframe 与新窗口入口使用这些 HTTPS 地址，应用源站端口仅允许入口代理访问。

## 独立部署

```bash
cd portal
docker compose up -d --build
```

本机端口 `3200` 仅绑定到 loopback，对外统一由宿主 Nginx 默认端口（80）反代——**默认端口归门户**，站点配置见 [`deploy/intranet/nginx-portal-80.conf`](../deploy/intranet/nginx-portal-80.conf)（安装命令见该文件头注释）。`PORTAL_API_TARGET` 指向可信知识治理服务。生产前端链接在镜像构建时由 `VITE_KNOWLEDGE_URL`、`VITE_EVALUATION_URL`、`VITE_SKILLHUB_URL` 设置，不得配置裸 IP、HTTP 或端口直连。

如不使用 Docker，将 `dist/` 部署到 Nginx 并按 `nginx.conf.template` 配置 API 代理。`pnpm preview` 仅用于检查静态产物，不代理问答服务。生产环境建议统一配置 HTTPS，包括被嵌入的应用。

## 生产环境统一入口

入口样例见 [`deploy/intranet/nginx-portal.conf`](../deploy/intranet/nginx-portal.conf)。它把门户、知识治理专家、测评、SkillHub 的 HTTPS 主机统一接到 OAuth2 Proxy；未登录浏览器跳转统一登录，API 未登录返回 401。请先将配置中的 `*.example.com` 和证书路径换成已备案/签发的正式值，再执行 `nginx -t` 和 reload。

生产环境准备：

1. 为 `portal`、`kge`、`evaluation`、`skillhub` 配置 DNS 与覆盖所有主机名的 HTTPS 证书；Keycloak issuer 使用正式 HTTPS 地址。
2. 在 Keycloak 创建 confidential OIDC 客户端 `jack-gateway`，只允许精确回调 `https://<门户域名>/oauth2/callback`，关闭 Direct Access Grants 和 Implicit Flow。客户端密钥只写在服务器环境文件中。
3. 在 `portal/.env` 配置 `PORTAL_PUBLIC_ORIGIN`、`OIDC_ISSUER`、`GATEWAY_CLIENT_SECRET`、随机 `OAUTH2_PROXY_COOKIE_SECRET`、受控的 `SSO_COOKIE_DOMAIN`，以及三个 `VITE_*_URL` 正式 HTTPS 地址。Cookie 域仅覆盖这组受控子域。
4. 执行 `docker compose --profile sso-gateway up -d --build`；OAuth2 Proxy 仅绑定 `127.0.0.1:4180`，门户仅绑定 `127.0.0.1:3200`。
5. 防火墙/安全组只允许公网访问 HTTPS 入口；封锁 `3200`、`8080`、`8082`、`3100`、`8001`、`8004`、`2027`、`4180`、`8180` 等应用和管理端口。网关后端端口仅允许本机或受控容器网络访问。
6. 测评和 SkillHub 当前不在本仓库源码中。上线前必须确认它们正确处理网关身份头，或各自接入 OIDC；只在 Nginx 传递身份头并不能替代应用内授权。务必关闭源站直连，否则客户端可以伪造身份头绕过网关。
