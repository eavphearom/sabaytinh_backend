"""Request parsing tests; authentication remains covered by API integration tests."""
import importlib
import inspect
import unittest
from unittest.mock import patch

from flask import Flask, g
from werkzeug.datastructures import MultiDict

from app.common.filters import BaseFilter, pagination_params
from app.exceptions.api_exception import BadRequestException


class PaginationParameterTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_canonical_defaults_legacy_and_invalid_values(self):
        self.assertEqual(pagination_params(MultiDict()), (1, 10))
        for names in (("pageNo", "perPage"), ("page_no", "per_page")):
            self.assertEqual(pagination_params(MultiDict(zip(names, ("2", "7")))), (2, 7))
        for query in ("pageNo=0", "pageNo=x", "perPage=0", "perPage=101", "perPage=1.5",
                      "pageNo=2&pageNo=2", "perPage=2&perPage=3", "pageNo=2&page_no=2",
                      "perPage=2&per_page=2", "pageNo=999999999999999999999"):
            with self.subTest(query=query), self.app.test_request_context("/?" + query):
                with self.assertRaises(BadRequestException):
                    BaseFilter.from_request()

    def test_all_base_filter_routes_receive_camel_case_pagination(self):
        routes = [
            ("admin.banner_routes", "get_banners", "BannerService.get_paginated"),
            ("admin.brand_routes", "get_brands", "BrandService.get_paginated"),
            ("admin.category_routes", "get_categories", "CategoryService.get_paginated"),
            ("admin.color_routes", "get_colors", "ColorService.get_paginated"),
            ("admin.size_routes", "get_sizes", "SizeService.get_paginated"),
            ("admin.product_routes", "get_products", "ProductService.get_paginated"),
            ("admin.stock_movement_routes", "get_stock_movements", "StockMovementService.get_paginated"),
            ("admin.order_routes", "list_orders", "OrderService.get_paginated"),
            ("admin.customer_routes", "list_customers", "CustomerService.get_paginated"),
            ("web.order_routes", "history", "OrderService.get_customer_history"),
            ("web.account_routes", "orders", "WebAccountService.orders"),
            ("web.catalog_routes", "products", "WebHomeService.products"),
        ]
        for module_name, function, target in routes:
            module = importlib.import_module("app.routes.v1." + module_name)
            with self.subTest(route=module_name), self.app.test_request_context("/?pageNo=2&perPage=3&search=shoe"):
                g.customer_id = 1
                with patch("app.routes.v1." + module_name + "." + target,
                           return_value=dict(items=[], page_no=2, per_page=3, total=0, total_page=0)) as service:
                    response, status = inspect.unwrap(getattr(module, function))()
                    self.assertEqual(status, 200)
                    values = list(service.call_args.args) + list(service.call_args.kwargs.values())
                    filters = next(value for value in values if isinstance(value, BaseFilter))
                    self.assertEqual((filters.page_no, filters.per_page, filters.search), (2, 3, "shoe"))
                    self.assertEqual(response.json["pagination"]["per_page"], 3)

    def test_delivery_routes_and_defaults(self):
        for scope, function, default in (("admin", "list_methods", 10), ("web", "list_active_delivery_methods", 100)):
            module = importlib.import_module(f"app.routes.v1.{scope}.delivery_method_routes")
            for query, expected in (("", (1, default)), ("?pageNo=2&perPage=3", (2, 3))):
                with self.subTest(scope=scope, query=query), self.app.test_request_context("/" + query):
                    with patch.object(module.DeliveryMethodService, "get_paginated", return_value=dict(
                        items=[], page_no=expected[0], page_size=expected[1], total_items=0, total_pages=0)) as service:
                        inspect.unwrap(getattr(module, function))()
                        self.assertEqual(service.call_args.args[:2], expected)

    def test_new_products_respect_explicit_per_page(self):
        from app.routes.v1.web.catalog_routes import products, WebHomeService
        for query, size in (("type=new", 15), ("type=new&perPage=2", 2)):
            with self.app.test_request_context("/?" + query), patch.object(WebHomeService, "products",
                return_value=dict(items=[], page_no=1, per_page=size, total=0, total_page=0)) as service:
                products()
                self.assertEqual(service.call_args.args[0].per_page, size)
