
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.enums.image_directory import ImageDirectory
from app.exceptions.api_exception import BadRequestException
from flask import request

class FileUtil:
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

    # Recognize actual image file signatures.
    @staticmethod
    def _extension(content: bytes):
        if content.startswith(b"\xff\xd8\xff"):
            return ".jpg"

        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return ".png"

        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return ".webp"

        return None

    @staticmethod
    def save_image(file: FileStorage, directory: ImageDirectory):
        if not isinstance(directory, ImageDirectory):
            raise BadRequestException("Invalid image directory")

        if not file or not file.filename:
            raise BadRequestException("Image file is required")

        extension = Path(file.filename).suffix.lower()

        if extension not in FileUtil.ALLOWED_EXTENSIONS:
            raise BadRequestException("Unsupported image format")

        # Limit the upload to 5 MB.
        content = file.stream.read(5 * 1024 * 1024 + 1)

        if len(content) > 5 * 1024 * 1024:
            raise BadRequestException("Image must not exceed 5 MB")

        detected = FileUtil._extension(content)

        if detected is None:
            raise BadRequestException("Invalid image content")

        # JPG and JPEG are equivalent extensions.
        if extension == ".jpeg":
            extension = ".jpg"

        if detected != extension:
            raise BadRequestException("Image extension does not match content")

        upload_root = Path(current_app.config["UPLOAD_FOLDER"])
        folder = upload_root / directory.value
        folder.mkdir(parents=True, exist_ok=True)

        filename = f"{uuid.uuid4().hex}{extension}"
        destination = folder / filename

        destination.write_bytes(content)

        # Store a relative public path in PostgreSQL.
        return f"/uploads/{directory.value}/{filename}"

    
    @staticmethod
    def delete_image(image_path: str | None):
        if not image_path or not image_path.startswith("/uploads/"):
            return

        relative = image_path.removeprefix("/uploads/")
        root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
        destination = (root / relative).resolve()

        if not destination.is_relative_to(root):
            return

        if destination.is_file():
            destination.unlink()

    @staticmethod
    def get_image_url(image_path):
        """Convert relative image path to full URL."""
        if not image_path:
            return None

        if image_path.startswith(("http://", "https://")):
            return image_path

        return (
            f"{request.host_url.rstrip('/')}/"
            f"{image_path.lstrip('/')}"
        )



