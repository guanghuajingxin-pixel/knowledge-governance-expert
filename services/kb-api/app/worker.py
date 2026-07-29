"""Stub: real Celery task wired in Task 9 (kb-worker). This lets kb-api start
and serve uploads (doc created PENDING) before the worker exists."""


class _StubTask:
    @staticmethod
    def delay(*_args, **_kwargs):
        return None


process_document = _StubTask()
