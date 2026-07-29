from FlagEmbedding import FlagModel
from kb_common.config import get_settings
_instance = None

def get_embedder():
    global _instance
    if _instance is None:
        s = get_settings()
        _instance = FlagModel(s.bge_embed_model, use_fp16=False,
                              devices=["cpu"])  # Mac 无 NVIDIA GPU，CPU 推理
        # FlagEmbedding 1.4+: normalize_embeddings 是构造器参数（默认 True），不能传给 encode()
    return _instance

def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts).tolist()
