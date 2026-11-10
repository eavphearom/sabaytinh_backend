# Public Web Home APIs

All three endpoints accept unauthenticated GET requests and use the existing
ApiResponse envelopes. No database columns, order/payment behavior, or admin
catalog behavior changed. The previously empty web/catalog_routes.py now owns
these routes and is registered by the Flask factory.

## Products

`GET /api/v1/web/home/products`

| Parameter | Behavior |
| --- | --- |
| page_no | 1-based, default 1 |
| per_page | 1–100; default 10, or 15 for type=new |
| type | Optional `new`; unsupported values return 400 |
| search | Case-insensitive literal substring of name, code or slug |
| category_id / brand_id | Positive IDs; both may be combined |
| price_sort | `asc` or `desc` |
| min_price / max_price | Inclusive nonnegative bounds on minimum active variant price |

Product visibility uses the existing is_active=true and is_deleted=false flags.
There is no separate publication flag in the model. No new stock-quantity or
parent-category availability rule is introduced. Price is MIN(price) over active,
nondeleted variants; deleted/inactive variants never contribute. A product with
no such variants has price=null, sorts after priced products, and is excluded
when a price bound is supplied. Multiple variants do not duplicate products.

Default ordering is created_at DESC, id DESC. With type=new, filters are applied
first, the newest 15 matches are selected, and this capped dataset is paginated;
the reported total is at most 15. type=new with price_sort returns 400 because
price ordering conflicts with the required newest-first ordering. Normal price
sorting uses newest-first/ID-descending tie-breakers. include_deleted=true is
rejected. Admin sort/filter arguments cannot expose inactive/deleted products.

Each item reuses ProductResponseSchema fields (id, category_id, brand_id, unit_id,
code, name, slug, description, is_active, created_at, updated_at), adding price
and image. Price is a Decimal string retaining the variant model's five decimal
places. Image uses FileUtil and selects a nondeleted image from active variants,
preferring the default variant then variant ID, and primary image then image ID.
It may be null. The representative image need not belong to the cheapest variant.
Costs, authentication information and inventory internals are not returned.

The response has the existing error/status/message/data envelope plus pagination:
per_page, total, total_page and page_no. Empty results return 200 with data=[],
total=0 and total_page=0. A page beyond the last is also 200 with data=[] and
unchanged total. Invalid supported filters/pagination return 400.

Products use two SQL queries (count and page) including aggregate pricing and
image selection, with no per-product lazy-loading queries.

## Banners

`GET /api/v1/web/home/banners`

Returns all active, nondeleted banners ordered by ID ASC, using the existing
BannerResponseSchema and FileUtil image URLs. No pagination or new display-order
column. Empty results are 200 with data=[]. One database query is used.

## Product detail

`GET /api/v1/web/home/products/{id}` returns ApiResponse.success with product data.
IDs must be positive ASCII integers within PostgreSQL bigint range; malformed,
zero, negative, fractional or oversized IDs return 400. A valid ID referencing
a missing, inactive or soft-deleted product returns 404.

The DTO extends the existing public product fields with brand_name,
category_name and variants. These fields match the inspected React
website/src/pages/product/ProductDetail.jsx contract. Inactive/deleted parent
brand/category names are omitted as null, without introducing a different
product-publication rule from the list endpoint.

Each variant contains id, product_id, color_id, color_name, color_hex, sku_prefix,
price, is_default, is_active, total_stock, stock_status, images and **stock**
(singular, as consumed by React). Only active, nondeleted variants with active,
nondeleted colors are included; default variants sort first, then ID ascending.
Price strings preserve five decimal places. Images contain id, variant_id,
image URL and is_primary, with primary images first; deleted images are excluded.

Each stock entry contains id, variant_stock_id, variant_id, size_id, size
(the Size.value label), size_name, unit_id, sku, qty and stock_status. Deleted
stock rows and inactive/deleted sizes are excluded. The id and variant_stock_id
identify the same row, supporting both existing stock IDs and checkout payloads.
Costs, audit-user fields and internal low-stock thresholds are not exposed.

Per-size status reuses StockStatus.from_quantity; variant totals sum the included
stock rows and report IN_STOCK or OUT_OF_STOCK. Zero-stock options remain visible
for the frontend's disabled selections. An active product with no visible
variants remains displayable with variants=[], price=null, image=null, consistent
with the existing list endpoint. Product visibility uses its active/deleted
flags; zero inventory does not unpublish a product. Availability can change after
this read; checkout remains authoritative and is unchanged.

Queries are bounded: one product query with joined brand/category, one variants
query with colors, one images query and one stocks query with sizes. No query
is issued per variant/size. Missing products stop after the first query, and
products without visible variants stop after the second.

## Hoppscotch examples

Set `base_url` to your local Flask origin, normally `http://127.0.0.1:5000`.
Authorization: **None**. Request body: **None**. All examples below expect 200;
data depends on the existing catalog.

```text
GET <<base_url>>/api/v1/web/home/products?page_no=1&per_page=10
GET <<base_url>>/api/v1/web/home/products?type=new
GET <<base_url>>/api/v1/web/home/products?type=new&page_no=2&per_page=5&category_id=1
GET <<base_url>>/api/v1/web/home/products?search=shoe&category_id=1&brand_id=1&min_price=10&max_price=100&price_sort=asc
GET <<base_url>>/api/v1/web/home/products?price_sort=desc&page_no=1&per_page=20
GET <<base_url>>/api/v1/web/home/products/1
GET <<base_url>>/api/v1/web/home/banners
```

Expect 400 for type=new&price_sort=asc, min_price=100&max_price=10, page_no=0,
per_page=101, nonnumeric IDs or unsupported type/price_sort values.

The Spring source found at D:/react vite/shoes project/backend did not contain
Home/Product/Banner endpoints. Exact Spring DTO parity could not be established;
the implementation uses existing Flask schemas and the user's confirmed minimum
price, newest-15 and banner-order rules.

Tests: tests/test_web_home.py. PostgreSQL tests reuse the existing disposable
schema fixture, with CHECKOUT_TEST_DATABASE_URL configured. They never modify
the development database's public tables.
