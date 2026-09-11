#!/usr/bin/env python3
"""Run enterprise questions and report auditable acceptance; never equate citations with accuracy.

Run with kb-api's virtualenv. Auth comes only from QA_EVAL_TOKEN, never CLI arguments.
Human annotations are keyed by question id and must refer to the exact answer_hash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def load_jsonl(path):
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    ids = [r.get('id') for r in rows]
    if not rows or any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('题集/结果必须非空，每行必须有唯一 id')
    return rows


def answer_hash(response):
    # A changed source snapshot invalidates previous human grades too.
    data = {'answer':response.get('answer'), 'citations':response.get('citations'),
            'answer_status':response.get('answer_status')}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def metrics(cases, responses, annotations=None, target=.90, minimum=100):
    by_id = {r['id']:r for r in responses}
    grades = {r['id']:r for r in annotations or []}
    automatic, correct, reviewed, refused, durations = 0, 0, 0, 0, []
    rows = []
    for case in cases:
        item = by_id.get(case['id'], {})
        response = item.get('response') or {}
        status = response.get('answer_status')
        answer = response.get('answer') or ''
        answerable = case.get('answerable', True)
        refused += int(status == 'insufficient')
        expected = 'answered' if answerable else 'insufficient'
        cited = {c.get('document_id') for c in response.get('citations', [])}
        source_ok = set(case.get('reference_ids', [])) <= cited if answerable else True
        passed = (status == expected and source_ok
                  and all(t in answer for t in case.get('must_include', []))
                  and all(t not in answer for t in case.get('must_not_include', [])))
        automatic += int(passed)
        grade = grades.get(case['id']) or {}
        valid_grade = (type(grade.get('correct')) is bool and bool(grade.get('reviewer'))
                       and grade.get('answer_hash') == answer_hash(response))
        reviewed += int(valid_grade)
        # Refusal/partial responses to answerable questions remain failures in the denominator.
        is_correct = valid_grade and grade['correct'] and status == expected and source_ok
        correct += int(is_correct)
        if item.get('duration_ms') is not None:
            durations.append(item['duration_ms'])
        rows.append({'id':case['id'], 'answer_hash':answer_hash(response), 'status':status,
                     'automatic_pass':passed, 'expert_reviewed':valid_grade, 'expert_correct':bool(is_correct)})
    n = len(cases)
    accuracy = correct/n if reviewed == n else None
    accepted = n >= minimum and accuracy is not None and accuracy > target
    return {'questions':n, 'automatic_check_rate':automatic/n, 'expert_reviewed':reviewed,
            'expert_end_to_end_accuracy':accuracy, 'refusal_rate':refused/n,
            'p95_duration_ms':sorted(durations)[min(len(durations)-1, int(len(durations)*.95))] if durations else None,
            'target_strictly_above':target, 'minimum_questions':minimum, 'accepted':accepted,
            'status':'passed' if accepted else ('needs_expert_review_or_more_questions' if reviewed<n or n<minimum else 'below_target'),
            'items':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('corpus')
    parser.add_argument('--responses', help='已保存的 JSONL 回答；提供时不调用服务')
    parser.add_argument('--annotations', help='专家判分 JSONL: id, answer_hash, correct, reviewer, reason')
    parser.add_argument('--endpoint', default='http://127.0.0.1:8000/api/v1/search/chat')
    parser.add_argument('--output', required=True, help='新输出目录，避免覆盖既有评测')
    args=parser.parse_args()
    cases=load_jsonl(args.corpus)
    for case in cases:
        if not case.get('question') or type(case.get('answerable')) is not bool:
            parser.error('每题必须有 question 和布尔值 answerable')
    output=Path(args.output); output.mkdir(parents=True, exist_ok=False)
    if args.responses:
        responses=load_jsonl(args.responses)
    else:
        import httpx
        import time
        token=os.getenv('QA_EVAL_TOKEN')
        if not token:
            parser.error('请通过 QA_EVAL_TOKEN 配置测试用户的 JWT/API Key')
        responses=[]
        with httpx.Client(timeout=320, headers={'Authorization':f'Bearer {token}'}) as client:
            for case in cases:
                start=time.monotonic()
                payload={'query':case['question']}
                for key in ('dify_dataset_ids','kb_ids','history','model'):
                    if key in case:
                        payload[key]=case[key]
                try:
                    response=client.post(args.endpoint,json=payload)
                    response.raise_for_status()
                    result=response.json()
                except Exception as exc:
                    result={'answer_status':'error','answer':'','error':type(exc).__name__}
                item={'id':case['id'],'response':result,'duration_ms':round((time.monotonic()-start)*1000)}
                responses.append(item)
                # Preserve progress across interrupted evaluation runs.
                with (output/'responses.jsonl').open('a') as f:
                    f.write(json.dumps(item,ensure_ascii=False)+'\n')
    report=metrics(cases,responses,load_jsonl(args.annotations) if args.annotations else [])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    (output/'review-template.jsonl').write_text('\n'.join(json.dumps({
        'id':r['id'], 'answer_hash':r['answer_hash'], 'correct':None, 'reviewer':'', 'reason':'',
    },ensure_ascii=False) for r in report['items'])+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='items'},ensure_ascii=False,indent=2))
    return 0 if report['accepted'] else 2


if __name__=='__main__':
    raise SystemExit(main())
