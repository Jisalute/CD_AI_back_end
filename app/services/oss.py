from pathlib import Path
from datetime import datetime


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "doc" / "template"
ESSAY_DIR = Path(__file__).resolve().parents[2] / "doc" / "essay"
ATTACHMENT_DIR = Path(__file__).resolve().parents[2] / "doc" / "attachment"
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
ESSAY_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_oss(filename: str, content: bytes) -> str:
    """Store template content under doc/template and return local path key."""
    safe_name = Path(filename).name
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{ts}_{safe_name}"
    stored_path = TEMPLATE_DIR / stored_name
    stored_path.write_bytes(content)
    return str(stored_path)


def upload_paper_to_storage(filename: str, content: bytes) -> str:
    """Store paper content under doc/essay and return local path key."""
    safe_name = Path(filename).name
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{ts}_{safe_name}"
    stored_path = ESSAY_DIR / stored_name
    stored_path.write_bytes(content)
    return str(stored_path)


def upload_attachment_to_storage(filename: str, content: bytes) -> str:
    """Store material content under doc/attachment and return local path key."""
    safe_name = Path(filename).name
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{ts}_{safe_name}"
    stored_path = ATTACHMENT_DIR / stored_name
    stored_path.write_bytes(content)
    return str(stored_path)
