import hashlib, re

def chunk(text: str, strategy: str = "FIXED_SIZE", size: int = 512,
          overlap: int = 150, delimiter: str | None = None) -> list[dict]:
    """返回 [{'text','chunk_index','content_hash','token_count','page_number'}]。
    - FIXED_SIZE: 按字符长度滑窗切片
    - DELIMITER: 优先按分隔符切段，超长段再按 FIXED_SIZE 兜底
    - MARKDOWN_HEADER: 按 # 标题切（MVP 近似按双换行段落 + 标题边界）
    """
    text = (text or "").strip()
    if not text: return []
    if strategy == "DELIMITER" and delimiter:
        parts = re.split(re.escape(delimiter), text)
    elif strategy == "MARKDOWN_HEADER":
        parts = re.split(r"\n(?=#{1,6}\s)", text)
    else:
        parts = [text]

    out, idx = [], 0
    for p in parts:
        p = p.strip()
        if not p: continue
        if len(p) <= size:
            _append(out, idx, p); idx += 1
        else:
            for i in range(0, len(p), size - overlap):
                seg = p[i:i+size]
                if seg.strip():
                    _append(out, idx, seg); idx += 1
                if i + size >= len(p): break
    return out

def _append(out, idx, text):
    out.append({
        "text": text,
        "chunk_index": idx,
        "content_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest()[:32],
        "token_count": len(text),   # MVP 以字符数近似 token
        "page_number": 1,
    })
