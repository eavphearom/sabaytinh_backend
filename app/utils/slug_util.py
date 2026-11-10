
import re


class SlugUtil:

    @staticmethod
    def generate(name: str) -> str:
        # Lowercase, replace spaces with underscores.
        slug = name.strip().lower()
        slug = re.sub(r"\s+", "_", slug)

        return slug
