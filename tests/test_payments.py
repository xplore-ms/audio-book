from unittest.mock import patch


def test_get_price_quote(client):
    response = client.get("/api/v1/payments/quote?plan_id=starter&currency=NGN")
    assert response.status_code == 200
    data = response.json()
    assert data["plan_id"] == "starter"
    assert data["currency"] == "NGN"

    with patch("app.api.v1.payments.get_usd_to_ngn_rate", return_value=1500.0):
        response_usd = client.get("/api/v1/payments/quote?plan_id=starter&currency=USD")
        assert response_usd.status_code == 200
        data_usd = response_usd.json()
        assert data_usd["currency"] == "USD"


@patch("app.api.v1.payments.requests.post")
@patch("app.api.v1.payments.subscriptions_collection")
@patch("app.api.v1.payments.payments_collection")
def test_initiate_payment(mock_payments, mock_subscriptions, mock_requests, client):
    mock_subscriptions.find_one.return_value = None
    mock_post_response = mock_requests.return_value
    mock_post_response.ok = True
    mock_post_response.json.return_value = {
        "status": True,
        "message": "Authorization URL created",
        "data": {
            "authorization_url": "https://checkout.paystack.com/test",
            "access_code": "test_code",
            "reference": "test_ref",
        },
    }

    response = client.post("/api/v1/payments/initiate", json={"plan_id": "starter"})
    assert response.status_code == 200
    assert response.json() == {
        "authorization_url": "https://checkout.paystack.com/test",
        "reference": "test_ref",
    }


@patch("app.api.v1.payments.requests.get")
@patch("app.api.v1.payments.subscriptions_collection")
@patch("app.api.v1.payments.users_collection")
@patch("app.api.v1.payments.payments_collection")
def test_verify_payment(
    mock_payments, mock_users, mock_subscriptions, mock_requests, client
):
    mock_payments_update_result = mock_payments.update_one.return_value
    mock_payments_update_result.modified_count = 1

    mock_payments.find_one.return_value = {
        "reference": "test_ref",
        "user_id": "user_id_123",  # matches MOCK_USER['_id']
        "credits": 50,
        "plan_id": "starter",
        "status": "pending",
    }

    mock_get_response = mock_requests.return_value
    mock_get_response.ok = True
    mock_get_response.json.return_value = {"data": {"status": "success"}}

    response = client.post("/api/v1/payments/verify/test_ref")
    assert response.status_code == 200
    assert response.json() == {"status": "success", "credits_added": 50}
