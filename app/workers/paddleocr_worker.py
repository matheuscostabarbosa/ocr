#!/usr/bin/env python3
"""
PaddleOCR Worker - Produção e Velocidade
=======================================

Worker especializado para processamento rápido usando PaddleOCR.
Ideal para:
- Processamento em lote
- Ambiente de produção
- Múltiplos idiomas
- Eficiência e velocidade
"""

import time
from typing import Dict, Any, List, Tuple
from PIL import Image
import numpy as np
import cv2

from app.workers.base_worker import BaseOCRWorker
from app.core.celery_app import celery_app
from app.core.config import settings, get_engine_config
from app.models.schemas import OCRRequest, OCRResponse

try:
    import paddleocr
    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False


class PaddleOCRWorker(BaseOCRWorker):
    """Worker PaddleOCR para processamento rápido em produção"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "paddleocr"
        self.config = get_engine_config(self.engine_name)
        
        # Configurações PaddleOCR
        self.lang = self.config.get("lang", "pt")
        self.use_angle_cls = self.config.get("use_angle_cls", True)
        self.use_gpu = self.config.get("use_gpu", False)
        
        if not PADDLEOCR_AVAILABLE:
            raise ImportError("PaddleOCR dependencies not available. Install with: pip install paddlepaddle paddleocr")
    
    def load_model(self):
        """Carrega modelo PaddleOCR"""
        try:
            self.logger.info(f"Loading PaddleOCR model with lang: {self.lang}")
            
            # Inicializar PaddleOCR
            self.model = paddleocr.PaddleOCR(
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                use_gpu=self.use_gpu,
                show_log=False  # Reduzir logs verbosos
            )
            
            self.logger.info("PaddleOCR model loaded successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to load PaddleOCR model: {e}")
            raise
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processa imagem com PaddleOCR"""
        try:
            start_time = time.time()
            
            # Pré-processamento específico se necessário
            processed_image_path = self._preprocess_for_paddleocr(image_path, **kwargs)
            
            try:
                # Executar OCR
                ocr_result = self.model.ocr(processed_image_path, cls=self.use_angle_cls)
                
                # Processar resultados
                result = self._process_paddleocr_result(ocr_result, **kwargs)
                
                result['processing_time'] = time.time() - start_time
                return result
                
            finally:
                # Limpar arquivo temporário se foi criado
                if processed_image_path != image_path:
                    try:
                        import os
                        os.unlink(processed_image_path)
                    except Exception:
                        pass
                        
        except Exception as e:
            self.logger.error(f"PaddleOCR processing failed: {e}")
            raise
    
    def _preprocess_for_paddleocr(self, image_path: str, **kwargs) -> str:
        """Pré-processamento específico para PaddleOCR"""
        try:
            # Carregar imagem
            image = cv2.imread(image_path)
            if image is None:
                return image_path
            
            modified = False
            
            # Aplicar filtros se especificado
            if kwargs.get('denoise', False):
                image = cv2.fastNlMeansDenoisingColored(image, None, 10, 10, 7, 21)
                modified = True
            
            # Melhorar contraste se especificado
            if kwargs.get('enhance_contrast', False):
                lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
                l, a, b = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                l = clahe.apply(l)
                image = cv2.merge([l, a, b])
                image = cv2.cvtColor(image, cv2.COLOR_LAB2BGR)
                modified = True
            
            # Redimensionar se muito grande
            max_size = kwargs.get('max_size', 2048)
            height, width = image.shape[:2]
            if max(height, width) > max_size:
                scale = max_size / max(height, width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
                modified = True
            
            # Salvar se modificada
            if modified:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    cv2.imwrite(tmp_file.name, image, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    return tmp_file.name
            
            return image_path
            
        except Exception as e:
            self.logger.warning(f"PaddleOCR preprocessing failed: {e}")
            return image_path
    
    def _process_paddleocr_result(self, ocr_result: List, **kwargs) -> Dict[str, Any]:
        """Processa resultado do PaddleOCR"""
        try:
            if not ocr_result or not ocr_result[0]:
                return {
                    "text": "",
                    "confidence": 0.0,
                    "blocks": [],
                    "statistics": {
                        "total_blocks": 0,
                        "avg_confidence": 0.0,
                        "char_count": 0,
                        "word_count": 0
                    }
                }
            
            text_lines = []
            blocks = []
            confidences = []
            
            # Processar cada linha detectada
            for line_data in ocr_result[0]:
                if not line_data or len(line_data) < 2:
                    continue
                
                bbox_points = line_data[0]  # Pontos da bounding box
                text_info = line_data[1]    # Texto e confiança
                
                # Extrair texto e confiança
                if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                    text = text_info[0]
                    confidence = float(text_info[1])
                else:
                    text = str(text_info)
                    confidence = 0.8  # Confiança padrão
                
                # Filtrar por confiança mínima
                min_confidence = kwargs.get('min_confidence', 0.3)
                if confidence < min_confidence:
                    continue
                
                # Converter pontos para bbox retangular
                bbox = self._points_to_bbox(bbox_points)
                
                if text.strip():
                    text_lines.append(text)
                    confidences.append(confidence)
                    
                    blocks.append({
                        "text": text,
                        "confidence": confidence,
                        "bbox": bbox,
                        "bbox_points": bbox_points
                    })
            
            # Combinar resultados
            combined_text = self._combine_text_lines(text_lines, blocks, **kwargs)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            result = {
                "text": combined_text,
                "confidence": avg_confidence,
                "blocks": blocks,
                "statistics": {
                    "total_blocks": len(blocks),
                    "avg_confidence": avg_confidence,
                    "min_confidence": min(confidences) if confidences else 0.0,
                    "max_confidence": max(confidences) if confidences else 0.0,
                    "char_count": len(combined_text),
                    "word_count": len(combined_text.split())
                }
            }
            
            # Detectar estrutura se solicitado
            if kwargs.get('detect_structure', True):
                result = self._detect_text_structure(result, **kwargs)
            
            return result
            
        except Exception as e:
            self.logger.error(f"PaddleOCR result processing failed: {e}")
            raise
    
    def _points_to_bbox(self, points: List) -> List[float]:
        """Converte pontos da bbox para formato retangular [x0, y0, x1, y1]"""
        try:
            if not points or len(points) != 4:
                return [0, 0, 0, 0]
            
            # Extrair coordenadas x e y
            x_coords = [point[0] for point in points]
            y_coords = [point[1] for point in points]
            
            return [
                min(x_coords),  # x0
                min(y_coords),  # y0
                max(x_coords),  # x1
                max(y_coords)   # y1
            ]
            
        except Exception:
            return [0, 0, 0, 0]
    
    def _combine_text_lines(self, text_lines: List[str], blocks: List[Dict], **kwargs) -> str:
        """Combina linhas de texto considerando layout"""
        try:
            if not text_lines:
                return ""
            
            # Ordenar blocos por posição (top-down, left-right)
            sorted_blocks = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
            
            # Detectar se é texto em colunas
            if kwargs.get('detect_columns', True):
                return self._combine_text_with_columns(sorted_blocks)
            else:
                return "\n".join([block["text"] for block in sorted_blocks])
                
        except Exception as e:
            self.logger.warning(f"Text combination failed: {e}")
            return "\n".join(text_lines)
    
    def _combine_text_with_columns(self, blocks: List[Dict]) -> str:
        """Combina texto considerando colunas"""
        try:
            if len(blocks) <= 1:
                return blocks[0]["text"] if blocks else ""
            
            # Detectar colunas baseado na posição horizontal
            columns = []
            current_column = []
            
            # Agrupar por proximidade horizontal
            tolerance = 50  # pixels
            
            for block in blocks:
                bbox = block["bbox"]
                x_center = (bbox[0] + bbox[2]) / 2
                
                # Verificar se pertence à coluna atual
                if not current_column:
                    current_column.append(block)
                else:
                    last_x = (current_column[-1]["bbox"][0] + current_column[-1]["bbox"][2]) / 2
                    
                    if abs(x_center - last_x) <= tolerance:
                        current_column.append(block)
                    else:
                        # Nova coluna
                        if current_column:
                            columns.append(current_column)
                        current_column = [block]
            
            if current_column:
                columns.append(current_column)
            
            # Combinar texto das colunas
            if len(columns) == 1:
                # Texto em coluna única
                return "\n".join([block["text"] for block in columns[0]])
            else:
                # Múltiplas colunas - combinar linha por linha
                column_texts = []
                for column in columns:
                    column_text = "\n".join([block["text"] for block in column])
                    column_texts.append(column_text)
                
                return "\n\n".join(column_texts)
                
        except Exception as e:
            self.logger.warning(f"Column detection failed: {e}")
            return "\n".join([block["text"] for block in blocks])
    
    def _detect_text_structure(self, result: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Detecta estrutura do texto (títulos, parágrafos, listas)"""
        try:
            blocks = result.get("blocks", [])
            if not blocks:
                return result
            
            structured_blocks = []
            
            for block in blocks:
                bbox = block["bbox"]
                text = block["text"]
                
                # Detectar tipo baseado na posição e formato
                block_type = "text"
                
                # Detectar títulos (texto maior, centralizado ou em bold)
                height = bbox[3] - bbox[1]
                if height > 30:  # Altura maior que normal
                    if text.isupper() or len(text.split()) <= 5:
                        block_type = "title"
                    else:
                        block_type = "header"
                
                # Detectar listas
                if text.strip().startswith(('•', '-', '*', '1.', '2.', '3.')):
                    block_type = "list_item"
                
                # Detectar números/datas
                if len(text.split()) <= 3 and any(char.isdigit() for char in text):
                    if "/" in text or "-" in text:
                        block_type = "date_number"
                
                structured_block = block.copy()
                structured_block["structure_type"] = block_type
                structured_blocks.append(structured_block)
            
            result["structured_blocks"] = structured_blocks
            
            # Gerar texto estruturado
            if kwargs.get('output_format') == 'markdown':
                result["markdown"] = self._generate_structured_markdown(structured_blocks)
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Structure detection failed: {e}")
            return result
    
    def _generate_structured_markdown(self, structured_blocks: List[Dict]) -> str:
        """Gera markdown baseado na estrutura detectada"""
        try:
            markdown_parts = []
            
            for block in structured_blocks:
                text = block["text"].strip()
                if not text:
                    continue
                
                structure_type = block.get("structure_type", "text")
                
                if structure_type == "title":
                    markdown_parts.append(f"# {text}")
                elif structure_type == "header":
                    markdown_parts.append(f"## {text}")
                elif structure_type == "list_item":
                    # Limpar marcadores existentes e adicionar markdown
                    clean_text = text.lstrip('•-* ').lstrip('0123456789. ')
                    markdown_parts.append(f"- {clean_text}")
                elif structure_type == "date_number":
                    markdown_parts.append(f"**{text}**")
                else:
                    markdown_parts.append(text)
            
            return "\n\n".join(markdown_parts)
            
        except Exception as e:
            self.logger.warning(f"Structured markdown generation failed: {e}")
            return "\n".join([block["text"] for block in structured_blocks])
    
    def get_supported_languages(self) -> List[str]:
        """Retorna idiomas suportados pelo PaddleOCR"""
        return [
            'ch', 'en', 'korean', 'japan', 'chinese_cht', 'ta', 'te', 'ka', 'latin', 'arabic', 'cyrillic', 
            'devanagari', 'french', 'german', 'it', 'xi', 'pu', 'ru', 'ad', 'rsc', 'rs', 'ms', 'tl', 
            'tg', 'mn', 'fa', 'ur', 'rs_latin', 'oc', 'mr', 'ne', 'or', 'as', 'ks', 'chinese_tra', 'pt'
        ]
    
    def batch_process_images(self, image_paths: List[str], **kwargs) -> List[Dict[str, Any]]:
        """Processa múltiplas imagens em lote (otimização PaddleOCR)"""
        try:
            results = []
            
            # PaddleOCR é otimizado para processamento individual
            # mas podemos otimizar o pipeline
            for image_path in image_paths:
                try:
                    result = self.process_image(image_path, **kwargs)
                    result["file_path"] = image_path
                    results.append(result)
                except Exception as e:
                    self.logger.error(f"Failed to process {image_path}: {e}")
                    results.append({
                        "file_path": image_path,
                        "error": str(e),
                        "text": "",
                        "confidence": 0.0,
                        "blocks": []
                    })
            
            return results
            
        except Exception as e:
            self.logger.error(f"Batch processing failed: {e}")
            raise


# Registrar tasks Celery
@celery_app.task(bind=True, base=PaddleOCRWorker, queue='paddleocr_queue')
def paddleocr_process_image(self, request_data: dict):
    """Task para processar imagem com PaddleOCR"""
    request = OCRRequest(**request_data)
    response = self.execute_ocr(request)
    return response.dict()


@celery_app.task(bind=True, base=PaddleOCRWorker, queue='paddleocr_queue')
def paddleocr_batch_process(self, image_paths: List[str], parameters: dict = None):
    """Task para processamento em lote com PaddleOCR"""
    worker = PaddleOCRWorker()
    worker._ensure_model_loaded()
    
    results = worker.batch_process_images(image_paths, **(parameters or {}))
    return results


@celery_app.task(bind=True, base=PaddleOCRWorker, queue='paddleocr_queue')
def paddleocr_health_check(self):
    """Task para verificar saúde do PaddleOCR"""
    return self.health_check()


# Configurações específicas do worker
def configure_paddleocr_worker():
    """Configura worker PaddleOCR"""
    config = get_engine_config("paddleocr")
    
    return {
        "queue": "paddleocr_queue",
        "concurrency": config.get("max_workers", 8),  # Pode ter mais workers por ser rápido
        "prefetch_multiplier": 2,  # Pode pré-carregar mais tasks
        "max_tasks_per_child": 200,  # Processar mais tasks antes de reiniciar
    }


if __name__ == "__main__":
    """Teste do worker PaddleOCR"""
    import os
    
    print("=== PaddleOCR Worker Test ===")
    
    if not PADDLEOCR_AVAILABLE:
        print("❌ PaddleOCR dependencies not available")
        exit(1)
    
    worker = PaddleOCRWorker()
    
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
    
    # Teste com imagem de exemplo
    test_image_path = "test_document.jpg"
    if os.path.exists(test_image_path):
        print(f"\n--- Testing with {test_image_path} ---")
        
        request = OCRRequest(
            file_path=test_image_path,
            engine="paddleocr",
            parameters={
                "detect_structure": True,
                "detect_columns": True,
                "min_confidence": 0.5,
                "output_format": "markdown"
            }
        )
        
        try:
            result = worker.execute_ocr(request)
            print(f"✅ OCR successful")
            print(f"Text length: {len(result.text)}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Blocks: {len(result.blocks)}")
            print(f"Processing time: {result.processing_time:.2f}s")
            
            if hasattr(result, 'markdown'):
                print(f"Markdown: {len(result.markdown)} chars")
                
        except Exception as e:
            print(f"❌ OCR failed: {e}")
    else:
        print(f"⚠️  Test image {test_image_path} not found")
    
    # Teste de idiomas suportados
    languages = worker.get_supported_languages()
    print(f"\nSupported languages: {len(languages)}")
    print(f"Sample languages: {languages[:10]}")
    
    print("\n✅ PaddleOCR Worker test completed")