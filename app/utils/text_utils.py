#!/usr/bin/env python3
"""
Utilitários de Processamento de Texto
=====================================

Funções utilitárias para:
- Limpeza e normalização de texto
- Correções de OCR
- Análise de qualidade de texto
- Formatação e conversão
- Detecção de idioma
- Métricas de texto
"""

import re
import string
import unicodedata
import logging
from typing import Dict, Any, List, Optional, Tuple, Union
from collections import Counter, defaultdict
import statistics

logger = logging.getLogger(__name__)


def clean_ocr_text(text: str, aggressive: bool = False) -> str:
    """
    Limpa texto extraído por OCR
    
    Args:
        text: Texto a ser limpo
        aggressive: Se deve aplicar limpeza agressiva
        
    Returns:
        Texto limpo
    """
    if not text:
        return ""
    
    try:
        # Remover caracteres de controle
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', text)
        
        # Normalizar espaços em branco
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
        
        # Correções básicas de OCR
        cleaned = apply_basic_ocr_corrections(cleaned)
        
        if aggressive:
            # Limpeza mais agressiva
            cleaned = apply_aggressive_corrections(cleaned)
        
        return cleaned.strip()
        
    except Exception as e:
        logger.warning(f"Text cleaning failed: {e}")
        return text


def apply_basic_ocr_corrections(text: str) -> str:
    """
    Aplica correções básicas comuns de OCR
    
    Args:
        text: Texto a ser corrigido
        
    Returns:
        Texto corrigido
    """
    corrections = {
        # Correções de caracteres individuais
        r'\b0\b(?=[a-zA-Z])': 'O',  # 0 -> O quando seguido de letra
        r'\b1\b(?=[a-zA-Z])': 'l',  # 1 -> l quando seguido de letra
        r'\brn\b': 'm',             # rn -> m
        r'\bvv\b': 'w',             # vv -> w
        r'\bii\b': 'ii',            # manter ii como está
        
        # Correções de pontuação
        r'\.{3,}': '...',           # Múltiplos pontos
        r'\,{2,}': ',',             # Múltiplas vírgulas
        r'\!{2,}': '!',             # Múltiplas exclamações
        r'\?{2,}': '?',             # Múltiplas interrogações
        
        # Espaços antes de pontuação
        r'\s+([.!?,:;])': r'\1',
        
        # Espaços após parênteses/colchetes de abertura
        r'([\(\[\{])\s+': r'\1',
        r'\s+([\)\]\}])': r'\1',
        
        # Aspas
        r'``': '"',
        r"''": '"',
        
        # Hífens e travessões
        r'--+': '—',
    }
    
    for pattern, replacement in corrections.items():
        text = re.sub(pattern, replacement, text)
    
    return text


def apply_aggressive_corrections(text: str) -> str:
    """
    Aplica correções mais agressivas (pode ter falsos positivos)
    
    Args:
        text: Texto a ser corrigido
        
    Returns:
        Texto corrigido
    """
    try:
        # Remover caracteres isolados suspeitos
        text = re.sub(r'\b[^\w\s]{1,2}\b', '', text)
        
        # Remover múltiplos espaços
        text = re.sub(r' {3,}', ' ', text)
        
        # Correções específicas para português
        portuguese_corrections = {
            r'\bca\b': 'ca',  # Preservar
            r'\bda\b': 'da',  # Preservar
            r'\bde\b': 'de',  # Preservar
            r'\bdo\b': 'do',  # Preservar
            r'\bem\b': 'em',  # Preservar
            r'\bna\b': 'na',  # Preservar
            r'\bno\b': 'no',  # Preservar
            r'\bse\b': 'se',  # Preservar
            r'\bte\b': 'te',  # Preservar
        }
        
        for pattern, replacement in portuguese_corrections.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        return text
        
    except Exception as e:
        logger.warning(f"Aggressive corrections failed: {e}")
        return text


def normalize_whitespace(text: str, preserve_paragraphs: bool = True) -> str:
    """
    Normaliza espaços em branco no texto
    
    Args:
        text: Texto a ser normalizado
        preserve_paragraphs: Se deve preservar quebras de parágrafo
        
    Returns:
        Texto normalizado
    """
    if not text:
        return ""
    
    # Normalizar espaços
    text = re.sub(r'[ \t]+', ' ', text)
    
    if preserve_paragraphs:
        # Preservar quebras de parágrafo duplas
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'\n(?!\n)', ' ', text)
    else:
        # Transformar tudo em espaços simples
        text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    """
    Divide texto em sentenças
    
    Args:
        text: Texto a ser dividido
        
    Returns:
        Lista de sentenças
    """
    if not text:
        return []
    
    # Padrão para detectar fim de sentença
    sentence_pattern = r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÃÕÇ])'
    
    sentences = re.split(sentence_pattern, text)
    
    # Limpar sentenças vazias
    sentences = [s.strip() for s in sentences if s.strip()]
    
    return sentences


def split_into_paragraphs(text: str) -> List[str]:
    """
    Divide texto em parágrafos
    
    Args:
        text: Texto a ser dividido
        
    Returns:
        Lista de parágrafos
    """
    if not text:
        return []
    
    # Dividir por quebras duplas
    paragraphs = re.split(r'\n\s*\n', text)
    
    # Limpar parágrafos vazios
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    
    return paragraphs


def detect_language_simple(text: str) -> str:
    """
    Detecção simples de idioma baseada em características
    
    Args:
        text: Texto para análise
        
    Returns:
        Código do idioma detectado
    """
    if not text or len(text) < 10:
        return "unknown"
    
    text_lower = text.lower()
    
    # Características do português
    portuguese_indicators = [
        'ão', 'ção', 'são', 'não', 'com', 'para', 'uma', 'dos', 'das',
        'que', 'por', 'mais', 'tem', 'seu', 'sua', 'foi', 'ser', 'está'
    ]
    
    # Características do inglês
    english_indicators = [
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can',
        'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has',
        'him', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see'
    ]
    
    # Características do espanhol
    spanish_indicators = [
        'que', 'con', 'por', 'para', 'una', 'del', 'las', 'los', 'son',
        'está', 'como', 'más', 'pero', 'sus', 'años', 'muy', 'año'
    ]
    
    # Contar ocorrências
    pt_count = sum(1 for word in portuguese_indicators if word in text_lower)
    en_count = sum(1 for word in english_indicators if word in text_lower)
    es_count = sum(1 for word in spanish_indicators if word in text_lower)
    
    # Verificar acentos (forte indicador de português/espanhol)
    accent_count = len(re.findall(r'[áéíóúàèìòùâêîôûãõç]', text_lower))
    if accent_count > len(text) * 0.02:  # > 2% de caracteres acentuados
        if pt_count >= es_count:
            return "pt"
        else:
            return "es"
    
    # Decisão baseada em contagens
    if pt_count > en_count and pt_count > es_count:
        return "pt"
    elif en_count > pt_count and en_count > es_count:
        return "en"
    elif es_count > pt_count and es_count > en_count:
        return "es"
    
    return "unknown"


def calculate_text_quality_score(text: str) -> float:
    """
    Calcula score de qualidade do texto (0-10)
    
    Args:
        text: Texto para análise
        
    Returns:
        Score de qualidade
    """
    if not text:
        return 0.0
    
    try:
        score = 5.0  # Score base
        
        # Fatores positivos
        
        # Comprimento adequado
        if 100 <= len(text) <= 10000:
            score += 1.0
        elif len(text) > 50:
            score += 0.5
        
        # Proporção de letras vs outros caracteres
        letter_ratio = sum(1 for c in text if c.isalpha()) / len(text)
        if letter_ratio > 0.8:
            score += 1.0
        elif letter_ratio > 0.6:
            score += 0.5
        
        # Presença de palavras reconhecíveis
        words = text.split()
        if len(words) > 5:
            score += 0.5
        
        # Estrutura de frases (presença de pontuação)
        punctuation_ratio = sum(1 for c in text if c in '.!?') / max(len(words), 1)
        if 0.05 <= punctuation_ratio <= 0.3:  # Pontuação balanceada
            score += 0.5
        
        # Fatores negativos
        
        # Excesso de caracteres especiais
        special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace() and c not in '.,!?;:-()[]{}"\'/\\')
        special_ratio = special_chars / len(text)
        if special_ratio > 0.1:
            score -= 2.0
        elif special_ratio > 0.05:
            score -= 1.0
        
        # Excesso de dígitos
        digit_ratio = sum(1 for c in text if c.isdigit()) / len(text)
        if digit_ratio > 0.3:
            score -= 1.0
        
        # Excesso de maiúsculas
        upper_ratio = sum(1 for c in text if c.isupper()) / max(sum(1 for c in text if c.isalpha()), 1)
        if upper_ratio > 0.5:
            score -= 1.0
        
        # Repetições excessivas
        if has_excessive_repetition(text):
            score -= 1.0
        
        return max(0.0, min(10.0, score))
        
    except Exception as e:
        logger.warning(f"Quality score calculation failed: {e}")
        return 5.0


def has_excessive_repetition(text: str) -> bool:
    """
    Verifica se há repetições excessivas no texto
    
    Args:
        text: Texto para análise
        
    Returns:
        True se há repetições excessivas
    """
    if len(text) < 10:
        return False
    
    # Verificar caracteres repetidos
    char_pattern = r'(.)\1{4,}'  # 5 ou mais caracteres iguais seguidos
    if re.search(char_pattern, text):
        return True
    
    # Verificar palavras muito repetidas
    words = text.lower().split()
    if len(words) > 10:
        word_counts = Counter(words)
        most_common = word_counts.most_common(1)[0][1]
        if most_common > len(words) * 0.3:  # Palavra aparece em >30% do texto
            return True
    
    return False


def extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
    """
    Extrai palavras-chave do texto
    
    Args:
        text: Texto para análise
        max_keywords: Número máximo de palavras-chave
        
    Returns:
        Lista de palavras-chave
    """
    if not text:
        return []
    
    # Palavras comuns a serem ignoradas (stopwords básicas)
    stopwords = {
        'a', 'e', 'o', 'de', 'do', 'da', 'em', 'um', 'uma', 'para', 'com', 'por',
        'que', 'se', 'não', 'mais', 'como', 'mas', 'foi', 'ao', 'ele', 'das',
        'tem', 'à', 'seu', 'sua', 'ou', 'ser', 'quando', 'muito', 'há', 'nos',
        'já', 'está', 'eu', 'também', 'só', 'pelo', 'pela', 'até', 'isso',
        'ela', 'entre', 'era', 'depois', 'sem', 'mesmo', 'aos', 'ter', 'seus',
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'had',
        'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his',
        'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who'
    }
    
    # Limpar e tokenizar
    text_clean = re.sub(r'[^\w\s]', ' ', text.lower())
    words = text_clean.split()
    
    # Filtrar palavras
    filtered_words = [
        word for word in words 
        if len(word) > 3 and word not in stopwords and word.isalpha()
    ]
    
    # Contar frequências
    word_counts = Counter(filtered_words)
    
    # Retornar palavras mais frequentes
    keywords = [word for word, count in word_counts.most_common(max_keywords)]
    
    return keywords


def calculate_readability_score(text: str) -> Dict[str, float]:
    """
    Calcula métricas de legibilidade do texto
    
    Args:
        text: Texto para análise
        
    Returns:
        Dict com métricas de legibilidade
    """
    if not text:
        return {"words_per_sentence": 0, "chars_per_word": 0, "sentences": 0, "words": 0}
    
    try:
        sentences = split_into_sentences(text)
        words = text.split()
        
        # Métricas básicas
        num_sentences = len(sentences)
        num_words = len(words)
        num_chars = sum(len(word) for word in words)
        
        # Calcular métricas
        words_per_sentence = num_words / max(num_sentences, 1)
        chars_per_word = num_chars / max(num_words, 1)
        
        # Contagem de sílabas aproximada (para português)
        syllable_count = estimate_syllables(text)
        syllables_per_word = syllable_count / max(num_words, 1)
        
        return {
            "words_per_sentence": words_per_sentence,
            "chars_per_word": chars_per_word,
            "syllables_per_word": syllables_per_word,
            "sentences": num_sentences,
            "words": num_words,
            "syllables": syllable_count
        }
        
    except Exception as e:
        logger.warning(f"Readability calculation failed: {e}")
        return {"words_per_sentence": 0, "chars_per_word": 0, "sentences": 0, "words": 0}


def estimate_syllables(text: str) -> int:
    """
    Estima número de sílabas no texto (aproximação para português)
    
    Args:
        text: Texto para análise
        
    Returns:
        Número estimado de sílabas
    """
    if not text:
        return 0
    
    # Padrão simples: contar vogais
    vowels = 'aeiouáéíóúàèìòùâêîôûãõy'
    syllable_count = 0
    
    words = re.findall(r'\b\w+\b', text.lower())
    
    for word in words:
        word_syllables = 0
        prev_was_vowel = False
        
        for char in word:
            is_vowel = char in vowels
            if is_vowel and not prev_was_vowel:
                word_syllables += 1
            prev_was_vowel = is_vowel
        
        # Pelo menos uma sílaba por palavra
        syllable_count += max(1, word_syllables)
    
    return syllable_count


def remove_diacritics(text: str) -> str:
    """
    Remove acentos e diacríticos do texto
    
    Args:
        text: Texto a ser processado
        
    Returns:
        Texto sem acentos
    """
    if not text:
        return ""
    
    # Normalizar unicode e remover acentos
    normalized = unicodedata.normalize('NFD', text)
    without_accents = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
    
    return without_accents


def format_for_display(text: str, max_width: int = 80) -> str:
    """
    Formata texto para exibição com quebras de linha
    
    Args:
        text: Texto a ser formatado
        max_width: Largura máxima por linha
        
    Returns:
        Texto formatado
    """
    if not text:
        return ""
    
    paragraphs = split_into_paragraphs(text)
    formatted_paragraphs = []
    
    for paragraph in paragraphs:
        words = paragraph.split()
        lines = []
        current_line = []
        current_length = 0
        
        for word in words:
            word_length = len(word)
            
            if current_length + word_length + len(current_line) <= max_width:
                current_line.append(word)
                current_length += word_length
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]
                current_length = word_length
        
        if current_line:
            lines.append(' '.join(current_line))
        
        formatted_paragraphs.append('\n'.join(lines))
    
    return '\n\n'.join(formatted_paragraphs)


def extract_text_statistics(text: str) -> Dict[str, Any]:
    """
    Extrai estatísticas completas do texto
    
    Args:
        text: Texto para análise
        
    Returns:
        Dict com estatísticas completas
    """
    if not text:
        return {
            "char_count": 0, "word_count": 0, "sentence_count": 0,
            "paragraph_count": 0, "avg_word_length": 0, "avg_sentence_length": 0,
            "language": "unknown", "quality_score": 0, "keywords": []
        }
    
    try:
        sentences = split_into_sentences(text)
        paragraphs = split_into_paragraphs(text)
        words = text.split()
        
        # Estatísticas básicas
        char_count = len(text)
        word_count = len(words)
        sentence_count = len(sentences)
        paragraph_count = len(paragraphs)
        
        # Médias
        avg_word_length = sum(len(word) for word in words) / max(word_count, 1)
        avg_sentence_length = word_count / max(sentence_count, 1)
        
        # Análises adicionais
        language = detect_language_simple(text)
        quality_score = calculate_text_quality_score(text)
        keywords = extract_keywords(text, max_keywords=5)
        readability = calculate_readability_score(text)
        
        return {
            "char_count": char_count,
            "word_count": word_count,
            "sentence_count": sentence_count,
            "paragraph_count": paragraph_count,
            "avg_word_length": round(avg_word_length, 2),
            "avg_sentence_length": round(avg_sentence_length, 2),
            "language": language,
            "quality_score": round(quality_score, 2),
            "keywords": keywords,
            "readability": readability
        }
        
    except Exception as e:
        logger.error(f"Text statistics extraction failed: {e}")
        return {
            "char_count": len(text), "word_count": len(text.split()),
            "error": str(e)
        }


def merge_text_blocks(blocks: List[Dict[str, Any]], method: str = "spatial") -> str:
    """
    Combina blocos de texto em texto contínuo
    
    Args:
        blocks: Lista de blocos com texto e posição
        method: Método de combinação ('spatial', 'confidence', 'order')
        
    Returns:
        Texto combinado
    """
    if not blocks:
        return ""
    
    try:
        if method == "spatial":
            # Ordenar por posição espacial (top-down, left-right)
            sorted_blocks = sorted(blocks, key=lambda b: (
                b.get("bbox", [0, 0, 0, 0])[1],  # y position
                b.get("bbox", [0, 0, 0, 0])[0]   # x position
            ))
        elif method == "confidence":
            # Ordenar por confiança (maior primeiro)
            sorted_blocks = sorted(blocks, key=lambda b: b.get("confidence", 0), reverse=True)
        elif method == "order":
            # Manter ordem original
            sorted_blocks = blocks
        else:
            sorted_blocks = blocks
        
        # Extrair texto dos blocos
        texts = [block.get("text", "") for block in sorted_blocks if block.get("text", "").strip()]
        
        # Combinar com espaços apropriados
        combined = ""
        for i, text in enumerate(texts):
            if i == 0:
                combined = text
            else:
                # Decidir se usar espaço ou quebra de linha
                if text[0].isupper() or combined.endswith('.'):
                    combined += "\n" + text
                else:
                    combined += " " + text
        
        return combined.strip()
        
    except Exception as e:
        logger.warning(f"Text block merging failed: {e}")
        return " ".join(block.get("text", "") for block in blocks if block.get("text", ""))


if __name__ == "__main__":
    """Teste das funções utilitárias de texto"""
    print("=== Text Utils Test ===")
    
    # Texto de teste
    test_text = "Este é  um texto    de teste.\n\nCom vários   espaços e\nproblemas típicos de 0CR.\n\n\nSegundo parágrafo aqui."
    
    print(f"Original text: {repr(test_text)}")
    
    # Teste de limpeza
    cleaned = clean_ocr_text(test_text)
    print(f"Cleaned text: {repr(cleaned)}")
    
    # Teste de normalização
    normalized = normalize_whitespace(cleaned)
    print(f"Normalized: {repr(normalized)}")
    
    # Teste de detecção de idioma
    language = detect_language_simple(cleaned)
    print(f"Detected language: {language}")
    
    # Teste de qualidade
    quality = calculate_text_quality_score(cleaned)
    print(f"Quality score: {quality:.1f}")
    
    # Teste de estatísticas
    stats = extract_text_statistics(cleaned)
    print(f"Statistics: {stats}")
    
    # Teste de palavras-chave
    keywords = extract_keywords(cleaned)
    print(f"Keywords: {keywords}")
    
    print("\n✅ Text Utils test completed")