import pytest

from .. import DEFAULT_ADDRESS
from ..product.utils.preparing_product import prepare_product
from ..shop.utils.preparing_shop import prepare_shop
from ..utils import assign_permissions
from ..vouchers.utils import create_voucher, create_voucher_channel_listing, get_voucher
from .utils import (
    draft_order_create,
    draft_order_delete,
    draft_order_update,
    order_query,
)


def prepare_voucher(
    e2e_staff_api_client,
    channel_id,
    voucher_code,
    voucher_discount_type,
    voucher_discount_value,
    voucher_type,
):
    input = {
        "code": voucher_code,
        "discountValueType": voucher_discount_type,
        "type": voucher_type,
    }
    voucher_data = create_voucher(e2e_staff_api_client, input)

    voucher_id = voucher_data["id"]
    channel_listing = [
        {
            "channelId": channel_id,
            "discountValue": voucher_discount_value,
        },
    ]
    create_voucher_channel_listing(
        e2e_staff_api_client,
        voucher_id,
        channel_listing,
    )

    return voucher_code, voucher_id, voucher_discount_value


@pytest.mark.e2e
def test_voucher_should_be_released_upon_draft_order_deletion_CORE_0922(
    e2e_staff_api_client,
    permission_manage_products,
    permission_manage_channels,
    permission_manage_product_types_and_attributes,
    permission_manage_shipping,
    permission_manage_orders,
    permission_manage_discounts,
    permission_manage_checkouts,
):
    # Before
    permissions = [
        permission_manage_products,
        permission_manage_channels,
        permission_manage_shipping,
        permission_manage_product_types_and_attributes,
        permission_manage_orders,
        permission_manage_discounts,
        permission_manage_checkouts,
    ]
    assign_permissions(e2e_staff_api_client, permissions)

    price = 10

    (
        warehouse_id,
        channel_id,
        _channel_slug,
        shipping_method_id,
    ) = prepare_shop(e2e_staff_api_client)

    (
        _product_id,
        product_variant_id,
        product_variant_price,
    ) = prepare_product(
        e2e_staff_api_client,
        warehouse_id,
        channel_id,
        price,
    )

    voucher_code, voucher_id, voucher_discount_value = prepare_voucher(
        e2e_staff_api_client,
        channel_id,
        voucher_code="PERCENTAGE_VOUCHER",
        voucher_discount_type="PERCENTAGE",
        voucher_discount_value=10,
        voucher_type="ENTIRE_ORDER",
    )

    # Step 1 - Create draft order
    draft_order_input = {
        "channelId": channel_id,
        "userEmail": "test_user@test.com",
        "lines": [{"variantId": product_variant_id, "quantity": 2}],
        "shippingAddress": DEFAULT_ADDRESS,
        "billingAddress": DEFAULT_ADDRESS,
        "voucherCode": voucher_code,
    }
    data = draft_order_create(
        e2e_staff_api_client,
        draft_order_input,
    )
    order_id = data["order"]["id"]
    assert order_id is not None
    order_line = data["order"]["lines"][0]
    shipping_method_id = data["order"]["shippingMethods"][0]["id"]
    unit_price = float(product_variant_price)
    assert data["order"]["isShippingRequired"] is True
    total_gross = data["order"]["total"]["gross"]["amount"]
    assert order_line["undiscountedUnitPrice"]["gross"]["amount"] == unit_price
    # discounted_unit_price = order_line["unitPrice"]["gross"]["amount"]
    # undiscounted_total_gross = data["order"]["undiscountedTotal"]["gross"]["amount"]
    # voucher_discount = 2 * (round(unit_price * 10 / 100, 2))
    # assert discounted_unit_price == unit_price - voucher_discount
    assert data["order"]["voucher"]["discountValue"] == voucher_discount_value
    # assert total_gross == undiscounted_total_gross - voucher_discount
    # assert discounted_unit_price == unit_price - (
    #     round(float(product_variant_price) * 10 / 100, 2)
    # )

    # Step 2 - Add a shipping method to the order
    input_data = {"shippingMethod": shipping_method_id}
    draft_update = draft_order_update(
        e2e_staff_api_client,
        order_id,
        input_data,
    )

    order_shipping_id = draft_update["order"]["deliveryMethod"]["id"]
    assert order_shipping_id is not None
    shipping_price = draft_update["order"]["shippingPrice"]["gross"]["amount"]

    # Step 3 - Delete the order
    cancelled_order = draft_order_delete(
        e2e_staff_api_client,
        order_id,
    )
    assert cancelled_order["order"]["status"] is not None
    order = order_query(e2e_staff_api_client, order_id)
    assert order is None

    # Step 3 - Check the voucher has been released
    voucher_data = get_voucher(e2e_staff_api_client, voucher_id)
    assert voucher_data["voucher"]["id"] == voucher_id
    assert voucher_data["voucher"]["codes"]["edges"][0]["node"]["used"] == 0
    assert voucher_data["voucher"]["codes"]["edges"][0]["node"]["isActive"] is True
