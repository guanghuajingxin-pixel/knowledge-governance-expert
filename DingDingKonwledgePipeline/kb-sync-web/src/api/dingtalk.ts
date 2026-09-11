import http from './http'
import type { TreeNode, TreeNodeLite, Workspace } from '@/types'

export async function listWorkspaces() { const { data } = await http.get<Workspace[]>('/dingtalk/workspaces'); return data }
export async function buildTree(rootNodeId: string, depth = 5) { const { data } = await http.get<TreeNode[]>('/dingtalk/tree', { params: { root_node_id: rootNodeId, depth } }); return data }
export async function listNodes(parentNodeId: string) { const { data } = await http.get<TreeNodeLite[]>('/dingtalk/nodes', { params: { parent_node_id: parentNodeId } }); return data }
