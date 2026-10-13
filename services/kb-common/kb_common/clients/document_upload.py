"""本地文档库同步/上传的扩展名白名单。

UPLOAD_EXTENSIONS 与本地解析通道能力对齐：txt/md/csv 等纯文本走本地解析，
PDF/DOCX/PPTX/XLSX/HTML 等走 MinerU 解析（云端 API 或本地 mineru-kit）。
目录级批量同步必须在上传前按此集合过滤，避免整批失败。
"""
UPLOAD_EXTENSIONS = {"pdf", "docx", "doc", "pptx", "ppt", "xls", "xlsx", "csv", "txt", "md", "markdown", "mdx", "html", "htm", "vtt", "properties", "eml", "msg", "xml", "epub"}
