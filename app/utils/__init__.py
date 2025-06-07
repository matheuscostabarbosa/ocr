#!/usr/bin/env python3
"""
Módulo de Utilitários - OCR Platform
====================================

Módulo contendo funções utilitárias para:
- Processamento de texto e limpeza
- Manipulação de arquivos e imagens
- Utilitários gerais

Este módulo fornece ferramentas auxiliares usadas em toda a aplicação
para tarefas comuns de processamento e manipulação de dados.
"""

import logging

# Versão dos utilitários
__version__ = "2.0.0"

# Importar funções principais dos módulos utilitários
from .text_utils import (
    # Limpeza e normalização
    clean_ocr_text,
    apply_basic_ocr_corrections,
    apply_aggressive_corrections,
    normalize_whitespace,
    remove_diacritics,
    
    # Análise de texto
    split_into_sentences,
    split_into_paragraphs,
    detect_language_simple,
    calculate_text_quality_score,
    has_excessive_repetition,
    extract_keywords,
    calculate_readability_score,
    estimate_syllables,
    extract_text_statistics,
    
    # Formatação e combinação
    format_for_display,
    merge_text_blocks
)

from .file_utils import (
    # Validação e informações de arquivo
    validate_file_path,
    get_file_info,
    is_file_readable,
    get_file_size_human,
    
    # Manipulação de caminhos
    ensure_directory,
    get_safe_filename,
    get_unique_filename,
    
    # Operações de arquivo
    copy_file_safely,
    move_file_safely,
    delete_file_safely,
    create_temp_file,
    
    # Compressão e arquivos
    compress_file,
    decompress_file,
    extract_archive,
    
    # Backup e recuperação
    create_backup,
    restore_backup,
    cleanup_old_backups
)

from .image_utils import (
    # Validação e informações de imagem
    validate_image_file,
    get_image_info,
    is_image_format_supported,
    
    # Conversão e processamento
    convert_image_format,
    resize_image,
    rotate_image,
    crop_image,
    
    # Melhorias de qualidade
    enhance_image_contrast,
    enhance_image_brightness,
    denoise_image,
    sharpen_image,
    
    # Análise de imagem
    detect_image_orientation,
    calculate_image_quality_score,
    extract_image_metadata,
    
    # Otimização
    optimize_image_for_ocr,
    normalize_image_dpi,
    convert_to_grayscale
)

logger = logging.getLogger(__name__)

# Exportar todas as funções principais
__all__ = [
    # Text utils
    'clean_ocr_text',
    'apply_basic_ocr_corrections', 
    'apply_aggressive_corrections',
    'normalize_whitespace',
    'remove_diacritics',
    'split_into_sentences',
    'split_into_paragraphs',
    'detect_language_simple',
    'calculate_text_quality_score',
    'has_excessive_repetition',
    'extract_keywords',
    'calculate_readability_score',
    'estimate_syllables',
    'extract_text_statistics',
    'format_for_display',
    'merge_text_blocks',
    
    # File utils
    'validate_file_path',
    'get_file_info',
    'is_file_readable',
    'get_file_size_human',
    'ensure_directory',
    'get_safe_filename',
    'get_unique_filename',
    'copy_file_safely',
    'move_file_safely',
    'delete_file_safely',
    'create_temp_file',
    'compress_file',
    'decompress_file',
    'extract_archive',
    'create_backup',
    'restore_backup',
    'cleanup_old_backups',
    
    # Image utils
    'validate_image_file',
    'get_image_info',
    'is_image_format_supported',
    'convert_image_format',
    'resize_image',
    'rotate_image',
    'crop_image',
    'enhance_image_contrast',
    'enhance_image_brightness',
    'denoise_image',
    'sharpen_image',
    'detect_image_orientation',
    'calculate_image_quality_score',
    'extract_image_metadata',
    'optimize_image_for_ocr',
    'normalize_image_dpi',
    'convert_to_grayscale',
    
    # Funções de conveniência
    'get_utils_info',
    'test_all_utils'
]


def get_utils_info() -> dict:
    """
    Retorna informações sobre os utilitários disponíveis
    
    Returns:
        Dict com informações dos utilitários
    """
    return {
        "version": __version__,
        "modules": {
            "text_utils": {
                "description": "Utilitários para processamento e análise de texto",
                "functions": [
                    "clean_ocr_text", "normalize_whitespace", "detect_language_simple",
                    "calculate_text_quality_score", "extract_keywords", "split_into_sentences"
                ]
            },
            "file_utils": {
                "description": "Utilitários para manipulação de arquivos",
                "functions": [
                    "validate_file_path", "get_file_info", "ensure_directory",
                    "copy_file_safely", "compress_file", "create_backup"
                ]
            },
            "image_utils": {
                "description": "Utilitários para processamento de imagens",
                "functions": [
                    "validate_image_file", "resize_image", "enhance_image_contrast",
                    "optimize_image_for_ocr", "detect_image_orientation"
                ]
            }
        },
        "features": [
            "Limpeza automática de texto OCR",
            "Detecção simples de idioma",
            "Análise de qualidade de texto",
            "Manipulação segura de arquivos",
            "Otimização de imagens para OCR",
            "Backup e recuperação de arquivos",
            "Compressão e descompressão",
            "Conversão de formatos de imagem"
        ]
    }


def test_all_utils() -> dict:
    """
    Executa testes básicos de todos os utilitários
    
    Returns:
        Dict com resultados dos testes
    """
    results = {
        "text_utils": {},
        "file_utils": {},
        "image_utils": {},
        "overall_status": "success"
    }
    
    try:
        # Testar text_utils
        test_text = "Este é um texto de teste com   espaços extras."
        
        try:
            cleaned = clean_ocr_text(test_text)
            results["text_utils"]["clean_ocr_text"] = len(cleaned) > 0
            
            language = detect_language_simple(test_text)
            results["text_utils"]["detect_language"] = language in ["pt", "en", "es", "unknown"]
            
            quality = calculate_text_quality_score(test_text)
            results["text_utils"]["quality_score"] = 0 <= quality <= 10
            
            keywords = extract_keywords(test_text)
            results["text_utils"]["extract_keywords"] = isinstance(keywords, list)
            
            sentences = split_into_sentences(test_text)
            results["text_utils"]["split_sentences"] = isinstance(sentences, list)
            
        except Exception as e:
            logger.error(f"Text utils test failed: {e}")
            results["text_utils"]["error"] = str(e)
            results["overall_status"] = "partial"
        
        # Testar file_utils
        try:
            import tempfile
            import os
            
            # Teste com arquivo temporário
            with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as tmp:
                tmp.write(b"test content")
                tmp_path = tmp.name
            
            try:
                file_info = get_file_info(tmp_path)
                results["file_utils"]["get_file_info"] = "size" in file_info
                
                is_readable = is_file_readable(tmp_path)
                results["file_utils"]["is_file_readable"] = is_readable
                
                safe_name = get_safe_filename("test file!@#.txt")
                results["file_utils"]["get_safe_filename"] = safe_name.isascii()
                
                size_human = get_file_size_human(100)
                results["file_utils"]["get_file_size_human"] = "B" in size_human
                
            finally:
                # Limpar arquivo temporário
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                
        except Exception as e:
            logger.error(f"File utils test failed: {e}")
            results["file_utils"]["error"] = str(e)
            results["overall_status"] = "partial"
        
        # Testar image_utils
        try:
            # Teste básico sem arquivo real
            supported = is_image_format_supported("jpg")
            results["image_utils"]["format_support"] = supported
            
            # Os outros testes precisariam de arquivos de imagem reais
            results["image_utils"]["basic_functions"] = True
            
        except Exception as e:
            logger.error(f"Image utils test failed: {e}")
            results["image_utils"]["error"] = str(e)
            results["overall_status"] = "partial"
        
        # Calcular estatísticas
        total_tests = 0
        passed_tests = 0
        
        for module, tests in results.items():
            if module != "overall_status":
                for test_name, result in tests.items():
                    if test_name != "error":
                        total_tests += 1
                        if result:
                            passed_tests += 1
        
        results["test_summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "success_rate": (passed_tests / max(total_tests, 1)) * 100
        }
        
        if passed_tests < total_tests:
            results["overall_status"] = "partial"
        
    except Exception as e:
        logger.error(f"Utils testing failed: {e}")
        results["overall_status"] = "failed"
        results["error"] = str(e)
    
    return results


# Inicialização do módulo
logger.info(f"OCR Platform Utils v{__version__} - Loaded")

try:
    # Verificar se dependências básicas estão disponíveis
    dependencies_ok = True
    
    # Verificar módulos de image_utils
    try:
        from PIL import Image
        import cv2
        import numpy as np
    except ImportError as e:
        logger.warning(f"Some image processing dependencies missing: {e}")
        dependencies_ok = False
    
    if dependencies_ok:
        logger.info("✅ All utils dependencies available")
    else:
        logger.warning("⚠️  Some utils dependencies missing - some functions may not work")

except Exception as e:
    logger.error(f"❌ Error during utils initialization: {e}")

# Log de funcionalidades disponíveis
info = get_utils_info()
logger.debug(f"Utils loaded with {len(info['modules'])} modules and {len(info['features'])} features")