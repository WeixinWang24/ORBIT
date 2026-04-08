from __future__ import annotations

import io
import logging
import warnings
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from orbit.memory.embedding_service import _load_model


class _FakeSentenceTransformer:
    def __init__(self, model_name: str):
        print(f"loading {model_name}")
        import sys

        print("hf warning", file=sys.stderr)
        warnings.warn("unauthenticated hf hub")
        logging.getLogger("transformers.utils.loading_report").warning("BertModel LOAD REPORT from: %s", model_name)
        logging.getLogger("huggingface_hub").warning("You are sending unauthenticated requests to the HF Hub.")
        self.model_name = model_name


def test_load_model_suppresses_sentence_transformer_init_output():
    _load_model.cache_clear()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    logging_buffer = io.StringIO()
    handler = logging.StreamHandler(logging_buffer)
    load_logger = logging.getLogger("transformers.utils.loading_report")
    hub_logger = logging.getLogger("huggingface_hub")
    load_logger.addHandler(handler)
    hub_logger.addHandler(handler)

    try:
        with patch("orbit.memory.embedding_service.SentenceTransformer", _FakeSentenceTransformer):
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                model = _load_model("fake-mini")
    finally:
        load_logger.removeHandler(handler)
        hub_logger.removeHandler(handler)

    assert model.model_name == "fake-mini"
    assert stdout_buffer.getvalue() == ""
    assert stderr_buffer.getvalue() == ""
    assert logging_buffer.getvalue() == ""
