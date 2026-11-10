
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from app.exceptions.api_exception import BadRequestException


ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def save_image(file, directory="categories"):
    """Validate and save an uploaded image."""
    if not file or not file.filename:
        raise BadRequestException("Image file is required")

    filename = secure_filename(file.filename)
    extension = Path(filename).suffix.lower().lstrip(".")

    if extension not in ALLOWED_EXTENSIONS:
        raise BadRequestException("Invalid image format")

    new_filename = f"{uuid4().hex}.{extension}"

    upload_dir = (
        Path(current_app.instance_path)
        / "uploads"
        / directory
    )
    upload_dir.mkdir(parents=True, exist_ok=True)

    file.save(upload_dir / new_filename)

    return f"{directory}/{new_filename}"
