#!/usr/bin/env python3
"""PDF to Markdown converter script."""

import os
import re
import pdfplumber


def normalize_text(text: str) -> str:
    """Normalize extracted text from PDF."""
    lines = text.split('\n')
    
    normalized_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if not line.strip():
            normalized_lines.append('')
            i += 1
            continue
        
        should_continue = True
        while should_continue:
            should_continue = False
            
            if i + 1 < len(lines):
                next_line = lines[i + 1]
                
                if line.endswith('-') and next_line.strip():
                    line = line[:-1] + next_line.strip()
                    i += 1
                    should_continue = True
                    continue
                
                if line and not line.endswith(('.', '!', '?', ':', ';', '}', ']', ')')) and next_line.strip():
                    first_char_next = next_line.strip()[0]
                    if first_char_next.islower() or first_char_next.isalpha():
                        line = line.rstrip() + ' ' + next_line.strip()
                        i += 1
                        should_continue = True
        
        normalized_lines.append(line)
        i += 1
    
    text = '\n'.join(normalized_lines)
    
    text = re.sub(r'[ \t]+', ' ', text)
    
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    
    return text.strip()


def pdf_to_md(pdf_path: str, output_dir: str) -> str:
    """Convert PDF file to Markdown format."""
    os.makedirs(output_dir, exist_ok=True)
    
    with pdfplumber.open(pdf_path) as pdf:
        pages_text = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
    
    full_text = '\n\n'.join(pages_text)
    
    if full_text:
        try:
            first_char = full_text[0]
            if first_char and ord(first_char) > 127:
                first_bytes = first_char.encode('utf-8')
                if len(first_bytes) == 2 and first_bytes[0] == 0xc3:
                    full_text = full_text.encode('latin-1', errors='replace').decode('cp1251', errors='replace')
        except Exception:
            pass
    
    normalized_text = normalize_text(full_text)
    
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    md_path = os.path.join(output_dir, f'{base_name}.md')
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(normalized_text)
    
    return md_path


def process_folder(input_dir: str, output_dir: str) -> list:
    """Process all PDF files in a folder."""
    os.makedirs(output_dir, exist_ok=True)
    
    results = []
    for filename in os.listdir(input_dir):
        if filename.lower().endswith('.pdf'):
            pdf_path = os.path.join(input_dir, filename)
            md_path = pdf_to_md(pdf_path, output_dir)
            results.append(md_path)
    
    return results


if __name__ == '__main__':
    input_folder = 'in_pdfs'
    output_folder = 'out_md'
    
    converted_files = process_folder(input_folder, output_folder)
    print(f'Converted {len(converted_files)} PDF files to Markdown')
