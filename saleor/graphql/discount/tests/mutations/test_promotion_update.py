from datetime import timedelta
from unittest.mock import patch

import graphene
from django.utils import timezone
from freezegun import freeze_time

from .....discount import PromotionEvents
from .....discount.error_codes import PromotionCreateErrorCode
from .....discount.models import PromotionEvent
from ....tests.utils import assert_no_permission, get_graphql_content

PROMOTION_UPDATE_MUTATION = """
    mutation promotionUpdate($id: ID!, $input: PromotionUpdateInput!) {
        promotionUpdate(id: $id, input: $input) {
            promotion {
                id
                name
                description
                startDate
                endDate
                createdAt
                updatedAt
                events {
                    ... on ObjectEvent {
                        type
                    }
                    ... on PromotionRuleEvent {
                        ruleId
                    }
                }
            }
            errors {
                field
                code
                message
            }
        }
    }
"""


@freeze_time("2020-03-18 12:00:00")
@patch("saleor.product.tasks.update_products_discounted_prices_of_promotion_task.delay")
@patch("saleor.plugins.manager.PluginsManager.promotion_started")
@patch("saleor.plugins.manager.PluginsManager.promotion_updated")
def test_promotion_update_by_staff_user(
    promotion_updated_mock,
    promotion_started_mock,
    update_products_discounted_prices_of_promotion_task_mock,
    staff_api_client,
    permission_group_manage_discounts,
    promotion,
):
    # given
    permission_group_manage_discounts.user_set.add(staff_api_client.user)
    start_date = timezone.now() - timedelta(days=1)
    end_date = timezone.now() + timedelta(days=10)

    new_promotion_name = "new test promotion"
    variables = {
        "id": graphene.Node.to_global_id("Promotion", promotion.id),
        "input": {
            "name": new_promotion_name,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
    }

    # when
    response = staff_api_client.post_graphql(PROMOTION_UPDATE_MUTATION, variables)

    # then
    content = get_graphql_content(response)
    data = content["data"]["promotionUpdate"]
    promotion_data = data["promotion"]

    assert not data["errors"]
    assert promotion_data["name"] == new_promotion_name
    assert promotion_data["description"] == promotion.description
    assert promotion_data["startDate"] == start_date.isoformat()
    assert promotion_data["endDate"] == end_date.isoformat()
    assert promotion_data["createdAt"] == promotion.created_at.isoformat()
    assert promotion_data["updatedAt"] == timezone.now().isoformat()

    promotion.refresh_from_db()
    assert promotion.last_notification_scheduled_at == timezone.now()

    promotion_updated_mock.assert_called_once_with(promotion)
    promotion_started_mock.assert_called_once_with(promotion)
    update_products_discounted_prices_of_promotion_task_mock.assert_called_once_with(
        promotion.id
    )


@freeze_time("2020-03-18 12:00:00")
@patch("saleor.product.tasks.update_products_discounted_prices_of_promotion_task.delay")
@patch("saleor.plugins.manager.PluginsManager.promotion_ended")
@patch("saleor.plugins.manager.PluginsManager.promotion_updated")
def test_promotion_update_by_app(
    promotion_updated_mock,
    promotion_ended_mock,
    update_products_discounted_prices_of_promotion_task_mock,
    app_api_client,
    permission_manage_discounts,
    promotion,
):
    # given
    promotion.end_date = None
    promotion.save(update_fields=["end_date"])

    start_date = timezone.now() - timedelta(days=10)
    end_date = timezone.now() - timedelta(days=2)

    new_promotion_name = "new test promotion"
    variables = {
        "id": graphene.Node.to_global_id("Promotion", promotion.id),
        "input": {
            "name": new_promotion_name,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
    }

    # when
    response = app_api_client.post_graphql(
        PROMOTION_UPDATE_MUTATION, variables, permissions=(permission_manage_discounts,)
    )

    # then
    content = get_graphql_content(response)
    data = content["data"]["promotionUpdate"]
    promotion_data = data["promotion"]

    assert not data["errors"]
    assert promotion_data["name"] == new_promotion_name
    assert promotion_data["description"] == promotion.description
    assert promotion_data["startDate"] == start_date.isoformat()
    assert promotion_data["endDate"] == end_date.isoformat()
    assert promotion_data["createdAt"] == promotion.created_at.isoformat()
    assert promotion_data["updatedAt"] == timezone.now().isoformat()

    promotion_updated_mock.assert_called_once_with(promotion)
    promotion_ended_mock.assert_called_once_with(promotion)
    update_products_discounted_prices_of_promotion_task_mock.assert_called_once_with(
        promotion.id
    )


@freeze_time("2020-03-18 12:00:00")
@patch("saleor.product.tasks.update_products_discounted_prices_of_promotion_task.delay")
@patch("saleor.plugins.manager.PluginsManager.promotion_started")
@patch("saleor.plugins.manager.PluginsManager.promotion_ended")
@patch("saleor.plugins.manager.PluginsManager.promotion_updated")
def test_promotion_update_dates_dont_change(
    promotion_updated_mock,
    promotion_started_mock,
    promotion_ended_mock,
    update_products_discounted_prices_of_promotion_task_mock,
    staff_api_client,
    permission_group_manage_discounts,
    promotion,
):
    # given
    permission_group_manage_discounts.user_set.add(staff_api_client.user)
    promotion.last_notification_scheduled_at = timezone.now() - timedelta(hours=1)
    promotion.save(update_fields=["last_notification_scheduled_at"])

    previous_notification_date = promotion.last_notification_scheduled_at

    new_promotion_name = "new test promotion"
    variables = {
        "id": graphene.Node.to_global_id("Promotion", promotion.id),
        "input": {
            "name": new_promotion_name,
        },
    }

    # when
    response = staff_api_client.post_graphql(PROMOTION_UPDATE_MUTATION, variables)

    # then
    content = get_graphql_content(response)
    data = content["data"]["promotionUpdate"]
    promotion_data = data["promotion"]

    assert not data["errors"]
    assert promotion_data["name"] == new_promotion_name
    assert promotion_data["description"] == promotion.description
    assert promotion_data["startDate"] == promotion.start_date.isoformat()
    assert promotion_data["endDate"] == promotion.end_date.isoformat()
    assert promotion_data["createdAt"] == promotion.created_at.isoformat()
    assert promotion_data["updatedAt"] == timezone.now().isoformat()

    promotion.refresh_from_db()
    assert promotion.last_notification_scheduled_at == previous_notification_date

    promotion_updated_mock.assert_called_once_with(promotion)
    promotion_started_mock.assert_not_called()
    promotion_ended_mock.assert_not_called()
    update_products_discounted_prices_of_promotion_task_mock.assert_not_called()


@freeze_time("2020-03-18 12:00:00")
@patch("saleor.product.tasks.update_products_discounted_prices_of_promotion_task.delay")
@patch("saleor.plugins.manager.PluginsManager.promotion_started")
@patch("saleor.plugins.manager.PluginsManager.promotion_ended")
@patch("saleor.plugins.manager.PluginsManager.promotion_updated")
def test_promotion_update_by_customer(
    promotion_updated_mock,
    promotion_started_mock,
    promotion_ended_mock,
    update_products_discounted_prices_of_promotion_task_mock,
    api_client,
    promotion,
):
    # given
    start_date = timezone.now() + timedelta(days=1)
    end_date = timezone.now() + timedelta(days=10)

    new_promotion_name = "new test promotion"
    variables = {
        "id": graphene.Node.to_global_id("Promotion", promotion.id),
        "input": {
            "name": new_promotion_name,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
    }

    # when
    response = api_client.post_graphql(PROMOTION_UPDATE_MUTATION, variables)

    # then
    assert_no_permission(response)

    promotion_updated_mock.assert_not_called()
    promotion_started_mock.assert_not_called()
    promotion_ended_mock.assert_not_called()
    update_products_discounted_prices_of_promotion_task_mock.assert_not_called()


@freeze_time("2020-03-18 12:00:00")
def test_promotion_update_end_date_before_start_date(
    staff_api_client, permission_group_manage_discounts, description_json, promotion
):
    # given
    permission_group_manage_discounts.user_set.add(staff_api_client.user)
    start_date = timezone.now() + timedelta(days=1)
    end_date = timezone.now() - timedelta(days=10)

    new_promotion_name = "new test promotion"
    variables = {
        "id": graphene.Node.to_global_id("Promotion", promotion.id),
        "input": {
            "name": new_promotion_name,
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        },
    }

    # when
    response = staff_api_client.post_graphql(PROMOTION_UPDATE_MUTATION, variables)

    # then
    content = get_graphql_content(response)
    data = content["data"]["promotionUpdate"]
    errors = data["errors"]

    assert not data["promotion"]
    assert len(errors) == 1
    assert errors[0]["code"] == PromotionCreateErrorCode.INVALID.name
    assert errors[0]["field"] == "endDate"


def test_promotion_update_events(
    staff_api_client, permission_group_manage_discounts, promotion
):
    # given
    permission_group_manage_discounts.user_set.add(staff_api_client.user)
    new_promotion_name = "new test promotion"
    variables = {
        "id": graphene.Node.to_global_id("Promotion", promotion.id),
        "input": {
            "name": new_promotion_name,
        },
    }
    event_count = PromotionEvent.objects.count()

    # when
    response = staff_api_client.post_graphql(PROMOTION_UPDATE_MUTATION, variables)

    # then
    content = get_graphql_content(response)
    data = content["data"]["promotionUpdate"]
    assert not data["errors"]

    events = data["promotion"]["events"]
    assert len(events) == 1
    assert PromotionEvent.objects.count() == event_count + 1
    assert PromotionEvents.PROMOTION_UPDATED == events[0]["type"]