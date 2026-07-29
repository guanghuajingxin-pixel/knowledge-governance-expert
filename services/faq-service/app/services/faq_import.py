import io, csv
from openpyxl import load_workbook

async def parse(file) -> list[dict]:
    data = await file.read()
    name = file.filename.lower()
    if name.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        return [_row(r) for r in reader]
    if name.endswith((".xlsx", ".xls")):
        wb = load_workbook(io.BytesIO(data)); ws = wb.active
        headers = [c.value for c in ws[1]]
        out = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            rec = dict(zip(headers, row)); out.append(_row(rec))
        return out
    raise ValueError("仅支持 csv/xlsx")

def _row(r: dict) -> dict:
    q = (r.get("question") or r.get("问题") or "").strip()
    a = (r.get("answer") or r.get("答案") or "").strip()
    kw = (r.get("keywords") or r.get("关键词") or "").strip()
    return {"question": q, "answer": a,
            "keywords": [k.strip() for k in kw.split(",") if k.strip()] if kw else []}
