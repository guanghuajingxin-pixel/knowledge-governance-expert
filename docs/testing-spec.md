# 测试规范(testing-spec)

> 本文是全仓测试的**唯一事实源**,扩展 AGENTS.md「自动化测试要求」。任何代码任务完成后必须跑对应层级测试、全绿才算交付;未跑或未过不得宣告完成。

## 1. 分层测试矩阵

| 层级 | 框架 | 命令 | 覆盖范围 |
|---|---|---|---|
| 前端单元/组件 | Vitest + @vue/test-utils + msw | `cd web && pnpm type-check && pnpm test:run` | 组件交互、store、api 封装、utils |
| 后端单元/路由 | pytest + pytest-asyncio(`asyncio_mode=auto`) | `cd services/kb-api && uv run pytest tests/ -q` | 路由行为、services、错误分支 |
| 核心链路 E2E | smoke 脚本 | `./scripts/smoke_test.sh`(需 `SMOKE_USERNAME/PASSWORD`) | 登录→建库→上传→检索→问答主链路 |

位置与命名:前端 `web/src/**/__tests__/*.test.ts`,与被测文件同目录;后端 `services/kb-api/tests/test_*.py`,文件名标注模块(如 `test_wiki_llm_error.py`)。

## 2. 强制规则

1. **测试同步维护**:改函数签名、路由行为或数据流时,必须同步更新受影响测试;禁止留下\"已知失败\"。
2. **新增功能/修 bug 必须带用例**:覆盖主路径 + 边界条件(空集、非法输入、部分失败、防御分支)。
3. **首轮 vitest 报错可能是瞬时 worker 崩溃**:重跑一次确认后再排查,不要立刻改代码。
4. **测试不依赖真实基础设施**:不连真实 PG/Redis/ES/MinIO/外部 API;全部 mock(见 §3/§4)。
5. 改动涉及核心链路或发布前,加跑 smoke。

## 3. 后端测试模式(pytest)

### 3.1 会话替身(mock session)

路由直调测函数,不启动 app;`AsyncSession` 用 `SimpleNamespace + AsyncMock` 替身:

```python
def _session_with(docs):
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: docs))
    return SimpleNamespace(execute=AsyncMock(side_effect=[result, Mock(), Mock()]),
                           delete=AsyncMock(), commit=AsyncMock())
```

- `execute.side_effect` 按**调用顺序**给结果(文档查询 → 计数/UPDATE → ...),一次写全;
- 直调路由函数时,未传的 Query 默认值是 `Query(None)` 对象——判断参数请用 `isinstance(x, int/str)` 而非 `is not None`(参照 `batch_delete_all_source_documents` 的 limit 处理);
- 断言 SQL 条件:`stmt.compile(compile_kwargs={'literal_binds': True})` 后 `assertIn` 关键条件(如 `LIMIT 50`、`status != 'PARSING'`),保证筛选口径与列表一致。

### 3.2 外部客户端替身

函数内延迟导入的客户端(如 minio_client)用 `sys.modules` + 包属性双保险替换:

```python
fake = types.ModuleType('kb_common.clients.minio_client')
fake.RAW = 'raw-docs'
fake.delete_prefix = delete_prefix  # Mock(return_value=n)
patch.dict(sys.modules, {...}), patch.object(clients_pkg, 'minio_client', fake, create=True)
```

### 3.3 异步与事件循环

- async 用例继承 `unittest.IsolatedAsyncioTestCase`(或裸 `async def test_` 交 asyncio_mode=auto);
- 测跨 loop 逻辑时用真实 `new_event_loop + run_forever` 线程(参照 `test_wiki_generator_loop.py` 的 `_spawn` 回主 loop 用例);
- mock async 函数用 `AsyncMock`,注意 `side_effect` 抛错路径。

### 3.4 错误分支必测

每个用户可见的失败路径至少一条用例:HTTPException 断言 `status_code` 与 `detail` 关键词;后台任务断言异常被兜底落状态(FAILED + 中文原因)、commit 未被调用等副作用。

## 4. 前端测试模式(vitest)

### 4.1 组件挂载

```ts
mount(Page, { attachTo: document.body,
  global: { plugins: [ElementPlus], stubs: { transition: false } } })
```

- Element Plus 以插件整体安装;`transition: false` 让弹层立即可断言;
- 每条用例后 `document.body.innerHTML = ''` 清理 teleport 残留 + `vi.clearAllMocks()`。

### 4.2 模块 mock

- `vi.mock('@/api/xxx', ...)` 整模块替身,**mock 全部被导入的导出**(漏一个会在 setup 阶段炸);
- 依赖 `vue-router`/`stores` 的页面:mock `useRoute/useRouter`、`useUserStore/useTabsStore` 返回最小对象;重弹窗子组件(如 AddKnowledgeDialog)mock 成空渲染;
- 数据用 `vi.mocked(fn).mockResolvedValueOnce(...)` 按**调用顺序**给结果(分批循环等场景)。

### 4.3 teleport 内容断言

el-drawer / el-dropdown / el-message-box / el-tooltip 的内容都 teleport 到 `document.body`,必须在 body 上断言:

```ts
document.querySelectorAll('.el-dropdown-menu__item')   // 下拉项
[...document.querySelectorAll('.el-message-box__btns button')]
  .find(b => b.textContent?.trim() === '删除')        // 确认弹窗按钮
```

- 下拉菜单默认 hover 触发:`await wrapper.find('.el-dropdown').trigger('mouseenter')`;
- tooltip hover:`el.dispatchEvent(new MouseEvent('mouseenter'))` + 等 ~300ms 再断言 body 文案;
- 每条用例聚焦一个交互闭环(菜单项禁用态→触发→确认→API 断言),断言写用户可见文案而非内部实现细节。

### 4.4 统一组件

新沉淀的公共组件(如 `HelpTip`)首发即带用例:角标仅失败行渲染、aria-label、hover 后 body 出现提示文案——防止再次出现各页面风格漂移。

## 5. 提交前检查清单

- [ ] `uv run pytest tests/ -q` 全绿(新增用例覆盖主路径+边界+错误分支)
- [ ] `cd web && pnpm type-check && pnpm test:run` 全绿
- [ ] 改动的行为断言里含用户可见文案(中文提示、禁用态),不只测内部状态
- [ ] mock 未泄漏真实基础设施;用例顺序无关(不依赖执行顺序)
- [ ] 核心链路改动补跑 `./scripts/smoke_test.sh`
