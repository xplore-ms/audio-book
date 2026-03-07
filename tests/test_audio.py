from unittest.mock import patch


@patch("app.api.v1.audio.jobs_collection")
def test_my_audios(mock_jobs, client):
    mock_cursor = [
        {
            "job_id": "job1",
            "title": "Audio 1",
            "file_name": "f1.pdf",
            "created_at": "2024-01-01",
            "user_id": "user_id_123",
        },
        {
            "job_id": "job2",
            "title": "Audio 2",
            "file_name": "f2.pdf",
            "created_at": "2024-01-02",
            "user_id": "other_user",
        },
    ]
    mock_jobs.find.return_value.sort.return_value = mock_cursor

    response = client.get("/api/v1/audio/my")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["is_owner"]
    assert not data[1]["is_owner"]


@patch("app.api.v1.audio.jobs_collection")
def test_get_sync(mock_jobs, client):
    mock_jobs.find_one.return_value = {
        "job_id": "job1",
        "user_id": "user_id_123",
        "pages": {"1": {"sync_path": "test"}},
    }

    response = client.get("/api/v1/audio/sync/job1")
    assert response.status_code == 200
    assert response.json() == {"pages": {"1": {"sync_path": "test"}}}


@patch("app.api.v1.audio.jobs_collection")
@patch("app.api.v1.audio._safe_create_signed_url")
def test_get_pages(mock_sign, mock_jobs, client):
    mock_jobs.find_one.return_value = {
        "job_id": "job1",
        "user_id": "user_id_123",
        "pages": {"page_1": {"audio_path": "test.mp3", "duration": 10}},
    }
    mock_sign.return_value = "http://signed"

    # mock token manually here by pass directly
    # In conftest we mocking oauth2_scheme but the get_pages explicitly uses Depends(oauth2_scheme)
    response = client.get(
        "/api/v1/audio/pages/job1", headers={"Authorization": "Bearer testtoken"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "job1"
    assert len(data["pages"]) == 1


@patch("app.api.v1.audio.users_collection")
@patch("app.api.v1.audio.jobs_collection")
def test_share_audiobook(mock_jobs, mock_users, client):
    mock_users.find.return_value = [{"email": "friend@example.com"}]
    mock_update = mock_jobs.update_one.return_value
    mock_update.matched_count = 1

    response = client.post(
        "/api/v1/audio/share/job1/emails", json={"emails": ["friend@example.com"]}
    )
    assert response.status_code == 200
    assert "friend@example.com" in response.json()["shared_with"]


@patch("app.api.v1.audio.jobs_collection")
def test_unshare_audiobook(mock_jobs, client):
    mock_update = mock_jobs.update_one.return_value
    mock_update.matched_count = 1

    response = client.get("/api/v1/audio/unshare/job1")
    assert response.status_code == 200
    assert response.json() == {"message": "Job updated successfully"}
