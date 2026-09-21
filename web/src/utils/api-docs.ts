/**
 * 解析引擎 API 文档入口的地址解析。
 *
 * 两类入口：
 *  - 「API 调用说明」：web/public 自编文档页（含端到端示例），地址固定；
 *  - 「OpenAPI」：Swagger 调试台 {Base}/docs，Base 与「自定义解析」页签
 *    （ParserCustomTab）、处理引擎页（ProcessEngine）共用同一份 localStorage 配置。
 * 后续新增其他 OpenAPI 服务时在此追加。
 */

const MINERU_CONFIG_KEY = 'kge:mineru_config_v1'
const DEFAULT_MINERU_BASE = 'http://127.0.0.1:8010'

/** 解析引擎 Swagger 文档地址（{Base}/docs），读取失败回退默认 Base */
export function getParserEngineDocsUrl(): string {
  let base = DEFAULT_MINERU_BASE
  try {
    const raw = localStorage.getItem(MINERU_CONFIG_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { baseUrl?: string }
      if (parsed.baseUrl?.trim()) base = parsed.baseUrl.trim()
    }
  } catch {
    /* 忽略损坏缓存，回退默认地址 */
  }
  return `${base.replace(/\/+$/, '')}/docs`
}

/** 在新浏览器页签打开解析引擎 API 调用说明文档页（Docsify 渲染的静态文档，含端到端示例） */
export function openParserApiGuide(): void {
  window.open('/mineru-api-docs.html', '_blank', 'noopener')
}

/** 在新浏览器页签打开解析引擎 OpenAPI 文档 */
export function openParserEngineDocs(): void {
  window.open(getParserEngineDocsUrl(), '_blank', 'noopener')
}
