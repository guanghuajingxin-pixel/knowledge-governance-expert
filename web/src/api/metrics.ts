import request from './request'

export interface OverviewMetrics {
  /** 今日新增：今日进入系统的知识文档数（上传 + 同步采集 + 手动转写 Dify） */
  today_new: number
  /** 今日加工：今日完成 AI 加工（打标/摘要）的文档数 */
  today_processed: number
  /** 累计采纳：问答反馈「有帮助」累计条数 */
  total_adopted: number
  /** 累计反馈：问答反馈全部累计条数 */
  total_feedback: number
}

/** 顶栏运营指标（后端实时聚合） */
export const getOverviewMetrics = () =>
  request.get<unknown, OverviewMetrics>('/metrics/overview')
