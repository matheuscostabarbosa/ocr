#!/usr/bin/env python3
"""
Surya OCR Worker - Análise de Layout Avançada
=============================================

Worker especializado para documentos complexos usando Surya OCR.
Excelente para:
- Análise de layout e estrutura
- Documentos acadêmicos e científicos
- Detecção de tabelas e elementos
- Ordem de leitura correta
"""

import time
from typing import Dict, Any, List, Tuple
from PIL import Image
import numpy as np

from app.workers.base_worker import BaseOCRWorker
from app.core.celery_app import celery_app
from app.core.config import settings, get_engine_config
from app.models.schemas import OCRRequest, OCRResponse

try:
    from surya.ocr import run_ocr
    from surya.model.detection.segformer import load_model as load_det_model, load_processor as load_det_processor
    from surya.model.recognition.model import load_model as load_rec_model
    from surya.model.recognition.processor import load_processor as load_rec_processor
    from surya.layout import batch_layout_detection
    from surya.model.layout.model import load_model as load_layout_model
    from surya.model.layout.processor import load_processor as load_layout_processor
    from surya.reading_order import batch_reading_order
    from surya.model.ordering.model import load_model as load_order_model
    from surya.model.ordering.processor import load_processor as load_order_processor
    SURYA_AVAILABLE = True
except ImportError:
    SURYA_AVAILABLE = False


class SuryaWorker(BaseOCRWorker):
    """Worker Surya OCR para análise avançada de layout"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "surya"
        self.config = get_engine_config(self.engine_name)
        
        # Modelos Surya
        self.det_model = None
        self.det_processor = None
        self.rec_model = None
        self.rec_processor = None
        self.layout_model = None
        self.layout_processor = None
        self.order_model = None
        self.order_processor = None
        
        if not SURYA_AVAILABLE:
            raise ImportError("Surya OCR dependencies not available. Install with: pip install surya-ocr")
    
    def load_model(self):
        """Carrega todos os modelos Surya"""
        try:
            self.logger.info("Loading Surya OCR models...")
            
            # Carregar modelos de detecção e reconhecimento
            self.det_processor = load_det_processor()
            self.det_model = load_det_model()
            self.rec_model = load_rec_model()
            self.rec_processor = load_rec_processor()
            
            self.logger.info("Surya OCR models loaded successfully")
            
            # Carregar modelo de layout (opcional)
            try:
                self.layout_model = load_layout_model()
                self.layout_processor = load_layout_processor()
                self.logger.info("Surya Layout model loaded successfully")
            except Exception as e:
                self.logger.warning(f"Layout model loading failed: {e}")
            
            # Carregar modelo de ordem de leitura (opcional)
            try:
                self.order_model = load_order_model()
                self.order_processor = load_order_processor()
                self.logger.info("Surya Reading Order model loaded successfully")
            except Exception as e:
                self.logger.warning(f"Reading order model loading failed: {e}")
                
        except Exception as e:
            self.logger.error(f"Failed to load Surya models: {e}")
            raise
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processa imagem com Surya OCR"""
        try:
            start_time = time.time()
            
            # Carregar imagem
            image = Image.open(image_path).convert('RGB')
            
            # Determinar idiomas
            languages = kwargs.get('languages', ['pt', 'en'])
            if isinstance(languages, str):
                languages = [languages]
            
            # Executar OCR
            ocr_result = self._run_ocr(image, languages)
            
            # Executar análise de layout se solicitada
            layout_result = None
            if kwargs.get('analyze_layout', True) and self.layout_model:
                layout_result = self._analyze_layout(image)
            
            # Executar análise de ordem de leitura se solicitada
            reading_order = None
            if kwargs.get('reading_order', True) and self.order_model and layout_result:
                reading_order = self._analyze_reading_order(image, layout_result)
            
            # Processar resultados
            result = self._process_results(
                ocr_result, 
                layout_result, 
                reading_order, 
                image.size,
                **kwargs
            )
            
            result['processing_time'] = time.time() - start_time
            return result
            
        except Exception as e:
            self.logger.error(f"Surya processing failed: {e}")
            raise
    
    def _run_ocr(self, image: Image.Image, languages: List[str]) -> Any:
        """Executa OCR com Surya"""
        try:
            # Executar OCR
            predictions = run_ocr(
                [image],
                [languages],
                self.det_model,
                self.det_processor,
                self.rec_model,
                self.rec_processor
            )
            
            return predictions[0] if predictions else None
            
        except Exception as e:
            self.logger.error(f"Surya OCR execution failed: {e}")
            raise
    
    def _analyze_layout(self, image: Image.Image) -> Any:
        """Analisa layout da página"""
        try:
            layout_predictions = batch_layout_detection(
                [image],
                self.layout_model,
                self.layout_processor
            )
            
            return layout_predictions[0] if layout_predictions else None
            
        except Exception as e:
            self.logger.warning(f"Layout analysis failed: {e}")
            return None
    
    def _analyze_reading_order(self, image: Image.Image, layout_result: Any) -> Any:
        """Analisa ordem de leitura"""
        try:
            if not layout_result:
                return None
                
            order_predictions = batch_reading_order(
                [image],
                [layout_result],
                self.order_model,
                self.order_processor
            )
            
            return order_predictions[0] if order_predictions else None
            
        except Exception as e:
            self.logger.warning(f"Reading order analysis failed: {e}")
            return None
    
    def _process_results(self, ocr_result: Any, layout_result: Any, 
                        reading_order: Any, image_size: Tuple[int, int], **kwargs) -> Dict[str, Any]:
        """Processa e combina todos os resultados"""
        try:
            result = {
                "text": "",
                "confidence": 0.0,
                "blocks": [],
                "layout": [],
                "reading_order": [],
                "statistics": {}
            }
            
            # Processar resultados OCR
            if ocr_result and hasattr(ocr_result, 'text_lines'):
                text_lines = []
                blocks = []
                confidences = []
                
                for line in ocr_result.text_lines:
                    if line.text.strip():
                        text_lines.append(line.text)
                        confidences.append(line.confidence)
                        
                        blocks.append({
                            "text": line.text,
                            "confidence": line.confidence,
                            "bbox": [line.bbox.x0, line.bbox.y0, line.bbox.x1, line.bbox.y1],
                            "type": "text_line"
                        })
                
                result["text"] = "\n".join(text_lines)
                result["blocks"] = blocks
                result["confidence"] = sum(confidences) / len(confidences) if confidences else 0.0
            
            # Processar resultados de layout
            if layout_result and hasattr(layout_result, 'bboxes'):
                layout_elements = []
                
                for bbox in layout_result.bboxes:
                    layout_elements.append({
                        "type": bbox.label,
                        "bbox": [bbox.bbox.x0, bbox.bbox.y0, bbox.bbox.x1, bbox.bbox.y1],
                        "confidence": bbox.confidence
                    })
                
                result["layout"] = layout_elements
                
                # Organizar texto por elementos de layout se solicitado
                if kwargs.get('organize_by_layout', True):
                    result = self._organize_text_by_layout(result, layout_elements, image_size)
            
            # Processar ordem de leitura
            if reading_order and hasattr(reading_order, 'bboxes'):
                order_elements = []
                
                for i, bbox in enumerate(reading_order.bboxes):
                    order_elements.append({
                        "order": i,
                        "bbox": [bbox.bbox.x0, bbox.bbox.y0, bbox.bbox.x1, bbox.bbox.y1],
                        "confidence": bbox.confidence
                    })
                
                result["reading_order"] = order_elements
                
                # Reorganizar texto pela ordem de leitura
                if kwargs.get('apply_reading_order', True):
                    result = self._apply_reading_order(result, order_elements)
            
            # Gerar markdown se solicitado
            if kwargs.get('output_format') == 'markdown':
                result["markdown"] = self._generate_markdown(result)
            
            # Calcular estatísticas
            result["statistics"] = self._calculate_statistics(result)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Result processing failed: {e}")
            raise
    
    def _organize_text_by_layout(self, result: Dict[str, Any], 
                               layout_elements: List[Dict], 
                               image_size: Tuple[int, int]) -> Dict[str, Any]:
        """Organiza texto por elementos de layout"""
        try:
            organized_blocks = []
            
            # Agrupar blocos de texto por elemento de layout
            for layout_elem in layout_elements:
                layout_bbox = layout_elem["bbox"]
                layout_type = layout_elem["type"]
                
                # Encontrar blocos de texto que intersectam com este elemento
                matching_blocks = []
                for block in result["blocks"]:
                    if self._bboxes_overlap(block["bbox"], layout_bbox):
                        matching_blocks.append(block)
                
                if matching_blocks:
                    # Ordenar blocos por posição vertical
                    matching_blocks.sort(key=lambda b: b["bbox"][1])
                    
                    # Combinar texto dos blocos
                    combined_text = "\n".join([b["text"] for b in matching_blocks])
                    avg_confidence = sum([b["confidence"] for b in matching_blocks]) / len(matching_blocks)
                    
                    organized_blocks.append({
                        "text": combined_text,
                        "confidence": avg_confidence,
                        "bbox": layout_bbox,
                        "type": layout_type,
                        "sub_blocks": matching_blocks
                    })
            
            # Atualizar resultado
            if organized_blocks:
                result["organized_blocks"] = organized_blocks
                
                # Reorganizar texto principal por tipo de elemento
                text_parts = []
                for block in organized_blocks:
                    if block["type"] in ["Title", "Header"]:
                        text_parts.append(f"# {block['text']}")
                    elif block["type"] == "Text":
                        text_parts.append(block["text"])
                    elif block["type"] == "Table":
                        text_parts.append(f"[TABLE]\n{block['text']}")
                    elif block["type"] == "Figure":
                        text_parts.append(f"[FIGURE] {block['text']}")
                    else:
                        text_parts.append(block["text"])
                
                result["organized_text"] = "\n\n".join(text_parts)
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Layout organization failed: {e}")
            return result
    
    def _apply_reading_order(self, result: Dict[str, Any], 
                           order_elements: List[Dict]) -> Dict[str, Any]:
        """Aplica ordem de leitura aos blocos de texto"""
        try:
            if not order_elements or "organized_blocks" not in result:
                return result
            
            # Mapear blocos organizados para elementos de ordem
            ordered_blocks = []
            
            for order_elem in sorted(order_elements, key=lambda x: x["order"]):
                order_bbox = order_elem["bbox"]
                
                # Encontrar bloco organizado correspondente
                for block in result["organized_blocks"]:
                    if self._bboxes_overlap(block["bbox"], order_bbox, threshold=0.5):
                        ordered_blocks.append(block)
                        break
            
            if ordered_blocks:
                result["ordered_blocks"] = ordered_blocks
                
                # Reconstruir texto na ordem correta
                ordered_text = "\n\n".join([block["text"] for block in ordered_blocks])
                result["ordered_text"] = ordered_text
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Reading order application failed: {e}")
            return result
    
    def _generate_markdown(self, result: Dict[str, Any]) -> str:
        """Gera markdown estruturado baseado no layout"""
        try:
            markdown_parts = []
            
            # Usar blocos ordenados se disponível, senão usar organizados
            blocks = result.get("ordered_blocks", result.get("organized_blocks", result.get("blocks", [])))
            
            current_level = 1
            
            for block in blocks:
                text = block.get("text", "").strip()
                if not text:
                    continue
                
                block_type = block.get("type", "text").lower()
                
                if block_type in ["title", "header"]:
                    # Determinar nível do cabeçalho
                    bbox = block.get("bbox", [0, 0, 0, 0])
                    height = bbox[3] - bbox[1] if len(bbox) >= 4 else 0
                    
                    if height > 50:  # Título principal
                        markdown_parts.append(f"# {text}")
                        current_level = 2
                    else:  # Subtítulo
                        markdown_parts.append(f"{'#' * min(current_level, 6)} {text}")
                
                elif block_type == "table":
                    # Tentar formatar como tabela markdown
                    table_md = self._format_table_markdown(text)
                    markdown_parts.append(table_md)
                
                elif block_type == "figure":
                    markdown_parts.append(f"![Figure]({text})")
                
                elif block_type == "list":
                    # Formatar como lista
                    lines = text.split('\n')
                    list_items = [f"- {line.strip()}" for line in lines if line.strip()]
                    markdown_parts.extend(list_items)
                
                else:
                    # Texto normal
                    # Quebrar em parágrafos se muito longo
                    if len(text) > 200:
                        paragraphs = text.split('\n\n')
                        markdown_parts.extend(paragraphs)
                    else:
                        markdown_parts.append(text)
            
            return "\n\n".join(markdown_parts)
            
        except Exception as e:
            self.logger.warning(f"Markdown generation failed: {e}")
            return result.get("text", "")
    
    def _format_table_markdown(self, table_text: str) -> str:
        """Formata texto de tabela como markdown"""
        try:
            lines = [line.strip() for line in table_text.split('\n') if line.strip()]
            
            if len(lines) < 2:
                return table_text
            
            # Tentar detectar colunas
            rows = []
            for line in lines:
                # Dividir por múltiplos espaços ou tabs
                import re
                cols = re.split(r'\s{2,}|\t', line)
                rows.append([col.strip() for col in cols])
            
            if not rows:
                return table_text
            
            # Determinar número de colunas
            max_cols = max(len(row) for row in rows)
            
            # Construir tabela markdown
            markdown_rows = []
            
            # Cabeçalho
            if rows:
                header = rows[0]
                while len(header) < max_cols:
                    header.append("")
                markdown_rows.append("| " + " | ".join(header) + " |")
                
                # Separador
                markdown_rows.append("| " + " | ".join(["---"] * max_cols) + " |")
                
                # Dados
                for row in rows[1:]:
                    while len(row) < max_cols:
                        row.append("")
                    markdown_rows.append("| " + " | ".join(row) + " |")
            
            return "\n".join(markdown_rows)
            
        except Exception as e:
            self.logger.warning(f"Table formatting failed: {e}")
            return table_text
    
    def _calculate_statistics(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula estatísticas dos resultados"""
        try:
            stats = {}
            
            # Estatísticas básicas
            text = result.get("text", "")
            stats["char_count"] = len(text)
            stats["word_count"] = len(text.split())
            stats["line_count"] = len([line for line in text.split('\n') if line.strip()])
            
            # Estatísticas de blocos
            blocks = result.get("blocks", [])
            if blocks:
                confidences = [block.get("confidence", 0) for block in blocks]
                stats["total_blocks"] = len(blocks)
                stats["avg_confidence"] = sum(confidences) / len(confidences)
                stats["min_confidence"] = min(confidences)
                stats["max_confidence"] = max(confidences)
            
            # Estatísticas de layout
            layout = result.get("layout", [])
            if layout:
                layout_types = {}
                for elem in layout:
                    elem_type = elem.get("type", "unknown")
                    layout_types[elem_type] = layout_types.get(elem_type, 0) + 1
                stats["layout_elements"] = layout_types
            
            return stats
            
        except Exception as e:
            self.logger.warning(f"Statistics calculation failed: {e}")
            return {}
    
    def _bboxes_overlap(self, bbox1: List[float], bbox2: List[float], threshold: float = 0.3) -> bool:
        """Verifica se duas bounding boxes se sobrepõem"""
        try:
            # Calcular área de interseção
            x_left = max(bbox1[0], bbox2[0])
            y_top = max(bbox1[1], bbox2[1])
            x_right = min(bbox1[2], bbox2[2])
            y_bottom = min(bbox1[3], bbox2[3])
            
            if x_right < x_left or y_bottom < y_top:
                return False
            
            intersection_area = (x_right - x_left) * (y_bottom - y_top)
            
            # Calcular área das bboxes
            area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
            area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
            
            # Calcular IoU (Intersection over Union)
            iou = intersection_area / (area1 + area2 - intersection_area)
            
            return iou > threshold
            
        except Exception:
            return False
    
    def get_supported_languages(self) -> List[str]:
        """Retorna idiomas suportados pelo Surya"""
        # Surya suporta 90+ idiomas
        return [
            "pt", "en", "es", "fr", "de", "it", "ru", "ja", "ko", "zh", 
            "ar", "hi", "th", "vi", "tr", "pl", "nl", "sv", "da", "no"
        ]


# Registrar tasks Celery
@celery_app.task(bind=True, base=SuryaWorker, queue='surya_queue')
def surya_process_image(self, request_data: dict):
    """Task para processar imagem com Surya OCR"""
    request = OCRRequest(**request_data)
    response = self.execute_ocr(request)
    return response.dict()


@celery_app.task(bind=True, base=SuryaWorker, queue='surya_queue')
def surya_health_check(self):
    """Task para verificar saúde do Surya"""
    return self.health_check()


@celery_app.task(bind=True, base=SuryaWorker, queue='surya_queue')
def surya_analyze_layout_only(self, image_path: str, languages: List[str] = None):
    """Task para análise apenas de layout"""
    try:
        worker = SuryaWorker()
        worker._ensure_model_loaded()
        
        image = Image.open(image_path).convert('RGB')
        
        # Análise de layout
        layout_result = worker._analyze_layout(image) if worker.layout_model else None
        
        # Análise de ordem de leitura
        reading_order = None
        if worker.order_model and layout_result:
            reading_order = worker._analyze_reading_order(image, layout_result)
        
        result = {
            "layout": [],
            "reading_order": [],
            "image_size": image.size
        }
        
        # Processar layout
        if layout_result and hasattr(layout_result, 'bboxes'):
            for bbox in layout_result.bboxes:
                result["layout"].append({
                    "type": bbox.label,
                    "bbox": [bbox.bbox.x0, bbox.bbox.y0, bbox.bbox.x1, bbox.bbox.y1],
                    "confidence": bbox.confidence
                })
        
        # Processar ordem de leitura
        if reading_order and hasattr(reading_order, 'bboxes'):
            for i, bbox in enumerate(reading_order.bboxes):
                result["reading_order"].append({
                    "order": i,
                    "bbox": [bbox.bbox.x0, bbox.bbox.y0, bbox.bbox.x1, bbox.bbox.y1],
                    "confidence": bbox.confidence
                })
        
        return result
        
    except Exception as e:
        logger.error(f"Layout analysis failed: {e}")
        raise


# Configurações específicas do worker
def configure_surya_worker():
    """Configura worker Surya"""
    config = get_engine_config("surya")
    
    return {
        "queue": "surya_queue",
        "concurrency": config.get("max_workers", 3),
        "prefetch_multiplier": 1,
        "max_tasks_per_child": 100,
    }


if __name__ == "__main__":
    """Teste do worker Surya"""
    import os
    
    print("=== Surya Worker Test ===")
    
    if not SURYA_AVAILABLE:
        print("❌ Surya dependencies not available")
        exit(1)
    
    worker = SuryaWorker()
    
    # Teste de carregamento do modelo
    try:
        worker.load_model()
        print("✅ Models loaded successfully")
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
            engine="surya",
            parameters={
                "languages": ["pt", "en"],
                "analyze_layout": True,
                "reading_order": True,
                "output_format": "markdown"
            }
        )
        
        try:
            result = worker.execute_ocr(request)
            print(f"✅ OCR successful")
            print(f"Text length: {len(result.text)}")
            print(f"Confidence: {result.confidence:.2f}")
            print(f"Blocks: {len(result.blocks)}")
            
            if hasattr(result, 'layout'):
                print(f"Layout elements: {len(result.layout)}")
            
            if hasattr(result, 'markdown'):
                print(f"Markdown generated: {len(result.markdown)} chars")
                
        except Exception as e:
            print(f"❌ OCR failed: {e}")
    else:
        print(f"⚠️  Test image {test_image_path} not found")
    
    print("\n✅ Surya Worker test completed")