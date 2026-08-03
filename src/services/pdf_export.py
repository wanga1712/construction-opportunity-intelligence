"""PDF-выгрузка карточек компаний — 26 на лист A4 (52 на два листа, 2×13)."""
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from loguru import logger

from modules.crm.analytics.analytics_models import DesignerAnalytics
from modules.crm.analytics.designer_profile_constants import (
    COMPANY_CATEGORY_LABELS,
    REGISTRY_LABELS,
)
from src.ui.company_title import get_company_display_name

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

CARDS_PER_SHEET = 26
CARDS_PER_SPREAD = 52
CARDS_PER_PAGE = CARDS_PER_SHEET
COLS = 2
ROWS = 13

PDF_SEGMENT_LEGEND = (
    "Ж — жилые объекты · С — социальные · К — коммерческие · Пр — прочие "
    "(цифра — количество объектов) · ND всего/строится — NashDom"
)


@dataclass
class CompanyPdfCard:
    """Краткая карточка для PDF."""
    full_name: str
    inn: str
    region: str
    nashdom_count: int
    nashdom_active: int
    residential: int
    social: int
    commercial: int
    other: int
    category_label: str
    grade: str
    registry_label: str
    website: Optional[str] = None


def card_from_company(company: DesignerAnalytics) -> CompanyPdfCard:
    return CompanyPdfCard(
        full_name=get_company_display_name(company),
        inn=company.inn,
        region=company.region or "—",
        nashdom_count=company.nashdom_count,
        nashdom_active=company.nashdom_active,
        residential=company.segments.residential,
        social=company.segments.social,
        commercial=company.segments.commercial,
        other=company.segments.other,
        category_label=COMPANY_CATEGORY_LABELS.get(
            company.company_category or "", "—"
        ),
        grade=company.company_grade or "—",
        registry_label=REGISTRY_LABELS.get(company.registry or "", "—"),
        website=company.website,
    )


class CompaniesPdfExporter:
    """Компактные карточки: 26 на лист A4 (52 на разворот из двух листов)."""

    PAGE_W, PAGE_H = A4
    MARGIN = 8 * mm
    HEADER_H = 12 * mm
    CARD_GAP = 1.2 * mm

    def __init__(self):
        self._font = "Helvetica"
        self._font_bold = "Helvetica-Bold"
        self._register_fonts()
        usable_h = self.PAGE_H - 2 * self.MARGIN - self.HEADER_H
        self.CARD_H = (usable_h - (ROWS - 1) * self.CARD_GAP) / ROWS
        usable_w = self.PAGE_W - 2 * self.MARGIN
        self.CARD_W = (usable_w - self.CARD_GAP) / COLS

    def build_pdf_bytes(self, items: List[CompanyPdfCard]) -> Optional[bytes]:
        if not REPORTLAB_AVAILABLE:
            logger.error("reportlab не установлен")
            return None
        if not items:
            return None

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        c.setTitle("Подборка компаний CRM")

        for page_start in range(0, len(items), CARDS_PER_PAGE):
            page_items = items[page_start : page_start + CARDS_PER_PAGE]
            self._draw_page(c, page_items, page_start // CARDS_PER_PAGE + 1)
            if page_start + CARDS_PER_PAGE < len(items):
                c.showPage()

        c.save()
        buffer.seek(0)
        return buffer.getvalue()

    def _draw_page(self, c, items: List[CompanyPdfCard], page_num: int) -> None:
        y_top = self.PAGE_H - self.MARGIN
        self._draw_header(c, y_top, page_num, len(items))

        y = y_top - self.HEADER_H
        x_positions = [
            self.MARGIN,
            self.MARGIN + self.CARD_W + self.CARD_GAP,
        ]

        for idx, item in enumerate(items):
            row = idx // COLS
            col = idx % COLS
            x = x_positions[col]
            card_y = y - (row + 1) * self.CARD_H - row * self.CARD_GAP
            self._draw_card(c, x, card_y, self.CARD_W, self.CARD_H, item)

    def _draw_header(self, c, y_top: float, page_num: int, count_on_page: int) -> None:
        c.setFont(self._font_bold, 11)
        c.setFillColor(colors.HexColor("#181818"))
        c.drawString(self.MARGIN, y_top - 3.5 * mm, "Подборка компаний CRM")

        c.setFont(self._font, 8)
        c.setFillColor(colors.HexColor("#706E6B"))
        right = (
            f"стр. {page_num} · {count_on_page} карточек · "
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        c.drawRightString(self.PAGE_W - self.MARGIN, y_top - 3.5 * mm, right)

        c.setFont(self._font, 6.5)
        c.setFillColor(colors.HexColor("#444444"))
        legend = self._fit_line(
            c,
            PDF_SEGMENT_LEGEND,
            self.PAGE_W - 2 * self.MARGIN,
            self._font,
            6.5,
        )
        c.drawString(self.MARGIN, y_top - 8.5 * mm, legend)

    def _draw_card(
        self, c, x: float, y: float, w: float, h: float, item: CompanyPdfCard
    ) -> None:
        border = colors.HexColor("#0176D3")
        muted = colors.HexColor("#706E6B")
        dark = colors.HexColor("#181818")

        c.setFillColor(colors.white)
        c.setStrokeColor(border)
        c.setLineWidth(0.4)
        c.roundRect(x, y, w, h, 1.5 * mm, fill=1, stroke=1)

        pad = 1.6 * mm
        tx = x + pad
        ty = y + h - pad
        text_w = w - 2 * pad
        compact = h < 10.5 * mm

        name_size = 7 if compact else 8
        meta_size = 5.8 if compact else 6.5
        name_max_lines = 2 if compact else 3
        name_line_h = 2.2 * mm if compact else 2.7 * mm
        meta_step = 2.35 * mm if compact else 3 * mm

        c.setFillColor(dark)
        name_lines = self._wrap_text(
            c, item.full_name, text_w, self._font_bold, name_size, max_lines=name_max_lines,
        )
        for i, line in enumerate(name_lines):
            c.setFont(self._font_bold, name_size)
            c.drawString(tx, ty - 2.4 * mm - i * name_line_h, line)

        meta_y = ty - 2.4 * mm - len(name_lines) * name_line_h - 0.8 * mm
        c.setFont(self._font, meta_size)
        c.setFillColor(muted)
        line1 = f"ИНН {item.inn} · {item.region}"
        c.drawString(tx, meta_y, self._fit_line(c, line1, text_w, self._font, meta_size))

        line2 = (
            f"ND {item.nashdom_count}/{item.nashdom_active} · "
            f"Ж{item.residential} С{item.social} К{item.commercial}"
        )
        if item.other:
            line2 += f" Пр{item.other}"
        line2 += f" · {item.category_label} · {item.grade} · {item.registry_label}"
        c.drawString(tx, meta_y - meta_step, self._fit_line(c, line2, text_w, self._font, meta_size))

        if item.website and not compact and meta_y - 2 * meta_step > y + pad:
            c.setFillColor(colors.HexColor("#0176D3"))
            c.drawString(
                tx, meta_y - 2 * meta_step,
                self._fit_line(c, item.website, text_w, self._font, meta_size),
            )

    @staticmethod
    def _fit_line(c, text: str, max_width: float, font: str, size: float) -> str:
        text = " ".join(str(text).split())
        if c.stringWidth(text, font, size) <= max_width:
            return text
        trimmed = text
        while trimmed and c.stringWidth(trimmed + "…", font, size) > max_width:
            trimmed = trimmed[:-1]
        return (trimmed + "…") if trimmed else "…"

    def _wrap_text(
        self,
        c,
        text: str,
        max_width: float,
        font: str,
        size: float,
        max_lines: int = 3,
    ) -> List[str]:
        text = " ".join(str(text).split())
        if not text:
            return ["—"]

        words = text.split()
        lines: List[str] = []
        current = ""

        for word in words:
            candidate = f"{current} {word}".strip() if current else word
            if c.stringWidth(candidate, font, size) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                if len(lines) >= max_lines:
                    current = word
                    break
            current = word

        if len(lines) < max_lines and current:
            lines.append(current)

        if not lines:
            return ["—"]

        used = sum(len(line.split()) for line in lines)
        if used < len(words):
            last = lines[-1]
            while last and c.stringWidth(last + "…", font, size) > max_width:
                last = last[:-1]
            lines[-1] = f"{last}…" if last else "…"

        return lines

    def _register_fonts(self) -> None:
        if not REPORTLAB_AVAILABLE:
            return
        candidates = [
            ("Arial", "C:/Windows/Fonts/arial.ttf"),
            ("Arial-Bold", "C:/Windows/Fonts/arialbd.ttf"),
        ]
        registered = {}
        for name, path in candidates:
            if Path(path).exists():
                try:
                    pdfmetrics.registerFont(TTFont(name, path))
                    registered[name] = True
                except Exception as e:
                    logger.debug(f"Шрифт {name}: {e}")
        if registered.get("Arial"):
            self._font = "Arial"
            self._font_bold = "Arial-Bold" if registered.get("Arial-Bold") else "Arial"
