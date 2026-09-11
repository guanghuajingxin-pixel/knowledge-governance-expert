"""Shared upload limits and text extraction for PowerPoint files."""
import io
import re
import zipfile
from pathlib import PurePath
from xml.etree import ElementTree

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
UPLOAD_EXTENSIONS = {"pdf", "docx", "doc", "pptx", "ppt", "xls", "xlsx", "csv", "txt", "md", "markdown", "mdx", "html", "htm", "vtt", "properties"}


def prepare_document(filename: str, content: bytes, *,
                     max_source_bytes: int = MAX_UPLOAD_BYTES) -> tuple[str, bytes]:
    extension = PurePath(filename).suffix.lower().lstrip(".")
    if extension not in UPLOAD_EXTENSIONS:
        raise ValueError("不支持此文件格式，请使用 PDF、Word、PowerPoint、Excel、CSV、TXT、Markdown 或 HTML。")
    if not content:
        raise ValueError("文件为空，请选择有内容的文档。")
    # 同步源 PPTX 可先转换文本；转换产物仍遵守 Dify 的 15 MB 上传上限。
    source_limit = max_source_bytes if extension == "pptx" else MAX_UPLOAD_BYTES
    if len(content) > source_limit:
        raise ValueError(f"单个文件不得超过 {source_limit // (1024 * 1024)} MB，请压缩或拆分后上传。")
    if extension != "pptx":
        return filename, content
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            slides = [item for item in archive.infolist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", item.filename)]
            if sum(item.file_size for item in slides) > 50 * 1024 * 1024:
                raise ValueError("PPTX 解压后的文本数据过大，请拆分演示文稿。")
            slides.sort(key=lambda item: int(re.search(r"slide(\d+)", item.filename)[1]))
            sections = []
            for index, item in enumerate(slides, 1):
                root = ElementTree.fromstring(archive.read(item))
                lines = [node.text for node in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t") if node.text]
                if lines:
                    sections.append(f"## 第 {index} 页\n\n" + "\n".join(lines))
            if not sections:
                raise ValueError("PPTX 未提取到文本；纯图片幻灯片请先 OCR 转为可搜索 PDF 或文本。")
            extracted = "\n\n".join(sections).encode("utf-8")
            if len(extracted) > MAX_UPLOAD_BYTES:
                raise ValueError("提取后的文本超过 15 MB，请拆分演示文稿。")
            return str(PurePath(filename).with_suffix(".md")), extracted
    except (zipfile.BadZipFile, ElementTree.ParseError, RuntimeError) as exc:
        raise ValueError("PPTX 无法读取，可能已损坏或加密，请解除密码后重新另存。") from exc
