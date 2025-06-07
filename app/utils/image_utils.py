#!/usr/bin/env python3
"""
Utilitários de Imagem
====================

Funções utilitárias para processamento de imagens:
- Validação e conversão de formatos
- Redimensionamento e otimização
- Correção de qualidade e orientação
- Detecção de características
- Pré-processamento para OCR
- Análise de qualidade
"""

import os
import tempfile
import logging
import math
from typing import Dict, Any, List, Optional, Tuple, Union
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ExifTags

logger = logging.getLogger(__name__)

# Formatos de imagem suportados
SUPPORTED_FORMATS = {
    'JPEG', 'JPG', 'PNG', 'BMP', 'TIFF', 'TIF', 'WEBP', 'GIF'
}

# Extensões para formatos
FORMAT_EXTENSIONS = {
    'JPEG': '.jpg',
    'PNG': '.png', 
    'BMP': '.bmp',
    'TIFF': '.tiff',
    'WEBP': '.webp',
    'GIF': '.gif'
}


def validate_image(image_path: str) -> bool:
    """
    Valida se arquivo é uma imagem válida
    
    Args:
        image_path: Caminho da imagem
        
    Returns:
        True se válida
    """
    try:
        with Image.open(image_path) as img:
            img.verify()
            return True
    except Exception as e:
        logger.warning(f"Image validation failed for {image_path}: {e}")
        return False


def get_image_info(image_path: str) -> Dict[str, Any]:
    """
    Obtém informações detalhadas da imagem
    
    Args:
        image_path: Caminho da imagem
        
    Returns:
        Dict com informações da imagem
    """
    try:
        with Image.open(image_path) as img:
            info = {
                "format": img.format,
                "mode": img.mode,
                "size": img.size,
                "width": img.width,
                "height": img.height,
                "aspect_ratio": img.width / img.height if img.height > 0 else 0,
                "megapixels": (img.width * img.height) / 1000000,
                "has_transparency": img.mode in ("RGBA", "LA") or "transparency" in img.info,
                "color_mode": _get_color_mode_info(img.mode),
                "estimated_size_mb": (img.width * img.height * _get_bytes_per_pixel(img.mode)) / (1024 * 1024)
            }
            
            # Informações EXIF
            exif_info = get_exif_info(img)
            if exif_info:
                info["exif"] = exif_info
            
            # Análise de qualidade
            info["quality_analysis"] = analyze_image_quality(image_path)
            
            # Análise de características para OCR
            info["ocr_analysis"] = analyze_for_ocr(image_path)
            
            return info
            
    except Exception as e:
        logger.error(f"Failed to get image info for {image_path}: {e}")
        return {"error": str(e)}


def _get_color_mode_info(mode: str) -> Dict[str, Any]:
    """Obtém informações sobre o modo de cor"""
    mode_info = {
        "L": {"name": "Grayscale", "channels": 1, "bits_per_pixel": 8},
        "RGB": {"name": "RGB Color", "channels": 3, "bits_per_pixel": 24},
        "RGBA": {"name": "RGB with Alpha", "channels": 4, "bits_per_pixel": 32},
        "CMYK": {"name": "CMYK Color", "channels": 4, "bits_per_pixel": 32},
        "P": {"name": "Palette", "channels": 1, "bits_per_pixel": 8},
        "1": {"name": "1-bit pixels", "channels": 1, "bits_per_pixel": 1}
    }
    return mode_info.get(mode, {"name": mode, "channels": 1, "bits_per_pixel": 8})


def _get_bytes_per_pixel(mode: str) -> int:
    """Obtém bytes por pixel baseado no modo"""
    bytes_per_mode = {
        "L": 1, "RGB": 3, "RGBA": 4, "CMYK": 4, "P": 1, "1": 0.125
    }
    return bytes_per_mode.get(mode, 3)


def get_exif_info(img: Image.Image) -> Optional[Dict[str, Any]]:
    """
    Extrai informações EXIF da imagem
    
    Args:
        img: Objeto PIL Image
        
    Returns:
        Dict com informações EXIF ou None
    """
    try:
        exif_dict = img._getexif()
        if not exif_dict:
            return None
        
        exif_info = {}
        
        for tag_id, value in exif_dict.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            
            # Extrair apenas informações relevantes e seguras
            if tag in ['DateTime', 'DateTimeOriginal', 'DateTimeDigitized']:
                exif_info[tag] = str(value)
            elif tag in ['Make', 'Model', 'Software']:
                exif_info[tag] = str(value)
            elif tag in ['XResolution', 'YResolution']:
                if isinstance(value, tuple) and len(value) == 2:
                    exif_info[tag] = value[0] / value[1] if value[1] != 0 else 0
            elif tag == 'Orientation':
                exif_info[tag] = value
            elif tag in ['ExifImageWidth', 'ExifImageHeight']:
                exif_info[tag] = value
        
        return exif_info if exif_info else None
        
    except Exception as e:
        logger.debug(f"EXIF extraction failed: {e}")
        return None


def resize_image(image_path: str, target_size: Tuple[int, int], 
                 maintain_aspect: bool = True, method: str = "lanczos") -> str:
    """
    Redimensiona imagem
    
    Args:
        image_path: Caminho da imagem
        target_size: Tamanho alvo (width, height)
        maintain_aspect: Manter proporção
        method: Método de redimensionamento
        
    Returns:
        Caminho da imagem redimensionada
    """
    try:
        # Mapeamento de métodos
        resize_methods = {
            "nearest": Image.NEAREST,
            "bilinear": Image.BILINEAR,
            "bicubic": Image.BICUBIC,
            "lanczos": Image.LANCZOS,
            "antialias": Image.ANTIALIAS
        }
        
        resize_method = resize_methods.get(method.lower(), Image.LANCZOS)
        
        with Image.open(image_path) as img:
            original_size = img.size
            
            if maintain_aspect:
                # Calcular novo tamanho mantendo proporção
                img.thumbnail(target_size, resize_method)
                new_size = img.size
            else:
                # Redimensionar para tamanho exato
                img = img.resize(target_size, resize_method)
                new_size = target_size
            
            # Salvar imagem redimensionada
            output_path = _generate_output_path(image_path, f"resized_{new_size[0]}x{new_size[1]}")
            img.save(output_path, quality=95, optimize=True)
            
            logger.debug(f"Image resized: {original_size} -> {new_size}")
            return output_path
            
    except Exception as e:
        logger.error(f"Image resize failed: {e}")
        raise


def crop_image(image_path: str, bbox: Tuple[int, int, int, int]) -> str:
    """
    Recorta imagem
    
    Args:
        image_path: Caminho da imagem
        bbox: Bounding box (left, top, right, bottom)
        
    Returns:
        Caminho da imagem recortada
    """
    try:
        with Image.open(image_path) as img:
            cropped = img.crop(bbox)
            
            output_path = _generate_output_path(image_path, "cropped")
            cropped.save(output_path, quality=95, optimize=True)
            
            logger.debug(f"Image cropped: {bbox}")
            return output_path
            
    except Exception as e:
        logger.error(f"Image crop failed: {e}")
        raise


def rotate_image(image_path: str, angle: float, expand: bool = True) -> str:
    """
    Rotaciona imagem
    
    Args:
        image_path: Caminho da imagem
        angle: Ângulo de rotação em graus
        expand: Expandir imagem para evitar cortes
        
    Returns:
        Caminho da imagem rotacionada
    """
    try:
        with Image.open(image_path) as img:
            rotated = img.rotate(angle, expand=expand, fillcolor='white')
            
            output_path = _generate_output_path(image_path, f"rotated_{angle}deg")
            rotated.save(output_path, quality=95, optimize=True)
            
            logger.debug(f"Image rotated: {angle} degrees")
            return output_path
            
    except Exception as e:
        logger.error(f"Image rotation failed: {e}")
        raise


def enhance_image(image_path: str, **enhancements) -> str:
    """
    Aplica melhorias na imagem
    
    Args:
        image_path: Caminho da imagem
        **enhancements: Parâmetros de melhoria
            - brightness: fator de brilho (1.0 = normal)
            - contrast: fator de contraste (1.0 = normal)
            - saturation: fator de saturação (1.0 = normal)
            - sharpness: fator de nitidez (1.0 = normal)
        
    Returns:
        Caminho da imagem melhorada
    """
    try:
        with Image.open(image_path) as img:
            enhanced = img.copy()
            
            # Aplicar melhorias
            if 'brightness' in enhancements:
                enhancer = ImageEnhance.Brightness(enhanced)
                enhanced = enhancer.enhance(enhancements['brightness'])
            
            if 'contrast' in enhancements:
                enhancer = ImageEnhance.Contrast(enhanced)
                enhanced = enhancer.enhance(enhancements['contrast'])
            
            if 'saturation' in enhancements:
                enhancer = ImageEnhance.Color(enhanced)
                enhanced = enhancer.enhance(enhancements['saturation'])
            
            if 'sharpness' in enhancements:
                enhancer = ImageEnhance.Sharpness(enhanced)
                enhanced = enhancer.enhance(enhancements['sharpness'])
            
            output_path = _generate_output_path(image_path, "enhanced")
            enhanced.save(output_path, quality=95, optimize=True)
            
            logger.debug(f"Image enhanced with: {enhancements}")
            return output_path
            
    except Exception as e:
        logger.error(f"Image enhancement failed: {e}")
        raise


def convert_format(image_path: str, target_format: str, quality: int = 95) -> str:
    """
    Converte formato da imagem
    
    Args:
        image_path: Caminho da imagem
        target_format: Formato alvo (JPEG, PNG, etc.)
        quality: Qualidade para formatos com perda
        
    Returns:
        Caminho da imagem convertida
    """
    try:
        target_format = target_format.upper()
        if target_format not in SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported format: {target_format}")
        
        with Image.open(image_path) as img:
            # Converter modo se necessário
            if target_format == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
                # JPEG não suporta transparência
                background = Image.new('RGB', img.size, 'white')
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = background
            elif target_format == 'PNG' and img.mode == 'CMYK':
                img = img.convert('RGB')
            
            # Gerar caminho de saída
            extension = FORMAT_EXTENSIONS.get(target_format, '.jpg')
            output_path = Path(image_path).with_suffix(extension)
            
            # Salvar com parâmetros apropriados
            save_kwargs = {'optimize': True}
            if target_format in ('JPEG', 'WEBP'):
                save_kwargs['quality'] = quality
            
            img.save(str(output_path), format=target_format, **save_kwargs)
            
            logger.debug(f"Image converted to {target_format}")
            return str(output_path)
            
    except Exception as e:
        logger.error(f"Image format conversion failed: {e}")
        raise


def correct_orientation(image_path: str) -> str:
    """
    Corrige orientação da imagem baseada no EXIF
    
    Args:
        image_path: Caminho da imagem
        
    Returns:
        Caminho da imagem com orientação corrigida
    """
    try:
        with Image.open(image_path) as img:
            # Usar ImageOps para correção automática
            corrected = ImageOps.exif_transpose(img)
            
            if corrected is None:
                corrected = img  # Sem correção necessária
            
            output_path = _generate_output_path(image_path, "oriented")
            corrected.save(output_path, quality=95, optimize=True)
            
            logger.debug("Image orientation corrected")
            return output_path
            
    except Exception as e:
        logger.error(f"Orientation correction failed: {e}")
        raise


def analyze_image_quality(image_path: str) -> Dict[str, Any]:
    """
    Analisa qualidade da imagem
    
    Args:
        image_path: Caminho da imagem
        
    Returns:
        Dict com análise de qualidade
    """
    try:
        # Carregar com OpenCV para análise
        img_cv = cv2.imread(image_path)
        if img_cv is None:
            raise ValueError("Could not load image with OpenCV")
        
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        # Métricas de qualidade
        analysis = {
            "mean_brightness": float(np.mean(gray)),
            "std_brightness": float(np.std(gray)),
            "contrast_ratio": float(np.std(gray) / np.mean(gray)) if np.mean(gray) > 0 else 0,
            "dynamic_range": int(np.max(gray) - np.min(gray)),
            "blur_score": _calculate_blur_score(gray),
            "noise_level": _estimate_noise_level(gray),
            "quality_score": 0.0
        }
        
        # Calcular score geral de qualidade (0-10)
        quality_score = 5.0  # Base
        
        # Fator de contraste
        if analysis["contrast_ratio"] > 0.8:
            quality_score += 2.0
        elif analysis["contrast_ratio"] > 0.5:
            quality_score += 1.0
        elif analysis["contrast_ratio"] < 0.3:
            quality_score -= 2.0
        
        # Fator de nitidez
        if analysis["blur_score"] > 100:
            quality_score += 1.0
        elif analysis["blur_score"] < 50:
            quality_score -= 1.0
        
        # Fator de ruído
        if analysis["noise_level"] < 10:
            quality_score += 1.0
        elif analysis["noise_level"] > 30:
            quality_score -= 1.0
        
        # Fator de brilho
        brightness = analysis["mean_brightness"]
        if 80 <= brightness <= 180:  # Faixa ideal
            quality_score += 0.5
        elif brightness < 50 or brightness > 200:
            quality_score -= 1.0
        
        analysis["quality_score"] = max(0.0, min(10.0, quality_score))
        
        return analysis
        
    except Exception as e:
        logger.error(f"Image quality analysis failed: {e}")
        return {"error": str(e)}


def _calculate_blur_score(gray_image: np.ndarray) -> float:
    """Calcula score de nitidez usando variância do Laplaciano"""
    try:
        return float(cv2.Laplacian(gray_image, cv2.CV_64F).var())
    except Exception:
        return 0.0


def _estimate_noise_level(gray_image: np.ndarray) -> float:
    """Estima nível de ruído da imagem"""
    try:
        # Usar filtro mediano para estimar ruído
        filtered = cv2.medianBlur(gray_image, 5)
        noise = cv2.absdiff(gray_image, filtered)
        return float(np.mean(noise))
    except Exception:
        return 0.0


def analyze_for_ocr(image_path: str) -> Dict[str, Any]:
    """
    Analisa imagem para determinar adequação para OCR
    
    Args:
        image_path: Caminho da imagem
        
    Returns:
        Dict com análise para OCR
    """
    try:
        img_cv = cv2.imread(image_path)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        
        analysis = {
            "text_regions_detected": 0,
            "estimated_text_coverage": 0.0,
            "background_uniformity": 0.0,
            "text_line_count": 0,
            "average_character_size": 0,
            "skew_angle": 0.0,
            "ocr_readiness_score": 0.0,
            "recommendations": []
        }
        
        # Detectar regiões de texto
        text_info = _detect_text_regions(gray)
        analysis.update(text_info)
        
        # Detectar inclinação
        skew_angle = _detect_skew(gray)
        analysis["skew_angle"] = skew_angle
        
        # Analisar uniformidade do fundo
        background_score = _analyze_background_uniformity(gray)
        analysis["background_uniformity"] = background_score
        
        # Calcular score de prontidão para OCR
        ocr_score = _calculate_ocr_readiness(analysis)
        analysis["ocr_readiness_score"] = ocr_score
        
        # Gerar recomendações
        recommendations = _generate_ocr_recommendations(analysis)
        analysis["recommendations"] = recommendations
        
        return analysis
        
    except Exception as e:
        logger.error(f"OCR analysis failed: {e}")
        return {"error": str(e)}


def _detect_text_regions(gray_image: np.ndarray) -> Dict[str, Any]:
    """Detecta regiões de texto na imagem"""
    try:
        # Binarização
        _, binary = cv2.threshold(gray_image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Detectar componentes conectados
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)
        
        # Analisar componentes que podem ser texto
        text_components = 0
        total_text_area = 0
        character_sizes = []
        
        for i in range(1, num_labels):  # Skip background
            area = stats[i, cv2.CC_STAT_AREA]
            width = stats[i, cv2.CC_STAT_WIDTH]
            height = stats[i, cv2.CC_STAT_HEIGHT]
            
            # Heurística para identificar caracteres
            if 20 < area < 10000 and 0.1 < width/height < 10:
                text_components += 1
                total_text_area += area
                character_sizes.append(height)
        
        # Estimar cobertura de texto
        total_area = gray_image.shape[0] * gray_image.shape[1]
        text_coverage = total_text_area / total_area if total_area > 0 else 0
        
        # Estimar linhas de texto
        line_count = max(1, text_components // 8)  # Aproximação
        
        # Tamanho médio de caracteres
        avg_char_size = int(np.mean(character_sizes)) if character_sizes else 0
        
        return {
            "text_regions_detected": text_components,
            "estimated_text_coverage": text_coverage,
            "text_line_count": line_count,
            "average_character_size": avg_char_size
        }
        
    except Exception as e:
        logger.warning(f"Text region detection failed: {e}")
        return {
            "text_regions_detected": 0,
            "estimated_text_coverage": 0.0,
            "text_line_count": 0,
            "average_character_size": 0
        }


def _detect_skew(gray_image: np.ndarray) -> float:
    """Detecta inclinação da imagem"""
    try:
        # Detectar bordas
        edges = cv2.Canny(gray_image, 50, 150, apertureSize=3)
        
        # Transformada de Hough para detectar linhas
        lines = cv2.HoughLines(edges, 1, np.pi/180, threshold=100)
        
        if lines is not None:
            angles = []
            for rho, theta in lines[:10]:  # Usar primeiras 10 linhas
                angle = theta * 180 / np.pi - 90
                angles.append(angle)
            
            if angles:
                return float(np.median(angles))
        
        return 0.0
        
    except Exception:
        return 0.0


def _analyze_background_uniformity(gray_image: np.ndarray) -> float:
    """Analisa uniformidade do fundo"""
    try:
        # Blur para suavizar
        blurred = cv2.GaussianBlur(gray_image, (15, 15), 0)
        
        # Calcular variação
        variation = np.std(blurred)
        
        # Normalizar para score 0-1 (menor variação = melhor)
        uniformity = max(0.0, 1.0 - (variation / 100.0))
        
        return float(uniformity)
        
    except Exception:
        return 0.0


def _calculate_ocr_readiness(analysis: Dict[str, Any]) -> float:
    """Calcula score de prontidão para OCR"""
    try:
        score = 5.0  # Base
        
        # Fator de regiões de texto
        text_regions = analysis.get("text_regions_detected", 0)
        if text_regions > 50:
            score += 2.0
        elif text_regions > 10:
            score += 1.0
        elif text_regions < 5:
            score -= 2.0
        
        # Fator de cobertura de texto
        coverage = analysis.get("estimated_text_coverage", 0)
        if coverage > 0.3:
            score += 1.0
        elif coverage < 0.05:
            score -= 1.0
        
        # Fator de uniformidade do fundo
        uniformity = analysis.get("background_uniformity", 0)
        if uniformity > 0.8:
            score += 1.0
        elif uniformity < 0.4:
            score -= 1.0
        
        # Fator de inclinação
        skew = abs(analysis.get("skew_angle", 0))
        if skew < 2:
            score += 0.5
        elif skew > 10:
            score -= 1.0
        
        # Fator de tamanho de caracteres
        char_size = analysis.get("average_character_size", 0)
        if 15 <= char_size <= 50:  # Tamanho ideal
            score += 0.5
        elif char_size < 8 or char_size > 100:
            score -= 1.0
        
        return max(0.0, min(10.0, score))
        
    except Exception:
        return 5.0


def _generate_ocr_recommendations(analysis: Dict[str, Any]) -> List[str]:
    """Gera recomendações para melhorar OCR"""
    recommendations = []
    
    try:
        # Verificar inclinação
        skew = abs(analysis.get("skew_angle", 0))
        if skew > 5:
            recommendations.append(f"Correct image skew (angle: {skew:.1f}°)")
        
        # Verificar tamanho de caracteres
        char_size = analysis.get("average_character_size", 0)
        if char_size < 12:
            recommendations.append("Increase image resolution - characters too small")
        elif char_size > 80:
            recommendations.append("Reduce image size - characters too large")
        
        # Verificar uniformidade do fundo
        uniformity = analysis.get("background_uniformity", 0)
        if uniformity < 0.5:
            recommendations.append("Improve background uniformity - use better lighting")
        
        # Verificar cobertura de texto
        coverage = analysis.get("estimated_text_coverage", 0)
        if coverage < 0.02:
            recommendations.append("Very little text detected - verify image contains text")
        
        # Verificar score geral
        score = analysis.get("ocr_readiness_score", 0)
        if score < 4:
            recommendations.append("Overall image quality needs improvement")
        elif score > 8:
            recommendations.append("Image is well-suited for OCR processing")
        
    except Exception as e:
        logger.warning(f"Failed to generate recommendations: {e}")
    
    return recommendations


def preprocess_for_ocr(image_path: str, **options) -> str:
    """
    Pré-processa imagem para OCR
    
    Args:
        image_path: Caminho da imagem
        **options: Opções de pré-processamento
        
    Returns:
        Caminho da imagem pré-processada
    """
    try:
        img_cv = cv2.imread(image_path)
        
        # Converter para escala de cinza
        if len(img_cv.shape) == 3:
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        else:
            gray = img_cv.copy()
        
        processed = gray.copy()
        
        # Aplicar correções baseadas nas opções
        if options.get('correct_skew', True):
            skew_angle = _detect_skew(gray)
            if abs(skew_angle) > 1:
                processed = _rotate_image_cv(processed, -skew_angle)
        
        if options.get('enhance_contrast', True):
            processed = cv2.equalizeHist(processed)
        
        if options.get('denoise', True):
            processed = cv2.fastNlMeansDenoising(processed)
        
        if options.get('sharpen', False):
            kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
            processed = cv2.filter2D(processed, -1, kernel)
        
        if options.get('binarize', False):
            _, processed = cv2.threshold(processed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Salvar resultado
        output_path = _generate_output_path(image_path, "preprocessed")
        cv2.imwrite(output_path, processed)
        
        logger.debug("Image preprocessed for OCR")
        return output_path
        
    except Exception as e:
        logger.error(f"OCR preprocessing failed: {e}")
        raise


def _rotate_image_cv(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotaciona imagem usando OpenCV"""
    try:
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rotated
    except Exception:
        return image


def _generate_output_path(input_path: str, suffix: str) -> str:
    """Gera caminho de arquivo de saída"""
    path = Path(input_path)
    output_name = f"{path.stem}_{suffix}{path.suffix}"
    return str(path.parent / output_name)


def create_thumbnail(image_path: str, size: Tuple[int, int] = (128, 128)) -> str:
    """
    Cria thumbnail da imagem
    
    Args:
        image_path: Caminho da imagem
        size: Tamanho do thumbnail
        
    Returns:
        Caminho do thumbnail
    """
    try:
        with Image.open(image_path) as img:
            img.thumbnail(size, Image.LANCZOS)
            
            output_path = _generate_output_path(image_path, f"thumb_{size[0]}x{size[1]}")
            img.save(output_path, quality=85, optimize=True)
            
            return output_path
            
    except Exception as e:
        logger.error(f"Thumbnail creation failed: {e}")
        raise


def batch_process_images(image_paths: List[str], operation: str, **kwargs) -> List[str]:
    """
    Processa múltiplas imagens em lote
    
    Args:
        image_paths: Lista de caminhos de imagem
        operation: Operação a realizar
        **kwargs: Parâmetros da operação
        
    Returns:
        Lista de caminhos das imagens processadas
    """
    try:
        results = []
        
        for image_path in image_paths:
            try:
                if operation == "resize":
                    result = resize_image(image_path, **kwargs)
                elif operation == "enhance":
                    result = enhance_image(image_path, **kwargs)
                elif operation == "convert":
                    result = convert_format(image_path, **kwargs)
                elif operation == "preprocess_ocr":
                    result = preprocess_for_ocr(image_path, **kwargs)
                elif operation == "thumbnail":
                    result = create_thumbnail(image_path, **kwargs)
                else:
                    raise ValueError(f"Unknown operation: {operation}")
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"Batch processing failed for {image_path}: {e}")
                results.append(None)
        
        return results
        
    except Exception as e:
        logger.error(f"Batch image processing failed: {e}")
        raise


if __name__ == "__main__":
    """Teste dos utilitários de imagem"""
    print("=== Image Utils Test ===")
    
    # Criar imagem de teste
    test_image = Image.new('RGB', (300, 200), color='white')
    
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        test_image.save(tmp.name)
        test_path = tmp.name
    
    try:
        print(f"Test image created: {test_path}")
        
        # Teste de validação
        print(f"Image is valid: {validate_image(test_path)}")
        
        # Teste de informações
        info = get_image_info(test_path)
        print(f"Image size: {info.get('width', 0)}x{info.get('height', 0)}")
        print(f"Image format: {info.get('format', 'unknown')}")
        print(f"Quality score: {info.get('quality_analysis', {}).get('quality_score', 0):.1f}")
        
        # Teste de redimensionamento
        resized = resize_image(test_path, (150, 100))
        print(f"Image resized: {resized}")
        
        # Teste de conversão
        converted = convert_format(test_path, 'JPEG')
        print(f"Image converted: {converted}")
        
        # Teste de thumbnail
        thumb = create_thumbnail(test_path, (64, 64))
        print(f"Thumbnail created: {thumb}")
        
        # Limpeza
        for f in [test_path, resized, converted, thumb]:
            try:
                os.unlink(f)
            except:
                pass
        
        print("✅ All image operations completed successfully")
        
    except Exception as e:
        print(f"❌ Image utils test failed: {e}")
        # Limpeza em caso de erro
        try:
            os.unlink(test_path)
        except:
            pass
    
    print("\n✅ Image Utils test completed")