#!/usr/bin/env python3
"""
Tesseract Worker - Fallback Confiável
====================================

Worker especializado usando Tesseract OCR.
Ideal para:
- Fallback confiável
- Textos digitais simples
- Documentos escaneados limpos
- CPU-only processing
- Alta disponibilidade
"""

import time
import tempfile
import subprocess
from typing import Dict, Any, List, Tuple
from PIL import Image
import numpy as np
import cv2

from app.workers.base_worker import BaseOCRWorker
from app.core.celery_app import celery_app
from app.core.config import settings, get_engine_config
from app.models.schemas import OCRRequest, OCRResponse

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False


class TesseractWorker(BaseOCRWorker):
    """Worker Tesseract para fallback e textos simples"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "tesseract"
        self.config = get_engine_config(self.engine_name)
        
        # Configurações Tesseract
        self.lang = self.config.get("lang", "por+eng")
        self.tesseract_config = self.config.get("config", "--oem 3 --psm 6")
        
        # Configurações de processamento
        self.preprocessing_enabled = True
        self.confidence_threshold = 0.0
        
        if not TESSERACT_AVAILABLE:
            raise ImportError("Tesseract dependencies not available. Install with: pip install pytesseract")
    
    def load_model(self):
        """Verifica se Tesseract está disponível"""
        try:
            self.logger.info("Checking Tesseract installation...")
            
            # Verificar se Tesseract está instalado
            version = pytesseract.get_tesseract_version()
            self.logger.info(f"Tesseract version: {version}")
            
            # Verificar idiomas disponíveis
            available_langs = pytesseract.get_languages()
            self.logger.info(f"Available languages: {available_langs}")
            
            # Verificar se os idiomas configurados estão disponíveis
            required_langs = self.lang.split('+')
            missing_langs = [lang for lang in required_langs if lang not in available_langs]
            
            if missing_langs:
                self.logger.warning(f"Missing language data: {missing_langs}")
                # Tentar com inglês como fallback
                if 'eng' in available_langs:
                    self.lang = 'eng'
                    self.logger.info("Falling back to English language")
                else:
                    raise ValueError("No suitable language data found")
            
            self.logger.info(f"Tesseract configured with language: {self.lang}")
            
        except Exception as e:
            self.logger.error(f"Tesseract setup failed: {e}")
            raise
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processa imagem com Tesseract"""
        try:
            start_time = time.time()
            
            # Pré-processamento
            processed_image_path = self._preprocess_for_tesseract(image_path, **kwargs)
            
            try:
                # Configurar parâmetros
                config = self._build_tesseract_config(**kwargs)
                lang = kwargs.get('language', self.lang)
                
                # Executar OCR
                if kwargs.get('detailed_output', True):
                    result = self._run_detailed_ocr(processed_image_path, lang, config, **kwargs)
                else:
                    result = self._run_simple_ocr(processed_image_path, lang, config, **kwargs)
                
                result['processing_time'] = time.time() - start_time
                return result
                
            finally:
                # Limpar arquivo temporário
                if processed_image_path != image_path:
                    try:
                        import os
                        os.unlink(processed_image_path)
                    except Exception:
                        pass
                        
        except Exception as e:
            self.logger.error(f"Tesseract processing failed: {e}")
            raise
    
    def _preprocess_for_tesseract(self, image_path: str, **kwargs) -> str:
        """Pré-processamento otimizado para Tesseract"""
        try:
            # Carregar imagem
            image = cv2.imread(image_path)
            if image is None:
                return image_path
            
            modified = False
            
            # Converter para escala de cinza
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                modified = True
            else:
                gray = image.copy()
            
            # Aplicar pré-processamento baseado no tipo de documento
            preprocess_mode = kwargs.get('preprocess_mode', 'auto')
            
            if preprocess_mode == 'auto':
                # Detectar automaticamente o melhor pré-processamento
                gray = self._auto_preprocess(gray)
                modified = True
            elif preprocess_mode == 'clean':
                # Para documentos limpos
                gray = self._clean_document_preprocess(gray)
                modified = True
            elif preprocess_mode == 'scanned':
                # Para documentos escaneados
                gray = self._scanned_document_preprocess(gray)
                modified = True
            elif preprocess_mode == 'noisy':
                # Para documentos com ruído
                gray = self._noisy_document_preprocess(gray)
                modified = True
            
            # Redimensionar se necessário
            target_height = kwargs.get('target_height', None)
            if target_height and gray.shape[0] != target_height:
                scale = target_height / gray.shape[0]
                new_width = int(gray.shape[1] * scale)
                gray = cv2.resize(gray, (new_width, target_height), interpolation=cv2.INTER_CUBIC)
                modified = True
            
            # Salvar se modificada
            if modified:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                    cv2.imwrite(tmp_file.name, gray)
                    return tmp_file.name
            
            return image_path
            
        except Exception as e:
            self.logger.warning(f"Tesseract preprocessing failed: {e}")
            return image_path
    
    def _auto_preprocess(self, gray: np.ndarray) -> np.ndarray:
        """Pré-processamento automático baseado nas características da imagem"""
        try:
            # Analisar características da imagem
            mean_intensity = np.mean(gray)
            std_intensity = np.std(gray)
            
            # Decidir estratégia baseada na análise
            if std_intensity < 30:  # Baixo contraste
                # Aplicar equalização de histograma
                gray = cv2.equalizeHist(gray)
            
            if mean_intensity < 100:  # Imagem escura
                # Aumentar brilho
                gray = cv2.convertScaleAbs(gray, alpha=1.2, beta=30)
            
            # Aplicar filtro de ruído
            gray = cv2.medianBlur(gray, 3)
            
            # Binarização adaptativa
            gray = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            
            return gray
            
        except Exception as e:
            self.logger.warning(f"Auto preprocessing failed: {e}")
            return gray
    
    def _clean_document_preprocess(self, gray: np.ndarray) -> np.ndarray:
        """Pré-processamento para documentos limpos"""
        try:
            # Suavização leve
            gray = cv2.GaussianBlur(gray, (3, 3), 0)
            
            # Binarização simples
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            return gray
            
        except Exception as e:
            self.logger.warning(f"Clean document preprocessing failed: {e}")
            return gray
    
    def _scanned_document_preprocess(self, gray: np.ndarray) -> np.ndarray:
        """Pré-processamento para documentos escaneados"""
        try:
            # Correção de inclinação
            gray = self._deskew_image(gray)
            
            # Remoção de ruído
            gray = cv2.fastNlMeansDenoising(gray)
            
            # Melhorar contraste
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            
            # Binarização adaptativa
            gray = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4
            )
            
            return gray
            
        except Exception as e:
            self.logger.warning(f"Scanned document preprocessing failed: {e}")
            return gray
    
    def _noisy_document_preprocess(self, gray: np.ndarray) -> np.ndarray:
        """Pré-processamento para documentos com ruído"""
        try:
            # Remoção agressiva de ruído
            gray = cv2.bilateralFilter(gray, 9, 75, 75)
            
            # Morfologia para conectar caracteres quebrados
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            gray = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
            
            # Binarização
            _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Remoção de pequenos componentes de ruído
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(gray, connectivity=8)
            
            # Filtrar componentes pequenos
            min_size = 20
            filtered = np.zeros_like(gray)
            for i in range(1, num_labels):
                if stats[i, cv2.CC_STAT_AREA] >= min_size:
                    filtered[labels == i] = 255
            
            return filtered
            
        except Exception as e:
            self.logger.warning(f"Noisy document preprocessing failed: {e}")
            return gray
    
    def _deskew_image(self, gray: np.ndarray) -> np.ndarray:
        """Corrige inclinação da imagem"""
        try:
            # Detectar linhas usando transformada de Hough
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            lines = cv2.HoughLines(edges, 1, np.pi/180, threshold=100)
            
            if lines is not None:
                # Calcular ângulo médio das linhas
                angles = []
                for rho, theta in lines[:10]:  # Usar apenas as primeiras 10 linhas
                    angle = theta * 180 / np.pi - 90
                    angles.append(angle)
                
                # Calcular ângulo médio
                median_angle = np.median(angles)
                
                # Corrigir apenas se o ângulo for significativo
                if abs(median_angle) > 0.5:
                    # Rotar imagem
                    (h, w) = gray.shape
                    center = (w // 2, h // 2)
                    rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                    gray = cv2.warpAffine(gray, rotation_matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            
            return gray
            
        except Exception as e:
            self.logger.warning(f"Deskewing failed: {e}")
            return gray
    
    def _build_tesseract_config(self, **kwargs) -> str:
        """Constrói configuração do Tesseract"""
        try:
            # Configuração base
            config_parts = []
            
            # OEM (OCR Engine Mode)
            oem = kwargs.get('oem', 3)  # Default: LSTM + Legacy
            config_parts.append(f"--oem {oem}")
            
            # PSM (Page Segmentation Mode)
            psm = kwargs.get('psm', 6)  # Default: Uniform block of text
            config_parts.append(f"--psm {psm}")
            
            # Configurações de whitelist/blacklist
            if kwargs.get('whitelist_chars'):
                config_parts.append(f"-c tessedit_char_whitelist={kwargs['whitelist_chars']}")
            
            if kwargs.get('blacklist_chars'):
                config_parts.append(f"-c tessedit_char_blacklist={kwargs['blacklist_chars']}")
            
            # Configurações específicas para melhorar precisão
            config_parts.extend([
                "-c preserve_interword_spaces=1",  # Preservar espaços
                "-c tessedit_do_invert=0",         # Não inverter
            ])
            
            return " ".join(config_parts)
            
        except Exception as e:
            self.logger.warning(f"Config building failed: {e}")
            return self.tesseract_config
    
    def _run_simple_ocr(self, image_path: str, lang: str, config: str, **kwargs) -> Dict[str, Any]:
        """Executa OCR simples (apenas texto)"""
        try:
            # Extrair texto
            text = pytesseract.image_to_string(
                image_path,
                lang=lang,
                config=config
            )
            
            return {
                "text": text.strip(),
                "confidence": 0.8,  # Confiança padrão para modo simples
                "blocks": [{
                    "text": text.strip(),
                    "confidence": 0.8,
                    "bbox": [0, 0, 0, 0]  # Sem informação de posição
                }],
                "method": "simple"
            }
            
        except Exception as e:
            self.logger.error(f"Simple OCR failed: {e}")
            raise
    
    def _run_detailed_ocr(self, image_path: str, lang: str, config: str, **kwargs) -> Dict[str, Any]:
        """Executa OCR detalhado (com posições e confiança)"""
        try:
            # Extrair dados detalhados
            data = pytesseract.image_to_data(
                image_path,
                lang=lang,
                config=config,
                output_type=pytesseract.Output.DICT
            )
            
            # Processar dados
            result = self._process_tesseract_data(data, **kwargs)
            result["method"] = "detailed"
            
            return result
            
        except Exception as e:
            self.logger.error(f"Detailed OCR failed: {e}")
            # Fallback para modo simples
            return self._run_simple_ocr(image_path, lang, config, **kwargs)
    
    def _process_tesseract_data(self, data: Dict, **kwargs) -> Dict[str, Any]:
        """Processa dados detalhados do Tesseract"""
        try:
            text_lines = []
            blocks = []
            confidences = []
            
            # Configurações
            min_confidence = kwargs.get('min_confidence', 0.0)
            group_by_line = kwargs.get('group_by_line', True)
            
            if group_by_line:
                # Agrupar palavras por linha
                lines = {}
                
                for i in range(len(data['text'])):
                    word = data['text'][i].strip()
                    conf = int(data['conf'][i])
                    
                    if word and conf > min_confidence:
                        line_num = data['line_num'][i]
                        
                        if line_num not in lines:
                            lines[line_num] = {
                                'words': [],
                                'confidences': [],
                                'boxes': []
                            }
                        
                        lines[line_num]['words'].append(word)
                        lines[line_num]['confidences'].append(conf)
                        lines[line_num]['boxes'].append([
                            data['left'][i],
                            data['top'][i],
                            data['left'][i] + data['width'][i],
                            data['top'][i] + data['height'][i]
                        ])
                
                # Processar linhas
                for line_num in sorted(lines.keys()):
                    line_data = lines[line_num]
                    line_text = ' '.join(line_data['words'])
                    line_conf = sum(line_data['confidences']) / len(line_data['confidences'])
                    
                    # Calcular bbox da linha
                    boxes = line_data['boxes']
                    line_bbox = [
                        min(box[0] for box in boxes),
                        min(box[1] for box in boxes),
                        max(box[2] for box in boxes),
                        max(box[3] for box in boxes)
                    ]
                    
                    text_lines.append(line_text)
                    confidences.append(line_conf)
                    
                    blocks.append({
                        "text": line_text,
                        "confidence": line_conf / 100.0,  # Converter para [0,1]
                        "bbox": line_bbox,
                        "word_count": len(line_data['words'])
                    })
            
            else:
                # Processar palavra por palavra
                for i in range(len(data['text'])):
                    word = data['text'][i].strip()
                    conf = int(data['conf'][i])
                    
                    if word and conf > min_confidence:
                        bbox = [
                            data['left'][i],
                            data['top'][i],
                            data['left'][i] + data['width'][i],
                            data['top'][i] + data['height'][i]
                        ]
                        
                        blocks.append({
                            "text": word,
                            "confidence": conf / 100.0,
                            "bbox": bbox,
                            "word_count": 1
                        })
                        
                        text_lines.append(word)
                        confidences.append(conf)
            
            # Combinar resultado
            combined_text = '\n'.join(text_lines) if group_by_line else ' '.join(text_lines)
            avg_confidence = sum(confidences) / len(confidences) / 100.0 if confidences else 0.0
            
            return {
                "text": combined_text,
                "confidence": avg_confidence,
                "blocks": blocks,
                "statistics": {
                    "total_blocks": len(blocks),
                    "avg_confidence": avg_confidence,
                    "min_confidence": min(confidences) / 100.0 if confidences else 0.0,
                    "max_confidence": max(confidences) / 100.0 if confidences else 0.0,
                    "char_count": len(combined_text),
                    "word_count": len(combined_text.split())
                }
            }
            
        except Exception as e:
            self.logger.error(f"Tesseract data processing failed: {e}")
            raise
    
    def get_supported_languages(self) -> List[str]:
        """Retorna idiomas suportados pelo Tesseract instalado"""
        try:
            return pytesseract.get_languages()
        except Exception:
            return ['eng', 'por']  # Fallback
    
    def get_tesseract_version(self) -> str:
        """Retorna versão do Tesseract"""
        try:
            return str(pytesseract.get_tesseract_version())
        except Exception:
            return "unknown"


# Registrar tasks Celery
@celery_app.task(bind=True, base=TesseractWorker, queue='tesseract_queue')
def tesseract_process_image(self, request_data: dict):
    """Task para processar imagem com Tesseract"""
    request = OCRRequest(**request_data)
    response = self.execute_ocr(request)
    return response.dict()


@celery_app.task(bind=True, base=TesseractWorker, queue='tesseract_queue')
def tesseract_health_check(self):
    """Task para verificar saúde do Tesseract"""
    return self.health_check()


@celery_app.task(bind=True, base=TesseractWorker, queue='tesseract_queue')
def tesseract_get_languages(self):
    """Task para obter idiomas suportados"""
    worker = TesseractWorker()
    return {
        "supported_languages": worker.get_supported_languages(),
        "tesseract_version": worker.get_tesseract_version()
    }


# Configurações específicas do worker
def configure_tesseract_worker():
    """Configura worker Tesseract"""
    config = get_engine_config("tesseract")
    
    return {
        "queue": "tesseract_queue",
        "concurrency": config.get("max_workers", 10),  # CPU only, pode ter muitos workers
        "prefetch_multiplier": 3,  # Pode pré-carregar várias tasks
        "max_tasks_per_child": 500,  # Muito estável, pode processar muitas tasks
    }


if __name__ == "__main__":
    """Teste do worker Tesseract"""
    import os
    
    print("=== Tesseract Worker Test ===")
    
    if not TESSERACT_AVAILABLE:
        print("❌ Tesseract dependencies not available")
        exit(1)
    
    worker = TesseractWorker()
    
    # Teste de carregamento/verificação
    try:
        worker.load_model()
        print("✅ Tesseract configured successfully")
    except Exception as e:
        print(f"❌ Tesseract setup failed: {e}")
        exit(1)
    
    # Teste de health check
    health = worker.health_check()
    print(f"Health status: {health['status']}")
    
    # Informações do sistema
    print(f"Tesseract version: {worker.get_tesseract_version()}")
    languages = worker.get_supported_languages()
    print(f"Supported languages: {languages[:10]}...")  # Mostrar apenas algumas
    
    # Teste com imagem de exemplo
    test_image_path = "test_document.jpg"
    if os.path.exists(test_image_path):
        print(f"\n--- Testing with {test_image_path} ---")
        
        request = OCRRequest(
            file_path=test_image_path,
            engine="tesseract",
            parameters={
                "preprocess_mode": "auto",
                "detailed_output": True,
                "group_by_line": True,
                "min_confidence": 30,
                "psm": 6
            }
        )
        
        try:
            result = worker.execute_ocr(request)
            print(f"✅ OCR successful")
            print(f"Text length: {len(result.text)}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Blocks: {len(result.blocks)}")
            print(f"Processing time: {result.processing_time:.2f}s")
                
        except Exception as e:
            print(f"❌ OCR failed: {e}")
    else:
        print(f"⚠️  Test image {test_image_path} not found")
    
    print("\n✅ Tesseract Worker test completed")