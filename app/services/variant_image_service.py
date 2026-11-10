import logging
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.variant_image import VariantImage
from app.repositories.variant_image_repository import VariantImageRepository
from app.repositories.variant_repository import VariantRepository
from app.schemas.variant_image_schema import VariantImageResponseSchema
from app.enums.image_directory import ImageDirectory
from app.utils.file_util import FileUtil
from app.utils.date_util import DateUtil
from app.exceptions.api_exception import BadRequestException, ResourceNotFoundException
log=logging.getLogger(__name__)
class VariantImageService:
    def __init__(self):
        self.repo=VariantImageRepository();self.variants=VariantRepository();self.schema=VariantImageResponseSchema()
    def _variant(self, variant_id):
        if self.variants.find_by_id(variant_id) is None: raise ResourceNotFoundException("Variant not found")
    def list_by_variant(self,variant_id):
        self._variant(variant_id)
        return self.schema.dump(self.repo.by_variant(variant_id),many=True)
    def create(self,variant_id,data,image_file,user_id):
        self._variant(variant_id)
        if not image_file or not image_file.filename: raise BadRequestException("Image is required")
        path=None
        try:
            # Lock variant row to serialize concurrent primary-image decisions.
            from app.models.variant import Variant
            db.session.scalar(select(Variant.id).where(Variant.id==variant_id).with_for_update())
            current=db.session.scalar(select(VariantImage).where(VariantImage.variant_id==variant_id,VariantImage.is_primary.is_(True),VariantImage.is_deleted.is_(False)))
            if data.get('is_primary') and current:
                current.is_primary=False;current.updated_at=DateUtil.now();current.update_uid=user_id
                db.session.flush()
            path=FileUtil.save_image(image_file,ImageDirectory.PRODUCT)
            row=VariantImage(variant_id=variant_id,image=path,is_primary=data.get('is_primary',False),created_at=DateUtil.now(),create_uid=user_id)
            db.session.add(row);db.session.flush();result=self.schema.dump(row);db.session.commit();return result
        except Exception:
            db.session.rollback()
            if path:
                try: FileUtil.delete_image(path)
                except OSError: log.exception("Image cleanup failed")
            raise
    def set_primary(self,variant_id,image_id,user_id):
        self._variant(variant_id)
        try:
            from app.models.variant import Variant
            db.session.scalar(select(Variant.id).where(Variant.id==variant_id).with_for_update())
            row=self.repo.find_by_id(image_id)
            if row is None or row.variant_id!=variant_id: raise ResourceNotFoundException("Variant image not found")
            old=db.session.scalar(select(VariantImage).where(VariantImage.variant_id==variant_id,VariantImage.is_primary.is_(True),VariantImage.is_deleted.is_(False)))
            if old and old.id!=row.id:
                old.is_primary=False;old.updated_at=DateUtil.now();old.update_uid=user_id;db.session.flush()
            row.is_primary=True;row.updated_at=DateUtil.now();row.update_uid=user_id
            db.session.flush();result=self.schema.dump(row);db.session.commit();return result
        except Exception:
            db.session.rollback();raise
    def delete(self,variant_id,image_id,user_id):
        self._variant(variant_id)
        row=self.repo.find_by_id(image_id)
        if row is None or row.variant_id!=variant_id: raise ResourceNotFoundException("Variant image not found")
        try:
            self.repo.soft_delete_by_id(image_id,deleted_uid=user_id)
            db.session.commit()
        except Exception:
            db.session.rollback();raise
        # Preserve file on disk for soft-delete restore.
