"""Tests for Playwright Web Crawler Agent API"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestHealthAndRoot:
    def test_root_message(self):
        res = requests.get(f"{BASE_URL}/api/")
        assert res.status_code == 200
        data = res.json()
        assert "message" in data
        assert "Playwright Web Crawler Agent" in data["message"]
        print(f"PASS: Root returns: {data['message']}")


class TestCrawlAPI:
    session_id = None

    def test_start_crawl(self):
        res = requests.post(f"{BASE_URL}/api/crawl/start", json={
            "url": "https://example.com",
            "max_pages": 3,
            "max_depth": 1
        })
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "session_id" in data
        assert data["status"] == "started"
        TestCrawlAPI.session_id = data["session_id"]
        print(f"PASS: Start crawl returned session_id: {data['session_id']}")

    def test_get_status_running(self):
        if not TestCrawlAPI.session_id:
            pytest.skip("No session_id from start_crawl")
        res = requests.get(f"{BASE_URL}/api/crawl/{TestCrawlAPI.session_id}/status")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert data["status"] in ("running", "completed", "failed")
        assert "stats" in data
        print(f"PASS: Status: {data['status']}")

    def test_wait_for_completion_and_report(self):
        if not TestCrawlAPI.session_id:
            pytest.skip("No session_id from start_crawl")
        # Wait up to 30s for crawl to complete
        for _ in range(30):
            res = requests.get(f"{BASE_URL}/api/crawl/{TestCrawlAPI.session_id}/status")
            data = res.json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(1)
        print(f"Final status: {data['status']}")

        # Get report
        res = requests.get(f"{BASE_URL}/api/crawl/{TestCrawlAPI.session_id}/report")
        assert res.status_code == 200
        data = res.json()
        assert "pages" in data
        assert "stats" in data
        assert "status" in data
        assert isinstance(data["pages"], list)
        print(f"PASS: Report has {len(data['pages'])} pages, status: {data['status']}")

    def test_stop_nonexistent_session(self):
        res = requests.post(f"{BASE_URL}/api/crawl/nonexistent-session-id/stop")
        assert res.status_code == 404
        print("PASS: Stop nonexistent returns 404")

    def test_status_nonexistent_session(self):
        res = requests.get(f"{BASE_URL}/api/crawl/nonexistent-session-id/status")
        assert res.status_code == 404
        print("PASS: Status nonexistent returns 404")

    def test_start_crawl_with_credentials(self):
        res = requests.post(f"{BASE_URL}/api/crawl/start", json={
            "url": "https://example.com",
            "username": "testuser",
            "password": "testpass",
            "max_pages": 2,
            "max_depth": 1
        })
        assert res.status_code == 200
        data = res.json()
        assert "session_id" in data
        # Stop it right away
        sid = data["session_id"]
        stop_res = requests.post(f"{BASE_URL}/api/crawl/{sid}/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "stopped"
        print(f"PASS: Start with credentials and stop works")
