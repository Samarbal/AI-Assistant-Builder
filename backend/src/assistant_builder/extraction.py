import json
import os
from pathlib import Path
import subprocess
import sys


class InvalidDocument(Exception):
    pass


def extract_text(content: bytes, file_format: str) -> str:
    # Only OS essentials: never forward DB/provider/Storage secrets to the parser.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH'}}
    try:
        result = subprocess.run(
            [sys.executable, '-I', str(Path(__file__).with_name('document_worker.py')), file_format],
            input=content, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=env, timeout=30, check=False)
        if result.returncode != 0:
            raise InvalidDocument()
        return json.loads(result.stdout)['text']
    except (subprocess.TimeoutExpired, OSError, ValueError, KeyError):
        raise InvalidDocument() from None
