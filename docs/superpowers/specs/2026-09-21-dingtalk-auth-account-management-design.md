# 钉钉认证与账户管理 · 设计方案

- 版本：v1.0（2026-09-21）
- 作者：黄景新（AI 创新 COE）
- 关联仓库：knowledge-governance-expert（feat/mvp 分支）
- 关联现状：`services/kb-api/app/routes/auth.py`、`services/kb-api/app/services/dingtalk_identity.py`、`kb_common/models.py:9-17,651-666`

---

## 一、背景与目标

### 1.1 现状痛点

| 现状 | 问题 |
|---|---|
| `resolve_user()` 已能按 `(corp_id, dt_userid)` 自动建档，但**建档时用 `secrets.token_urlsafe(24)` 生成随机 password_hash** | 新用户拿不到密码，也无法自主设置；一旦钉钉侧异常（换手机、退出组织），账号立刻失联 |
| 钉钉免登只在 `/chat` 页做 H5 免登（`dd.getAuthCode`） | PC 浏览器打开 `/login` 只能用 admin 账号密码；无法让业务用户自助进入 |
| `Setting.dingtalk_operator_union_id` 是**全局单值**，被 `dingtalk_client.py` / `sync_settings.py` / `agent_internal.py` 共用 | 后台同步任务用管理员的 union_id 拉知识库，**权限被拉高**：普通用户看不到全量库，但同步后落到本系统就都能检索 |
| `users.py` 只有管理员能改密码，用户端**没有"忘记密码/修改密码"入口** | 管理员重置后用户仍不知道密码；也无法强制首次改密 |
| KB 表已有 `owner_id`，但同步链路**没用它**取 operator | 天然可以按 owner 权限过滤，却没落地 |

### 1.2 目标（本次范围）

1. **登录入口双通道**：Web 端登录页新增"钉钉扫码"Tab；PC 扫码与钉钉工作台内 H5 免登共用后端 `POST /auth/dingtalk-login`。
2. **首次建档强制设密**：钉钉认证通过后，若用户是新建（无密码），跳到 `/onboarding/set-password` 要求设两次密码，写入 `password_hash` + `password_updated_at`。
3. **钉钉身份按登录用户维度**：
   - JWT payload 补 `dt_unionid`；`DingtalkClient` 所有调用点接受 `operator_union_id` 参数。
   - 同步任务按 `KB.owner_id → User → DingtalkBinding.dt_unionid` 取 operator；owner 缺失或未绑定钉钉时**回退全局** `dingtalk_operator_union_id` 作为服务账号兜底。
   - 前端 `agent_internal` 检索接口按 JWT 里的 `sub` 反查 union_id。
4. **管理员账户管理增强**：
   - "用户管理"页新增列：钉钉姓名、dt_userid、绑定时间、`must_change_password`。
   - 管理员重置密码时勾选"要求下次登录改密" → `must_change_password=true`；用户下次密码登录/扫码登录都会跳设密页。
   - 支持"解绑钉钉"操作（保留本地用户，清 `DingtalkBinding`）。
5. **用户自助**：`/settings/account` 页支持改密码（需旧密码）、查看钉钉绑定状态。

### 1.3 非目标（本次不做）

- 钉钉部门/角色自动映射到本系统 role（后续 v2）
- SSO 单点登出、Refresh Token、多设备会话管理
- 邮箱/手机号找回密码（内网工具，走管理员重置）
- 双因子认证

---

## 二、产品方案

### 2.1 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-01 | **作为**新员工，**我希望**用钉钉扫码登录知识治理平台，**以便**不用记额外账号密码。 | P0 |
| US-02 | **作为**首次登录的新员工，**我希望**扫码后被引导设置一个本地密码，**以便**钉钉不可用时也能进入系统。 | P0 |
| US-03 | **作为**普通业务用户，**我希望**在系统里只看到我在钉钉侧有权限的知识库，**以便**符合公司数据分级要求。 | P0 |
| US-04 | **作为**知识库 owner，**我希望**我创建的 KB 用我的钉钉身份同步，**以便**同步范围与我实际权限一致。 | P0 |
| US-05 | **作为**管理员，**我希望**在用户管理页看到每个人的钉钉姓名和绑定时间，**以便**排查权限问题。 | P1 |
| US-06 | **作为**管理员，**我希望**重置某个用户密码时勾选"强制下次改密"，**以便**避免用户长期使用初始密码。 | P1 |
| US-07 | **作为**管理员，**我希望**能把某个用户的钉钉绑定解除，**以便**处理换岗/离职场景。 | P1 |
| US-08 | **作为**已登录用户，**我希望**在个人设置里主动改密码，**以便**定期轮换。 | P2 |
| US-09 | **作为**运维，**我希望**同步任务在 KB.owner 未绑定钉钉时**回退到全局服务账号**而不是失败，**以便**历史 KB 平滑过渡。 | P0 |
| US-10 | **作为**首个通过钉钉登录的用户（冷启动场景），**我希望**系统已有 admin/admin123 种子账号，**以便**至少有一个 super_admin 能给我授权。 | P0（依赖 `scripts/seed_admin.py`，无新增开发） |

### 2.2 功能需求（FR）

**FR-1 认证与登录**
- FR-1.1 `POST /auth/dingtalk-login` body `{auth_code, corp_id?}` → 返回 `{access_token, token_type, user, must_set_password}`；`must_set_password=true` 时前端强制跳 `/onboarding/set-password`。
- FR-1.2 `GET /auth/dingtalk-config` 扩展返回 `{corp_id, app_key, auto_login_enabled, qr_login_enabled, redirect_uri}`；`qr_login_enabled` 由 Setting `dingtalk_qr_login_enabled`（默认 true）控制。
- FR-1.3 `POST /auth/set-password` 需 JWT，body `{new_password, new_password_confirm}`；仅当 `must_change_password=true` 或 `password_updated_at IS NULL` 时允许；成功后 `must_change_password=false`，`password_updated_at=now()`。
- FR-1.4 `POST /auth/change-password` 需 JWT，body `{old_password, new_password, new_password_confirm}`；任何时候可用。
- FR-1.5 `POST /auth/login` 密码登录，成功后若 `must_change_password=true`，返回同结构带该字段，前端跳设密页。
- FR-1.6 JWT payload 新增 `dt_unionid`（有绑定时）、`must_change_password`（bool），TTL 保持 `jwt_ttl_minutes`。

**FR-2 权限与同步身份**
- FR-2.1 `DingtalkClient` 所有涉及"读取用户可见资源"的方法（`list_nodes` / `get_doc_content` / `search_docs` 等）签名新增 `operator_union_id: str | None = None`；不传时回退到 `Setting.dingtalk_operator_union_id`。
- FR-2.2 `services/sync/sync_settings.resolve_operator(kb_id)`：`KB.owner_id → User → DingtalkBinding.dt_unionid`；owner 不存在或未绑定 → 全局 Setting；均无 → 抛 `OperatorUnavailable` 让同步任务落 FAILED 并写审计日志。
- FR-2.3 `routes/agent_internal.py` 中所有钉钉检索/读取工具，从 JWT `sub` 反查 `dt_unionid` 后传入 client；无绑定时使用全局。
- FR-2.4 KB 创建接口 `POST /knowledge-bases` 强制 `owner_id=current_user.id`（不再接受 body 传入）；已有 KB 的 owner 保持不变。
- FR-2.5 同步任务日志新增字段 `operator_source ∈ {owner_binding, global_fallback}`，写入 `sync_tasks.meta`，前端"同步历史"页可见。

**FR-3 账户管理（管理员）**
- FR-3.1 `GET /users?include_binding=true` 响应每用户附 `dingtalk_binding: {dt_name, dt_userid, dt_unionid, corp_id, bound_at} | null`。
- FR-3.2 `PATCH /users/{id}` body 支持 `password`、`must_change_password`、`role`、`is_active`；重置密码时自动置 `must_change_password=true`（除非 body 显式 `must_change_password=false`）。
- FR-3.3 `DELETE /users/{id}/dingtalk-binding` 解绑，仅 super_admin/admin；解绑后该用户下次密码登录仍可用，但失去"按登录用户维度"的钉钉权限映射。
- FR-3.4 最后一名 super_admin 不可解绑钉钉（避免同步链路全断）。

**FR-4 前端**
- FR-4.1 `web/src/views/login/index.vue` 改成 Tab：`密码登录 | 钉钉扫码`；扫码 Tab 嵌入 DingTalk QR SDK（`https://g.alicdn.com/dingding/h5-dingtalk-login/0.21.4/ddlogin.js`），拿到 `loginTmpCode` 后换 `authCode` 调 `/auth/dingtalk-login`。
- FR-4.2 新增 `web/src/views/onboarding/SetPassword.vue`：两个密码输入 + 强度校验（≥8 位含字母数字），提交调 `/auth/set-password`；路由守卫：`userStore.userInfo.must_change_password===true` 时**除了 logout 和该页**全部重定向过来。
- FR-4.3 `web/src/views/admin/Users.vue` 表格新增列：钉钉姓名、dt_userid、绑定时间；行操作菜单增加"重置密码（弹窗带强制改密勾选）"、"解绑钉钉"。
- FR-4.4 新增 `web/src/views/settings/Account.vue`（普通用户可见）：显示 username / role / 钉钉绑定状态；改密码表单。
- FR-4.5 `web/src/views/governance/model.vue` 的"钉钉"分组：`dingtalk_operator_union_id` 字段标签改成"**服务账号 union_id（兜底用）**"，并加提示文案"当 KB owner 未绑定钉钉时使用；建议只在冷启动/系统 KB 上生效"。

### 2.3 非功能需求（NFR）

| ID | 类别 | 指标 |
|---|---|---|
| NFR-1 | 安全 | 密码 bcrypt cost≥12（沿用 `passlib.context.CryptContext(schemes=["bcrypt"])` 默认）；重置密码/解绑钉钉操作**必须**写 `audit_logs`（若无表则新建）：actor_id、action、target_user_id、ip、ua、ts。 |
| NFR-2 | 安全 | `auth_code` 单次消费；后端换 `access_token` 后立即丢弃；`dt_unionid` 不进 URL query。 |
| NFR-3 | 性能 | `/auth/dingtalk-login` P95 < 800ms（含钉钉侧 `getuserinfo` 调用），本地 DB 查询 ≤ 3 次。 |
| NFR-4 | 性能 | `resolve_operator()` 结果按 `kb_id` 做 60s 内存 LRU 缓存（`cachetools.TTLCache`），避免每文档同步都查 DB；owner 变更或 binding 解绑时主动失效。 |
| NFR-5 | 可用性 | 钉钉侧 API 500/超时不阻塞密码登录通道；`/auth/dingtalk-config` 返回 `qr_login_enabled=false` 时前端 Tab 隐藏。 |
| NFR-6 | 兼容 | 已有 61 个未提交变动 + 0039 迁移之前创建的 KB，`owner_id` 已存在（`models.py:36` 是 NOT NULL），不需要回填。 |
| NFR-7 | 兼容 | 已有 `dingtalk_operator_union_id` Setting 保留；不删除现有 `resolve_user` 逻辑，只在其上叠加 `must_change_password=true` 标记。 |
| NFR-8 | 观测 | 结构化日志新增字段：`login_channel ∈ {password, dingtalk_h5, dingtalk_qr}`、`user_created`（bool）、`operator_source`。 |

### 2.4 使用场景

**场景 A：新员工首次登录**
1. 张三 PC 浏览器打开 `http://kge.internal/login` → 点"钉钉扫码" Tab → 手机钉钉扫码 → 前端拿到 `authCode` → POST `/auth/dingtalk-login`。
2. 后端 `resolve_user` 发现 `(corp_id, dt_userid)` 无绑定 → 建 `User(username=dd_{userid}, role=viewer, must_change_password=true, password_hash=random)` + `DingtalkBinding(dt_name=张三, dt_unionid=xxx)` → 签发 JWT（payload 含 `dt_unionid`, `must_change_password=true`）→ 返回 `{token, must_set_password: true, user}`。
3. 前端存 token → 检测 `must_set_password` → 跳 `/onboarding/set-password`。
4. 张三输入两次密码 → POST `/auth/set-password` → 后端更新 `password_hash`、`password_updated_at=now()`、`must_change_password=false` → 前端跳 `/chat`。
5. 张三后续用密码或扫码都可登录；调 `/agent_internal/dingtalk/search` 时用他自己的 union_id，只看到他有权限的钉钉库。

**场景 B：管理员重置密码**
1. 李四忘记密码，找管理员王五。
2. 王五进 `/admin/users` → 找到李四 → 行操作"重置密码" → 弹窗输入临时密码 `Kge@2026` + 勾选"要求下次登录改密"（默认勾上）→ 提交。
3. 后端 `PATCH /users/{id}` 写 `password_hash=bcrypt(Kge@2026)`、`must_change_password=true`、`password_updated_at=null`，同时写 audit_log。
4. 王五把临时密码通过钉钉私聊发给李四。
5. 李四用 `dd_{userid}` + `Kge@2026` 登录 → 响应带 `must_change_password=true` → 前端跳设密页 → 李四改成自己的密码。

**场景 C：KB 同步按 owner 权限**
1. 张三（viewer）在 `/knowledge-bases/new` 创建 KB "产品手册"，owner_id=张三。
2. XXL-Job 定时触发该 KB 同步 → `resolve_operator(kb_id)` → 张三的 `dt_unionid=xxx_zhangsan`。
3. `DingtalkClient.list_nodes(folder_id, operator_union_id=xxx_zhangsan)` → 钉钉侧按张三权限返回可见节点。
4. 若张三未绑定钉钉（比如他只用密码登录且从未扫码），回退到全局 `dingtalk_operator_union_id`（服务账号），同步继续但在 `sync_tasks.meta.operator_source="global_fallback"`，前端"同步历史"显示黄色警告标。

**场景 D：解绑钉钉（换岗）**
1. 张三从产品部换到运营部，钉钉 userid 变了。
2. 管理员在 `/admin/users` 找到张三 → "解绑钉钉" → 二次确认。
3. 后端 `DELETE /users/{id}/dingtalk-binding` → 清 `DingtalkBinding` 行 → JWT payload 里的 `dt_unionid` 下次续签时消失。
4. 张三下次登录只能用密码；他创建的 KB 同步会走全局兜底，直到他重新扫码绑定新钉钉身份（此时 `(corp_id, new_userid)` 无绑定，`resolve_user` 会**建一个新 User**——需要额外做"同 username 冲突"处理，见 §4.3）。

### 2.5 验收标准（Given / When / Then）

**AC-01（对应 US-01, FR-1.1）**
- Given 一个从未登录过的钉钉用户
- When 他在 PC 扫码并通过 `/auth/dingtalk-login` 认证
- Then DB 出现一行 `users` 和一行 `dingtalk_bindings`；`users.username` 形如 `dd_{dt_userid}`；`users.role='viewer'`；`users.must_change_password=true`；返回 JWT 的 payload 含 `dt_unionid`；HTTP 响应 `must_set_password=true`。

**AC-02（对应 US-02, FR-1.3）**
- Given 一个 `must_change_password=true` 的用户已登录
- When 他访问 `/dashboard`、`/chat`、`/admin/*` 任一非白名单路由
- Then 前端路由守卫重定向到 `/onboarding/set-password`；`/onboarding/set-password` 与 `/login` 可正常访问。

**AC-03（对应 US-03, FR-2.1/2.3）**
- Given 张三绑定钉钉且 union_id=U1，李四 union_id=U2，钉钉侧库 K1 只对 U1 开放
- When 张三和李四分别调 `POST /agent_internal/dingtalk/search` 查 K1 里的关键词
- Then 张三能召回，李四空结果；日志显示两次调用的 `operator_union_id` 分别为 U1/U2。

**AC-04（对应 US-04/US-09, FR-2.2）**
- Given KB_A.owner=张三（有绑定 union_id=U1），KB_B.owner=王五（无钉钉绑定）
- When 同步任务分别处理 KB_A 和 KB_B
- Then KB_A 用 U1 调钉钉 API，`sync_tasks.meta.operator_source='owner_binding'`；KB_B 用全局 Setting，`operator_source='global_fallback'`；两者都成功。

**AC-05（对应 US-06, FR-3.2）**
- Given 管理员王五
- When 他 `PATCH /users/{李四.id}` body `{"password":"Kge@2026","must_change_password":true}`
- Then 李四的 `password_hash` 更新、`must_change_password=true`、`password_updated_at=null`；audit_logs 新增一行 `action='admin_reset_password'`；李四用旧密码登录 401，用新密码登录成功但被强制跳设密页。

**AC-06（对应 US-07, FR-3.3/3.4）**
- Given 张三是 viewer 且已绑定钉钉，赵六是**唯一**的 super_admin 且已绑定
- When 管理员对张三调 `DELETE /users/{张三.id}/dingtalk-binding`
- Then 成功，`dingtalk_bindings` 该行删除；张三仍能用密码登录。
- When 管理员对赵六调同接口
- Then 409 Conflict，返回 `{"detail":"最后一名 super_admin 不可解绑钉钉"}`。

**AC-07（对应 NFR-1）**
- Given 任意"重置密码/解绑钉钉/角色变更"操作
- When 操作成功
- Then `audit_logs` 表存在一行含 `actor_id`（管理员）、`action`、`target_user_id`、`ip`、`user_agent`、`created_at`；操作失败则不写。

**AC-08（对应 NFR-4）**
- Given 张三绑定钉钉且创建 KB_A
- When 60 秒内触发 KB_A 的 100 个文档同步
- Then `resolve_operator(KB_A.id)` 只查 DB 一次（可用 pytest + sqlalchemy event counter 断言）。

**AC-09（对应 FR-1.5, US-08）**
- Given 已登录且 `must_change_password=false` 的用户
- When 他调 `POST /auth/change-password` body `{"old_password":"<correct>","new_password":"<new>","new_password_confirm":"<new>"}`
- Then 成功；用旧密码登录 401，新密码 200；`password_updated_at` 更新。
- When `old_password` 错误
- Then 403，audit_logs 记 `action='self_change_password_failed'`。

**AC-10（对应 FR-4.1, NFR-5）**
- Given Setting `dingtalk_qr_login_enabled=false`
- When 用户访问 `/login`
- Then `GET /auth/dingtalk-config` 返回 `qr_login_enabled=false`；登录页只显示密码 Tab，钉钉 Tab 隐藏。

### 2.6 迭代规划

| 迭代 | 交付内容 | 预估工时 | 依赖 |
|---|---|---|---|
| **M1（P0，2 天）** | 后端：User 表加 `must_change_password`/`password_updated_at`；迁移 0040；`resolve_user` 打标记；`/auth/set-password`、`/auth/change-password`；JWT payload 扩展；`/auth/login` 返回 `must_set_password`。 | 12h | 无 |
| **M2（P0，2 天）** | 后端：`DingtalkClient` 全量方法加 `operator_union_id`；`resolve_operator()` + TTL 缓存；`sync_settings` / `agent_internal` 调用点改造；`sync_tasks.meta.operator_source`。 | 14h | M1 |
| **M3（P0，1.5 天）** | 前端：登录页 Tab 化 + DingTalk QR SDK；`/onboarding/set-password`；路由守卫；`stores/user.ts` 存 `must_change_password`；`api/auth.ts` 加 3 个方法。 | 10h | M1 |
| **M4（P1，1.5 天）** | 后端：`GET /users?include_binding`；`PATCH /users/{id}` 扩展；`DELETE /users/{id}/dingtalk-binding`；`audit_logs` 表（迁移 0041）+ 中间件写入。 | 10h | M1 |
| **M5（P1，1.5 天）** | 前端：`admin/Users.vue` 加列 + 弹窗；`settings/Account.vue` 新页；`governance/model.vue` 文案调整；`sync-history` 页显示 `operator_source`。 | 10h | M4 |
| **M6（P2，0.5 天）** | 联调：`scripts/smoke_test.sh` 增加"新用户扫码→设密→创建 KB→同步→检索"链路；`.env.example` 补 `DINGTALK_QR_LOGIN_ENABLED`。 | 4h | M1-M5 |

**总计：约 60 小时（7.5 人日）**，单人 1.5 周。

---

## 三、技术方案

### 3.1 数据模型变更

**`kb_common/models.py::User`（追加字段）**

```python
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # 新增
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    password_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
```

**新增 `AuditLog` 表**

```python
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)  # admin_reset_password / admin_unbind_dingtalk / self_change_password / login / logout ...
    target_type: Mapped[str] = mapped_column(String(32))  # user / kb / setting
    target_id: Mapped[str | None] = mapped_column(String(64), index=True)
    detail: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
```

**`DingtalkBinding` 无变更**（`models.py:651-666` 已有 `user_id/corp_id/dt_userid/dt_unionid/dt_name/bound_at`）。

### 3.2 Alembic 迁移

新增 `alembic/versions/0040_user_password_flags.py`：

```python
revision = "0040_user_password_flags"
down_revision = "0039_merge_library_heads"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(),
                                     server_default=sa.text("false"), nullable=False))
    op.add_column("users", sa.Column("password_updated_at", sa.DateTime(), nullable=True))
    # 历史用户回填：password_updated_at = created_at，must_change_password=false（不影响老用户）
    op.execute("UPDATE users SET password_updated_at = created_at WHERE password_updated_at IS NULL")

def downgrade() -> None:
    op.drop_column("users", "password_updated_at")
    op.drop_column("users", "must_change_password")
```

新增 `alembic/versions/0041_audit_logs.py`：

```python
revision = "0041_audit_logs"
down_revision = "0040_user_password_flags"

def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), index=True),
        sa.Column("action", sa.String(64), index=True, nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), index=True),
        sa.Column("detail", sa.JSON()),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(300)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), index=True),
    )

def downgrade() -> None:
    op.drop_table("audit_logs")
```

> 执行前跑 `cd services/kb-common && uv run alembic heads` 确认无并行 head；若 `0039_merge_library_heads` 已被后续迁移引用需相应调整 down_revision。

### 3.3 后端接口清单

| 方法 | 路径 | 权限 | 请求体 | 响应体 |
|---|---|---|---|---|
| POST | `/api/v1/auth/login` | 公开 | `{username, password}` | `{access_token, token_type, user, must_set_password}` |
| POST | `/api/v1/auth/dingtalk-login` | 公开 | `{auth_code, corp_id?}` | 同上 |
| GET | `/api/v1/auth/dingtalk-config` | 公开 | — | `{corp_id, app_key, auto_login_enabled, qr_login_enabled, redirect_uri}` |
| **POST** | **`/api/v1/auth/set-password`** | JWT + `must_change_password=true` | `{new_password, new_password_confirm}` | `{ok:true, user}` |
| **POST** | **`/api/v1/auth/change-password`** | JWT | `{old_password, new_password, new_password_confirm}` | `{ok:true}` |
| GET | `/api/v1/users/me` | JWT | — | 现有结构 + `must_change_password` + `dingtalk_binding` |
| GET | `/api/v1/users?include_binding=true` | admin | — | 现有 + 每行 `dingtalk_binding` |
| PATCH | `/api/v1/users/{id}` | admin | `{role?, is_active?, password?, must_change_password?}` | `{ok:true}` |
| **DELETE** | **`/api/v1/users/{id}/dingtalk-binding`** | admin | — | `{ok:true}` |

**Pydantic 契约样例**（放 `services/kb-api/app/schemas/auth.py`）：

```python
from pydantic import BaseModel, Field, field_validator

class SetPasswordBody(BaseModel):
    new_password: str = Field(min_length=8, max_length=64)
    new_password_confirm: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("密码须同时包含字母和数字")
        return v

    @field_validator("new_password_confirm")
    def confirm_matches(self, v, info):
        # pydantic v2 field_validator 需 model_validator 才能跨字段；改用 model_validator(mode='after')
        return v

class ChangePasswordBody(SetPasswordBody):
    old_password: str = Field(min_length=1)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserPublic"
    must_set_password: bool = False
```

### 3.4 JWT payload 扩展

**`kb_common/security.py`**

```python
def create_jwt(user_id: str, role: str, *,
               dt_unionid: str | None = None,
               must_change_password: bool = False) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": user_id,
        "role": role,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
        "iat": now,
    }
    if dt_unionid:
        payload["dtu"] = dt_unionid          # 缩短 key，避免 token 过长
    if must_change_password:
        payload["mcp"] = True
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
```

**`services/kb-api/app/deps.py::get_current_user`**：在返回的 `Principal` 上挂 `dt_unionid`（从 payload `dtu` 读），供 `agent_internal` / `sync_settings` 复用而不用再查 DB。

**注意**：`must_change_password` 状态变化（用户设密成功、管理员重置）后，**旧 token 仍在有效期内**——用两个策略叠加：
1. `/auth/set-password` 成功后前端立即用新签发的 token 替换 localStorage。
2. 路由守卫额外用 `userStore.userInfo.must_change_password` 判断（`/users/me` 每次刷新会返回最新值）。

### 3.5 钉钉身份链路改造

**`services/kb-api/app/services/dingtalk_identity.py`**

```python
async def resolve_user(s, corp_id, dt_userid, dt_unionid="", dt_name=""):
    # ... 现有查询逻辑不变
    user = User(
        username=f"dd_{dt_userid}"[:100],
        password_hash=hash_password(secrets.token_urlsafe(24)),
        role="viewer",
        is_active=True,
        must_change_password=True,        # 新增
        password_updated_at=None,         # 新增
    )
    # ...

def issue_token(user: User, binding: DingtalkBinding | None = None) -> dict:
    return {
        "access_token": create_jwt(
            str(user.id), user.role,
            dt_unionid=binding.dt_unionid if binding else None,
            must_change_password=user.must_change_password,
        ),
        "token_type": "bearer",
        "user": {
            "id": str(user.id), "username": user.username, "email": user.email or "",
            "role": user.role, "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "must_change_password": user.must_change_password,
            "dingtalk_binding": {
                "dt_name": binding.dt_name, "dt_userid": binding.dt_userid,
                "corp_id": binding.corp_id,
            } if binding else None,
        },
        "must_set_password": user.must_change_password,
    }
```

**新增 `services/kb-api/app/services/dingtalk_operator.py`**

```python
from cachetools import TTLCache
from sqlalchemy import select
from kb_common.models import DingtalkBinding, KnowledgeBase, Setting

_cache: TTLCache[str, tuple[str, str]] = TTLCache(maxsize=512, ttl=60)  # kb_id -> (union_id, source)

class OperatorUnavailable(RuntimeError):
    pass

async def resolve_operator(s: AsyncSession, kb_id: str) -> tuple[str, str]:
    """返回 (union_id, source)，source ∈ {'owner_binding','global_fallback'}"""
    if kb_id in _cache:
        return _cache[kb_id]

    kb = await s.get(KnowledgeBase, kb_id)
    if kb and kb.owner_id:
        row = (await s.execute(
            select(DingtalkBinding).where(DingtalkBinding.user_id == kb.owner_id)
        )).scalar_one_or_none()
        if row and row.dt_unionid:
            result = (row.dt_unionid, "owner_binding")
            _cache[kb_id] = result
            return result

    setting = await s.get(Setting, "dingtalk_operator_union_id")
    if setting and setting.value:
        result = (setting.value, "global_fallback")
        _cache[kb_id] = result
        return result

    raise OperatorUnavailable(f"KB {kb_id} 无法确定 operator：owner 未绑定钉钉且未配置全局兜底")

def invalidate(kb_id: str | None = None):
    if kb_id is None:
        _cache.clear()
    else:
        _cache.pop(kb_id, None)
```

**`kb_common/clients/dingtalk_client.py`**：所有涉及用户可见资源的方法签名改造，示例：

```python
async def list_nodes(self, workspace_id: str, folder_id: str,
                     operator_union_id: str | None = None) -> list[Node]:
    union_id = operator_union_id or self._default_operator_union_id()
    if not union_id:
        raise OperatorUnavailable("缺少 operator_union_id")
    # ... 现有 HTTP 调用，把 union_id 放进 header 或 query
```

**调用点改造清单**（grep 已定位）：
- `services/sync/sync_settings.py:18,51` — 用 `resolve_operator(kb_id)` 替代直接读 Setting
- `services/sync/task_retry.py`（同步重试单节点）— 同上
- `routes/agent_internal.py:337-366` — 从 `principal.dt_unionid` 取（JWT 里已有），无绑定时 fallback 到全局
- `services/dingtalk_bot.py:151-166` — 保持用 `resolve_user` 归因，operator 用消息发送人的 union_id

### 3.6 前端结构

**`web/src/api/auth.ts` 新增**

```typescript
export const setPassword = (data: { new_password: string; new_password_confirm: string }) =>
  request.post('/auth/set-password', data)

export const changePassword = (data: { old_password: string; new_password: string; new_password_confirm: string }) =>
  request.post('/auth/change-password', data)

export interface DingtalkConfig {
  corp_id: string
  app_key: string
  auto_login_enabled: boolean
  qr_login_enabled: boolean
  redirect_uri: string
}
export const getDingtalkConfig = () => request.get<DingtalkConfig>('/auth/dingtalk-config')
```

**`web/src/views/login/index.vue`（Tab 化伪代码）**

```vue
<el-tabs v-model="activeTab">
  <el-tab-pane label="密码登录" name="password">
    <!-- 现有表单 -->
  </el-tab-pane>
  <el-tab-pane v-if="dtConfig?.qr_login_enabled" label="钉钉扫码" name="dingtalk">
    <div id="dingtalk-qr" />
  </el-tab-pane>
</el-tabs>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getDingtalkConfig, dingtalkLogin } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const activeTab = ref('password')
const dtConfig = ref<DingtalkConfig | null>(null)
const router = useRouter()
const userStore = useUserStore()

onMounted(async () => {
  dtConfig.value = await getDingtalkConfig()
  if (activeTab.value === 'dingtalk' || dtConfig.value?.qr_login_enabled) {
    await loadDingtalkQR()
  }
})

async function loadDingtalkQR() {
  // 动态加载 https://g.alicdn.com/dingding/h5-dingtalk-login/0.21.4/ddlogin.js
  // new window.DDLogin({ id: 'dingtalk-qr', goto: encodeURIComponent(qrUrl), style: 'border:none;background-color:#fff;', width: '365', height: '400' })
  // window.addEventListener('message', async (e) => {
  //   const loginTmpCode = new URL(e.data).searchParams.get('loginTmpCode')
  //   const authCode = await exchangeAuthCode(loginTmpCode)  // 走后端 /auth/dingtalk-login/qr-exchange
  //   const res = await dingtalkLogin({ auth_code: authCode })
  //   userStore.setToken(res.access_token)
  //   if (res.must_set_password) router.push('/onboarding/set-password')
  //   else router.push((route.query.redirect as string) || '/chat')
  // })
}
</script>
```

**钉钉扫码登录两种模式**（择一，M3 里决定）：
1. **前端拿 `loginTmpCode` → 后端换 authCode**：需新增 `POST /auth/dingtalk-login/qr-exchange`，body `{login_tmp_code}`，后端用 AppKey/AppSecret 调钉钉 `sns/gettoken` + `sns/getuserinfo_bycode`。
2. **前端 iframe 直接跳授权页 → redirect_uri 回调带 authCode**：把 `redirect_uri` 设成 `/login/callback`，前端新增 `views/login/Callback.vue` 读 `?code=` 后调 `/auth/dingtalk-login`。**推荐模式 2**，无需后端多加接口，符合钉钉官方文档主流做法。

**新增路由**（`web/src/router/index.ts`）：

```typescript
{
  path: '/onboarding/set-password',
  name: 'OnboardingSetPassword',
  component: () => import('@/views/onboarding/SetPassword.vue'),
  meta: { requiresAuth: true, allowWhenMustChange: true, standalone: true }
},
{
  path: '/login/callback',
  name: 'LoginCallback',
  component: () => import('@/views/login/Callback.vue'),
  meta: { public: true }
},
{
  path: '/settings/account',
  name: 'AccountSettings',
  component: () => import('@/views/settings/Account.vue'),
  meta: { requiresAuth: true }
},
```

**路由守卫补丁**：

```typescript
router.beforeEach((to, from, next) => {
  const userStore = useUserStore()
  if (to.meta.public) return next()
  if (!userStore.token) return next({ path: '/login', query: { redirect: to.fullPath } })

  if (userStore.userInfo?.must_change_password && !to.meta.allowWhenMustChange) {
    return next({ path: '/onboarding/set-password', query: { redirect: to.fullPath } })
  }
  // ... 原有 role 检查
  next()
})
```

### 3.7 前端管理页布局

**`web/src/views/admin/Users.vue` 表格列（按 AGENTS.md「表格与弹窗布局要求」）**

| 列 | 宽度 | 备注 |
|---|---|---|
| 用户名 | `min-width="180"` `show-overflow-tooltip` | 主内容 |
| 钉钉姓名 | `min-width="140"` `show-overflow-tooltip` | 未绑定显示 `—` |
| dt_userid | `width="180"` `show-overflow-tooltip` | 未绑定显示 `—` |
| 角色 | `width="110"` | Tag |
| 状态 | `width="90"` | 启用/停用 |
| 强制改密 | `width="100"` | 是/否 Tag，warning 色 |
| 绑定时间 | `width="170"` | 未绑定显示 `—` |
| 创建时间 | `width="170"` | |
| 操作 | `width="220"` `fixed="right"` | 外显"编辑 / 重置密码"，其余入"更多"下拉（解绑钉钉、停用、删除） |

**重置密码弹窗**（`el-dialog`）：

```vue
<el-dialog v-model="resetDialog" title="重置密码" width="480px">
  <el-form :model="resetForm" label-width="120px">
    <el-form-item label="新密码" required>
      <el-input v-model="resetForm.password" type="password" show-password
                placeholder="≥8 位，含字母和数字" />
      <el-button link type="primary" @click="generateRandom">随机生成</el-button>
    </el-form-item>
    <el-form-item label="强制下次改密">
      <el-switch v-model="resetForm.must_change_password" />
      <span class="form-hint">开启后用户下次登录必须设置新密码</span>
    </el-form-item>
  </el-form>
  <template #footer>
    <el-button @click="resetDialog=false">取消</el-button>
    <el-button type="primary" @click="submitReset">确定</el-button>
  </template>
</el-dialog>
```

**`web/src/views/settings/Account.vue`（普通用户）**

- 顶部：头像、用户名、角色、邮箱、创建时间
- "钉钉绑定"卡片：已绑定→显示 dt_name/dt_userid/bound_at；未绑定→"绑定钉钉"按钮（触发扫码流程，成功后调 `POST /users/me/dingtalk-binding` 附加到当前账号，见 §3.8）
- "修改密码"卡片：旧密码 / 新密码 / 确认新密码 → `POST /auth/change-password`

### 3.8 已有账号绑定钉钉（补充流程）

**场景**：老用户 `admin` 已有密码登录，想把自己和钉钉身份绑定，之后同步 KB 用自己的 union_id。

**接口**：`POST /api/v1/users/me/dingtalk-binding` body `{auth_code}`
- 后端换 `(dt_userid, dt_unionid, dt_name)`
- 若 `(corp_id, dt_userid)` 已被别的 User 绑定 → 409 返回冲突用户 username
- 若当前 User 已有绑定 → 409 提示先解绑
- 成功后创建 `DingtalkBinding(user_id=current_user.id, ...)`，重签 JWT（payload 带 `dtu`），前端替换 localStorage

**注意**：这里**不合并用户**，避免误伤；如果确要合并走管理员手动流程（v2 再做）。

### 3.9 迁移与回滚

**上线步骤**
1. `cd services/kb-common && uv run alembic heads` 确认当前 head=`0039_merge_library_heads`
2. 部署代码 → `uv run alembic upgrade head`
3. `INSERT INTO settings (key, value) VALUES ('dingtalk_qr_login_enabled','true') ON CONFLICT DO NOTHING`
4. 前端 build → nginx reload
5. 冒烟：`./scripts/smoke_test.sh` + 手动跑一遍场景 A/B/C

**回滚**
1. `alembic downgrade 0039_merge_library_heads`（会丢 `must_change_password` 和 `audit_logs`）
2. 回退代码 tag

**风险点**
- **username 冲突**：钉钉换 userid 场景（§2.4 场景 D），`resolve_user` 建新 User 时 `dd_{new_userid}` 可能撞已有 username → 现有代码 `User.username` 有 unique 约束会抛错。**处理**：`resolve_user` 捕获 `IntegrityError`，追加短 uuid 后缀 `dd_{userid}_{6位}` 重试一次。
- **JWT 未过期但状态已变**：见 §3.4 说明，双策略兜底。
- **全局 Setting 为空**：冷启动阶段 `dingtalk_operator_union_id` 未配置且 KB.owner 无绑定 → 同步任务 FAILED 且写清晰错误"请在系统配置里设置服务账号 union_id 或让 KB owner 绑定钉钉"。

---

## 四、交付清单

### 4.1 后端新增/修改文件

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `services/kb-common/kb_common/models.py` | 修改 | User 加 2 字段；新增 AuditLog 类 |
| `services/kb-common/kb_common/security.py` | 修改 | `create_jwt` 加 kwargs |
| `alembic/versions/0040_user_password_flags.py` | 新增 | 见 §3.2 |
| `alembic/versions/0041_audit_logs.py` | 新增 | 见 §3.2 |
| `services/kb-api/app/schemas/auth.py` | 新增 | Pydantic 契约 |
| `services/kb-api/app/routes/auth.py` | 修改 | 加 set-password / change-password / users/me/dingtalk-binding |
| `services/kb-api/app/routes/users.py` | 修改 | PATCH 扩展；DELETE dingtalk-binding；GET 加 include_binding |
| `services/kb-api/app/services/dingtalk_identity.py` | 修改 | resolve_user 打标记；issue_token 扩展 |
| `services/kb-api/app/services/dingtalk_operator.py` | 新增 | resolve_operator + TTL 缓存 |
| `services/kb-api/app/services/audit.py` | 新增 | write_audit(actor, action, target, detail, request) 中间件 |
| `services/kb-common/kb_common/clients/dingtalk_client.py` | 修改 | 所有相关方法加 operator_union_id 参数 |
| `services/kb-api/app/services/sync/sync_settings.py` | 修改 | 用 resolve_operator |
| `services/kb-api/app/services/sync/task_retry.py` | 修改 | 用 resolve_operator |
| `services/kb-api/app/routes/agent_internal.py` | 修改 | 从 principal.dt_unionid 取 operator |
| `services/kb-api/app/deps.py` | 修改 | Principal 挂 dt_unionid |
| `services/kb-api/app/routes/settings_route.py` | 修改 | 白名单加 `dingtalk_qr_login_enabled` |
| `.env.example` | 修改 | 补 `DINGTALK_QR_LOGIN_ENABLED=true` |

### 4.2 前端新增/修改文件

| 文件 | 变更类型 |
|---|---|
| `web/src/api/auth.ts` | 修改 |
| `web/src/api/users.ts` | 修改（加解绑、重置带 flag） |
| `web/src/stores/user.ts` | 修改（userInfo 加 must_change_password） |
| `web/src/router/index.ts` | 修改（加 3 条路由 + 守卫补丁） |
| `web/src/views/login/index.vue` | 修改（Tab 化 + QR SDK） |
| `web/src/views/login/Callback.vue` | 新增 |
| `web/src/views/onboarding/SetPassword.vue` | 新增 |
| `web/src/views/settings/Account.vue` | 新增 |
| `web/src/views/admin/Users.vue` | 修改（新列 + 重置弹窗 + 解绑） |
| `web/src/views/governance/model.vue` | 修改（文案 + 新增 qr_login_enabled 开关） |
| `web/src/views/sync/History.vue` | 修改（显示 operator_source） |

### 4.3 冒烟脚本增补

`scripts/smoke_test.sh` 末尾追加：

```bash
# 场景 A：新用户扫码→设密→创建 KB
echo "=== SMOKE: dingtalk onboarding ==="
AUTH_CODE="${SMOKE_DINGTALK_AUTH_CODE:-}"
if [ -n "$AUTH_CODE" ]; then
  RESP=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/dingtalk-login \
         -H 'Content-Type: application/json' \
         -d "{\"auth_code\":\"$AUTH_CODE\"}")
  TOKEN=$(echo "$RESP" | jq -r .access_token)
  MUST=$(echo "$RESP" | jq -r .must_set_password)
  [ "$MUST" = "true" ] || { echo "FAIL: 新用户应需设密"; exit 1; }
  curl -s -X POST http://127.0.0.1:8000/api/v1/auth/set-password \
       -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
       -d '{"new_password":"Kge2026abc","new_password_confirm":"Kge2026abc"}' | jq .
  echo "OK: onboarding"
else
  echo "SKIP: 未提供 SMOKE_DINGTALK_AUTH_CODE"
fi
```

### 4.4 手册与通知

- `docs/features/` 新增《钉钉认证与账户管理使用手册.md》：面向业务用户（扫码/改密）+ 面向管理员（重置/解绑/授权）
- 上线通知模板（钉钉群公告）：
  > 【知识治理平台】v0.X 上线钉钉扫码登录。首次登录请扫码 → 设置本地密码。原有 admin/密码登录**不受影响**。管理员重置密码后默认需强制改密。使用问题反馈 @黄景新。

### 4.5 监控

新增指标（Prometheus / 日志聚合）：
- `kge_login_total{channel}` counter — channel ∈ password/dingtalk_h5/dingtalk_qr
- `kge_login_failed_total{reason}` counter — reason ∈ bad_password/dingtalk_timeout/user_inactive
- `kge_onboarding_set_password_total` counter
- `kge_sync_operator_source_total{source}` counter — 观察 global_fallback 占比，>30% 提示管理员推动 owner 绑定
- `kge_audit_log_write_failed_total` counter — 审计写入失败必须告警

---

## 五、Open Questions（等落地时定）

1. 钉钉扫码模式：§3.6 里两种，推荐模式 2（redirect_uri 回调），M3 开发时最终确认 `redirect_uri` 域名（内网 `http://kge.internal/login/callback` 还是走公网反代）。
2. `audit_logs` 保留时长：默认 90 天，超期用 pg_cron 或 XXL-Job 定期清理，M4 时决定是否本次实现。
3. 密码强度：当前规则 ≥8 位含字母数字，是否需要加"不含用户名/dt_name"、"不与最近 3 次重复"？建议 v2 再加，避免首版阻力。
4. 是否允许用户**自主解绑**自己的钉钉？当前设计只允许管理员解绑，用户端 Account 页只显示状态。

---

## 六、实施记录（2026-09-21 落地，与方案的偏差）

1. **迁移编号**：仓库已存在未跟踪的 `0040_governance_standards`（且 dev DB 已 apply），本功能迁移顺延为
   `0041_user_password_flags` / `0042_audit_logs` / `0043_sync_source_owner`（后者把
   `sync_sources.owner_user_id` 与 `sync_runs.operator_source` 合并进一个迁移）。三个迁移已在 dev DB apply 通过。
2. **同步 owner 挂在 SyncSource 而非 KnowledgeBase**：同步链路的实体是 `sync_sources`（钉钉目录→引擎数据集），
   与本地 `knowledge_bases` 表无外键关系；故 FR-2.2 的 `KB.owner_id` 落地为 `SyncSource.owner_user_id`，
   创建同步源时默认记当前登录用户，管理员可在编辑时改/置空。
3. **扫码登录走统一授权页全页跳转**（方案 §3.6 模式 2）：`login.dingtalk.com/oauth2/auth`（client_id=AppKey,
   scope=openid）→ 回调 `/login/callback?code=` → 后端新增 `dingtalk_client.get_user_info_by_qr_code()`
   （userAccessToken → contact/users/me → topapi/user/getbyunionid 反查企业 userid）。不引钉钉 JS SDK。
   `POST /auth/dingtalk-login` 增加 `channel: "h5"|"qr"` 区分两种换码接口。
4. **检索按用户隔离为工作区级**：`/internal/dingtalk/search` 与「钉钉知识」列表读的是全局 operator 遍历出的
   持久化快照，无法按用户重放节点级权限；落地为「已绑定用户按其 unionId 的可见 workspace 集合过滤快照」
   （`knowledge_center._visible_workspace_ids`，60s/operator 缓存）。节点级差异不做隔离，列为已知限制。
   拉取权限范围失败时按空集合隔离（宁可少看不可越权），并在响应 error 字段提示。
5. **交互链路的实时接口真隔离**：`/knowledge-center/dingtalk/workspaces|nodes` 直接用登录用户 unionId 调
   钉钉（钉钉侧权限过滤）；`dingtalk_client` 的 workspace 列表缓存改为按 operator 分键。
6. **`.env.example` 无新增键**：钉钉全部配置（含 `dingtalk_qr_login_enabled`）走 DB settings 表
   （`settings_route.KEYS` 已加该键与「服务账号 union_id（兜底）」新标签），与 AppKey/corpId 口径一致。
7. **smoke_test 修正**：第 9 节密钥掩码断言原为旧口径（masked 值应为空串），与现行 `sk-****f57b` 掩码设计
   冲突（历史遗留失败），已改为接受掩码形态；新增第 10 节 Onboarding 强制改密全链路、第 11 节
   dingtalk-config 字段断言。全量 `SMOKE OK`。
8. **环境债修复（非本功能回归）**：celery worker 连续运行 15 天，内存中仍是「停用本地 BGE」之前的旧代码
   （embed 时 import transformers，venv 已无该包）导致 ingestion 必 FAILED；重启 worker 后恢复。
9. **审计写入为旁路**：`services/audit.py::write_audit` 失败只 rollback+error 日志，不阻断主业务。
10. **前端交付**：登录页 Tab 化、`/login/callback`、`/onboarding/set-password`、`/settings/account`、
    用户管理页钉钉列+重置密码弹窗+解绑钉钉、同步监控页「同步身份」列、model.vue 兜底标签与扫码开关；
    `pnpm type-check` 0 错误、`pnpm build` 通过。

### 验证结果（2026-09-21）

- `alembic upgrade head` → `0043_sync_source_owner (head)`，一次通过
- 后端全模块 import 自检 OK
- `EXTERNAL_SERVICES=1 ./scripts/smoke_test.sh` → SMOKE OK（含 [10] Onboarding、[11] dingtalk-config）
- `pnpm type-check` 0 错误；`pnpm build` 5.02s 通过

### 上线前置（钉钉开放平台控制台，代码侧无法代办）

1. dev 库 `dingtalk_corp_id` 已于 2026-09-21 通过设置接口写入 `dingb832549ed9dd356e`
   （由 `dingtalk_client.get_corp_id()` 经服务账号实测取得），`dingtalk_qr_login_enabled=true`；
   登录页「钉钉扫码」Tab 随之出现（playwright 实测渲染正常）。
2. 点击扫码跳转 `login.dingtalk.com/oauth2/auth` 报 **Code 900103 应用不存在**：
   该 AppKey 的服务端 API 凭证有效（wiki/accessToken 正常），但统一身份认证要求应用在
   开发者后台开通「应用功能 → 登录与分享 → 接入登录」并登记回调地址。需控制台操作：
   - 回调地址登记：`http://localhost:3000/login/callback`（dev）、生产域名同路径；
   - 开通后扫码链路即可走通（后端换码接口已就绪并有冒烟外的手工验证路径）。
3. 钉钉工作台内打开平台走 H5 免登（`/chat` 页 dd.getAuthCode），corp_id 写入后已具备启用条件，
   不依赖上述控制台登录能力。

## 七、附录

### A. 现状代码索引

- `services/kb-api/app/routes/auth.py:11-63` — 现有 login / dingtalk-config / dingtalk-login
- `services/kb-api/app/routes/users.py:38-104` — 现有 CRUD + reset password
- `services/kb-api/app/services/dingtalk_identity.py:16-65` — resolve_user / issue_token
- `services/kb-api/app/deps.py:20-67` — get_current_user / get_principal / require_role
- `kb_common/models.py:9-17` — User 表
- `kb_common/models.py:651-666` — DingtalkBinding 表
- `kb_common/security.py:1-19` — bcrypt + JWT
- `services/kb-common/kb_common/clients/dingtalk_client.py:87-97,162` — operator_union_id 消费点
- `services/kb-api/app/services/sync/sync_settings.py:18,51` — 同步链路消费点
- `services/kb-api/app/routes/agent_internal.py:337-366` — Agent 内部工具消费点
- `web/src/views/login/index.vue:14-45` — 前端登录页
- `web/src/views/chat/index.vue:12,54-61` — H5 免登入口
- `web/src/stores/user.ts` — token/userInfo 状态
- `web/src/router/index.ts:245-273` — 路由守卫

### B. 泳道流程图

见 `docs/superpowers/specs/2026-09-21-dingtalk-auth-account-management-swimlane.drawio` 与同名 `.png` 预览。
