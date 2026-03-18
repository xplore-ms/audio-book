from unittest.mock import patch, AsyncMock


@patch("app.api.v1.auth.user_service.UserService.default")
def test_register(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.register_user = AsyncMock(
        return_value={"message": "User registered successfully"}
    )

    response = client.post(
        "/api/v1/auth/register",
        data={
            "email": "test@test.com",
            "password": "password",
            "device_fingerprint_hash": "hash123",
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "User registered successfully"


@patch("app.api.v1.auth.user_service.UserService.default")
def test_login(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.login_user = AsyncMock(
        return_value={
            "access_token": "token",
            "refresh_token": "refresh",
            "token_type": "bearer",
        }
    )

    response = client.post(
        "/api/v1/auth/login", data={"email": "test@test.com", "password": "password"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "token"


@patch("app.api.v1.auth.user_service.UserService.default")
def test_get_me(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.get_me = AsyncMock(return_value={"email": "test@test.com"})

    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "test@test.com"


@patch("app.api.v1.auth.user_service.UserService.default")
def test_forgot_password(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.forgot_password = AsyncMock(
        return_value={"message": "Password reset code sent"}
    )

    response = client.post(
        "/api/v1/auth/forgot-password", data={"email": "test@test.com"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Password reset code sent"


@patch("app.api.v1.auth.user_service.UserService.default")
def test_verify_email_code(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.verify_email_code = AsyncMock(return_value={"message": "Email verified"})

    response = client.post(
        "/api/v1/auth/verify-email-code",
        data={"email": "test@test.com", "code": "123456"},
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Email verified"


@patch("app.api.v1.auth.user_service.UserService.default")
def test_reset_password(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.reset_password = AsyncMock(
        return_value={"message": "Password reset successfully"}
    )

    response = client.post(
        "/api/v1/auth/reset-password",
        data={
            "email": "test@test.com",
            "code": "123456",
            "new_password": "newpassword",
        },
    )
    assert response.status_code == 200


@patch("app.api.v1.auth.user_service.UserService.default")
def test_refresh_token(mock_default_svc, client):
    mock_svc = mock_default_svc.return_value
    mock_svc.refresh_user_token = AsyncMock(
        return_value={
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "token_type": "bearer",
        }
    )

    response = client.post(
        "/api/v1/auth/refresh-token", data={"refresh_token": "old_token"}
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "new_token"
