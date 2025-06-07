#!/usr/bin/env python3
"""
EasyOCR Worker - Simplicidade e Versatilidade
=============================================

Worker especializado usando EasyOCR.
Ideal para:
- Uso geral e multipropósito
- Múltiplos idiomas
- Textos em várias orientações
- Balanceamento custo-benefício
- Setup simples
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
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False


class EasyOCRWorker(BaseOCRWorker):
    """Worker EasyOCR para uso geral e múltiplos idiomas"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "easyocr"
        self.config = get_engine_config(self.engine_name)
        
        # Configurações EasyOCR
        self.languages = self.config.get("languages", ["pt", "en"])
        self.gpu = self.config.get("use_gpu", True)  # EasyOCR se beneficia de GPU
        
        # Configurações de processamento
        self.detail_mode = True
        self.width_threshold = 0.7
        self.height_threshold = 0.7
        
        if not EASYOCR_AVAILABLE:
            raise ImportError("EasyOCR dependencies not available. Install with: pip install easyocr")
    
    def load_model(self):
        """Carrega modelo EasyOCR"""
        try:
            self.logger.info(f"Loading EasyOCR with languages: {self.languages}")
            
            # Inicializar EasyOCR Reader
            self.model = easyocr.Reader(
                self.languages,
                gpu=self.gpu,
                verbose=False  # Reduzir logs verbosos
            )
            
            self.logger.info("EasyOCR model loaded successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to load EasyOCR model: {e}")
            raise
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processa imagem com EasyOCR"""
        try:
            start_time = time.time()
            
            # Configurar parâmetros
            detail = kwargs.get('detail_mode', self.detail_mode)
            width_ths = kwargs.get('width_threshold', self.width_threshold)
            height_ths = kwargs.get('height_threshold', self.height_threshold)
            
            # Parâmetros avançados
            decoder = kwargs.get('decoder', 'greedy')  # 'greedy' ou 'beamsearch'
            beamWidth = kwargs.get('beam_width', 5)
            batch_size = kwargs.get('batch_size', 1)
            
            # Pré-processamento se necessário
            processed_image_path = self._preprocess_for_easyocr(image_path, **kwargs)
            
            try:
                # Executar OCR
                if decoder == 'beamsearch':
                    results = self.model.readtext(
                        processed_image_path,
                        detail=detail,
                        width_ths=width_ths,
                        height_ths=height_ths,
                        decoder=decoder,
                        beamWidth=beamWidth,
                        batch_size=batch_size
                    )
                else:
                    results = self.model.readtext(
                        processed_image_path,
                        detail=detail,
                        width_ths=width_ths,
                        height_ths=height_ths,
                        batch_size=batch_size
                    )
                
                # Processar resultados
                result = self._process_easyocr_results(results, **kwargs)
                
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
            self.logger.error(f"EasyOCR processing failed: {e}")
            raise
    
    def _preprocess_for_easyocr(self, image_path: str, **kwargs) -> str:
        """Pré-processamento otimizado para EasyOCR"""
        try:
            # Carregar imagem
            image = cv2.imread(image_path)
            if image is None:
                return image_path
            
            modified = False
            
            # EasyOCR funciona bem com imagens em cores, mas pode ser otimizado
            
            # Redimensionamento inteligente
            target_size = kwargs.get('target_size', None)
            if target_size:
                height, width = image.shape[:2]
                if max(height, width) != target_size:
                    if height > width:
                        new_height = target_size
                        new_width = int(width * target_size / height)
                    else:
                        new_width = target_size
                        new_height = int(height * target_size / width)
                    
                    image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
                    modified = True
            
            # Correção de iluminação se especificado
            if kwargs.get('correct_lighting', False):
                image = self._correct_lighting(image)
                modified = True
            
            # Melhoria de contraste se especificado
            if kwargs.get('enhance_contrast', False):
                image = self._enhance_contrast(image)
                modified = True
            
            # Correção de perspectiva se especificado
            if kwargs.get('correct_perspective', False):
                corrected = self._correct_perspective(image)
                if corrected is not None:
                    image = corrected
                    modified = True
            
            # Salvar se modificada
            if modified:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                    cv2.imwrite(tmp_file.name, image, [cv2.IMWRITE_JPEG_QUALITY, 95])
                    return tmp_file.name
            
            return image_path
            
        except Exception as e:
            self.logger.warning(f"EasyOCR preprocessing failed: {e}")
            return image_path
    
    def _correct_lighting(self, image: np.ndarray) -> np.ndarray:
        """Corrige iluminação desigual"""
        try:
            # Converter para LAB
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            
            # Aplicar CLAHE no canal L
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            l = clahe.apply(l)
            
            # Recombinar
            enhanced = cv2.merge([l, a, b])
            image = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
            
            return image
            
        except Exception as e:
            self.logger.warning(f"Lighting correction failed: {e}")
            return image
    
    def _enhance_contrast(self, image: np.ndarray) -> np.ndarray:
        """Melhora contraste da imagem"""
        try:
            # Converter para YUV
            yuv = cv2.cvtColor(image, cv2.COLOR_BGR2YUV)
            
            # Equalizar histograma do canal Y
            yuv[:, :, 0] = cv2.equalizeHist(yuv[:, :, 0])
            
            # Converter de volta
            image = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)
            
            return image
            
        except Exception as e:
            self.logger.warning(f"Contrast enhancement failed: {e}")
            return image
    
    def _correct_perspective(self, image: np.ndarray) -> np.ndarray:
        """Corrige perspectiva da imagem"""
        try:
            # Converter para escala de cinza para detectar bordas
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Detectar bordas
            edges = cv2.Canny(gray, 50, 150, apertureSize=3)
            
            # Encontrar contornos
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Encontrar o maior contorno retangular
            largest_contour = None
            max_area = 0
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area > max_area:
                    # Aproximar contorno para polígono
                    epsilon = 0.02 * cv2.arcLength(contour, True)
                    approx = cv2.approxPolyDP(contour, epsilon, True)
                    
                    # Se é um quadrilátero e tem área significativa
                    if len(approx) == 4 and area > gray.shape[0] * gray.shape[1] * 0.3:
                        largest_contour = approx
                        max_area = area
            
            if largest_contour is not None:
                # Ordenar pontos
                pts = largest_contour.reshape(4, 2)
                rect = self._order_points(pts)
                
                # Calcular dimensões do retângulo
                (tl, tr, br, bl) = rect
                
                widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
                widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
                maxWidth = max(int(widthA), int(widthB))
                
                heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
                heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
                maxHeight = max(int(heightA), int(heightB))
                
                # Definir pontos de destino
                dst = np.array([
                    [0, 0],
                    [maxWidth - 1, 0],
                    [maxWidth - 1, maxHeight - 1],
                    [0, maxHeight - 1]
                ], dtype="float32")
                
                # Calcular transformação de perspectiva
                M = cv2.getPerspectiveTransform(rect, dst)
                warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
                
                return warped
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Perspective correction failed: {e}")
            return None
    
    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """Ordena pontos em sentido horário: top-left, top-right, bottom-right, bottom-left"""
        rect = np.zeros((4, 2), dtype="float32")
        
        # Top-left terá menor soma, bottom-right terá maior soma
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        
        # Top-right terá menor diferença, bottom-left terá maior diferença
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        
        return rect
    
    def _process_easyocr_results(self, results: List, **kwargs) -> Dict[str, Any]:
        """Processa resultados do EasyOCR"""
        try:
            if not results:
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
            
            # Configurações
            min_confidence = kwargs.get('min_confidence', 0.2)
            group_by_lines = kwargs.get('group_by_lines', True)
            
            # Processar cada detecção
            for result in results:
                bbox_points = result[0]  # Pontos da bounding box
                text = result[1]         # Texto detectado
                confidence = float(result[2])  # Confiança
                
                # Filtrar por confiança mínima
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
            
            # Organizar texto
            if group_by_lines:
                organized_text = self._organize_text_by_position(blocks)
            else:
                organized_text = " ".join(text_lines)
            
            # Calcular estatísticas
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            result = {
                "text": organized_text,
                "confidence": avg_confidence,
                "blocks": blocks,
                "statistics": {
                    "total_blocks": len(blocks),
                    "avg_confidence": avg_confidence,
                    "min_confidence": min(confidences) if confidences else 0.0,
                    "max_confidence": max(confidences) if confidences else 0.0,
                    "char_count": len(organized_text),
                    "word_count": len(organized_text.split())
                }
            }
            
            # Detectar orientação do texto se solicitado
            if kwargs.get('detect_orientation', False):
                result["text_orientation"] = self._detect_text_orientation(blocks)
            
            # Detectar idiomas se solicitado
            if kwargs.get('detect_languages', False):
                result["detected_languages"] = self._detect_languages(organized_text)
            
            return result
            
        except Exception as e:
            self.logger.error(f"EasyOCR result processing failed: {e}")
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
    
    def _organize_text_by_position(self, blocks: List[Dict]) -> str:
        """Organiza texto baseado na posição dos blocos"""
        try:
            if not blocks:
                return ""
            
            # Ordenar blocos por posição (top-down, left-right)
            sorted_blocks = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
            
            # Agrupar em linhas baseado na proximidade vertical
            lines = []
            current_line = []
            line_threshold = 20  # pixels
            
            for block in sorted_blocks:
                bbox = block["bbox"]
                y_center = (bbox[1] + bbox[3]) / 2
                
                if not current_line:
                    current_line.append(block)
                else:
                    last_y = (current_line[-1]["bbox"][1] + current_line[-1]["bbox"][3]) / 2
                    
                    if abs(y_center - last_y) <= line_threshold:
                        current_line.append(block)
                    else:
                        # Nova linha
                        if current_line:
                            lines.append(current_line)
                        current_line = [block]
            
            if current_line:
                lines.append(current_line)
            
            # Construir texto final
            text_lines = []
            for line in lines:
                # Ordenar blocos da linha por posição horizontal
                line_sorted = sorted(line, key=lambda b: b["bbox"][0])
                line_text = " ".join([block["text"] for block in line_sorted])
                text_lines.append(line_text)
            
            return "\n".join(text_lines)
            
        except Exception as e:
            self.logger.warning(f"Text organization failed: {e}")
            return " ".join([block["text"] for block in blocks])
    
    def _detect_text_orientation(self, blocks: List[Dict]) -> str:
        """Detecta orientação predominante do texto"""
        try:
            if not blocks:
                return "horizontal"
            
            # Analisar orientação dos blocos
            horizontal_count = 0
            vertical_count = 0
            rotated_count = 0
            
            for block in blocks:
                bbox_points = block.get("bbox_points", [])
                if len(bbox_points) == 4:
                    # Calcular ângulo baseado nos pontos
                    p1, p2 = bbox_points[0], bbox_points[1]
                    angle = np.arctan2(p2[1] - p1[1], p2[0] - p1[0]) * 180 / np.pi
                    
                    if -15 <= angle <= 15 or 165 <= angle <= 195:
                        horizontal_count += 1
                    elif 75 <= angle <= 105 or -105 <= angle <= -75:
                        vertical_count += 1
                    else:
                        rotated_count += 1
            
            # Retornar orientação predominante
            max_count = max(horizontal_count, vertical_count, rotated_count)
            if max_count == horizontal_count:
                return "horizontal"
            elif max_count == vertical_count:
                return "vertical"
            else:
                return "rotated"
                
        except Exception as e:
            self.logger.warning(f"Orientation detection failed: {e}")
            return "horizontal"
    
    def _detect_languages(self, text: str) -> List[str]:
        """Detecta idiomas no texto (implementação simples)"""
        try:
            if not text.strip():
                return []
            
            # Implementação simples baseada em caracteres
            # Para implementação mais robusta, usar libraries como langdetect
            
            detected = []
            
            # Verificar português (acentos específicos)
            if any(c in text for c in "ãõçáéíóúâêîôû"):
                detected.append("pt")
            
            # Verificar inglês (palavras comuns)
            english_words = ["the", "and", "for", "are", "but", "not", "you", "all", "can", "had", "her", "was", "one", "our", "day"]
            if any(word in text.lower() for word in english_words):
                detected.append("en")
            
            # Verificar espanhol
            if any(c in text for c in "ñáéíóúü¿¡"):
                detected.append("es")
            
            return detected if detected else ["unknown"]
            
        except Exception as e:
            self.logger.warning(f"Language detection failed: {e}")
            return ["unknown"]
    
    def get_supported_languages(self) -> List[str]:
        """Retorna idiomas suportados pelo EasyOCR"""
        # EasyOCR suporta 80+ idiomas
        return [
            'af', 'az', 'be', 'bg', 'bn', 'bs', 'cs', 'cy', 'da', 'de', 'en', 'es', 'et', 'fr', 'ga',
            'hr', 'hu', 'id', 'is', 'it', 'ja', 'ko', 'ku', 'lt', 'lv', 'mi', 'ms', 'mt', 'ne', 'nl',
            'no', 'oc', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv', 'sw', 'th', 'tl', 'tr', 'uz',
            'vi', 'ar', 'fa', 'ug', 'ur', 'mn', 'la', 'zh', 'ab', 'ad', 'ae', 'ak', 'bh', 'bho', 'bo',
            'ch', 'cht', 'cu', 'hi', 'jv', 'ka', 'kk', 'km', 'kn', 'ky', 'lo', 'mr', 'my', 'or', 'pa',
            'pnb', 'ps', 'sd', 'si', 'ta', 'te', 'uk', 'xi'
        ]
    
    def batch_process_images(self, image_paths: List[str], **kwargs) -> List[Dict[str, Any]]:
        """Processa múltiplas imagens em lote"""
        try:
            # EasyOCR não tem suporte nativo para batch, mas podemos otimizar
            results = []
            
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
@celery_app.task(bind=True, base=EasyOCRWorker, queue='easyocr_queue')
def easyocr_process_image(self, request_data: dict):
    """Task para processar imagem com EasyOCR"""
    request = OCRRequest(**request_data)
    response = self.execute_ocr(request)
    return response.dict()


@celery_app.task(bind=True, base=EasyOCRWorker, queue='easyocr_queue')
def easyocr_batch_process(self, image_paths: List[str], parameters: dict = None):
    """Task para processamento em lote com EasyOCR"""
    worker = EasyOCRWorker()
    worker._ensure_model_loaded()
    
    results = worker.batch_process_images(image_paths, **(parameters or {}))
    return results


@celery_app.task(bind=True, base=EasyOCRWorker, queue='easyocr_queue')
def easyocr_health_check(self):
    """Task para verificar saúde do EasyOCR"""
    return self.health_check()


# Configurações específicas do worker
def configure_easyocr_worker():
    """Configura worker EasyOCR"""
    config = get_engine_config("easyocr")
    
    return {
        "queue": "easyocr_queue",
        "concurrency": config.get("max_workers", 6),
        "prefetch_multiplier": 2,
        "max_tasks_per_child": 150,
    }


if __name__ == "__main__":
    """Teste do worker EasyOCR"""
    import os
    
    print("=== EasyOCR Worker Test ===")
    
    if not EASYOCR_AVAILABLE:
        print("❌ EasyOCR dependencies not available")
        exit(1)
    
    worker = EasyOCRWorker()
    
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
    
    # Informações de idiomas
    languages = worker.get_supported_languages()
    print(f"Supported languages: {len(languages)} total")
    print(f"Sample languages: {languages[:15]}")
    
    # Teste com imagem de exemplo
    test_image_path = "test_document.jpg"
    if os.path.exists(test_image_path):
        print(f"\n--- Testing with {test_image_path} ---")
        
        request = OCRRequest(
            file_path=test_image_path,
            engine="easyocr",
            parameters={
                "detail_mode": True,
                "group_by_lines": True,
                "min_confidence": 0.3,
                "detect_orientation": True,
                "detect_languages": True,
                "enhance_contrast": True
            }
        )
        
        try:
            result = worker.execute_ocr(request)
            print(f"✅ OCR successful")
            print(f"Text length: {len(result.text)}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Blocks: {len(result.blocks)}")
            print(f"Processing time: {result.processing_time:.2f}s")
            
            if hasattr(result, 'text_orientation'):
                print(f"Text orientation: {result.text_orientation}")
            
            if hasattr(result, 'detected_languages'):
                print(f"Detected languages: {result.detected_languages}")
                
        except Exception as e:
            print(f"❌ OCR failed: {e}")
    else:
        print(f"⚠️  Test image {test_image_path} not found")
    
    print("\n✅ EasyOCR Worker test completed")