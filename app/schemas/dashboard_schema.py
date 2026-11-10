from marshmallow import Schema, fields


class CountStatisticSchema(Schema):
    value = fields.Integer()
    current_month = fields.Integer()
    previous_month = fields.Integer()
    percentage_change = fields.Float(allow_none=True)


class RevenueStatisticSchema(Schema):
    currency = fields.String()
    value = fields.Decimal(places=2, as_string=True)
    current_month = fields.Decimal(places=2, as_string=True)
    previous_month = fields.Decimal(places=2, as_string=True)
    percentage_change = fields.Float(allow_none=True)


class InventoryStatisticSchema(Schema):
    value = fields.Integer()
    out_of_stock = fields.Integer()
    percentage_change = fields.Float(allow_none=True)


class DashboardOverviewSchema(Schema):
    total_revenue = fields.List(fields.Nested(RevenueStatisticSchema))
    orders = fields.Nested(CountStatisticSchema)
    customers = fields.Nested(CountStatisticSchema)
    low_stock = fields.Nested(InventoryStatisticSchema)
    metadata = fields.Dict()
