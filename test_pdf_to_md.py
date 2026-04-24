#!/usr/bin/env python3
"""Tests for PDF to Markdown converter."""

import os
import pytest
from pdf_to_md import normalize_text, pdf_to_md, process_folder


def test_normalize_text_removes_line_breaks_in_paragraphs():
    """Test that line breaks within paragraphs are removed."""
    text = "This is a sentence that is\nbroken across lines and should\nbe joined."
    result = normalize_text(text)
    assert 'broken across lines and should be joined' in result


def test_normalize_text_hyphenated_words():
    """Test that hyphenated words at line breaks are joined."""
    text = "This is a hyphen-\nated word that should be joined."
    result = normalize_text(text)
    assert 'hyphenated' in result
    assert 'hyphen-' not in result


def test_normalize_text_preserves_paragraphs():
    """Test that paragraph separation is preserved."""
    text = "First paragraph here.\n\nSecond paragraph here."
    result = normalize_text(text)
    assert '\n\n' in result


def test_normalize_text_removes_extra_spaces():
    """Test that multiple spaces are reduced to one."""
    text = "Multiple    spaces    here"
    result = normalize_text(text)
    assert 'Multiple spaces here' in result


def test_pdf_to_md_creates_output_file():
    """Test that PDF to MD conversion creates output file."""
    input_dir = 'in_pdfs'
    output_dir = 'test_out'
    
    test_file = os.path.join(input_dir, '01_Masagutov_s.pdf')
    
    if not os.path.exists(test_file):
        pytest.skip('Test PDF file not found')
    
    md_path = pdf_to_md(test_file, output_dir)
    
    assert os.path.exists(md_path)
    assert md_path.endswith('.md')
    
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert 'возможности для развития коллекторов' in content


def test_pdf_to_md_vyalov_file():
    """Test Vyalov PDF file contains expected text."""
    input_dir = 'in_pdfs'
    output_dir = 'test_out'
    
    test_file = os.path.join(input_dir, '01_Vyalov_7704kJ7.pdf')
    
    if not os.path.exists(test_file):
        pytest.skip('Test PDF file not found')
    
    md_path = pdf_to_md(test_file, output_dir)
    
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert 'исследованиями проб диктионемовых сланцев на целый' in content


def test_process_folder_processes_all_pdfs():
    """Test that process_folder converts all PDF files."""
    input_dir = 'in_pdfs'
    output_dir = 'test_out'
    
    result_files = process_folder(input_dir, output_dir)
    
    pdf_files = [f for f in os.listdir(input_dir) if f.endswith('.pdf')]
    assert len(result_files) == len(pdf_files)
    
    for md_file in result_files:
        assert os.path.exists(md_file)


def test_normalize_text_empty_input():
    """Test normalize_text with empty input."""
    result = normalize_text('')
    assert result == ''


def test_normalize_text_only_whitespace():
    """Test normalize_text with only whitespace."""
    text = '   \n\t\n   '
    result = normalize_text(text)
    assert result == ''


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
