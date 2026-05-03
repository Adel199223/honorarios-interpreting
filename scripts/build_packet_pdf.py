from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class PacketError(ValueError):
    """Raised when a packet PDF cannot be built."""


def image_pdf_buffer(image_path: Path) -> BytesIO:
    image = ImageReader(str(image_path))
    image_width, image_height = image.getSize()
    page_width, page_height = A4
    margin = 16 * mm
    max_width = page_width - 2 * margin
    max_height = page_height - 2 * margin
    scale = min(max_width / image_width, max_height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    x = (page_width - draw_width) / 2
    y = (page_height - draw_height) / 2

    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    page.drawImage(image, x, y, width=draw_width, height=draw_height, preserveAspectRatio=True, mask="auto")
    page.showPage()
    page.save()
    buffer.seek(0)
    return buffer


def add_pdf_pages(writer: PdfWriter, path: Path) -> None:
    reader = PdfReader(str(path))
    for page in reader.pages:
        writer.add_page(page)


def add_image_page(writer: PdfWriter, path: Path) -> None:
    reader = PdfReader(image_pdf_buffer(path))
    writer.add_page(reader.pages[0])


def build_packet_pdf(items: list[Path], output: Path) -> int:
    if not items:
        raise PacketError("At least one packet item is required.")

    writer = PdfWriter()
    for item in items:
        path = item.resolve()
        if not path.exists():
            raise PacketError(f"Packet item does not exist: {path}")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            add_pdf_pages(writer, path)
        elif suffix in IMAGE_SUFFIXES:
            add_image_page(writer, path)
        else:
            raise PacketError(f"Unsupported packet item type: {path}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        writer.write(handle)
    return len(writer.pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a single PDF packet from PDFs and declaration images.")
    parser.add_argument("items", nargs="+", type=Path, help="PDF/image files, in packet order.")
    parser.add_argument("--output", required=True, type=Path, help="Combined packet PDF path.")
    args = parser.parse_args(argv)

    try:
        pages = build_packet_pdf(args.items, args.output)
    except (OSError, PacketError) as exc:
        print(f"Cannot build packet PDF: {exc}", file=sys.stderr)
        return 2

    print(f"Packet PDF: {args.output}")
    print(f"Pages: {pages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
