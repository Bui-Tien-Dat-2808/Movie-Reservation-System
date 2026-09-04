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
        movie_title = (
            getattr(showtime.movie, "title", "Phim CineVerse")
            if showtime and getattr(showtime, "movie", None)
            else "Xem Phim Trực Tuyến"
        )
        movie_poster = (
            getattr(showtime.movie, "poster_url", None)
            if showtime and getattr(showtime, "movie", None)
            else None
        )
        room_name = (
            getattr(showtime.room, "name", "Phòng chiếu CineVerse")
            if showtime and getattr(showtime, "room", None)
            else "Phòng chiếu CineVerse"
        )
        room_type = (
            getattr(showtime.room, "room_type", "2D")
            if showtime and getattr(showtime, "room", None)
            else "2D"
        )

        # Format start & end time in VN TZ
        start_str = "N/A"
        end_str = ""
        if showtime and getattr(showtime, "start_time", None):
            start_dt = (
                showtime.start_time.astimezone(VN_TZ)
                if hasattr(showtime.start_time, "astimezone")
                else showtime.start_time
            )
            start_str = start_dt.strftime("%H:%M - %d/%m/%Y")
        if showtime and getattr(showtime, "end_time", None):
            end_dt = (
                showtime.end_time.astimezone(VN_TZ)
                if hasattr(showtime.end_time, "astimezone")
                else showtime.end_time
            )
            end_str = end_dt.strftime("%H:%M")

        time_display = f"{start_str}"

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

        # Payment Method Label
        pm_code = getattr(reservation, "payment_method", None)
        if not pm_code and hasattr(reservation, "payment_transactions") and reservation.payment_transactions:
            pm_code = reservation.payment_transactions[0].payment_method
        pm_label = "Tiền mặt (Thanh toán tại rạp chiếu)" if pm_code == "cash" else "VNPay / ATM / Ví điện tử"

        # -----------------------------------------------------------------
        # Concessions / Food & Drink parsing
        # -----------------------------------------------------------------
        concessions_list = []
        concessions_total = Decimal(0)

        # 1. Check reservation_concessions relationship
        if hasattr(reservation, "reservation_concessions") and reservation.reservation_concessions:
            for rc in reservation.reservation_concessions:
                qty = getattr(rc, "quantity", 1) or 1
                unit_p = getattr(rc, "unit_price", None) or Decimal(0)
                item_total = Decimal(qty) * Decimal(unit_p)
                concessions_total += item_total

                c_name = "Bắp nước"
                c_obj = getattr(rc, "concession", None)
                if c_obj:
                    c_name = getattr(c_obj, "name", "Bắp nước")
                    c_size = getattr(c_obj, "size", None)
                    if c_size and f"size {c_size.lower()}" not in c_name.lower():
                        c_name += f" (Size {c_size})"

                c_opts = getattr(rc, "custom_options", "") or ""
                concessions_list.append({
                    "name": c_name,
                    "quantity": qty,
                    "unit_price": unit_p,
                    "total_price": item_total,
                    "custom_options": c_opts,
                })

        # 2. Fallback to notes if reservation_concessions is empty
        if not concessions_list and hasattr(reservation, "notes") and reservation.notes:
            notes = str(reservation.notes).strip()
            if any(k in notes.lower() for k in ["combo:", "bắp", "bap", "nước", "nuoc", "snack", "popcorn", "coca", "pepsi"]):
                clean_note = notes.replace("Combo:", "").replace("combo:", "").strip()
                if clean_note:
                    concessions_list.append({
                        "name": clean_note,
                        "quantity": 1,
                        "unit_price": Decimal(0),
                        "total_price": Decimal(0),
                        "custom_options": "",
                    })

        # 3. Build Concessions HTML section (Only shown if user actually ordered concessions)
        concessions_html = ""
        if concessions_list:
            items_rows = []
            for item in concessions_list:
                # Deduplicate custom_options if it only repeats the size already present in name
                opts = (item.get("custom_options") or "").strip()
                if opts and opts.lower() in item["name"].lower():
                    opts = ""

                opts_html = (
                    f'<div style="font-size: 11px; color: #a09e9a; margin-top: 3px; line-height: 1.4;">{opts}</div>'
                    if opts
                    else ""
                )
                price_html = (
                    f'<span style="font-family: monospace; font-weight: 700; color: #e8b84b;">{cls.format_currency(item["total_price"])}</span>'
                    if item.get("total_price") and item["total_price"] > 0
                    else ""
                )
                items_rows.append(
                    f"""
                    <tr style="border-bottom: 1px dashed rgba(255,255,255,0.08);">
                        <td style="padding: 8px 0; vertical-align: top;">
                            <strong style="color: #ffffff; font-size: 13px;">{item['name']}: <span style="color: #e8b84b; font-weight: 700;">{item['quantity']}</span></strong>
                            {opts_html}
                        </td>
                        <td align="right" style="padding: 8px 0; vertical-align: top; white-space: nowrap;">
                            {price_html}
                        </td>
                    </tr>
                    """
                )

            joined_items = "".join(items_rows)
            concessions_html = f"""
            <!-- Concessions Section -->
            <tr>
                <td style="padding: 0 24px 12px 24px;">
                    <div style="background: #181824; border-radius: 12px; padding: 16px; border: 1px solid rgba(232, 184, 75, 0.3);">
                        <div style="font-size: 12px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #e8b84b; margin-bottom: 10px;">
                            🍿 ĐỒ ĂN & NƯỚC UỐNG ĐI KÈM:
                        </div>
                        <table width="100%" cellspacing="0" cellpadding="0">
                            {joined_items}
                        </table>
                    </div>
                </td>
            </tr>
            """

        # Payment Breakdown rows
        discount_amount = getattr(reservation, "discount_amount", 0) or 0
        discount_html = ""
        if discount_amount and float(discount_amount) > 0:
            voucher_code = getattr(reservation, "voucher_code", "") or ""
            v_label = f"Giảm giá ({voucher_code}):" if voucher_code else "Giảm giá khuyến mãi:"
            discount_html = f"""
            <tr>
                <td style="font-size: 13px; color: #a09e9a; padding-bottom: 6px;">{v_label}</td>
                <td align="right" style="font-size: 13px; font-weight: 700; color: #ef4444; padding-bottom: 6px;">-{cls.format_currency(discount_amount)}</td>
            </tr>
            """

        concessions_breakdown_html = ""
        if concessions_total > 0:
            concessions_breakdown_html = f"""
            <tr>
                <td style="font-size: 13px; color: #a09e9a; padding-bottom: 6px;">Bắp nước & đồ ăn:</td>
                <td align="right" style="font-size: 13px; font-weight: 700; color: #e8b84b; padding-bottom: 6px;">{cls.format_currency(concessions_total)}</td>
            </tr>
            """

        poster_html = (
            f'<img src="{movie_poster}" alt="{movie_title}" style="width: 90px; height: 130px; object-fit: cover; border-radius: 8px; border: 1px solid rgba(255,255,255,0.2); margin-right: 16px; float: left;">'
            if movie_poster
            else ''
        )

        # Determine if this is a pending cash reservation
        is_cash = pm_code == "cash" or (hasattr(reservation, "notes") and "tiền mặt" in str(reservation.notes or "").lower())
        is_pending = str(getattr(reservation, "status", "")).lower() in ("pending", "reservationstatus.pending")

        if is_cash and is_pending:
            header_title = "XÁC NHẬN ĐẶT GIỮ CHỖ THÀNH CÔNG"
            header_sub = "Đơn giữ chỗ của bạn đã được ghi nhận. Vui lòng thanh toán tiền mặt tại quầy vé CineVerse trước giờ chiếu ít nhất 15 phút để nhận vé."
            barcode_instruction = "🎟️ Vui lòng xuất trình mã này tại quầy vé CineVerse để thanh toán tiền mặt và nhận vé vào rạp."
            total_label = "Tổng tiền thanh toán tại quầy:"
            pm_label = "Tiền mặt (Thanh toán tại quầy rạp chiếu)"
        else:
            header_title = "XÁC NHẬN ĐẶT VÉ THÀNH CÔNG"
            header_sub = "Cảm ơn bạn đã lựa chọn trải nghiệm điện ảnh tại CineVerse!"
            barcode_instruction = "🎟️ Vui lòng đưa mã này cho nhân viên tại rạp để soát vé vào phòng chiếu."
            total_label = "Tổng tiền đã thanh toán:"

        return f"""
        <!DOCTYPE html>
        <html lang="vi" class="notranslate">
        <head>
            <meta charset="utf-8">
            <meta http-equiv="Content-Language" content="vi">
            <meta name="google" content="notranslate">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{header_title} - CineVerse</title>
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
                                    <h1 style="margin: 8px 0 0 0; font-size: 22px; font-weight: 800; color: #ffffff;">{header_title}</h1>
                                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #a09e9a;">{header_sub}</p>
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
                                    </div>
                                </td>
                            </tr>

                            {concessions_html}

                            <!-- E-Ticket Barcode Container (Matches ETicketModal style) -->
                            <tr>
                                <td align="center" style="padding: 10px 24px 20px 24px;">
                                    <div style="background: #ffffff; border-radius: 20px; padding: 24px 20px; display: block; width: 85%; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.4);">
                                        <span style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; color: #64748b; display: block; margin-bottom: 6px;">MÃ VÉ VÀO RẠP (TICKET CODE)</span>
                                        <span style="font-family: monospace, sans-serif; font-size: 30px; font-weight: 900; color: #d97706; letter-spacing: 3px; display: block; margin-bottom: 12px;">{ticket_code}</span>
                                        <img src="cid:barcode_img" alt="Barcode Ticket" style="width: 88%; max-width: 360px; height: auto; min-height: 55px; display: block; margin: 0 auto 12px auto;">
                                        <p style="margin: 0; font-size: 12px; color: #e11d48; font-weight: 600;">
                                            {barcode_instruction}
                                        </p>
                                    </div>
                                </td>
                            </tr>

                            <!-- Payment Summary -->
                            <tr>
                                <td style="padding: 0 24px 24px 24px;">
                                    <table width="100%" cellspacing="0" cellpadding="0" style="border-top: 1px solid rgba(255,255,255,0.1); padding-top: 16px;">
                                        <tr>
                                            <td style="font-size: 13px; color: #a09e9a; padding-bottom: 6px;">Phương thức thanh toán:</td>
                                            <td align="right" style="font-size: 13px; font-weight: 700; color: #e8b84b; padding-bottom: 6px;">{pm_label}</td>
                                        </tr>
                                        {concessions_breakdown_html}
                                        {discount_html}
                                        <tr>
                                            <td style="font-size: 14px; color: #a09e9a; padding-top: 4px;">{total_label}</td>
                                            <td align="right" style="font-size: 20px; font-weight: 900; color: #2ecc71; font-family: monospace; padding-top: 4px;">{total_price_str}</td>
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
            is_cash_pending = "giữ chỗ" in html_content.lower() or "quầy vé" in html_content.lower()
            if is_cash_pending:
                msg["Subject"] = f"🎟️ [CineVerse] Xác nhận đặt giữ chỗ vé xem phim - Mã vé {ticket_code}"
            else:
                msg["Subject"] = f"🎟️ [CineVerse] Xác nhận đặt vé thành công! Mã vé {ticket_code}"
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

                                    <div style="margin-top: 20px; padding: 14px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 10px; text-align: center; font-size: 13px; color: #34d399; line-height: 1.5;">
                                        Cảm ơn bạn đã lựa chọn dịch vụ của <strong>CineVerse</strong>. Nếu có bất kỳ thắc mắc hoặc cần hỗ trợ thêm, vui lòng liên hệ tổng đài CSKH: <strong>1900-CINEVERSE</strong>.
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

    @classmethod
    def build_cash_cancellation_email_html(
        cls, ticket_code: str, movie_title: str, amount: Any, reason: str = "Khách hàng huỷ vé"
    ) -> str:
        """Build HTML template for Cash payment ticket cancellation notification."""
        amount_str = cls.format_currency(amount)
        reason_display = reason or "Khách hàng hủy vé đặt"

        return f"""
        <!DOCTYPE html>
        <html lang="vi" class="notranslate">
        <head>
            <meta charset="utf-8">
            <meta http-equiv="Content-Language" content="vi">
            <meta name="google" content="notranslate">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Thông Báo Hủy Vé Thành Công - CineVerse</title>
        </head>
        <body class="notranslate" style="margin: 0; padding: 0; background-color: #09090e; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f0ede8;">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #09090e; padding: 20px 0;">
                <tr>
                    <td align="center">
                        <table role="presentation" width="600" cellspacing="0" cellpadding="0" style="background-color: #111118; border: 1px solid rgba(232, 184, 75, 0.3); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                            
                            <!-- Header -->
                            <tr>
                                <td style="background-color: #1c1917; padding: 24px; text-align: center; border-bottom: 1px solid rgba(232, 184, 75, 0.3);">
                                    <div style="display: inline-block; background: #e8b84b; color: #09090e; font-weight: 900; font-size: 16px; padding: 4px 12px; border-radius: 6px; margin-bottom: 8px;">
                                        ❌ THÔNG BÁO HỦY VÉ
                                    </div>
                                    <h1 style="margin: 8px 0 0 0; font-size: 22px; font-weight: 800; color: #ffffff;">XÁC NHẬN HỦY VÉ THÀNH CÔNG</h1>
                                    <p style="margin: 4px 0 0 0; font-size: 13px; color: #d6d3d1;">Đơn đặt vé chọn thanh toán Tiền mặt tại rạp của bạn đã được hủy</p>
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
                                                <td><strong>Phương thức thanh toán:</strong></td>
                                                <td><span style="color: #f59e0b; font-weight: 700;">💵 Tiền mặt (Thanh toán tại rạp)</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Tổng giá trị đơn:</strong></td>
                                                <td><span style="font-family: monospace; font-size: 16px; font-weight: 800; color: #f0ede8;">{amount_str}</span></td>
                                            </tr>
                                            <tr>
                                                <td><strong>Lý do hủy:</strong></td>
                                                <td><span style="color: #f0ede8;">{reason_display}</span></td>
                                            </tr>
                                        </table>
                                    </div>

                                    <div style="margin-top: 20px; padding: 14px; background: rgba(232, 184, 75, 0.1); border: 1px solid rgba(232, 184, 75, 0.2); border-radius: 10px; text-align: center; font-size: 13px; color: #fef08a;">
                                        Cảm ơn bạn đã lựa chọn dịch vụ của <strong>CineVerse</strong>. Nếu có bất kỳ thắc mắc hoặc cần hỗ trợ thêm, vui lòng liên hệ tổng đài CSKH: <strong>1900-CINEVERSE</strong>.
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
    def send_cash_cancellation_email(
        cls,
        user_email: str,
        ticket_code: str,
        movie_title: str,
        amount: Any,
        reason: str = "Khách hàng huỷ vé",
    ) -> bool:
        """
        Thread-safe email dispatch for Cash payment ticket cancellation.
        """
        if not user_email:
            logger.warning("cash_cancel_email_skipped_no_email", ticket_code=ticket_code)
            return False

        if not settings.EMAIL_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info(
                "cash_cancel_email_logged_dev_mode",
                recipient=user_email,
                ticket_code=ticket_code,
                reason=reason,
            )
            return True

        try:
            from_email = settings.SMTP_USER or settings.EMAILS_FROM_EMAIL
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"❌ THÔNG BÁO HỦY VÉ THÀNH CÔNG - Vé {ticket_code} (CineVerse)"
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{from_email}>"
            msg["To"] = user_email

            html_content = cls.build_cash_cancellation_email_html(ticket_code, movie_title, amount, reason)
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info("cash_cancel_email_sent_successfully", recipient=user_email, ticket_code=ticket_code)
            return True
        except Exception as e:
            logger.exception("cash_cancel_email_send_failed", recipient=user_email, ticket_code=ticket_code, error=str(e))
            return False

    @classmethod
    def build_password_changed_email_html(cls, full_name: str) -> str:
        """Build HTML email alert for successful password change."""
        now_str = datetime.now(VN_TZ).strftime("%H:%M:%S ngày %d/%m/%Y")
        return f"""
        <!DOCTYPE html>
        <html lang="vi">
        <head><meta charset="UTF-8"><title>Cảnh báo bảo mật mật khẩu</title></head>
        <body style="margin: 0; padding: 0; background-color: #08080c; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f0ede8;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #08080c; padding: 40px 16px;">
                <tr>
                    <td align="center">
                        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 540px; background-color: #111118; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08);">
                            <tr>
                                <td style="padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.08);">
                                    <h1 style="margin: 0; font-size: 24px; font-weight: 900; color: #ff2a5f; letter-spacing: 1px;">CINEVERSE</h1>
                                    <p style="margin: 6px 0 0; font-size: 13px; color: #a09d98;">CẢNH BÁO BẢO MẬT TÀI KHOẢN</p>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 32px;">
                                    <div style="width: 56px; height: 56px; background-color: rgba(16, 185, 129, 0.15); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 50%; margin: 0 auto 20px; text-align: center; line-height: 56px; font-size: 24px;">🔐</div>
                                    <h2 style="margin: 0 0 12px; font-size: 18px; font-weight: 700; text-align: center; color: #ffffff;">Mật khẩu tài khoản đã được thay đổi</h2>
                                    <p style="margin: 0 0 20px; font-size: 14px; line-height: 1.6; color: #c4c1ba; text-align: center;">
                                        Xin chào <strong>{full_name}</strong>,<br>
                                        Mật khẩu tài khoản CineVerse của bạn đã được thay đổi thành công vào lúc <strong>{now_str}</strong>.
                                    </p>
                                    <div style="background-color: rgba(255, 42, 95, 0.08); border: 1px solid rgba(255, 42, 95, 0.25); border-radius: 12px; padding: 16px; margin-bottom: 24px;">
                                        <p style="margin: 0; font-size: 13px; line-height: 1.5; color: #ff859d;">
                                            ⚠️ <strong>Bạn không thực hiện thay đổi này?</strong><br>
                                            Vui lòng liên hệ ngay với Hotline <strong>1900-CINEVERSE</strong> hoặc sử dụng chức năng Quên mật khẩu để bảo vệ tài khoản ngay lập tức.
                                        </p>
                                    </div>
                                </td>
                            </tr>
                            <tr>
                                <td style="background-color: #0d0d14; padding: 16px 24px; text-align: center; border-top: 1px solid rgba(255,255,255,0.08);">
                                    <p style="margin: 0; font-size: 11px; color: #6e6c68;">CineVerse Cinema · Hotline: 1900-CINEVERSE</p>
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
    def send_password_changed_alert_email(cls, user_email: str, full_name: str) -> bool:
        """FEAT-05: Dispatch security alert email when user password is changed."""
        if not user_email:
            return False
        if not settings.EMAIL_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info("pwd_changed_email_logged_dev_mode", recipient=user_email)
            return True
        try:
            from_email = settings.SMTP_USER or settings.EMAILS_FROM_EMAIL
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "🔐 [CineVerse] Cảnh báo: Mật khẩu của bạn vừa được thay đổi"
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{from_email}>"
            msg["To"] = user_email
            html_content = cls.build_password_changed_email_html(full_name)
            msg.attach(MIMEText(html_content, "html", "utf-8"))
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info("pwd_changed_email_sent_successfully", recipient=user_email)
            return True
        except Exception as e:
            logger.exception("pwd_changed_email_send_failed", recipient=user_email, error=str(e))
            return False

    @classmethod
    def build_password_reset_email_html(cls, full_name: str, reset_url: str) -> str:
        """Build HTML email template for password reset."""
        return f"""
        <!DOCTYPE html>
        <html lang="vi">
        <head><meta charset="UTF-8"><title>Đặt lại mật khẩu CineVerse</title></head>
        <body style="margin: 0; padding: 0; background-color: #08080c; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #f0ede8;">
            <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #08080c; padding: 40px 16px;">
                <tr>
                    <td align="center">
                        <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 540px; background-color: #111118; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08);">
                            <tr>
                                <td style="padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.08);">
                                    <h1 style="margin: 0; font-size: 24px; font-weight: 900; color: #ff2a5f; letter-spacing: 1px;">CINEVERSE</h1>
                                    <p style="margin: 6px 0 0; font-size: 13px; color: #a09d98;">YÊU CẦU ĐẶT LẠI MẬT KHẨU</p>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 32px; text-align: center;">
                                    <div style="width: 56px; height: 56px; background-color: rgba(255, 42, 95, 0.15); border: 1px solid rgba(255, 42, 95, 0.3); border-radius: 50%; margin: 0 auto 20px; text-align: center; line-height: 56px; font-size: 24px;">🔑</div>
                                    <h2 style="margin: 0 0 12px; font-size: 18px; font-weight: 700; color: #ffffff;">Khôi phục mật khẩu tài khoản</h2>
                                    <p style="margin: 0 0 24px; font-size: 14px; line-height: 1.6; color: #c4c1ba;">
                                        Xin chào <strong>{full_name}</strong>,<br>
                                        Chúng tôi nhận được yêu cầu đặt lại mật khẩu cho tài khoản CineVerse của bạn. Nhấn vào nút bên dưới để tạo mật khẩu mới (liên kết có hiệu lực trong <strong>15 phút</strong>):
                                    </p>
                                    <div style="margin: 28px 0;">
                                        <a href="{reset_url}" target="_blank" style="display: inline-block; background-color: #ff2a5f; color: #ffffff; text-decoration: none; padding: 14px 32px; font-size: 14px; font-weight: 700; border-radius: 12px; box-shadow: 0 4px 14px rgba(255, 42, 95, 0.4);">
                                            👉 Đặt lại mật khẩu ngay
                                        </a>
                                    </div>
                                    <p style="margin: 24px 0 0; font-size: 12px; line-height: 1.5; color: #8e8b84;">
                                        Nếu bạn không yêu cầu đặt lại mật khẩu, bạn có thể yên tâm bỏ qua email này. Mật khẩu hiện tại của bạn vẫn được giữ an toàn.
                                    </p>
                                </td>
                            </tr>
                            <tr>
                                <td style="background-color: #0d0d14; padding: 16px 24px; text-align: center; border-top: 1px solid rgba(255,255,255,0.08);">
                                    <p style="margin: 0; font-size: 11px; color: #6e6c68;">CineVerse Cinema · Hotline: 1900-CINEVERSE</p>
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
    def send_password_reset_email(cls, user_email: str, full_name: str, reset_token: str, frontend_base_url: Optional[str] = None) -> bool:
        """FEAT-06: Dispatch password reset email with secure token link."""
        if not user_email:
            return False
        base_url = (frontend_base_url or settings.FRONTEND_BASE_URL).rstrip("/")
        reset_url = f"{base_url}?reset_token={reset_token}"
        if not settings.EMAIL_ENABLED or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info("pwd_reset_email_logged_dev_mode", recipient=user_email, reset_url=reset_url)
            return True
        try:
            from_email = settings.SMTP_USER or settings.EMAILS_FROM_EMAIL
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "🔑 [CineVerse] Yêu cầu đặt lại mật khẩu tài khoản"
            msg["From"] = f"{settings.EMAILS_FROM_NAME} <{from_email}>"
            msg["To"] = user_email
            html_content = cls.build_password_reset_email_html(full_name, reset_url)
            msg.attach(MIMEText(html_content, "html", "utf-8"))
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10.0) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            logger.info("pwd_reset_email_sent_successfully", recipient=user_email, reset_url=reset_url)
            return True
        except Exception as e:
            logger.exception("pwd_reset_email_send_failed", recipient=user_email, error=str(e))
            return False
