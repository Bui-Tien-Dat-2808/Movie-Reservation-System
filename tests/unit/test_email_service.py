import pytest
from unittest.mock import MagicMock, patch

from app.services.email_service import EmailService


def test_generate_barcode_bytes():
    ticket_code = "CVN-TEST123"
    barcode_bytes = EmailService.generate_barcode_bytes(ticket_code)

    assert isinstance(barcode_bytes, bytes)
    assert len(barcode_bytes) > 0
    # Check PNG magic header bytes \x89PNG
    assert barcode_bytes.startswith(b"\x89PNG")


def test_format_currency():
    assert EmailService.format_currency(150000) == "150.000₫"
    assert EmailService.format_currency(95000.0) == "95.000₫"
    assert EmailService.format_currency(0) == "0₫"
    assert EmailService.format_currency(None) == "0₫"


def test_build_ticket_email_html():
    # Mock Reservation object
    reservation = MagicMock()
    reservation.id = 42
    reservation.ticket_code = "CVN-9ISIES"
    reservation.total_price = 150000
    reservation.notes = "Combo: 1 Bắp Rang Bơ + 2 Nước Ngọt"

    # Mock Showtime & Movie
    movie = MagicMock()
    movie.title = "The Odyssey"
    movie.poster_url = "https://image.tmdb.org/t/p/w500/sample.jpg"

    room = MagicMock()
    room.name = "Phòng chiếu 01"
    room.room_type = "2D"

    showtime = MagicMock()
    showtime.movie = movie
    showtime.room = room
    showtime.start_time = None
    showtime.end_time = None
    reservation.showtime = showtime

    # Mock Seats
    seat1 = MagicMock()
    seat1.row_label = "A"
    seat1.col_number = 5
    seat1.seat_type = "standard"

    showtime_seat1 = MagicMock()
    showtime_seat1.seat = seat1

    rs1 = MagicMock()
    rs1.showtime_seat = showtime_seat1
    reservation.reservation_seats = [rs1]

    html = EmailService.build_ticket_email_html(reservation)

    assert "CVN-9ISIES" in html
    assert "The Odyssey" in html
    assert "Phòng chiếu 01" in html
    assert "A5" in html
    assert "150.000₫" in html
    assert "1 Bắp Rang Bơ + 2 Nước Ngọt" in html
    assert "cid:barcode_img" in html


def test_send_ticket_confirmation_email_dev_mode():
    reservation = MagicMock()
    reservation.id = 42
    reservation.ticket_code = "CVN-DEV99"

    with patch("app.services.email_service.settings.EMAIL_ENABLED", False):
        res = EmailService.send_ticket_confirmation_email("user@example.com", reservation)
        assert res is True


def test_send_ticket_confirmation_email_smtp_success():
    reservation = MagicMock()
    reservation.id = 42
    reservation.ticket_code = "CVN-SMTP01"
    reservation.total_price = 120000
    reservation.notes = ""
    reservation.showtime = None
    reservation.reservation_seats = []

    with patch("app.services.email_service.settings.EMAIL_ENABLED", True), \
         patch("app.services.email_service.settings.SMTP_USER", "sender@test.com"), \
         patch("app.services.email_service.settings.SMTP_PASSWORD", "secret_pass"), \
         patch("smtplib.SMTP") as mock_smtp:

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        res = EmailService.send_ticket_confirmation_email("customer@domain.com", reservation)

        assert res is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("sender@test.com", "secret_pass")
        mock_server.send_message.assert_called_once()


def test_build_refund_success_email_html():
    html = EmailService.build_refund_success_email_html(
        ticket_code="CVN-RF99",
        movie_title="Minions & Quái Vật",
        amount=198000,
        note="Đã chuyển khoản ngân hàng",
    )
    assert "CVN-RF99" in html
    assert "Minions &amp; Quái Vật" in html or "Minions & Quái Vật" in html or "Minions" in html
    assert "198.000₫" in html
    assert "Đã chuyển khoản ngân hàng" in html
    assert "HOÀN TIỀN THÀNH CÔNG" in html


def test_build_refund_failure_email_html():
    html = EmailService.build_refund_failure_email_html(
        ticket_code="CVN-FAIL01",
        movie_title="The Odyssey",
        amount=227700,
        reason="VNPay từ chối giao dịch do hết hạn 24h",
    )
    assert "CVN-FAIL01" in html
    assert "The Odyssey" in html
    assert "227.700₫" in html
    assert "VNPay từ chối giao dịch do hết hạn 24h" in html
    assert "CHƯA THÀNH CÔNG" in html


def test_send_refund_notification_email_smtp():
    with patch("app.services.email_service.settings.EMAIL_ENABLED", True), \
         patch("app.services.email_service.settings.SMTP_USER", "sender@test.com"), \
         patch("app.services.email_service.settings.SMTP_PASSWORD", "secret_pass"), \
         patch("smtplib.SMTP") as mock_smtp:

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        # Test Success Refund Email
        res_ok = EmailService.send_refund_notification_email(
            user_email="buid1066@gmail.com",
            ticket_code="CVN-RF001",
            movie_title="The Odyssey",
            amount=150000,
            is_success=True,
            note_or_reason="Admin đã hoàn tiền thành công",
        )
        assert res_ok is True

        # Test Failure Refund Email
        res_fail = EmailService.send_refund_notification_email(
            user_email="buid1066@gmail.com",
            ticket_code="CVN-RF002",
            movie_title="The Odyssey",
            amount=150000,
            is_success=False,
            note_or_reason="Lỗi hệ thống cổng VNPay",
        )
        assert res_fail is True


def test_build_cash_cancellation_email_html():
    html = EmailService.build_cash_cancellation_email_html(
        ticket_code="CVN-CASH99",
        movie_title="Avengers Doomsday",
        amount=207000,
        reason="Khách hàng huỷ vé",
    )
    assert "CVN-CASH99" in html
    assert "Avengers Doomsday" in html
    assert "207.000₫" in html
    assert "Tiền mặt (Thanh toán tại rạp)" in html
    assert "XÁC NHẬN HỦY VÉ THÀNH CÔNG" in html


def test_send_cash_cancellation_email_smtp():
    with patch("app.services.email_service.settings.EMAIL_ENABLED", True), \
         patch("app.services.email_service.settings.SMTP_USER", "sender@test.com"), \
         patch("app.services.email_service.settings.SMTP_PASSWORD", "secret_pass"), \
         patch("smtplib.SMTP") as mock_smtp:

        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        res_ok = EmailService.send_cash_cancellation_email(
            user_email="buid1066@gmail.com",
            ticket_code="CVN-CASH99",
            movie_title="Avengers Doomsday",
            amount=207000,
            reason="Khách hàng huỷ vé",
        )
        assert res_ok is True
