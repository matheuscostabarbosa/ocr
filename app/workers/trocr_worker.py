#!/usr/bin/env python3
"""
TrOCR Worker - Especializado em Manuscritos
==========================================

Worker especializado para textos manuscritos usando TrOCR.
Melhor performance para:
- Textos manuscritos
- Documentos de baixa qualidade
- Textos complexos e degradados
"""

import torch
import time
from typing import Dict, Any, List
from PIL import Image
import numpy as np

from app.workers.base_worker import BaseOCRWorker
from app.core.celery_app import celery_app
from app.core.config import settings, get_engine_config
from app.models.schemas import OCRRequest, OCRResponse

try:
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    TROCR_AVAILABLE = True
except ImportError:
    TROCR_AVAILABLE = False


class TrOCRWorker(BaseOCRWorker):
    """Worker TrOCR para reconhecimento de manuscritos"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "trocr"
        self.config = get_engine_config(self.engine_name)
        
        # Configurações específicas do TrOCR
        self.model_name = self.config.get("model_name", "microsoft/trocr-large-handwritten")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.max_length = 384  # Tamanho máximo de tokens
        
        if not TROCR_AVAILABLE:
            raise ImportError("TrOCR dependencies not available. Install with: pip install transformers torch")
    
    def load_model(self):
        """Carrega modelo TrOCR"""
        try:
            self.logger.info(f"Loading TrOCR model: {self.model_name}")
            
            # Carregar processor e model
            self.processor = TrOCRProcessor.from_pretrained(self.model_name)
            self.model = VisionEncoderDecoderModel.from_pretrained(self.model_name)
            
            # Mover para GPU se disponível
            self.model.to(self.device)
            self.model.eval()  # Modo de inferência
            
            self.logger.info(f"TrOCR model loaded on device: {self.device}")
            
            # Configurar para otimização
            if torch.cuda.is_available():
                # Usar mixed precision se disponível
                try:
                    self.model = torch.jit.script(self.model)
                    self.logger.info("TrOCR model optimized with TorchScript")
                except Exception as e:
                    self.logger.warning(f"TorchScript optimization failed: {e}")
            
        except Exception as e:
            self.logger.error(f"Failed to load TrOCR model: {e}")
            raise
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processa imagem com TrOCR"""
        try:
            # Carregar e preparar imagem
            image = Image.open(image_path).convert('RGB')
            
            # Pré-processamento específico para manuscritos
            image = self._preprocess_for_handwriting(image, **kwargs)
            
            # Detectar se precisa segmentar texto
            if kwargs.get('segment_lines', True):
                return self._process_with_segmentation(image, **kwargs)
            else:
                return self._process_single_region(image, **kwargs)
                
        except Exception as e:
            self.logger.error(f"TrOCR processing failed: {e}")
            raise
    
    def _preprocess_for_handwriting(self, image: Image.Image, **kwargs) -> Image.Image:
        """Pré-processamento específico para manuscritos"""
        try:
            # Melhorar contraste para manuscritos
            if kwargs.get('enhance_contrast', True):
                from PIL import ImageEnhance
                
                # Aumentar contraste
                enhancer = ImageEnhance.Contrast(image)
                image = enhancer.enhance(1.3)
                
                # Aumentar brilho se necessário
                if kwargs.get('enhance_brightness', False):
                    enhancer = ImageEnhance.Brightness(image)
                    image = enhancer.enhance(1.1)
            
            # Redimensionar mantendo proporção ideal para TrOCR
            target_height = kwargs.get('target_height', 384)
            if image.height != target_height:
                ratio = target_height / image.height
                new_width = int(image.width * ratio)
                image = image.resize((new_width, target_height), Image.Resampling.LANCZOS)
            
            return image
            
        except Exception as e:
            self.logger.warning(f"Handwriting preprocessing failed: {e}")
            return image
    
    def _process_single_region(self, image: Image.Image, **kwargs) -> Dict[str, Any]:
        """Processa região única de texto"""
        try:
            start_time = time.time()
            
            # Preparar entrada para o modelo
            pixel_values = self.processor(image, return_tensors="pt").pixel_values.to(self.device)
            
            # Configurar geração
            generation_config = {
                "max_length": kwargs.get('max_length', self.max_length),
                "num_beams": kwargs.get('num_beams', 5),
                "early_stopping": True,
                "do_sample": False,
                "pad_token_id": self.processor.tokenizer.pad_token_id,
                "eos_token_id": self.processor.tokenizer.eos_token_id,
            }
            
            # Executar inferência
            with torch.no_grad():
                generated_ids = self.model.generate(pixel_values, **generation_config)
            
            # Decodificar resultado
            generated_text = self.processor.batch_decode(
                generated_ids, 
                skip_special_tokens=True
            )[0]
            
            processing_time = time.time() - start_time
            
            # Calcular confiança aproximada (TrOCR não retorna scores)
            confidence = self._estimate_confidence(generated_text, image)
            
            return {
                "text": generated_text,
                "confidence": confidence,
                "processing_time": processing_time,
                "blocks": [{
                    "text": generated_text,
                    "confidence": confidence,
                    "bbox": [0, 0, image.width, image.height]
                }],
                "method": "single_region"
            }
            
        except Exception as e:
            self.logger.error(f"Single region processing failed: {e}")
            raise
    
    def _process_with_segmentation(self, image: Image.Image, **kwargs) -> Dict[str, Any]:
        """Processa com segmentação de linhas de texto"""
        try:
            # Detectar linhas de texto
            text_lines = self._detect_text_lines(image, **kwargs)
            
            if not text_lines:
                # Fallback para região única
                return self._process_single_region(image, **kwargs)
            
            all_texts = []
            all_blocks = []
            total_processing_time = 0
            
            for i, (line_image, bbox) in enumerate(text_lines):
                try:
                    # Processar linha individual
                    line_result = self._process_single_region(line_image, **kwargs)
                    
                    if line_result["text"].strip():
                        all_texts.append(line_result["text"])
                        
                        # Ajustar bbox para coordenadas da imagem original
                        adjusted_bbox = [
                            bbox[0], bbox[1], 
                            bbox[0] + line_image.width, 
                            bbox[1] + line_image.height
                        ]
                        
                        all_blocks.append({
                            "text": line_result["text"],
                            "confidence": line_result["confidence"],
                            "bbox": adjusted_bbox,
                            "line_number": i + 1
                        })
                    
                    total_processing_time += line_result["processing_time"]
                    
                except Exception as e:
                    self.logger.warning(f"Failed to process line {i}: {e}")
                    continue
            
            # Combinar resultados
            combined_text = "\n".join(all_texts)
            avg_confidence = sum(block["confidence"] for block in all_blocks) / len(all_blocks) if all_blocks else 0
            
            return {
                "text": combined_text,
                "confidence": avg_confidence,
                "processing_time": total_processing_time,
                "blocks": all_blocks,
                "method": "line_segmentation",
                "lines_detected": len(text_lines),
                "lines_processed": len(all_blocks)
            }
            
        except Exception as e:
            self.logger.error(f"Segmented processing failed: {e}")
            # Fallback para região única
            return self._process_single_region(image, **kwargs)
    
    def _detect_text_lines(self, image: Image.Image, **kwargs) -> List[tuple]:
        """Detecta linhas de texto na imagem"""
        try:
            import cv2
            
            # Converter PIL para OpenCV
            img_array = np.array(image)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # Binarizar imagem
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # Detectar contornos de texto
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 2))
            dilated = cv2.morphologyEx(binary, cv2.MORPH_DILATE, kernel)
            
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filtrar e ordenar contornos
            text_lines = []
            min_area = kwargs.get('min_line_area', 500)
            
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                
                # Filtrar por área e proporção
                if w * h > min_area and w > h * 2:  # Linha deve ser mais larga que alta
                    # Extrair região da imagem
                    line_image = image.crop((x, y, x + w, y + h))
                    text_lines.append((line_image, (x, y, w, h)))
            
            # Ordenar por posição vertical (top-down)
            text_lines.sort(key=lambda x: x[1][1])
            
            return text_lines
            
        except Exception as e:
            self.logger.warning(f"Text line detection failed: {e}")
            return []
    
    def _estimate_confidence(self, text: str, image: Image.Image) -> float:
        """Estima confiança baseada em heurísticas"""
        try:
            # Heurísticas simples para estimar confiança
            confidence = 0.8  # Base confidence
            
            # Penalizar texto muito curto
            if len(text.strip()) < 3:
                confidence -= 0.3
            
            # Penalizar muitos caracteres especiais
            special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace())
            if special_chars > len(text) * 0.3:
                confidence -= 0.2
            
            # Bonificar texto com palavras reconhecíveis
            words = text.split()
            if len(words) > 1:
                confidence += 0.1
            
            # Ajustar baseado na qualidade da imagem
            img_array = np.array(image.convert('L'))
            
            # Calcular contraste
            contrast = img_array.std()
            if contrast < 30:  # Baixo contraste
                confidence -= 0.1
            elif contrast > 60:  # Bom contraste
                confidence += 0.1
            
            # Garantir que está no range [0, 1]
            confidence = max(0.0, min(1.0, confidence))
            
            return confidence
            
        except Exception as e:
            self.logger.warning(f"Confidence estimation failed: {e}")
            return 0.8  # Default confidence
    
    def get_supported_languages(self) -> List[str]:
        """Retorna idiomas suportados pelo TrOCR"""
        # TrOCR foi treinado principalmente em inglês, mas funciona razoavelmente com outros idiomas latinos
        return ["en", "pt", "es", "fr", "de", "it"]
    
    def cleanup_model(self):
        """Limpa modelo da memória"""
        try:
            if hasattr(self, 'model') and self.model is not None:
                del self.model
            
            if hasattr(self, 'processor') and self.processor is not None:
                del self.processor
            
            # Limpar cache CUDA se disponível
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
            self._model_loaded = False
            self.logger.info("TrOCR model cleaned up from memory")
            
        except Exception as e:
            self.logger.warning(f"Model cleanup failed: {e}")


# Registrar tasks Celery
@celery_app.task(bind=True, base=TrOCRWorker, queue='trocr_queue')
def trocr_process_image(self, request_data: dict):
    """Task para processar imagem com TrOCR"""
    request = OCRRequest(**request_data)
    response = self.execute_ocr(request)
    return response.dict()


@celery_app.task(bind=True, base=TrOCRWorker, queue='trocr_queue')
def trocr_health_check(self):
    """Task para verificar saúde do TrOCR"""
    return self.health_check()


@celery_app.task(bind=True, base=TrOCRWorker, queue='trocr_queue')
def trocr_cleanup_model(self):
    """Task para limpar modelo da memória"""
    self.cleanup_model()
    return {"status": "model_cleaned"}


# Configurações específicas do worker
def configure_trocr_worker():
    """Configura worker TrOCR"""
    config = get_engine_config("trocr")
    
    # Verificar se GPU está disponível e tem memória suficiente
    if torch.cuda.is_available():
        gpu_memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        required_memory = config.get("gpu_memory_required", 4)
        
        if gpu_memory_gb < required_memory:
            logger.warning(f"GPU memory ({gpu_memory_gb:.1f}GB) below recommended ({required_memory}GB) for TrOCR")
    
    return {
        "queue": "trocr_queue",
        "concurrency": config.get("max_workers", 2),
        "prefetch_multiplier": 1,  # GPU intensive, process one at a time
        "max_tasks_per_child": 50,  # Restart worker periodically to prevent memory leaks
    }


if __name__ == "__main__":
    """Teste do worker TrOCR"""
    import tempfile
    import os
    
    print("=== TrOCR Worker Test ===")
    
    if not TROCR_AVAILABLE:
        print("❌ TrOCR dependencies not available")
        exit(1)
    
    worker = TrOCRWorker()
    
    # Teste de carregamento do modelo
    try:
        worker.load_model()
        print("✅ Model loaded successfully")
    except Exception as e:
        print(f"❌ Model loading failed: {e}")
        exit(1)
    
    # Teste de health check
    health = worker.health_check()
    print(f"Health status: {health['status']}")
    
    # Teste com imagem de exemplo (se disponível)
    test_image_path = "test_handwriting.jpg"
    if os.path.exists(test_image_path):
        print(f"\n--- Testing with {test_image_path} ---")
        
        request = OCRRequest(
            file_path=test_image_path,
            engine="trocr",
            parameters={"segment_lines": True, "enhance_contrast": True}
        )
        
        try:
            result = worker.execute_ocr(request)
            print(f"✅ OCR successful")
            print(f"Text: {result.text[:100]}...")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Blocks: {len(result.blocks)}")
        except Exception as e:
            print(f"❌ OCR failed: {e}")
    else:
        print(f"⚠️  Test image {test_image_path} not found")
    
    print("\n✅ TrOCR Worker test completed")