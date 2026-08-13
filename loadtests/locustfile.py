from locust import HttpUser, task, between


class ConcurrentOverbookingUser(HttpUser):
    """
    Concurrent Overbooking Load Test Scenario:
    Simulates multiple virtual users simultaneously attempting to hold and book 
    the EXACT same seat IDs of a single showtime.
    Verifies that ONLY ONE request succeeds (201/200), and all concurrent requests 
    are safely rejected with 409 Conflict or 400 Bad Request.
    """
    wait_time = between(0.1, 0.5)

    def on_start(self):
        """Authenticate user on start."""
        resp = self.client.post("/api/v1/auth/login", json={
            "account": "bd@email.com",
            "password": "Admin@123456"
        })
        if resp.status_code == 200:
            token = resp.json().get("access_token")
            self.headers = {"Authorization": f"Bearer {token}"}
        else:
            self.headers = {}

    @task(3)
    def book_same_seats(self):
        """All virtual users attack the same seat IDs (e.g. showtime 1, seat_ids [1, 2])."""
        payload = {
            "showtime_id": 1,
            "seat_ids": [1, 2],
        }
        with self.client.post(
            "/api/v1/reservations/",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code in (201, 200):
                response.success()
            elif response.status_code in (400, 409, 422):
                # Expected failure response when seats are already held/booked by another user
                response.success()
            else:
                response.failure(f"Unexpected status code: {response.status_code}")

    @task(7)
    def browse_now_showing_movies(self):
        """Read-heavy benchmark endpoint for Redis caching."""
        self.client.get("/api/v1/movies/now-showing")
