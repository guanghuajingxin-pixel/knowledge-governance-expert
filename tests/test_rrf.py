from kb_common.rag.searcher import _rrf


def test_rrf_fuses_and_ranks():
    a = [("h1", 10, {"t": "a"}), ("h2", 9, {"t": "b"}), ("h3", 8, {"t": "c"})]
    b = [("h2", 10, {"t": "b"}), ("h1", 9, {"t": "a"}), ("h4", 8, {"t": "d"})]
    r = _rrf([a, b], top_k=4)
    ids = [x[0] for x in r]
    assert ids[0] in ("h1", "h2")   # 两路都靠前，融合后置顶
    assert "h4" in ids and "h3" in ids
