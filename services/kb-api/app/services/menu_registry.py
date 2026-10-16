"""菜单注册表：门户 + 知识治理专家主应用的可配置菜单全集。

key 约定：门户菜单以 portal.* 命名；主应用菜单直接用路由 path（web 侧边栏过滤零映射）。
系统管理页面（用户管理/角色管理）不入权限树——由 admin 角色门槛 + 后端护栏控制。
"""
from typing import Any

MENU_GROUPS: list[dict[str, Any]] = [
    {
        "key": "portal",
        "label": "门户",
        "children": [
            {"key": "portal.home", "label": "与小杰对话"},
            {"key": "portal.app.knowledge", "label": "知识治理专家"},
            {"key": "portal.app.evaluation", "label": "智能体测评"},
            {"key": "portal.app.skillhub", "label": "SkillHub"},
        ],
    },
    {
        "key": "web",
        "label": "知识治理专家",
        "children": [
            {"key": "/chat", "label": "智能问答"},
            {"key": "/deap-agent", "label": "DEAP智能问答"},
            {"key": "/hiagent", "label": "HiAgent智能问答"},
            {"key": "/dify", "label": "Dify智能问答"},
            {
                "key": "/collection",
                "label": "知识采集",
                "children": [
                    {"key": "/knowledge-sources", "label": "知识源管理"},
                    {"key": "/collection/knowledge-center", "label": "知识中心"},
                    {"key": "/collection/queue", "label": "同步队列"},
                ],
            },
            {
                "key": "/apply",
                "label": "知识应用",
                "children": [
                    {"key": "/apply/masking", "label": "脱敏策略"},
                    {"key": "/apply/knowledge-libraries", "label": "知识库"},
                ],
            },
            {
                "key": "/operate",
                "label": "知识运营",
                "children": [
                    {"key": "/operate/dashboard", "label": "运营看板"},
                    {"key": "/operate/qa", "label": "问答明细"},
                    {"key": "/operate/corrections", "label": "知识纠错"},
                ],
            },
            {
                "key": "/govern",
                "label": "知识治理",
                "children": [
                    {"key": "/govern/gaps", "label": "知识缺口"},
                    {"key": "/govern/review", "label": "入库审核"},
                ],
            },
            {"key": "/model", "label": "系统配置"},
            {"key": "/agent-config", "label": "智能体配置"},
            {"key": "/settings/api-keys", "label": "API Key"},
        ],
    },
]


def _collect_keys(nodes: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for node in nodes:
        keys.add(node["key"])
        keys.update(_collect_keys(node.get("children", [])))
    return keys


#: 全部菜单 key 的扁平集合（含分组 key，用于服务端宽松校验权限配置；
#: 前端树形勾选会提交分组 key，消费侧只按叶子 key 过滤，未知 key 忽略）
KNOWN_MENU_KEYS: frozenset[str] = frozenset(_collect_keys(MENU_GROUPS))


def menu_tree() -> list[dict[str, Any]]:
    """深拷贝返回菜单树（供 GET /api/v1/portal/menus，避免调用方原地改写常量）。"""
    import copy
    return copy.deepcopy(MENU_GROUPS)
