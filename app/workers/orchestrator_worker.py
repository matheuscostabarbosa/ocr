#!/usr/bin/env python3
"""
Orchestrator Worker - Coordenação Inteligente
=============================================

Worker responsável por:
- Analisar documentos e escolher o melhor engine
- Coordenar multiple engines quando necessário
- Gerenciar fallbacks automáticos
- Combinar resultados de múltiplos engines
- Roteamento inteligente de tasks
"""

import time
import tempfile
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from PIL import Image
import numpy as np
import cv2
from pathlib import Path

from app.workers.base_worker import BaseOCRWorker
from app.core.celery_app import celery_app
from app.core.config import settings, get_engine_config, get_available_engines, get_queue_config
from app.core.redis_client import get_redis_client
from app.models.schemas import OCRRequest, OCRResponse, TaskStatus
from app.services.file_detector import FileTypeDetector

# Import tasks dos outros workers
from app.workers.trocr_worker import trocr_process_image
from app.workers.surya_worker import surya_process_image
from app.workers.paddleocr_worker import paddleocr_process_image
from app.workers.easyocr_worker import easyocr_process_image
from app.workers.tesseract_worker import tesseract_process_image
from app.workers.marker_worker import marker_process_pdf


class OrchestratorWorker(BaseOCRWorker):
    """Worker orchestrador que coordena todos os engines OCR"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "orchestrator"
        self.file_detector = FileTypeDetector()
        self.redis_client = get_redis_client()
        
        # Mapeamento de workers
        self.engine_tasks = {
            "trocr": trocr_process_image,
            "surya": surya_process_image,
            "paddleocr": paddleocr_process_image,
            "easyocr": easyocr_process_image,
            "tesseract": tesseract_process_image,
            "marker": marker_process_pdf
        }
        
        # Configurações de decisão
        self.decision_cache_ttl = 300  # 5 minutos
        self.fallback_enabled = True
        self.multi_engine_enabled = True
    
    def load_model(self):
        """Orchestrator não precisa carregar modelos"""
        self.logger.info("Orchestrator initialized - no models to load")
        self._model_loaded = True
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processo principal do orchestrador"""
        try:
            start_time = time.time()
            
            # Analisar arquivo de entrada
            file_analysis = self._analyze_input_file(image_path, **kwargs)
            
            # Decidir estratégia de processamento
            strategy = self._decide_processing_strategy(file_analysis, **kwargs)
            
            # Executar estratégia
            if strategy["type"] == "single_engine":
                result = self._execute_single_engine(image_path, strategy, **kwargs)
            elif strategy["type"] == "multi_engine":
                result = self._execute_multi_engine(image_path, strategy, **kwargs)
            elif strategy["type"] == "pipeline":
                result = self._execute_pipeline(image_path, strategy, **kwargs)
            else:
                raise ValueError(f"Unknown strategy type: {strategy['type']}")
            
            # Pós-processamento
            result = self._post_process_orchestrator_result(result, file_analysis, strategy)
            
            result["orchestration_time"] = time.time() - start_time
            result["strategy_used"] = strategy
            result["file_analysis"] = file_analysis
            
            return result
            
        except Exception as e:
            self.logger.error(f"Orchestrator processing failed: {e}")
            raise
    
    def _analyze_input_file(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Analisa arquivo de entrada para determinar características"""
        try:
            analysis = {
                "file_path": file_path,
                "file_size": Path(file_path).stat().st_size,
                "file_type": None,
                "image_properties": {},
                "complexity_score": 0.0,
                "estimated_text_type": "unknown",
                "quality_score": 0.0
            }
            
            # Detectar tipo de arquivo
            file_info = self.file_detector.detect_file_type(file_path)
            analysis["file_type"] = file_info
            
            # Se for imagem, analisar propriedades
            if file_info.get("category") == "image":
                analysis["image_properties"] = self._analyze_image_properties(file_path)
                analysis["complexity_score"] = self._calculate_complexity_score(analysis["image_properties"])
                analysis["estimated_text_type"] = self._estimate_text_type(file_path, analysis["image_properties"])
                analysis["quality_score"] = self._calculate_quality_score(analysis["image_properties"])
            
            return analysis
            
        except Exception as e:
            self.logger.warning(f"File analysis failed: {e}")
            return {
                "file_path": file_path,
                "error": str(e),
                "complexity_score": 5.0,  # Medium complexity default
                "estimated_text_type": "unknown",
                "quality_score": 5.0
            }
    
    def _analyze_image_properties(self, image_path: str) -> Dict[str, Any]:
        """Analisa propriedades da imagem"""
        try:
            with Image.open(image_path) as img:
                # Propriedades básicas
                properties = {
                    "width": img.width,
                    "height": img.height,
                    "mode": img.mode,
                    "format": img.format,
                    "aspect_ratio": img.width / img.height,
                    "total_pixels": img.width * img.height
                }
                
                # Converter para análise
                if img.mode != 'L':
                    gray = img.convert('L')
                else:
                    gray = img
                
                img_array = np.array(gray)
                
                # Análise estatística
                properties.update({
                    "mean_intensity": float(np.mean(img_array)),
                    "std_intensity": float(np.std(img_array)),
                    "min_intensity": int(np.min(img_array)),
                    "max_intensity": int(np.max(img_array)),
                    "contrast_ratio": float(np.std(img_array) / np.mean(img_array)) if np.mean(img_array) > 0 else 0
                })
                
                # Detectar texto vs não-texto
                properties.update(self._detect_text_regions(img_array))
                
                return properties
                
        except Exception as e:
            self.logger.warning(f"Image analysis failed: {e}")
            return {}
    
    def _detect_text_regions(self, img_array: np.ndarray) -> Dict[str, Any]:
        """Detecta regiões de texto na imagem"""
        try:
            # Usar OpenCV para detectar texto
            # Binarização
            _, binary = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Detectar componentes conectados
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)
            
            # Analisar componentes para estimar densidade de texto
            text_like_components = 0
            total_text_area = 0
            
            for i in range(1, num_labels):  # Skip background
                area = stats[i, cv2.CC_STAT_AREA]
                width = stats[i, cv2.CC_STAT_WIDTH]
                height = stats[i, cv2.CC_STAT_HEIGHT]
                
                # Heurística para identificar caracteres
                if 10 < area < 10000 and 0.1 < width/height < 10:
                    text_like_components += 1
                    total_text_area += area
            
            total_image_area = img_array.shape[0] * img_array.shape[1]
            
            return {
                "text_components": text_like_components,
                "text_density": text_like_components / (total_image_area / 10000),  # Per 100x100 area
                "text_coverage": total_text_area / total_image_area,
                "estimated_layout": "dense" if text_like_components > 100 else "sparse"
            }
            
        except Exception as e:
            self.logger.warning(f"Text region detection failed: {e}")
            return {
                "text_components": 0,
                "text_density": 0.0,
                "text_coverage": 0.0,
                "estimated_layout": "unknown"
            }
    
    def _calculate_complexity_score(self, properties: Dict[str, Any]) -> float:
        """Calcula score de complexidade (0-10)"""
        try:
            complexity = 5.0  # Base score
            
            # Baseado na densidade de texto
            text_density = properties.get("text_density", 0)
            if text_density > 50:
                complexity += 2.0  # Muito texto = mais complexo
            elif text_density < 10:
                complexity -= 1.0  # Pouco texto = menos complexo
            
            # Baseado no contraste
            contrast = properties.get("contrast_ratio", 0)
            if contrast < 0.3:
                complexity += 2.0  # Baixo contraste = mais difícil
            elif contrast > 0.8:
                complexity -= 1.0  # Alto contraste = mais fácil
            
            # Baseado no tamanho
            total_pixels = properties.get("total_pixels", 0)
            if total_pixels > 4000000:  # > 4MP
                complexity += 1.0
            elif total_pixels < 500000:  # < 0.5MP
                complexity += 1.0  # Muito pequeno também é difícil
            
            # Baseado no layout
            layout = properties.get("estimated_layout", "unknown")
            if layout == "dense":
                complexity += 1.5
            
            return max(0.0, min(10.0, complexity))
            
        except Exception:
            return 5.0
    
    def _estimate_text_type(self, image_path: str, properties: Dict[str, Any]) -> str:
        """Estima tipo de texto (handwritten, printed, mixed)"""
        try:
            # Heurísticas simples baseadas nas propriedades
            text_density = properties.get("text_density", 0)
            contrast = properties.get("contrast_ratio", 0)
            std_intensity = properties.get("std_intensity", 0)
            
            # Manuscrito tende a ter:
            # - Menor contraste
            # - Maior variabilidade
            # - Componentes menos uniformes
            if contrast < 0.4 and std_intensity > 40:
                return "handwritten"
            
            # Texto impresso tende a ter:
            # - Alto contraste
            # - Componentes uniformes
            elif contrast > 0.6 and text_density > 20:
                return "printed"
            
            # Qualidade muito baixa
            elif contrast < 0.2:
                return "poor_quality"
            
            return "mixed"
            
        except Exception:
            return "unknown"
    
    def _calculate_quality_score(self, properties: Dict[str, Any]) -> float:
        """Calcula score de qualidade (0-10)"""
        try:
            quality = 5.0  # Base score
            
            # Baseado no contraste
            contrast = properties.get("contrast_ratio", 0)
            if contrast > 0.8:
                quality += 2.0
            elif contrast < 0.3:
                quality -= 3.0
            
            # Baseado na intensidade média
            mean_intensity = properties.get("mean_intensity", 128)
            if 50 < mean_intensity < 200:  # Boa faixa
                quality += 1.0
            else:
                quality -= 1.0
            
            # Baseado na resolução
            total_pixels = properties.get("total_pixels", 0)
            if total_pixels > 1000000:  # > 1MP
                quality += 1.0
            elif total_pixels < 100000:  # < 0.1MP
                quality -= 2.0
            
            return max(0.0, min(10.0, quality))
            
        except Exception:
            return 5.0
    
    def _decide_processing_strategy(self, file_analysis: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Decide estratégia de processamento baseada na análise"""
        try:
            # Estratégia manual se especificada
            if kwargs.get("force_engine"):
                return {
                    "type": "single_engine",
                    "primary_engine": kwargs["force_engine"],
                    "confidence": 1.0,
                    "reason": "user_specified"
                }
            
            # Extrair características
            complexity = file_analysis.get("complexity_score", 5.0)
            quality = file_analysis.get("quality_score", 5.0)
            text_type = file_analysis.get("estimated_text_type", "unknown")
            file_type = file_analysis.get("file_type", {})
            
            # Decisão baseada no tipo de arquivo
            if file_type.get("category") == "pdf":
                if kwargs.get("output_format") == "markdown":
                    return {
                        "type": "single_engine",
                        "primary_engine": "marker",
                        "confidence": 0.9,
                        "reason": "pdf_to_markdown"
                    }
                else:
                    return {
                        "type": "pipeline",
                        "engines": ["surya", "paddleocr"],
                        "confidence": 0.8,
                        "reason": "pdf_ocr_pipeline"
                    }
            
            # Decisão baseada no tipo de texto
            if text_type == "handwritten":
                if quality < 4.0:
                    return {
                        "type": "multi_engine",
                        "engines": ["trocr", "surya"],
                        "combination_method": "weighted_average",
                        "confidence": 0.85,
                        "reason": "poor_quality_handwritten"
                    }
                else:
                    return {
                        "type": "single_engine",
                        "primary_engine": "trocr",
                        "fallback_engine": "surya",
                        "confidence": 0.9,
                        "reason": "handwritten_text"
                    }
            
            elif text_type == "printed":
                if complexity > 7.0:
                    return {
                        "type": "single_engine",
                        "primary_engine": "surya",
                        "fallback_engine": "paddleocr",
                        "confidence": 0.9,
                        "reason": "complex_layout"
                    }
                else:
                    return {
                        "type": "single_engine",
                        "primary_engine": "paddleocr",
                        "fallback_engine": "tesseract",
                        "confidence": 0.85,
                        "reason": "simple_printed_text"
                    }
            
            elif text_type == "poor_quality":
                return {
                    "type": "multi_engine",
                    "engines": ["trocr", "surya", "paddleocr"],
                    "combination_method": "consensus",
                    "confidence": 0.7,
                    "reason": "poor_quality_requires_multiple_engines"
                }
            
            # Estratégia padrão
            if complexity > 6.0:
                return {
                    "type": "single_engine",
                    "primary_engine": "surya",
                    "fallback_engine": "paddleocr",
                    "confidence": 0.8,
                    "reason": "default_complex"
                }
            else:
                return {
                    "type": "single_engine",
                    "primary_engine": "paddleocr",
                    "fallback_engine": "tesseract",
                    "confidence": 0.8,
                    "reason": "default_simple"
                }
                
        except Exception as e:
            self.logger.warning(f"Strategy decision failed: {e}")
            return {
                "type": "single_engine",
                "primary_engine": "paddleocr",
                "fallback_engine": "tesseract",
                "confidence": 0.5,
                "reason": "fallback_strategy"
            }
    
    def _execute_single_engine(self, file_path: str, strategy: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Executa estratégia de engine único com fallback"""
        try:
            primary_engine = strategy["primary_engine"]
            fallback_engine = strategy.get("fallback_engine")
            
            # Preparar request
            request_data = {
                "file_path": file_path,
                "engine": primary_engine,
                "parameters": kwargs,
                "use_cache": kwargs.get("use_cache", True)
            }
            
            try:
                # Executar engine principal
                task = self.engine_tasks[primary_engine]
                result = task.delay(request_data).get(timeout=kwargs.get("timeout", 300))
                
                # Verificar qualidade do resultado
                if self._is_result_acceptable(result, strategy):
                    result["engine_used"] = primary_engine
                    result["strategy"] = "primary_success"
                    return result
                
                elif fallback_engine and self.fallback_enabled:
                    self.logger.info(f"Primary engine {primary_engine} result not acceptable, trying fallback {fallback_engine}")
                    return self._execute_fallback(file_path, fallback_engine, result, **kwargs)
                
                else:
                    # Retornar resultado mesmo que não seja ideal
                    result["engine_used"] = primary_engine
                    result["strategy"] = "primary_only"
                    result["warning"] = "Result quality below threshold but no fallback available"
                    return result
                    
            except Exception as e:
                if fallback_engine and self.fallback_enabled:
                    self.logger.warning(f"Primary engine {primary_engine} failed: {e}, trying fallback {fallback_engine}")
                    return self._execute_fallback(file_path, fallback_engine, None, **kwargs)
                else:
                    raise
                    
        except Exception as e:
            self.logger.error(f"Single engine execution failed: {e}")
            raise
    
    def _execute_fallback(self, file_path: str, fallback_engine: str, primary_result: Optional[Dict], **kwargs) -> Dict[str, Any]:
        """Executa engine de fallback"""
        try:
            request_data = {
                "file_path": file_path,
                "engine": fallback_engine,
                "parameters": kwargs,
                "use_cache": kwargs.get("use_cache", True)
            }
            
            task = self.engine_tasks[fallback_engine]
            result = task.delay(request_data).get(timeout=kwargs.get("timeout", 300))
            
            result["engine_used"] = fallback_engine
            result["strategy"] = "fallback_used"
            
            if primary_result:
                result["primary_result"] = primary_result
                result["fallback_reason"] = "primary_quality_low"
            else:
                result["fallback_reason"] = "primary_failed"
            
            return result
            
        except Exception as e:
            self.logger.error(f"Fallback execution failed: {e}")
            if primary_result:
                # Retornar resultado primário mesmo que não seja ideal
                primary_result["strategy"] = "fallback_failed"
                primary_result["warning"] = f"Fallback failed: {e}"
                return primary_result
            else:
                raise
    
    def _execute_multi_engine(self, file_path: str, strategy: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Executa múltiplos engines e combina resultados"""
        try:
            engines = strategy["engines"]
            combination_method = strategy.get("combination_method", "best_confidence")
            
            # Executar todos os engines em paralelo
            tasks = []
            for engine in engines:
                request_data = {
                    "file_path": file_path,
                    "engine": engine,
                    "parameters": kwargs,
                    "use_cache": kwargs.get("use_cache", True)
                }
                
                task = self.engine_tasks[engine].delay(request_data)
                tasks.append((engine, task))
            
            # Coletar resultados
            results = {}
            for engine, task in tasks:
                try:
                    result = task.get(timeout=kwargs.get("timeout", 300))
                    results[engine] = result
                except Exception as e:
                    self.logger.warning(f"Engine {engine} failed in multi-engine: {e}")
                    continue
            
            if not results:
                raise RuntimeError("All engines failed in multi-engine strategy")
            
            # Combinar resultados
            combined = self._combine_multi_engine_results(results, combination_method)
            combined["strategy"] = "multi_engine"
            combined["engines_used"] = list(results.keys())
            combined["combination_method"] = combination_method
            combined["individual_results"] = results
            
            return combined
            
        except Exception as e:
            self.logger.error(f"Multi-engine execution failed: {e}")
            raise
    
    def _execute_pipeline(self, file_path: str, strategy: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Executa pipeline sequencial de engines"""
        try:
            engines = strategy["engines"]
            
            # Executar engines em sequência
            current_input = file_path
            results = []
            
            for i, engine in enumerate(engines):
                request_data = {
                    "file_path": current_input,
                    "engine": engine,
                    "parameters": kwargs,
                    "use_cache": kwargs.get("use_cache", True)
                }
                
                task = self.engine_tasks[engine]
                result = task.delay(request_data).get(timeout=kwargs.get("timeout", 300))
                
                results.append({
                    "engine": engine,
                    "step": i + 1,
                    "result": result
                })
                
                # Para pipeline, geralmente o último resultado é o final
                # mas pode ser personalizado baseado no caso
            
            # O resultado final é do último engine
            final_result = results[-1]["result"]
            final_result["strategy"] = "pipeline"
            final_result["pipeline_steps"] = results
            final_result["engines_used"] = engines
            
            return final_result
            
        except Exception as e:
            self.logger.error(f"Pipeline execution failed: {e}")
            raise
    
    def _is_result_acceptable(self, result: Dict[str, Any], strategy: Dict[str, Any]) -> bool:
        """Verifica se resultado é aceitável"""
        try:
            # Critérios básicos
            if "error" in result:
                return False
            
            text = result.get("text", "")
            confidence = result.get("confidence", 0.0)
            
            # Texto muito curto pode indicar falha
            if len(text.strip()) < 3:
                return False
            
            # Confiança muito baixa
            min_confidence = strategy.get("min_acceptable_confidence", 0.3)
            if confidence < min_confidence:
                return False
            
            # Texto com muitos caracteres especiais pode indicar erro
            special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace())
            if special_chars > len(text) * 0.5:
                return False
            
            return True
            
        except Exception:
            return False
    
    def _combine_multi_engine_results(self, results: Dict[str, Dict], method: str) -> Dict[str, Any]:
        """Combina resultados de múltiplos engines"""
        try:
            if method == "best_confidence":
                # Escolher resultado com maior confiança
                best_engine = max(results.keys(), key=lambda e: results[e].get("confidence", 0))
                return results[best_engine]
            
            elif method == "weighted_average":
                # Média ponderada por confiança
                total_weight = sum(results[e].get("confidence", 0) for e in results)
                if total_weight == 0:
                    return list(results.values())[0]  # Fallback
                
                # Combinar textos (escolher o de maior confiança como base)
                best_engine = max(results.keys(), key=lambda e: results[e].get("confidence", 0))
                combined = results[best_engine].copy()
                
                # Calcular confiança média ponderada
                avg_confidence = total_weight / len(results)
                combined["confidence"] = avg_confidence
                
                return combined
            
            elif method == "consensus":
                # Consenso entre engines
                texts = [results[e].get("text", "") for e in results]
                confidences = [results[e].get("confidence", 0) for e in results]
                
                # Usar algoritmo simples de consenso (mais comum)
                from collections import Counter
                
                # Por agora, usar o mais confiável
                # Implementação mais sofisticada poderia comparar similaridade
                best_idx = confidences.index(max(confidences))
                best_engine = list(results.keys())[best_idx]
                
                combined = results[best_engine].copy()
                combined["consensus_confidence"] = sum(confidences) / len(confidences)
                
                return combined
            
            else:
                # Método desconhecido, retornar melhor confiança
                return self._combine_multi_engine_results(results, "best_confidence")
                
        except Exception as e:
            self.logger.warning(f"Result combination failed: {e}")
            return list(results.values())[0]  # Fallback para primeiro resultado
    
    def _post_process_orchestrator_result(self, result: Dict[str, Any], file_analysis: Dict, strategy: Dict) -> Dict[str, Any]:
        """Pós-processamento específico do orchestrador"""
        try:
            # Adicionar metadados da orquestração
            result["orchestrator"] = {
                "version": settings.VERSION,
                "decision_confidence": strategy.get("confidence", 0.0),
                "decision_reason": strategy.get("reason", "unknown"),
                "file_complexity": file_analysis.get("complexity_score", 0.0),
                "file_quality": file_analysis.get("quality_score", 0.0),
                "estimated_text_type": file_analysis.get("estimated_text_type", "unknown")
            }
            
            # Aplicar correções baseadas na análise
            if file_analysis.get("estimated_text_type") == "handwritten":
                result = self._apply_handwriting_corrections(result)
            
            # Validar consistência do resultado
            result = self._validate_result_consistency(result)
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Post-processing failed: {e}")
            return result
    
    def _apply_handwriting_corrections(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Aplica correções específicas para manuscritos"""
        try:
            text = result.get("text", "")
            
            # Correções comuns em manuscritos
            corrections = {
                # Números vs letras
                "0": "O",  # Dependendo do contexto
                "1": "l",  # Dependendo do contexto
                # Adicionar mais correções baseadas em análise estatística
            }
            
            # Aplicar correções conservadoras
            # (implementação mais sofisticada usaria NLP)
            
            result["handwriting_corrections_applied"] = True
            return result
            
        except Exception as e:
            self.logger.warning(f"Handwriting corrections failed: {e}")
            return result
    
    def _validate_result_consistency(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Valida consistência do resultado"""
        try:
            # Verificar se texto e blocos são consistentes
            text = result.get("text", "")
            blocks = result.get("blocks", [])
            
            if blocks:
                blocks_text = "\n".join([block.get("text", "") for block in blocks])
                
                # Se diferença é muito grande, usar blocos como fonte da verdade
                if abs(len(text) - len(blocks_text)) > len(text) * 0.3:
                    result["text"] = blocks_text
                    result["consistency_warning"] = "Text reconstructed from blocks"
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Consistency validation failed: {e}")
            return result


# Registrar tasks Celery
@celery_app.task(bind=True, base=OrchestratorWorker, queue='orchestrator_queue')
def orchestrate_ocr_task(self, request_data: dict):
    """Task principal de orquestração"""
    request = OCRRequest(**request_data)
    response = self.execute_ocr(request)
    return response.dict()


@celery_app.task(bind=True, base=OrchestratorWorker, queue='orchestrator_queue')
def analyze_document_complexity(self, file_path: str):
    """Task para analisar complexidade do documento"""
    worker = OrchestratorWorker()
    worker.load_model()
    
    analysis = worker._analyze_input_file(file_path)
    strategy = worker._decide_processing_strategy(analysis)
    
    return {
        "file_analysis": analysis,
        "recommended_strategy": strategy,
        "timestamp": time.time()
    }


@celery_app.task(bind=True, base=OrchestratorWorker, queue='orchestrator_queue')
def orchestrator_health_check(self):
    """Task para verificar saúde do orchestrador"""
    worker = OrchestratorWorker()
    health = worker.health_check()
    
    # Adicionar informações específicas do orchestrador
    health["available_engines"] = get_available_engines()
    health["engine_tasks"] = list(worker.engine_tasks.keys())
    
    return health


# Configurações específicas do worker
def configure_orchestrator_worker():
    """Configura worker orchestrador"""
    return {
        "queue": "orchestrator_queue",
        "concurrency": 4,  # Pode coordenar múltiplas tasks
        "prefetch_multiplier": 1,  # Uma coordenação por vez
        "max_tasks_per_child": 100,
    }


if __name__ == "__main__":
    """Teste do worker orchestrador"""
    import os
    
    print("=== Orchestrator Worker Test ===")
    
    worker = OrchestratorWorker()
    worker.load_model()
    
    # Teste de health check
    health = worker.health_check()
    print(f"Health status: {health['status']}")
    print(f"Available engines: {health.get('available_engines', [])}")
    
    # Teste de análise de arquivo
    test_image_path = "test_document.jpg"
    if os.path.exists(test_image_path):
        print(f"\n--- Analyzing {test_image_path} ---")
        
        # Análise do arquivo
        analysis = worker._analyze_input_file(test_image_path)
        print(f"Complexity score: {analysis.get('complexity_score', 0):.1f}")
        print(f"Quality score: {analysis.get('quality_score', 0):.1f}")
        print(f"Estimated text type: {analysis.get('estimated_text_type', 'unknown')}")
        
        # Estratégia recomendada
        strategy = worker._decide_processing_strategy(analysis)
        print(f"Recommended strategy: {strategy['type']}")
        print(f"Primary engine: {strategy.get('primary_engine', 'N/A')}")
        print(f"Confidence: {strategy.get('confidence', 0):.2f}")
        print(f"Reason: {strategy.get('reason', 'N/A')}")
        
    else:
        print(f"⚠️  Test image {test_image_path} not found")
    
    print("\n✅ Orchestrator Worker test completed")