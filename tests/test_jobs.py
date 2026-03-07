from unittest.mock import patch


@patch("app.api.v1.jobs.jobs_collection")
def test_get_job(mock_jobs, client):
    mock_jobs.find_one.return_value = {
        "job_id": "job1",
        "num_pages": 10,
        "title": "Title",
        "file_name": "f.pdf",
        "created_at": "2024",
        "status": "processing",
        "processing_id": "123",
    }
    response = client.get("/api/v1/job/job1")
    assert response.status_code == 200
    assert response.json()["status"] == "processing"


@patch("app.api.v1.jobs.jobs_collection")
@patch("app.api.v1.jobs.celery.send_task")
@patch("app.api.v1.jobs.job_tasks")
@patch("app.api.v1.jobs.deduct_credits_atomic", return_value=True)
def test_start_job(mock_deduct, mock_job_tasks, mock_celery, mock_jobs, client):
    mock_jobs.find_one.return_value = {
        "job_id": "job1",
        "user_id": "user_id_123",
        "num_pages": 4,
        "remote_pdf_path": "path/test.pdf",
    }

    response = client.post("/api/v1/start?job_id=job1&start=1&end=4")
    assert response.status_code == 200
    assert response.json()["pages"] == 4
    assert mock_celery.call_count == 4


@patch("app.api.v1.jobs.jobs_collection")
@patch("app.api.v1.jobs.upload_bytes")
@patch("app.api.v1.jobs.get_num_pages_and_extension")
@patch("app.api.v1.jobs.deduct_credits_atomic", return_value=True)
def test_upload_pdf(mock_deduct, mock_get_pages, mock_upload, mock_jobs, client):
    mock_get_pages.return_value = (10, ".pdf", b"pdfcontent")

    response = client.post(
        "/api/v1/upload",
        data={"title": "Test Title"},
        files={"file": ("test.pdf", b"%PDF-1.4...", "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pages"] == 10
    assert "job_id" in data


@patch("app.api.v1.jobs.jobs_collection")
@patch("app.api.v1.jobs.celery.send_task")
def test_request_full_review(mock_celery, mock_jobs, client, app_with_plan_user):
    """Test full-review request; uses app_with_plan_user fixture to inject active_plan_id."""
    mock_jobs.find_one.return_value = {
        "job_id": "job1",
        "user_id": "user_id_123",
        "num_pages": 10,
        "review_required": False,
    }
    response = client.post("/api/v1/request-full-review?job_id=job1")
    assert response.status_code == 200
    assert response.json()["status"] == "queued_for_review"


@patch("app.api.v1.jobs.jobs_collection")
def test_my_activity(mock_jobs, client):
    mock_jobs.find.return_value.sort.return_value = [{"job_id": "job1", "num_pages": 5}]
    response = client.get("/api/v1/me/activity")
    assert response.status_code == 200
    assert response.json()["jobs"] == [{"job_id": "job1", "num_pages": 5}]
