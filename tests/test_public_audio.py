from unittest.mock import patch, AsyncMock


@patch("app.api.v1.public_audio.jobs_collection")
def test_list_public_audios(mock_jobs, client):
    mock_cursor = [{"job_id": "job1", "title": "Public 1", "required_credits": 2}]
    mock_jobs.find.return_value = AsyncMock()
    mock_jobs.find.return_value.__aiter__.return_value = mock_cursor

    response = client.get("/api/v1/public/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["job_id"] == "job1"


@patch("app.api.v1.public_audio.jobs_collection")
@patch("app.api.v1.public_audio.users_collection")
@patch("app.api.v1.public_audio.build_playlist_response")
def test_listen_public_audio(mock_build, mock_users, mock_jobs, client):
    mock_jobs.find_one = AsyncMock(
        return_value={
            "_id": "job_id_obj",
            "job_id": "job1",
            "pages": {"page": 1},
            "required_credits": 5,
            "is_admin": True,
        }
    )
    mock_users.find_one = AsyncMock(return_value={"_id": "user_id_123", "credits": 10})
    mock_build.return_value = {"playlist": "url"}

    # Needs update_one mock too because listen_public_audio updates user credits
    mock_users.update_one = AsyncMock()
    mock_jobs.update_one = AsyncMock()

    response = client.get("/api/v1/public/listen/job1")
    assert response.status_code == 200
    assert response.json() == {"playlist": "url"}


@patch("app.api.v1.public_audio.jobs_collection")
def test_get_public_sync(mock_jobs, client):
    mock_jobs.find_one = AsyncMock(
        return_value={
            "job_id": "job1",
            "pages": {"page1": {"sync_path": "test"}},
        }
    )
    response = client.get("/api/v1/public/sync/job1")
    assert response.status_code == 200
    assert response.json() == {"pages": {"page1": {"sync_path": "test"}}}
