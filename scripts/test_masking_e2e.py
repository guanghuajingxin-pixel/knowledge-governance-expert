"""脱敏策略控制台端到端验证（TestClient，直连本地基础设施）。"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "kb-api"))
os.environ.setdefault("JWT_SECRET", "kb-mvp-dev-secret")
os.environ.setdefault("XXL_JOB_ENABLED", "false")  # 测试环境禁用调度，避免 xxl-job 偶发超时阻断启动

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as c:
    # 1. 登录
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    H = {"Authorization": f"Bearer {token}"}
    print("login ok")

    # 2. 未登录 401
    assert c.get("/api/v1/masking-policies").status_code == 401
    print("unauth 401 ok")

    # 3. 全局配置读写
    r = c.get("/api/v1/masking-global", headers=H)
    assert r.status_code == 200, r.text
    print("global:", r.json())
    r = c.put("/api/v1/masking-global", headers=H,
              json={"enabled": True, "pre_llm": True, "post_output": True,
                    "failure_strategy": "non_sensitive", "hint": "部分内容因权限隐藏"})
    assert r.status_code == 200, r.text

    # 4. 策略 CRUD（幂等：先清理历史残留）
    r = c.get("/api/v1/masking-policies", headers=H)
    assert r.status_code == 200, r.text
    for old in r.json():
        if old["name"].startswith("验证-"):
            assert c.delete(f"/api/v1/masking-policies/{old['id']}", headers=H).status_code == 200
    r = c.post("/api/v1/masking-policies", headers=H, json={
        "name": "验证-全量内置脱敏",
        "description": "e2e 临时策略",
        "scope_type": "global",
        "priority": 1,
        "scenes": ["search", "chat"],
        "dict_types": ["custom"],
        "context_rules": [{"keyword": "薪酬", "entity_type": "custom"}],
        "actions": {"phone": "partial", "id_card": "partial", "bank_card": "hash",
                    "email": "partial", "custom": "replace"},
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    print("policy created:", pid)
    # 重名 409
    assert c.post("/api/v1/masking-policies", headers=H, json={
        "name": "验证-全量内置脱敏", "actions": {}}).status_code == 409
    # 非法正则 422
    assert c.post("/api/v1/masking-policies", headers=H, json={
        "name": "bad", "regex_rules": [{"pattern": "("}]}).status_code == 422
    # 更新
    r = c.put(f"/api/v1/masking-policies/{pid}", headers=H, json={
        "name": "验证-全量内置脱敏", "priority": 5, "enabled": True,
        "actions": {"phone": "partial", "custom": "replace"}})
    assert r.status_code == 200 and r.json()["priority"] == 5, r.text

    # 5. 沙箱（带敏感词的查询；无本地库时也应正常返回结构）
    r = c.post("/api/v1/masking/sandbox", headers=H, json={
        "query": "薪酬 手机号 13812345678", "mock_role": "viewer", "scene": "chat"})
    assert r.status_code == 200, r.text
    sb = r.json()
    print("sandbox: active=%s policies=%s masked=%s" % (
        sb.get("masking_active"), sb.get("policies_applied"), sb.get("masked_count")))

    # 6. 送LLM前脱敏：直接调 _mask_pre_llm（外部检索后端在测试环境不可用，
    #    端点 502 属环境问题；此处验证边界逻辑：身份回溯 + 片段脱敏 + 审计）。
    #    经 c.portal 在应用同一事件循环执行，使 fire-and-forget 审计任务正常落库。
    import time as _t

    async def _t_pre_llm():
        from kb_common.database import SessionLocal
        from app.routes.agent_internal import _mask_pre_llm, _resolve_thread_user
        from kb_common.models import User
        from sqlalchemy import select as _sel
        async with SessionLocal() as s:
            admin = (await s.execute(_sel(User).where(User.username == "admin"))).scalars().first()
            # anon-<uid>：身份回溯
            uid, role = await _resolve_thread_user(s, f"anon-{admin.id}-xyz")
            assert str(uid) == str(admin.id) and role == admin.role, (uid, role)
            # 无效 thread → viewer 最严格
            uid2, role2 = await _resolve_thread_user(s, "not-a-thread")
            assert uid2 is None and role2 == "viewer"
            hits = [{"content": "联系人电话13812345678，详见合同", "document_title": "通讯录-13812345678.docx"}]
            kept, meta = await _mask_pre_llm(s, hits, "电话", thread_id="not-a-thread")
            assert meta and meta.get("applied"), meta
            assert "13812345678" not in (kept[0]["content"] + kept[0]["document_title"]), kept
            await asyncio.sleep(1.2)  # 审计为同循环 fire-and-forget 任务，等其落库
            return meta
    meta = c.portal.call(_t_pre_llm)
    print("pre-llm masking ok:", meta)

    # 7. 审计日志（应包含 pre_llm 命中记录）
    r = c.get("/api/v1/masking-logs", headers=H)
    assert r.status_code == 200, r.text
    logs = r.json()
    print("logs total:", logs["total"])
    pre_llm_hit = any(l["node"] == "pre_llm" and l["masked_count"] > 0 for l in logs["items"])
    assert pre_llm_hit, logs["items"][:3]
    # 日志自身脱敏：不出现完整手机号
    blob = str(logs)
    assert "13812345678" not in blob
    print("audit self-masking ok")

    # 8. 豁免
    r = c.get("/api/v1/users", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"] if isinstance(body, dict) else body
    uid = items[0]["id"] if items else None
    assert uid, "no users"
    r = c.post("/api/v1/masking-exemptions", headers=H, json={
        "user_id": uid, "scope_type": "global", "entity_types": ["phone"],
        "reason": "e2e 豁免验证"})
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    print("exemption created:", eid, r.json()["username"])
    r = c.get("/api/v1/masking-exemptions", headers=H)
    assert any(x["id"] == eid for x in r.json())
    assert c.delete(f"/api/v1/masking-exemptions/{eid}", headers=H).status_code == 200
    print("exemption deleted")

    # 9. 清理
    assert c.delete(f"/api/v1/masking-policies/{pid}", headers=H).status_code == 200
    print("ALL E2E PASSED")
