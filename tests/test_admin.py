from unittest.mock import patch


@patch("app.api.v1.admin.users_collection")
@patch("app.api.v1.admin.jobs_collection")
def test_admin_metrics_overview(mock_jobs, mock_users, admin_client):
    mock_users.count_documents.side_effect = [10, 5]
    mock_jobs.count_documents.side_effect = [20, 2, 18]

    response = admin_client.get("/api/v1/admin/metrics/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["users"]["total"] == 10
    assert data["jobs"]["total"] == 20


@patch("app.api.v1.admin.users_collection")
def test_admin_user_metrics(mock_users, admin_client):
    mock_users.count_documents.side_effect = [5, 10]
    mock_users.aggregate.return_value = [{"total": 100}]

    response = admin_client.get("/api/v1/admin/metrics/users")
    assert response.status_code == 200
    data = response.json()
    assert data["new_users"]["last_7_days"] == 5
    assert data["credits"]["total_remaining"] == 100


@patch("app.api.v1.admin.payments_collection")
def test_admin_revenue_metrics(mock_payments, admin_client):
    mock_payments.aggregate.side_effect = [
        [
            {
                "_id": {"year": 2024, "month": 1, "day": 1},
                "total_revenue_kobo": 500000,
                "count": 10,
            }
        ],
        [{"total": 500000}],
    ]
    response = admin_client.get("/api/v1/admin/metrics/revenue")
    assert response.status_code == 200
    data = response.json()
    assert data["total_revenue_ngn"] == 5000.0


@patch("app.api.v1.admin.jobs_collection")
def test_admin_upload_pdf(mock_jobs, admin_client):
    with patch("app.api.v1.admin.upload_bytes"):
        with patch(
            "app.api.v1.admin.get_num_pages_and_extension",
            return_value=(10, ".pdf", b"pdfcontent"),
        ):
            with patch("app.api.v1.admin.log_activity"):
                response = admin_client.post(
                    "/api/v1/admin/upload",
                    data={
                        "title": "Test Title",
                        "category": "Test Cat",
                        "required_credits": 2,
                    },
                    files={"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")},
                )
                assert response.status_code == 200
                assert response.json()["num_pages"] == 10


@patch("app.api.v1.admin.jobs_collection")
def test_admin_approve_review(mock_jobs, admin_client):
    with patch(
        "app.api.v1.admin.users_collection.find_one",
        return_value={"email": "test@test.com"},
    ):
        with patch("app.api.v1.admin.celery.send_task"):
            with patch("app.api.v1.admin.log_activity"):
                mock_jobs.find_one.return_value = {
                    "job_id": "job1",
                    "num_pages": 5,
                    "user_id": "60a7e6b91dbdb92848abcabc",
                }
                response = admin_client.post(
                    "/api/v1/admin/approve-review", data={"job_id": "job1"}
                )
                assert response.status_code == 200
                assert response.json() == {"status": "approved", "job_id": "job1"}
