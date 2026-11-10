
import re

from flask import request

from app.exceptions.api_exception import BadRequestException
from app.schemas.product_schema import ProductRequestSchema


class ProductRequestMapper:

    KEY_PATTERN = re.compile(
        r"([^\[\].]+)|\[(\d+)\]|\[([^\]]+)\]"
    )

    @staticmethod
    def _normalize_key(key):
        parts = []

        for match in ProductRequestMapper.KEY_PATTERN.finditer(key):
            part = next(
                value for value in match.groups()
                if value is not None
            )

            if not part.isdigit():
                part = re.sub(
                    r"(?<!^)(?=[A-Z])", "_", part
                ).lower()

            parts.append(part)

        if not parts:
            raise BadRequestException("Invalid form field")

        return parts

    @staticmethod
    def _assign(data, parts, value):
        current = data

        for i, part in enumerate(parts):
            is_last = i == len(parts) - 1
            next_is_list = (
                not is_last and parts[i + 1].isdigit()
            )

            if isinstance(current, list):
                if not part.isdigit():
                    raise BadRequestException(
                        "Invalid form structure"
                    )

                index = int(part)

                if index > 1000:
                    raise BadRequestException(
                        "Too many form items"
                    )

                while len(current) <= index:
                    current.append(None)

                if is_last:
                    if current[index] is not None:
                        raise BadRequestException(
                            "Duplicate form field"
                        )
                    current[index] = value
                else:
                    if current[index] is None:
                        current[index] = (
                            [] if next_is_list else {}
                        )
                    current = current[index]

            else:
                if part.isdigit():
                    raise BadRequestException(
                        "Invalid form structure"
                    )

                if is_last:
                    if part in current:
                        raise BadRequestException(
                            "Duplicate form field"
                        )
                    current[part] = value
                else:
                    if part not in current:
                        current[part] = (
                            [] if next_is_list else {}
                        )
                    current = current[part]

    @staticmethod
    def _validate_structure(value):
        if isinstance(value, list):
            if any(item is None for item in value):
                raise BadRequestException(
                    "Form indexes must be continuous"
                )

            for item in value:
                ProductRequestMapper._validate_structure(item)

        elif isinstance(value, dict):
            for item in value.values():
                ProductRequestMapper._validate_structure(item)

    @staticmethod
    def parse():
        if request.mimetype != "multipart/form-data":
            raise BadRequestException(
                "Product requires multipart/form-data"
            )

        data = {}

        # Parse regular form fields
        for key, value in request.form.items(multi=True):
            parts = ProductRequestMapper._normalize_key(key)

            if parts[-1] == "image":
                raise BadRequestException(
                    "Image must be uploaded as a file"
                )

            ProductRequestMapper._assign(
                data, parts, value
            )

        # Attach uploaded files to their nested image entries
        for key, file in request.files.items(multi=True):
            parts = ProductRequestMapper._normalize_key(key)

            if (
                len(parts) != 5
                or parts[0] != "variants"
                or not parts[1].isdigit()
                or parts[2] != "images"
                or not parts[3].isdigit()
                or parts[4] != "image"
            ):
                raise BadRequestException(
                    "Invalid variant image field"
                )

            if not file.filename:
                raise BadRequestException(
                    "Uploaded image is required"
                )

            ProductRequestMapper._assign(
                data, parts, file
            )

        ProductRequestMapper._validate_structure(data)

        # Temporarily remove files before schema validation
        image_files = []

        for variant_index, variant in enumerate(
            data.get("variants", [])
        ):
            if not isinstance(variant, dict):
                raise BadRequestException(
                    "Invalid variant structure"
                )

            for image_index, image in enumerate(
                variant.get("images", [])
            ):
                if not isinstance(image, dict):
                    raise BadRequestException(
                        "Invalid image structure"
                    )

                uploaded_file = image.pop("image", None)

                if uploaded_file is not None:
                    image_files.append(
                        (variant_index, image_index, uploaded_file)
                    )

        validated = ProductRequestSchema().load(data)

        # Restore files after Marshmallow validation
        for variant_index, image_index, uploaded_file in image_files:
            validated["variants"][variant_index]["images"][
                image_index
            ]["image"] = uploaded_file

        return validated
