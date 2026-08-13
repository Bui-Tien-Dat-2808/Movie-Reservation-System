import io
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import barcode
from barcode.writer import ImageWriter
import structlog

from app.config import settings

logger = structlog.get_logger()
VN_TZ = timezone(timedelta(hours=7))


class EmailService:
    @staticmethod
    def generate_barcode_bytes(text: str) -> bytes:
        """Generate high-contrast CODE128 Barcode PNG image as bytes."""
        rv = io.BytesIO()
        code128 = barcode.get("code128", text, writer=ImageWriter())
        # Configure writer options for clean barcode display
        options = {
            "module_width": 0.35,
            "module_height": 14.0,
            "quiet_zone": 2.0,
            "font_size": 0,  # Hide built-in text to render custom styled ticket code
            "text_distance": 0.0,
            "background": "white",
            "foreground": "black",
        }
        code128.write(rv, options=options)
        return rv.getvalue()

    @staticmethod
    def format_currency(amount: Any) -> str:
        """Format decimal/float to VND currency string without trailing decimals."""
        if amount is None:
            return "0₫"
        try:
            val = float(amount)
            return f"{round(val):,}".replace(",", ".") + "₫"
        except (ValueError, TypeError):
            return "0₫"

    @classmethod
    def build_ticket_email_html(cls, reservation: Any) -> str:
        """Build premium dark-themed HTML email template matching ETicketModal barcode style."""
        ticket_code = getattr(reservation, "ticket_code", None) or f"#{reservation.id}"
        total_price_str = cls.format_currency(reservation.total_price)

        # Showtimes and Movie Info
        showtime = getattr(reservation, "showtime", None)
        movie_title = getattr(showtime.movie, "title", "Phim CineVerse") if showtime and getattr(showtime, "movie", None) else "Xem Phim Trực Tuyến"
        movie_poster = getattr(showtime.movie, "poster_url", None) if showtime and getattr(showtime, "movie", None) else None
        room_name = getattr(showtime.room, "name", "Phòng chiếu CineVerse") if showtime and getattr(showtime, "room", None) else "Phòng chiếu CineVerse"
        room_type = getattr(showtime.room, "room_type", "2D") if showtime and getattr(showtime, "room", None) else "2D"

        # Format start & end time in VN TZ
        start_str = "N/A"
        end_str = ""
        if showtime and getattr(showtime, "start_time", None):
            start_dt = showtime.start_time.astimezone(VN_TZ) if hasattr(showtime.start_time, "astimezone") else showtime.start_time
            start_str = start_dt.strftime("%H:%M - %d/%m/%Y")
        if showtime and getattr(showtime, "end_time", None):
            end_dt = showtime.end_time.astimezone(VN_TZ) if hasattr(showtime.end_time, "astimezone") else showtime.end_time
            end_str = end_dt.strftime("%H:%M")

        time_display = f"{start_str}" + (f" (Kết thúc ~{end_str})" if end_str else "")

        # Format Seats
        seats_list = []
        if hasattr(reservation, "reservation_seats") and reservation.reservation_seats:
            for rs in reservation.reservation_seats:
                ss = getattr(rs, "showtime_seat", None)
                seat = getattr(ss, "seat", None) if ss else None
                if seat:
                    label = f"{seat.row_label}{seat.col_number}"
                    if getattr(seat, "seat_type", "") == "couple":
                        label += " (Ghế Đôi)"
                    seats_list.append(label)
        seats_str = ", ".join(seats_list) if seats_list else "Đang cập nhật"

        # Format Concessions / Food Combos if present
        concessions_html = ""
        notes = getattr(reservation, "notes", "") or ""
        if notes and "Combo:" in notes:
            concessions_html = f"""
            <div style="margin-top: 12px; padding: 10px; background: rgba(232, 184, 75, 0.1); border-left: 3px solid #e8b84b; border-radius: 6px; font-size: 13px; color: #f0ede8;">
                🍿 <strong>Đồ ăn & Nước uống:</strong> {notes.replace('Combo:', '').strip()}
            </div>
            """

        poster_html = f'<img src="{movie_poster}" alt="{movie_title}" style="width: 90px; height: 130px; object-fit: cover; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2); margin-right: 16px; float: left;">' if movie_poster else ''

        return f"""
        <!DOCTYPE html>
        <html lang="vi" class="notranslate">
        <head>
            <meta charset="utf-8">
            <meta http-equiv="Content-Language" content="vi">
            <meta name="google" content="notranslate">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Xác Nhận Đặt Vé CineVerse</title>
        </head>
        <body class="notranslate" style="margin: 0; padding: 0; background-color: #09090e; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f0ede8;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #09090e; padding: 20px 0;">
                <tr>
                    <td align="center">
                        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color: #111118; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #161622; padding: 24px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.1);">
                                    <div style="display: inline-block; background: #e8b84b; color: #09090e; font-weight: 900; font-size: 18px; padding: 4px 12px; border-radius: 6px; margin-bottom: 8px;">
                                        🎬 CINEVERSE CINEMA
                                    </div>
                                    <h1 style="margin: 8px 0 0 0; font-size: 22px; font-weight: 800; color: #ffffff;">XÁC NHẬN ĐẶT VÉ THÀNH CÔNG</h1>
                                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #a09e9a;">Cảm ơn bạn đã lựa chọn trải nghiệm điện ảnh tại CineVerse!</p>
                                </td>
                            </tr>

                            <!-- Movie & Showtime Info -->
                            <tr>
                                <td style="padding: 20px 24px 12px 24px;">
                                    <div style="background: #181824; border-radius: 12px; padding: 16px; border: 1px solid rgba(255,255,255,0.05);">
                                        {poster_html}
                                        <div style="overflow: hidden;">
                                            <h2 style="margin: 0 0 8px 0; font-size: 18px; color: #ffffff; font-weight: 700;">{movie_title}</h2>
                                            <p style="margin: 0 0 6px 0; font-size: 13px; color: #a09e9a;">
                                                🕒 <strong>Suất chiếu:</strong> <span style="color: #e8b84b; font-weight: 600;">{time_display}</span>
                                            </p>
                                            <p style="margin: 0 0 6px 0; font-size: 13px; color: #a09e9a;">
                                                🏛️ <strong>Phòng chiếu:</strong> {room_name}
                                            </p>
                                            <p style="margin: 0; font-size: 13px; color: #a09e9a;">
                                                💺 <strong>Ghế đã chọn:</strong> <span style="color: #ffffff; font-weight: 700;">{seats_str}</span>
                                            </p>
                                        </div>
                                        <div style="clear: both;"></div>
                                        {concessions_html}
                                    </div>
                                </td>
                            </tr>

                            <!-- E-Ticket Barcode Container (Matches ETicketModal style) -->
                            <tr>
                                <td align="center" style="padding: 10px 24px 20px 24px;">
                                    <div style="background: #ffffff; border-radius: 20px; padding: 24px 20px; display: block; width: 85%; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.4);">
                                        <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; color: #64748b; display: block; margin-bottom: 6px;">MÃ VÉ VÀO RẠP (TICKET CODE)</span>
                                        <span style="font-family: monospace, sans-serif; font-size: 30px; font-weight: 900; color: #d97706; letter-spacing: 3px; display: block; margin-bottom: 12px;">{ticket_code}</span>
                                        <img src="cid:barcode_img" alt="Barcode Ticket" style="width: 88%; max-width: 360px; height: auto; min-height: 55px; display: block; margin: 0 auto 12px auto;">
                                        <p style="margin: 0; font-size: 12px; color: #e11d48; font-weight: 600;">
                                            🎟️ Vui lòng đưa mã này cho nhân viên tại rạp để soát vé vào phòng chiếu.
                                        </p>
                                    </div>
                                </td>
                            </tr>

                            <!-- Payment Summary -->
                            <tr>
                                <td style="padding: 0 24px 24px 24px;">
                                    <table width="100%" cellspacing="0" cellpadding="0" style="border-t: 1px solid rgba(255,255,255,0.1); padding-top: 16px;">
                                        <tr>
                                            <td style="font-size: 14px; color: #a09e9a;">Tổng tiền đã thanh toán:</td>
                                            <td align="right" style="font-size: 20px; font-weight: 900; color: #2ecc71; font-family: monospace;">{total_price_str}</td>
                                        </tr>
                                    </table>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #0d0d14; padding: 16px 24px; text-align: center; border-top: 1px solid rgba(255,255,255,0.08);">
                                    <p style="margin: 0; font-size: 11px; color: #6e6c68;">
                                        CineVerse Entertainment Inc. · Mọi thắc mắc xin liên hệ Hotline 1900-CINEVERSE
                                    </p>
                                </td>
                            </tr>

                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    @classmethod
    def send_ticket_email_raw(
        cls, user_email: str, ticket_code: str, html_content: str, barcode_bytes: bytes
    ) -> bool:
        """
        Thread-safe email dispatch using pre-rendered HTML and barcode bytes.
        """
        if not user_email:
            logger.warning("ticket_email_skipped_no_email", ticket_code=ticket_code)
            return False

        # Check if email dispatch is enabled
        if not settings.EMAIL_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info(
                "ticket_email_confirmation_logged_dev_mode",
                recipient=user_email,
                ticket_code=ticket_code,
                notice="SMTP disabled or not configured in .env. Set EMAIL_ENABLED=True to send live emails.",
            )
            return True

        try:
            from_email = settings.SMTP_USER or settings.EMAILS_FROM_EMAIL
            msg = MIMEMultipart("related")
            msg["Subject"] = f"🎟️ Xác nhận đặt vé thành công! Mã vé {ticket_code} - CineVerse"
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{from_email}>"
            msg["To"] = user_email

            # Alternative HTML body container
            msg_alternative = MIMEMultipart("alternative")
            msg.attach(msg_alternative)

            html_part = MIMEText(html_content, "html", "utf-8")
            msg_alternative.attach(html_part)

            # Attach inline Barcode PNG image with Content-ID <barcode_img>
            if barcode_bytes:
                img_part = MIMEImage(barcode_bytes, _subtype="png")
                img_part.add_header("Content-ID", "<barcode_img>")
                img_part.add_header("Content-Disposition", "inline", filename=f"{ticket_code}_barcode.png")
                msg.attach(img_part)

            # Dispatch via SMTP Server
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("ticket_email_sent_successfully", recipient=user_email, ticket_code=ticket_code)
            return True
        except Exception as e:
            logger.exception("ticket_email_send_failed", recipient=user_email, ticket_code=ticket_code, error=str(e))
            return False

    @classmethod
    def send_ticket_confirmation_email(cls, user_email: str, reservation: Any) -> bool:
        """
        Construct MIME Email with inline CODE128 Barcode image and dispatch via SMTP.
        """
        ticket_code = getattr(reservation, "ticket_code", None) or f"#{reservation.id}"
        if not user_email:
            logger.warning("ticket_email_skipped_no_email", reservation_id=reservation.id)
            return False

        try:
            barcode_bytes = cls.generate_barcode_bytes(ticket_code)
        except Exception as e:
            logger.exception("barcode_generation_failed", ticket_code=ticket_code, error=str(e))
            barcode_bytes = b""

        html_content = cls.build_ticket_email_html(reservation)
        return cls.send_ticket_email_raw(user_email, ticket_code, html_content, barcode_bytes)

    @classmethod
    def build_refund_success_email_html(
        cls, ticket_code: str, movie_title: str, amount: Any, note: str
    ) -> str:
        """Build HTML template for successful refund notification."""
        amount_str = cls.format_currency(amount)
        note_display = note or "Xác nhận hoàn tiền thành công cho khách"

        return f"""
        <!DOCTYPE html>
        <html lang="vi" class="notranslate">
        <head>
            <meta charset="utf-8">
            <meta http-equiv="Content-Language" content="vi">
            <meta name="google" content="notranslate">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Hoàn Tiền Thành Công - CineVerse</title>
        </head>
        <body class="notranslate" style="margin: 0; padding: 0; background-color: #09090e; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f0ede8;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #09090e; padding: 20px 0;">
                <tr>
                    <td align="center">
                        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color: #111118; border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #064e3b; padding: 24px; text-align: center; border-bottom: 1px solid rgba(16, 185, 129, 0.3);">
                                    <div style="display: inline-block; background: #10b981; color: #09090e; font-weight: 900; font-size: 16px; padding: 4px 12px; border-radius: 6px; margin-bottom: 8px;">
                                        💸 THÔNG BÁO HOÀN TIỀN
                                    </div>
                                    <h1 style="margin: 8px 0 0 0; font-size: 22px; font-weight: 800; color: #ffffff;">XÁC NHẬN HOÀN TIỀN THÀNH CÔNG</h1>
                                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #a7f3d0;">Yêu cầu hoàn tiền vé của bạn đã được xử lý hoàn tất</p>
                                </td>
                            </tr>

                            <!-- Details Card -->
                            <tr>
                                <td style="padding: 24px;">
                                    <div style="background: #161622; border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.08);">
                                        <table width="100%" cellspacing="0" cellpadding="6" style="font-size: 13px; color: #a09e9a;">
                                            <tr>
                                                <td width="40%"><strong>Mã vé đã hủy:</strong></td>
                                                <td><span style="font-family: monospace; font-size: 16px; font-weight: 800; color: #e8b84b;">{ticket_code}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Bộ phim:</strong></td>
                                                <td><span style="color: #ffffff; font-weight: 700;">{movie_title}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Số tiền hoàn lại:</strong></td>
                                                <td><span style="font-family: monospace; font-size: 18px; font-weight: 900; color: #10b981;">{amount_str}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Ghi chú xử lý:</strong></td>
                                                <td><span style="color: #f0ede8;">{note_display}</span></td>
                                            </tr>
                                        </table>
                                    </div>

                                    <div style="margin-top: 20px; padding: 14px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 10px; text-align: center; font-size: 13px; color: #34d399;">
                                        ✓ Số tiền <strong>{amount_str}</strong> đã được chuyển về tài khoản/thẻ thanh toán của bạn. Cảm ơn bạn đã đồng hành cùng CineVerse!
                                    </div>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #0d0d14; padding: 16px 24px; text-align: center; border-top: 1px solid rgba(255,255,255,0.08);">
                                    <p style="margin: 0; font-size: 11px; color: #6e6c68;">
                                        CineVerse Entertainment Inc. · Hotline hỗ trợ khách hàng: 1900-CINEVERSE
                                    </p>
                                </td>
                            </tr>

                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    @classmethod
    def build_refund_failure_email_html(
        cls, ticket_code: str, movie_title: str, amount: Any, reason: str
    ) -> str:
        """Build HTML template for failed refund notification."""
        amount_str = cls.format_currency(amount)
        reason_display = reason or "Không thể hoàn tự động qua VNPAY"

        return f"""
        <!DOCTYPE html>
        <html lang="vi" class="notranslate">
        <head>
            <meta charset="utf-8">
            <meta http-equiv="Content-Language" content="vi">
            <meta name="google" content="notranslate">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Cập Nhật Xử Lý Hoàn Tiền - CineVerse</title>
        </head>
        <body class="notranslate" style="margin: 0; padding: 0; background-color: #09090e; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f0ede8;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #09090e; padding: 20px 0;">
                <tr>
                    <td align="center">
                        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color: #111118; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #7f1d1d; padding: 24px; text-align: center; border-bottom: 1px solid rgba(239, 68, 68, 0.3);">
                                    <div style="display: inline-block; background: #ef4444; color: #ffffff; font-weight: 900; font-size: 16px; padding: 4px 12px; border-radius: 6px; margin-bottom: 8px;">
                                        ⚠️ THÔNG BÁO XỬ LÝ HOÀN TIỀN
                                    </div>
                                    <h1 style="margin: 8px 0 0 0; font-size: 22px; font-weight: 800; color: #ffffff;">YÊU CẦU HOÀN TIỀN CHƯA THÀNH CÔNG</h1>
                                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #fca5a5;">Thông tin chi tiết về sự cố xử lý hoàn tiền cho vé của bạn</p>
                                </td>
                            </tr>

                            <!-- Details Card -->
                            <tr>
                                <td style="padding: 24px;">
                                    <div style="background: #161622; border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.08);">
                                        <table width="100%" cellspacing="0" cellpadding="6" style="font-size: 13px; color: #a09e9a;">
                                            <tr>
                                                <td width="40%"><strong>Mã vé:</strong></td>
                                                <td><span style="font-family: monospace; font-size: 16px; font-weight: 800; color: #e8b84b;">{ticket_code}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Bộ phim:</strong></td>
                                                <td><span style="color: #ffffff; font-weight: 700;">{movie_title}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Số tiền hoàn yêu cầu:</strong></td>
                                                <td><span style="font-family: monospace; font-size: 16px; font-weight: 800; color: #f87171;">{amount_str}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Lý do chưa thành công:</strong></td>
                                                <td><span style="color: #fca5a5; font-weight: 600;">{reason_display}</span></td>
                                            </tr>
                                        </table>
                                    </div>

                                    <div style="margin-top: 20px; padding: 14px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 10px; text-align: center; font-size: 13px; color: #f87171;">
                                        📞 Đội ngũ CSKH CineVerse đang kiểm tra để hỗ trợ bạn. Nếu cần xử lý gấp, xin vui lòng liên hệ Hotline <strong>1900-CINEVERSE</strong>.
                                    </div>
                                </td>
                            </tr>

                            <!-- Footer -->
                            <tr>
                                <td style="background-color: #0d0d14; padding: 16px 24px; text-align: center; border-top: 1px solid rgba(255,255,255,0.08);">
                                    <p style="margin: 0; font-size: 11px; color: #6e6c68;">
                                        CineVerse Entertainment Inc. · Hotline hỗ trợ khách hàng: 1900-CINEVERSE
                                    </p>
                                </td>
                            </tr>

                        </table>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """

    @classmethod
    def send_refund_notification_email(
        cls,
        user_email: str,
        ticket_code: str,
        movie_title: str,
        amount: Any,
        is_success: bool,
        note_or_reason: str,
    ) -> bool:
        """
        Thread-safe email dispatch for refund outcome (success or failure).
        """
        if not user_email:
            logger.warning("refund_email_skipped_no_email", ticket_code=ticket_code)
            return False

        if not settings.EMAIL_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info(
                "refund_email_logged_dev_mode",
                recipient=user_email,
                ticket_code=ticket_code,
                is_success=is_success,
                note_or_reason=note_or_reason,
            )
            return True

        try:
            from_email = settings.SMTP_USER or settings.EMAILS_FROM_EMAIL
            msg = MIMEMultipart("alternative")
            status_tag = "💸 HOÀN TIỀN THÀNH CÔNG" if is_success else "⚠️ THÔNG BÁO HOÀN TIỀN"
            msg["Subject"] = f"{status_tag} - Vé {ticket_code} (CineVerse)"
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{from_email}>"
            msg["To"] = user_email

            if is_success:
                html_content = cls.build_refund_success_email_html(ticket_code, movie_title, amount, note_or_reason)
            else:
                html_content = cls.build_refund_failure_email_html(ticket_code, movie_title, amount, note_or_reason)

            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("refund_email_sent_successfully", recipient=user_email, ticket_code=ticket_code, is_success=is_success)
            return True
        except Exception as e:
            logger.exception("refund_email_send_failed", recipient=user_email, ticket_code=ticket_code, error=str(e))
            return False
