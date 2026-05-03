import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_to_md import pdf_to_md


def test_masagutov_pdf():
    pdf_path = "in_pdfs/01_Masagutov_s.pdf"
    md_content = pdf_to_md(pdf_path)
    assert "возможности для развития коллекторов" in md_content


def test_vyalov_pdf():
    pdf_path = "in_pdfs/01_Vyalov_7704kJ7.pdf"
    md_content = pdf_to_md(pdf_path)
    assert "исследованиями проб диктионемовых сланцев на целый" in md_content
