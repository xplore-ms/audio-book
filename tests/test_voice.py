from unittest.mock import patch
from bson.objectid import ObjectId


@patch("app.api.v1.voice.voices_collection")
@patch("app.api.v1.voice._safe_create_signed_url")
def test_list_voices(mock_sign, mock_voices, client):
    mock_voices.find.return_value = [
        {
            "_id": "vid1",
            "voice_name": "Test Voice",
            "supabase_path": "path",
            "language_codes": ["en-US"],
        }
    ]
    mock_sign.return_value = "http://signed.url"

    response = client.get("/api/v1/voices/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["voices"]) == 1
    assert data["voices"][0]["voice_name"] == "Test Voice"
    assert data["voices"][0]["url"] == "http://signed.url"


@patch("app.api.v1.voice.voices_collection")
@patch("app.api.v1.voice._safe_create_signed_url")
def test_get_voice_signed_url(mock_sign, mock_voices, client):
    mock_voices.find_one.return_value = {
        "_id": ObjectId("60a7e6b91dbdb92848abcabc"),
        "supabase_path": "test/path.wav",
    }
    mock_sign.return_value = "http://signed.url"

    response = client.get("/api/v1/voices/60a7e6b91dbdb92848abcabc/url")
    assert response.status_code == 200
    assert response.json()["url"] == "http://signed.url"
    assert "expires_at" in response.json()
