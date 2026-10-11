"""The single predefined certificate template.

render_certificate() draws one landscape A4 PDF with ReportLab. It knows
nothing about jobs or the database, which keeps it easy to test and to swap
for a different design later.
"""

from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
CENTER_X = PAGE_WIDTH / 2

NAVY = HexColor("#1F3A5F")
GOLD = HexColor("#B8860B")
GREY = HexColor("#555555")


class CertificateRenderError(Exception):
    """Raised when a certificate cannot be drawn with the given data."""


def _check_supported(label: str, text: str) -> None:
    # The template uses the built-in Helvetica/Times fonts, which only cover
    # Western European characters. Anything else would be drawn as black boxes,
    # so we fail loudly rather than hand out a broken certificate.
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        raise CertificateRenderError(
            f"{label} contains characters the certificate font cannot display: {text!r}"
        ) from None


def _fit_font_size(text: str, font: str, max_size: float, max_width: float) -> float:
    """Shrink the font until the text fits on one line (long names)."""
    size = max_size
    while size > 12 and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def render_certificate(
    output_path: Path,
    *,
    recipient_name: str,
    course_name: str,
    issued_by: str,
    issue_date: date,
    certificate_id: str,
) -> None:
    """Draw the certificate and save it as a PDF at output_path."""
    _check_supported("Recipient name", recipient_name)
    _check_supported("Course name", course_name)
    _check_supported("Issuer name", issued_by)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output_path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    pdf.setTitle(f"Certificate - {recipient_name}")
    pdf.setAuthor(issued_by)

    # Double border
    pdf.setStrokeColor(NAVY)
    pdf.setLineWidth(4)
    pdf.rect(30, 30, PAGE_WIDTH - 60, PAGE_HEIGHT - 60)
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(1.5)
    pdf.rect(42, 42, PAGE_WIDTH - 84, PAGE_HEIGHT - 84)

    # Heading
    pdf.setFillColor(NAVY)
    pdf.setFont("Times-Bold", 38)
    pdf.drawCentredString(CENTER_X, PAGE_HEIGHT - 135, "CERTIFICATE OF COMPLETION")

    pdf.setFillColor(GREY)
    pdf.setFont("Helvetica", 15)
    pdf.drawCentredString(CENTER_X, PAGE_HEIGHT - 190, "This is to certify that")

    # Recipient name, shrunk if needed so it never overflows the border
    max_text_width = PAGE_WIDTH - 180
    name_size = _fit_font_size(recipient_name, "Times-BoldItalic", 40, max_text_width)
    pdf.setFillColor(NAVY)
    pdf.setFont("Times-BoldItalic", name_size)
    pdf.drawCentredString(CENTER_X, PAGE_HEIGHT - 250, recipient_name)
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(1)
    pdf.line(CENTER_X - 200, PAGE_HEIGHT - 265, CENTER_X + 200, PAGE_HEIGHT - 265)

    pdf.setFillColor(GREY)
    pdf.setFont("Helvetica", 15)
    pdf.drawCentredString(CENTER_X, PAGE_HEIGHT - 305, "has successfully completed")

    course_size = _fit_font_size(course_name, "Helvetica-Bold", 24, max_text_width)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", course_size)
    pdf.drawCentredString(CENTER_X, PAGE_HEIGHT - 345, course_name)

    # Footer: date on the left, issuer on the right
    footer_y = 115
    left_x, right_x = 190, PAGE_WIDTH - 190
    pdf.setStrokeColor(GREY)
    pdf.line(left_x - 90, footer_y, left_x + 90, footer_y)
    pdf.line(right_x - 90, footer_y, right_x + 90, footer_y)

    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(left_x, footer_y + 8, issue_date.strftime("%d %B %Y"))
    issuer_size = _fit_font_size(issued_by, "Helvetica-Bold", 13, 220)
    pdf.setFont("Helvetica-Bold", issuer_size)
    pdf.drawCentredString(right_x, footer_y + 8, issued_by)

    pdf.setFillColor(GREY)
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(left_x, footer_y - 15, "Date of issue")
    pdf.drawCentredString(right_x, footer_y - 15, "Issued by")

    pdf.setFont("Helvetica", 8)
    pdf.drawCentredString(CENTER_X, 55, f"Certificate ID: {certificate_id}")

    pdf.showPage()
    pdf.save()
