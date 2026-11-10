
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.unit import Unit
from app.repositories.product_repository import ProductRepository
from app.repositories.product_unit_repository import ProductUnitRepository
from app.models.product_unit import ProductUnit
from app.schemas.product_unit_schema import ProductUnitResponseSchema
from app.exceptions.api_exception import (
    BadRequestException,
    DuplicateException,
    ResourceNotFoundException,
)
from app.utils.date_util import DateUtil


class ProductUnitService:

    def __init__(self):
        self.repository = ProductUnitRepository()
        self.product_repository = ProductRepository()
        self.schema = ProductUnitResponseSchema()

    def _get_product(self, product_id):
        product = self.product_repository.find_by_id(product_id)

        if product is None:
            raise ResourceNotFoundException("Product not found")

        return product

    def _validate_multiplier(self, value):
        multiplier = Decimal(value)

        if multiplier <= 0:
            raise BadRequestException(
                "Multiplier must be greater than zero"
            )

        if multiplier > Decimal("99999.99999"):
            raise BadRequestException("Multiplier is too large")

        if multiplier != multiplier.quantize(Decimal("0.00001")):
            raise BadRequestException(
                "Multiplier supports up to 5 decimal places"
            )

        return multiplier

    # Get configured units for a product
    def get_by_product(self, product_id):
        self._get_product(product_id)

        units = self.repository.find_by_product(product_id)
        return self.schema.dump(units, many=True)

    # Add a unit to a product
    def create(self, product_id, data, user_id):
        product = self._get_product(product_id)

        unit_id = data["unit_id"]

        unit = db.session.get(Unit, unit_id)

        if unit is None or unit.is_deleted:
            raise BadRequestException("Unit not found")

        existing = self.repository.find_by_product_and_unit(
            product_id, unit_id
        )

        if existing:
            raise DuplicateException(
                "Unit is already configured for this product"
            )

        multiplier = self._validate_multiplier(
            data["multiplier"]
        )

        # Base unit must always have multiplier 1.
        if unit_id == product.unit_id and multiplier != 1:
            raise BadRequestException(
                "Base unit multiplier must be 1"
            )

        try:
            product_unit = ProductUnit(
                product_id=product_id,
                unit_id=unit_id,
                multiplier=multiplier,
                created_at=DateUtil.now(),
                create_uid=user_id
            )

            db.session.add(product_unit)
            db.session.flush()

            result = self.schema.dump(product_unit)
            db.session.commit()
            return result

        except IntegrityError as error:
            db.session.rollback()
            raise DuplicateException(
                "Product unit already exists"
            ) from error

        except Exception:
            db.session.rollback()
            raise

    # Update conversion multiplier
    def update(self, product_id, product_unit_id, data, user_id):
        product = self._get_product(product_id)

        product_unit = self.repository.find_by_id(
            product_unit_id
        )

        if (
            product_unit is None
            or product_unit.product_id != product_id
        ):
            raise ResourceNotFoundException(
                "Product unit not found"
            )

        multiplier = self._validate_multiplier(
            data["multiplier"]
        )

        if product_unit.unit_id == product.unit_id:
            if multiplier != 1:
                raise BadRequestException(
                    "Base unit multiplier must be 1"
                )

        try:
            product_unit.multiplier = multiplier
            product_unit.updated_at = DateUtil.now()
            product_unit.update_uid = user_id

            db.session.flush()
            result = self.schema.dump(product_unit)
            db.session.commit()

            return result

        except Exception:
            db.session.rollback()
            raise

    # Soft delete product unit
    def delete(self, product_id, product_unit_id, user_id):
        product = self._get_product(product_id)

        product_unit = self.repository.find_by_id(
            product_unit_id
        )

        if (
            product_unit is None
            or product_unit.product_id != product_id
        ):
            raise ResourceNotFoundException(
                "Product unit not found"
            )

        # Do not remove the product's base unit.
        if product_unit.unit_id == product.unit_id:
            raise BadRequestException(
                "Cannot delete the product base unit"
            )

        try:
            self.repository.soft_delete_by_id(
                product_unit_id,
                deleted_uid=user_id
            )
            db.session.commit()

        except Exception:
            db.session.rollback()
            raise
