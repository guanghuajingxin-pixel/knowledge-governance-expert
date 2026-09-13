"""杰克百晓生智能问答 Agent（DeerFlow sidecar 链路）。

问答主链：routes/search.py → services/agent/deerflow_runner.py → DeerFlow QA Sidecar
（services/deerflow，工具经 agent_internal 内部接口回查本平台）。
"""
