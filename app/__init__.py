
from flask import Flask
from sqlalchemy import text

from app.config import Config
from app.extensions import db, migrate, jwt
from app.common.api_response import success_response
from app.exceptions.handlers import register_error_handlers
# Register SQLAlchemy models
import app.models
from flask import send_from_directory
from flask import Flask, send_from_directory
from flask_cors import CORS
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.json.sort_keys = False

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    
    from app.security.jwt_utils import register_jwt_handlers
    register_jwt_handlers(jwt)
    from app.seeders.admin_seeder import seed_admin
    app.cli.add_command(seed_admin)

    # Global exception handling
    register_error_handlers(app)
    
    # Catalog: Category
    from app.routes.v1.admin.category_routes import category_bp
    app.register_blueprint(category_bp)
    
    # Catalog: Brand
    from app.routes.v1.admin.brand_routes import brand_bp
    app.register_blueprint(brand_bp)
    # Catalog: Color
    from app.routes.v1.admin.color_routes import color_bp
    
    # Catalog: Size
    from app.routes.v1.admin.size_routes import size_bp
    app.register_blueprint(size_bp)
    # Catalog: Banner
    from app.routes.v1.admin.banner_routes import banner_bp
    app.register_blueprint(banner_bp)
    
    app.register_blueprint(color_bp)
    # Register authentication routes
    from app.routes.v1.auth import auth_bp
    app.register_blueprint(auth_bp)

    @app.get("/api/v1/health")
    def health():
        return success_response(
            data={"service": "e-commerce-flask-api"},
            message="API is running"
        )

    @app.get("/api/v1/health/db")
    def database_health():
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return success_response(
            data={"database": "connected"},
            message="PostgreSQL connection successful"
        )
    # Serve uploaded images
    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(
            app.config["UPLOAD_FOLDER"],
            filename
        )
    
    @app.cli.command("seed_units")
    def seed_units():
        from app.seeders.unit_seeder import UnitSeeder

        created = UnitSeeder.seed()

        if created:
            print("PAIR unit seeded successfully")
        else:
            print("PAIR unit already exists")
    # Catalog: Product
    from app.routes.v1.admin.product_routes import product_bp
    app.register_blueprint(product_bp)
    from app.routes.v1.admin.product_unit_routes import product_unit_bp

    app.register_blueprint(product_unit_bp)
    
    # Product Variants and Inventory
    from app.routes.v1.admin.variant_routes import variant_bp
    from app.routes.v1.admin.variant_image_routes import image_bp
    from app.routes.v1.admin.variant_stock_routes import stock_bp
    from app.routes.v1.admin.stock_movement_routes import movement_bp

    app.register_blueprint(variant_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(movement_bp)
    from app.routes.v1.admin.product_routes import product_bp

    from app.routes.v1.user_profile_routes import user_profile_bp

    app.register_blueprint(user_profile_bp)
    from app.routes.v1.admin.delivery_method_routes import (
    admin_delivery_method_bp,
)
    from app.routes.v1.web.delivery_method_routes import (
        web_delivery_method_bp,
    )
    from app.models.delivery_method import DeliveryMethod
    app.register_blueprint(admin_delivery_method_bp)
    app.register_blueprint(web_delivery_method_bp)
    from app.routes.v1.web.catalog_routes import web_home_bp
    app.register_blueprint(web_home_bp)
    from app.routes.v1.admin.general_setting_routes import admin_setting_bp
    from app.routes.v1.web.general_setting_routes import web_setting_bp
    app.register_blueprint(admin_setting_bp)
    app.register_blueprint(web_setting_bp)
    from app.routes.v1.web.account_routes import web_account_bp
    app.register_blueprint(web_account_bp)
    from app.routes.v1.web.order_routes import web_order_bp
    from app.routes.v1.admin.order_routes import admin_order_bp
    from app.routes.v1.payway_callback_routes import register_payway_callback
    app.register_blueprint(web_order_bp)
    app.register_blueprint(admin_order_bp)
    from app.routes.v1.admin.customer_routes import admin_customer_bp
    app.register_blueprint(admin_customer_bp)
    from app.routes.v1.admin.user_routes import admin_user_bp
    app.register_blueprint(admin_user_bp)
    from app.routes.v1.admin.dashboard_routes import admin_dashboard_bp
    app.register_blueprint(admin_dashboard_bp)
    register_payway_callback(app)
    
    


    CORS(app, resources={
        r"/api/*": {
            "origins": [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
            ]
        }
    })
        

    return app




