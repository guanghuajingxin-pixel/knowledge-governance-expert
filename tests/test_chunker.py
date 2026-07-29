from kb_common.rag.chunker import chunk


def test_fixed_size_basic():
    r = chunk("a" * 1200, "FIXED_SIZE", size=512, overlap=150)
    assert len(r) >= 3
    assert all("text" in x and "content_hash" in x for x in r)


def test_delimiter_priority():
    r = chunk("aa\n\nbb\n\ncc", "DELIMITER", size=512, overlap=0, delimiter="\n\n")
    assert len(r) == 3 and r[0]["text"] == "aa"


def test_empty():
    assert chunk("") == []
