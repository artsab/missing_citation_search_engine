#!/usr/bin/env python3
"""
Семантический поиск по архиву научных статей.
Находит в архиве похожие статьи на основе текстового контекста.
"""

import os
import re
from pathlib import Path
from typing import List, Dict, Tuple

import pdfplumber
import numpy as np
from sentence_transformers import SentenceTransformer, util


class ArticleArchive:
    """Архив научных статей для семантического поиска."""
    
    def __init__(self, archive_dir: str, output_dir: str = 'out_md'):
        """
        Инициализация архива статей.
        
        Args:
            archive_dir: Путь к папке с PDF файлами архива
            output_dir: Путь к папке с извлеченными текстами MD
        """
        self.archive_dir = Path(archive_dir)
        self.output_dir = Path(output_dir)
        self.model = SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')
        self.articles: Dict[str, Dict] = {}
        self.embeddings = None
        self.article_ids: List[str] = []
        
    def extract_text(self, pdf_path: Path) -> str:
        """Извлечение текста из PDF файла."""
        text_parts = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ''
                    text_parts.append(text)
        except Exception as e:
            print(f"Ошибка при извлечении текста из {pdf_path}: {e}")
            return ''
        
        full_text = '\n\n'.join(text_parts)
        
        if full_text:
            try:
                first_char = full_text[0]
                if first_char and ord(first_char) > 127:
                    first_bytes = first_char.encode('utf-8')
                    if len(first_bytes) == 2 and first_bytes[0] == 0xc3:
                        full_text = full_text.encode('latin-1', errors='replace').decode('cp1251', errors='replace')
            except Exception:
                pass
        
        return self._normalize_text(full_text)
    
    def _normalize_text(self, text: str) -> str:
        """Нормализация текста."""
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
    
    def load_archive(self, force_reload: bool = False) -> None:
        """
        Загрузка архива статей из папки или из уже извлеченных MD файлов.
        
        Args:
            force_reload: Если True, пересоздать embeddings
        """
        archive_dir = self.output_dir
        
        if not archive_dir.exists():
            print(f"Папка с выходными файлами не найдена: {archive_dir}")
            return
        
        self.articles = {}
        self.article_ids = []
        
        for md_file in archive_dir.glob('*.md'):
            article_id = md_file.stem
            with open(md_file, 'r', encoding='utf-8') as f:
                text = f.read()
            
            self.articles[article_id] = {
                'path': str(md_file),
                'text': text,
                'filename': md_file.name
            }
            self.article_ids.append(article_id)
        
        print(f"Загружено {len(self.articles)} статей из архива")
    
    def create_embeddings(self, force_rebuild: bool = False) -> None:
        """Создание эмбеддингов для всех статей в архиве."""
        if not self.articles:
            self.load_archive()
        
        if self.embeddings is not None and not force_rebuild:
            return
        
        texts = [self.articles[aid]['text'] for aid in self.article_ids]
        
        print("Создание эмбеддингов для статей...")
        self.embeddings = self.model.encode(texts, convert_to_tensor=True, show_progress_bar=True)
        print(f"Создано {len(self.embeddings)} эмбеддингов")
    
    def find_similar_articles(
        self, 
        query_text: str,
        top_k: int = 5,
        min_similarity: float = 0.4
    ) -> List[Tuple[str, float, str]]:
        """
        Поиск похожих статей в архиве.
        
        Args:
            query_text: Текст запроса (текст из новой статьи)
            top_k: Количество результатов
            min_similarity: Минимальный порог схожести
            
        Returns:
            Список кортежей (article_id, similarity_score, highlighted_text)
        """
        if self.embeddings is None:
            self.create_embeddings()
        
        query_embedding = self.model.encode(query_text, convert_to_tensor=True)
        
        similarities = util.cos_sim(query_embedding, self.embeddings)[0]
        
        results = []
        for idx, score in enumerate(similarities):
            if score >= min_similarity:
                article_id = self.article_ids[idx]
                results.append((article_id, float(score), self.articles[article_id]['path']))
        
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:top_k]
    
    def analyze_new_article(
        self,
        pdf_path: str,
        top_k: int = 5,
        min_similarity: float = 0.4
    ) -> Dict:
        """
        Анализ новой статьи и поиск похожих в архиве.
        
        Args:
            pdf_path: Путь к новой статье PDF
            top_k: Количество результатов
            min_similarity: Минимальный порог схожести
            
        Returns:
            Словарь с результатами анализа
        """
        pdf_path = Path(pdf_path)
        text = self.extract_text(pdf_path)
        
        if not text:
            return {'error': 'Не удалось извлечь текст из статьи'}
        
        sections = self._split_into_sections(text)
        
        recommendations = []
        for section_name, section_text in sections.items():
            similar = self.find_similar_articles(section_text, top_k, min_similarity)
            if similar:
                for article_id, similarity, path in similar:
                    recommendations.append({
                        'section': section_name,
                        'text': section_text[:200] + '...',
                        'found_in': article_id,
                        'similarity': round(similarity, 3),
                        'path': path
                    })
        
        return {
            'total_sections': len(sections),
            'total_recommendations': len(recommendations),
            'recommendations': recommendations
        }
    
    def _split_into_sections(self, text: str) -> Dict[str, str]:
        """Разделение текста на логические секции для более точного поиска."""
        sections = {}
        
        lines = text.split('\n')
        
        current_section = 'Введение'
        current_text = []
        
        for line in lines:
            line_stripped = line.strip()
            
            if not line_stripped:
                continue
            
            keywords = {
                'Введение': ['введение', 'в paper', 'paper', 'для'],
                'Методы': ['материалы', 'методы', 'методика', 'анализ'],
                'Результаты': ['результаты', 'получены', 'представлены', 'показано'],
                'Обсуждение': ['обсуждение', 'анализ', 'сравнение', 'возможности'],
                'Заключение': ['заключение', 'выводы', 'считаем', 'целесообразно'],
                'Литература': ['литература', 'references', 'источники']
            }
            
            found_section = None
            for section_name, keywords_list in keywords.items():
                if any(kw in line_stripped.lower() for kw in keywords_list):
                    if current_text:
                        sections[current_section] = ' '.join(current_text)
                    current_section = section_name
                    current_text = []
                    found_section = True
                    break
            
            if not found_section:
                current_text.append(line_stripped)
        
        if current_text:
            sections[current_section] = ' '.join(current_text)
        
        return sections


def main():
    """Основная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Семантический поиск по архиву статей')
    parser.add_argument('pdf_path', help='Путь к новой статье в формате PDF')
    parser.add_argument('--archive', default='in_pdfs', help='Путь к папке с архивом PDF')
    parser.add_argument('--md-output', default='out_md', help='Путь к папке с извлеченными MD файлами')
    parser.add_argument('--top-k', type=int, default=5, help='Количество результатов')
    parser.add_argument('--min-sim', type=float, default=0.4, help='Минимальная схожесть (0-1)')
    
    args = parser.parse_args()
    
    archive = ArticleArchive(args.archive, args.md_output)
    archive.load_archive()
    archive.create_embeddings()
    
    print(f"\nАнализ статьи: {args.pdf_path}\n")
    
    results = archive.analyze_new_article(
        args.pdf_path,
        top_k=args.top_k,
        min_similarity=args.min_sim
    )
    
    if 'error' in results:
        print(f"Ошибка: {results['error']}")
        return
    
    print(f"Найдено секций: {results['total_sections']}")
    print(f"Итоговых рекомендаций: {results['total_recommendations']}")
    print("\nРекомендации для цитирования:")
    print("-" * 80)
    
    for rec in results['recommendations'][:10]:
        print(f"\nСекция: {rec['section']}")
        print(f"Извлеченный текст: {rec['text']}")
        print(f"Похожая статья: {rec['found_in']}")
        print(f"Схожесть: {rec['similarity']:.3f}")
        print(f"Путь: {rec['path']}")


if __name__ == '__main__':
    main()
