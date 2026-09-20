"""本地分段器：MinerU 解析产物（markdown）按文档库既有分段规则切块。

规则与 ProcessingConfig 对齐（RAGFlow 时代的配置项全部保留）：
- chunk_method=one：整篇一个分段；
- chunk_method=auto：【自动】分层瀑布分段（无大模型），三级策略逐级兜底——
  ① 结构切分：fence 感知地扫描 markdown 标题（# ~ ######），按标题树切节，
     节内保留标题行；超长节拆分出的续块补「标题路径」行（一级 > 二级 > 三级），
     保证脱离上下文的 chunk 仍可溯源；
  ② 递归长度修正：超长节按 段落（空行，围栏代码块整体为一块）→ 原子行
     （连续表格行/图片行不拆）→ 句子（delimiter 集合）→ 字符滑窗（重叠 limit/8）
     逐级递归，目标长度 chunk_token_num；过短邻块（< limit/4）同节内合并；
  ③ 统计兜底：全文无标题时按 TextTiling-lite 切分——句子块（3 句/块）的
     字符 1/2-gram 向量做余弦相似度，谷值深度 ≥ μ+σ/2 且为局部极小处判定
     主题边界，产出仍走 ② 的长度修正；
- 其他方法（naive/book/laws/manual/paper/presentation/table）统一按 naive
  近似处理：delimiter 集合切句 + chunk_token_num 滚动窗口聚合（单句不硬拆）；
- enable_children：父分段按 children_delimiter 切子块（子块行 parent_id 指向
  父分段，列表页只展示父分段）；仅 naive 生效；
- auto_keywords / auto_questions：引擎侧生成能力，本地解析不生成，忽略；
- layout_recognize：MinerU 恒做版面识别，该选项保留在配置中但不区分行为。

markdown 清理：剔除 data:image 内联图（base64 会撑爆存储），保留普通图片引用。
"""
import math
import re

_DATA_URI_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*data:image/[^)]*\)", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(\S.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def clean_markdown(md: str) -> str:
    if not md:
        return ""
    lines = []
    for line in md.splitlines():
        if "data:image/" in line:
            line = _DATA_URI_IMG_RE.sub("", line)
            if not line.strip():
                continue
        lines.append(line)
    return "\n".join(lines).strip()


def est_tokens(text: str) -> int:
    """token 估算：非 ASCII ≈ 1 token/字，ASCII ≈ 1 token/4 字符。"""
    if not text:
        return 0
    ascii_len = sum(1 for ch in text if ord(ch) < 128)
    return (len(text) - ascii_len) + (ascii_len + 3) // 4


def _split_sentences(text: str, delimiters: str) -> list[str]:
    """按分隔符集合切句，分隔符保留在句尾；空句丢弃。"""
    if not delimiters:
        return [text] if text.strip() else []
    parts, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch in delimiters:
            parts.append("".join(buf))
            buf = []
    if buf:
        parts.append("".join(buf))
    return [p for p in parts if p.strip()]


def _split_sections(text: str) -> list[dict]:
    """① 结构切分：按 markdown 标题树切节（fence 感知，代码块内的 # 不算标题）。

    返回 [{"path": [一级标题, ..., 当前标题], "text": 节正文（含标题行）}]，
    首个标题之前的前言作为 path 为空的首节；全文无标题时返回单个 path 为空的节。
    """
    sections: list[dict] = []
    stack: list[tuple[int, str]] = []
    cur: list[str] = []
    cur_path: list[str] = []
    in_fence = False

    def flush():
        body = "\n".join(cur).strip()
        if body:
            sections.append({"path": cur_path, "text": body})

    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            flush()
            cur = [line]
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            cur_path = [t for _, t in stack]
        else:
            cur.append(line)
    flush()
    return sections


def _top_blocks(text: str) -> list[str]:
    """顶层块切分：空行分段，围栏代码块整体为一块（围栏内允许空行）。"""
    blocks, cur, in_fence = [], [], False
    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return [b for b in blocks if b.strip()]


def _atomic_lines(text: str) -> list[str]:
    """原子行切分：连续表格行聚为一个单元，其余逐行（图片/公式行天然单行）。"""
    units, table = [], []
    for line in text.split("\n"):
        if _TABLE_ROW_RE.match(line):
            table.append(line)
            continue
        if table:
            units.append("\n".join(table))
            table = []
        if line.strip():
            units.append(line)
    if table:
        units.append("\n".join(table))
    return units


def _sliding_window(text: str, limit: int) -> list[str]:
    """字符滑窗兜底：无可用边界时硬切，重叠 limit/8 保上下文连续。
    est_tokens 对 CJK ≈ 1 token/字、ASCII ≈ 1/4，故 limit 字符窗口必不超 token 上限。"""
    overlap = max(8, limit // 8)
    step = max(1, limit - overlap)
    out = []
    for start in range(0, len(text), step):
        piece = text[start:start + limit].strip()
        if piece:
            out.append(piece)
    return out


def _pack(units: list[str], joiner: str, limit: int, split_deeper) -> list[str]:
    """滚动聚合 ≤ limit；单个超长单元交下一级拆分。"""
    out, cur = [], ""
    for u in units:
        if est_tokens(u) > limit:
            if cur.strip():
                out.append(cur.strip())
                cur = ""
            out.extend(split_deeper(u))
            continue
        cand = cur + (joiner if cur else "") + u
        if cur and est_tokens(cand) > limit:
            out.append(cur.strip())
            cur = u
        else:
            cur = cand
    if cur.strip():
        out.append(cur.strip())
    return out


def _rec_split(text: str, limit: int, delimiters: str, level: int = 0) -> list[str]:
    """② 递归长度修正：段落 → 原子行 → 句子 → 滑窗，逐级兜底直到 ≤ limit。"""
    text = text.strip()
    if not text:
        return []
    if est_tokens(text) <= limit:
        return [text]
    levels = (
        lambda t: (_top_blocks(t), "\n\n"),
        lambda t: (_atomic_lines(t), "\n"),
        lambda t: (_split_sentences(t, delimiters), ""),
    )
    if level < len(levels):
        units, joiner = levels[level](text)
        if len(units) > 1:
            return _pack(units, joiner, limit,
                         lambda t: _rec_split(t, limit, delimiters, level + 1))
        return _rec_split(text, limit, delimiters, level + 1)
    return _sliding_window(text, limit)


def _merge_small(pieces: list[str], min_tokens: int, limit: int) -> list[str]:
    """过短邻块（< min_tokens）向前合并，合并后仍不超 limit。"""
    out: list[str] = []
    for p in pieces:
        if out and est_tokens(out[-1]) < min_tokens \
                and est_tokens(out[-1]) + est_tokens(p) <= limit:
            out[-1] = out[-1] + "\n\n" + p
        else:
            out.append(p)
    return out


def _ngrams(text: str) -> dict:
    """字符 1/2-gram 词频向量（CJK 无需分词）。"""
    chars = [c for c in text if not c.isspace()]
    counts: dict[str, int] = {}
    for n in (1, 2):
        for i in range(len(chars) - n + 1):
            g = "".join(chars[i:i + n])
            counts[g] = counts.get(g, 0) + 1
    return counts


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[g] * b[g] for g in a.keys() & b.keys())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _texttile_segments(text: str, delimiters: str, block: int = 2) -> list[str]:
    """③ 统计兜底（TextTiling-lite）：滑动窗口间隙评分——每个句子间隙取左右各 block 句
    的 1/2-gram 余弦相似度（避免固定分块骑跨边界）。含 ≥2 个自然段时仅以段落边界为候选
    （作者常用分段表达话题切换，同时抑制段内噪声谷值），否则全部间隙候选。
    谷值深度 ≥ max(μ+σ/2, 0.1)、间隙相似度 ≤ 0.5（绝对上限，防止高相似均匀文本因相对
    波动被误切）且为局部极小处判为主题边界；均匀文本不切，交长度修正层处理。"""
    sentences: list[str] = []
    para_gaps: set[int] = set()
    for line in text.split("\n"):
        if not line.strip():
            continue
        sentences.extend(_split_sentences(line, delimiters))
        para_gaps.add(len(sentences) - 1)
    para_gaps.discard(len(sentences) - 1)  # 文末不是间隙
    if len(sentences) < block * 3:
        return [text]
    scores = []
    for gap in range(len(sentences) - 1):
        left = "".join(sentences[max(0, gap - block + 1):gap + 1])
        right = "".join(sentences[gap + 1:gap + 1 + block])
        scores.append(_cosine(_ngrams(left), _ngrams(right)))
    if not scores:
        return [text]
    candidates = sorted(para_gaps) if para_gaps else list(range(len(scores)))
    depths: dict[int, float] = {}
    for i in candidates:
        s = scores[i]
        lp = rp = s
        j = i - 1
        while j >= 0 and scores[j] > lp:
            lp = scores[j]
            j -= 1
        j = i + 1
        while j < len(scores) and scores[j] > rp:
            rp = scores[j]
            j += 1
        depths[i] = (lp - s) + (rp - s)
    # 候选 ≥4 时统计阈值（μ+σ/2）才有意义；候选过少时 μ+σ/2 会在两个等大深谷之间
    # 取中间值而漏切，退化为仅用绝对下限 0.1。
    if len(depths) >= 4:
        mean = sum(depths.values()) / len(depths)
        std = math.sqrt(sum((d - mean) ** 2 for d in depths.values()) / len(depths))
        threshold = max(mean + std / 2, 0.1)
    else:
        threshold = 0.1
    cuts = []
    for i, d in depths.items():
        if d < threshold or scores[i] > 0.5:
            continue
        left_ok = i == 0 or scores[i] <= scores[i - 1]
        right_ok = i + 1 == len(scores) or scores[i] <= scores[i + 1]
        if left_ok and right_ok:
            cuts.append(i)
    bounds = [0] + [i + 1 for i in sorted(cuts)] + [len(sentences)]
    segments = ["".join(sentences[a:b]).strip() for a, b in zip(bounds, bounds[1:])]
    return [s for s in segments if s] or [text]


def _auto_chunk(text: str, delimiters: str, limit: int) -> list[str]:
    """【自动】分层瀑布：结构切分 → 递归长度修正 → 统计兜底。"""
    sections = _split_sections(text)
    if not any(s["path"] for s in sections):
        sections = [{"path": [], "text": seg}
                    for seg in _texttile_segments(text, delimiters)]
    min_tokens = max(32, limit // 4)
    chunks: list[str] = []
    for sec in sections:
        pieces = _merge_small(_rec_split(sec["text"], limit, delimiters), min_tokens, limit)
        path_line = " > ".join(sec["path"])
        for i, piece in enumerate(pieces):
            if i > 0 and path_line:
                piece = f"{path_line}\n{piece}"
            chunks.append(piece)
    return chunks


def chunk_markdown(md: str, cfg: dict) -> list[dict]:
    """按分段规则切块。返回 [{"content": str, "children": [str] | None}]，
    顺序即 position；children 仅在父子分段启用且子块多于 1 个时给出。"""
    text = clean_markdown(md)
    if not text:
        return []
    method = str(cfg.get("chunk_method") or "naive").lower()
    if method == "one":
        return [{"content": text, "children": None}]

    delimiters = cfg.get("delimiter") or "\n。！？；"
    limit = max(1, int(cfg.get("chunk_token_num") or 512))
    if method == "auto":
        chunks = _auto_chunk(text, delimiters, limit)
    else:
        chunks = []
        cur = ""
        for sentence in _split_sentences(text, delimiters):
            if cur and est_tokens(cur) + est_tokens(sentence) > limit:
                chunks.append(cur.strip())
                cur = sentence
            else:
                cur += sentence
        if cur.strip():
            chunks.append(cur.strip())

    enable_children = bool(cfg.get("enable_children")) and method == "naive"
    child_delim = cfg.get("children_delimiter") or "\n"
    result = []
    for chunk in chunks:
        children = None
        if enable_children:
            pieces = [p.strip() for p in chunk.split(child_delim) if p.strip()]
            if len(pieces) > 1:
                children = pieces
        result.append({"content": chunk, "children": children})
    return result
