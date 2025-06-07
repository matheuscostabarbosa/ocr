#!/usr/bin/env python3
"""
Serviço de Orquestração
=======================

Coordena e gerencia o processamento OCR:
- Análise de documentos
- Seleção de engines
- Distribuição de tasks
- Coordenação de fallbacks
- Agregação de resultados
"""

import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import hashlib
import json

from app.core.config import settings, get_engine_config, get_available_engines, get_queue_config
from app.core.redis_client import get_redis_client
from app.models.schemas import OCRRequest, OCRResponse, TaskStatus, OCREngine
from app.services.file_detector import FileTypeDetector

logger = logging.getLogger(__name__)


class OrchestratorService:
    """Serviço principal de orquestração"""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        self.file_detector = FileTypeDetector()
        
        # Cache para decisões de engine
        self.decision_cache_ttl = 300  # 5 minutos
        
        # Configurações de estratégia
        self.enable_fallback = True
        self.enable_multi_engine = True
        self.enable_caching = True
        
        # Métricas
        self.orchestration_count = 0
        self.decision_hit_count = 0
        
    def analyze_document(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        Analisa documento para determinar características
        
        Args:
            file_path: Caminho do arquivo
            **kwargs: Parâmetros adicionais
            
        Returns:
            Dict com análise do documento
        """
        try:
            analysis_start = time.time()
            
            # Verificar cache de análise
            cache_key = self._generate_analysis_cache_key(file_path)
            
            if self.enable_caching:
                cached_analysis = self.redis_client.cache_get(cache_key)
                if cached_analysis:
                    logger.debug(f"Using cached analysis for {file_path}")
                    return cached_analysis
            
            # Informações básicas do arquivo
            file_stats = Path(file_path).stat()
            file_info = self.file_detector.detect_file_type(file_path)
            
            analysis = {
                "file_path": file_path,
                "file_size": file_stats.st_size,
                "file_type": file_info,
                "complexity_score": 5.0,  # Default medium
                "quality_score": 5.0,     # Default medium
                "estimated_text_type": "mixed",
                "processing_priority": "normal",
                "recommended_engines": [],
                "estimated_processing_time": 30.0,
                "analysis_time": 0.0
            }
            
            # Análise específica por tipo
            if file_info.get("category") == "image":
                analysis.update(self._analyze_image_document(file_path, file_info))
            elif file_info.get("category") == "pdf":
                analysis.update(self._analyze_pdf_document(file_path, file_info))
            elif file_info.get("category") == "office":
                analysis.update(self._analyze_office_document(file_path, file_info))
            
            # Calcular prioridade baseada nas características
            analysis["processing_priority"] = self._calculate_processing_priority(analysis)
            
            # Recomendar engines
            analysis["recommended_engines"] = self._recommend_engines(analysis, **kwargs)
            
            # Estimar tempo de processamento
            analysis["estimated_processing_time"] = self._estimate_processing_time(analysis)
            
            analysis["analysis_time"] = time.time() - analysis_start
            
            # Cachear resultado
            if self.enable_caching:
                self.redis_client.cache_set(cache_key, analysis, self.decision_cache_ttl)
            
            return analysis
            
        except Exception as e:
            logger.error(f"Document analysis failed for {file_path}: {e}")
            return {
                "file_path": file_path,
                "error": str(e),
                "complexity_score": 5.0,
                "quality_score": 5.0,
                "estimated_text_type": "unknown",
                "processing_priority": "normal",
                "recommended_engines": ["paddleocr"],  # Safe fallback
                "estimated_processing_time": 60.0
            }
    
    def _analyze_image_document(self, file_path: str, file_info: Dict) -> Dict[str, Any]:
        """Análise específica para imagens"""
        try:
            from PIL import Image
            import cv2
            import numpy as np
            
            analysis = {}
            
            with Image.open(file_path) as img:
                # Características básicas
                analysis["image_dimensions"] = img.size
                analysis["image_mode"] = img.mode
                analysis["aspect_ratio"] = img.width / img.height
                
                # Converter para análise
                if img.mode != 'L':
                    gray_img = img.convert('L')
                else:
                    gray_img = img
                
                img_array = np.array(gray_img)
                
                # Análise estatística
                mean_intensity = np.mean(img_array)
                std_intensity = np.std(img_array)
                
                analysis["mean_intensity"] = float(mean_intensity)
                analysis["std_intensity"] = float(std_intensity)
                analysis["contrast_ratio"] = float(std_intensity / mean_intensity) if mean_intensity > 0 else 0
                
                # Estimar qualidade
                if analysis["contrast_ratio"] > 0.8:
                    quality_score = 9.0
                elif analysis["contrast_ratio"] > 0.5:
                    quality_score = 7.0
                elif analysis["contrast_ratio"] > 0.3:
                    quality_score = 5.0
                else:
                    quality_score = 3.0
                
                analysis["quality_score"] = quality_score
                
                # Detectar tipo de texto baseado em características
                if analysis["contrast_ratio"] < 0.4 and std_intensity > 40:
                    analysis["estimated_text_type"] = "handwritten"
                    analysis["complexity_score"] = 8.0
                elif analysis["contrast_ratio"] > 0.6:
                    analysis["estimated_text_type"] = "printed"
                    analysis["complexity_score"] = 4.0
                else:
                    analysis["estimated_text_type"] = "mixed"
                    analysis["complexity_score"] = 6.0
                
                # Análise de layout usando OpenCV
                try:
                    # Detectar regiões de texto
                    _, binary = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    
                    # Análise de componentes conectados
                    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary)
                    
                    # Contar componentes que parecem texto
                    text_components = 0
                    for i in range(1, num_labels):
                        area = stats[i, cv2.CC_STAT_AREA]
                        width = stats[i, cv2.CC_STAT_WIDTH]
                        height = stats[i, cv2.CC_STAT_HEIGHT]
                        
                        # Heurística para identificar texto
                        if 10 < area < 10000 and 0.1 < width/height < 10:
                            text_components += 1
                    
                    analysis["text_components"] = text_components
                    analysis["text_density"] = text_components / (img.width * img.height / 10000)
                    
                    # Ajustar complexidade baseada na densidade
                    if analysis["text_density"] > 50:
                        analysis["complexity_score"] += 2
                    elif analysis["text_density"] < 5:
                        analysis["complexity_score"] -= 1
                        
                except Exception as e:
                    logger.warning(f"Layout analysis failed: {e}")
            
            return analysis
            
        except Exception as e:
            logger.warning(f"Image analysis failed: {e}")
            return {
                "quality_score": 5.0,
                "complexity_score": 5.0,
                "estimated_text_type": "mixed"
            }
    
    def _analyze_pdf_document(self, file_path: str, file_info: Dict) -> Dict[str, Any]:
        """Análise específica para PDFs"""
        try:
            import fitz  # PyMuPDF
            
            analysis = {
                "estimated_text_type": "printed",
                "complexity_score": 6.0,
                "quality_score": 7.0
            }
            
            doc = fitz.open(file_path)
            
            # Informações básicas
            analysis["total_pages"] = len(doc)
            analysis["has_text"] = False
            analysis["has_images"] = False
            analysis["text_coverage"] = 0.0
            
            # Analisar algumas páginas (amostra)
            sample_pages = min(5, len(doc))
            text_pages = 0
            total_text_length = 0
            
            for page_num in range(0, sample_pages):
                page = doc.load_page(page_num)
                
                # Verificar texto
                text = page.get_text()
                if text.strip():
                    analysis["has_text"] = True
                    text_pages += 1
                    total_text_length += len(text)
                
                # Verificar imagens
                if page.get_images():
                    analysis["has_images"] = True
                
                # Detectar tabelas (heurística simples)
                if "table" in text.lower() or text.count("|") > 5:
                    analysis["complexity_score"] += 1
            
            doc.close()
            
            # Calcular métricas
            if sample_pages > 0:
                analysis["text_coverage"] = text_pages / sample_pages
                analysis["avg_text_per_page"] = total_text_length / text_pages if text_pages > 0 else 0
            
            # Ajustar scores baseado nas características
            if analysis["has_images"]:
                analysis["complexity_score"] += 1
            
            if analysis["total_pages"] > 50:
                analysis["complexity_score"] += 1
            
            if analysis["avg_text_per_page"] > 3000:
                analysis["complexity_score"] += 1
            
            # PDFs geralmente têm boa qualidade
            if analysis["has_text"] and analysis["text_coverage"] > 0.8:
                analysis["quality_score"] = 8.0
            
            return analysis
            
        except Exception as e:
            logger.warning(f"PDF analysis failed: {e}")
            return {
                "estimated_text_type": "printed",
                "complexity_score": 6.0,
                "quality_score": 7.0
            }
    
    def _analyze_office_document(self, file_path: str, file_info: Dict) -> Dict[str, Any]:
        """Análise específica para documentos Office"""
        # Office documents precisariam ser convertidos primeiro
        return {
            "estimated_text_type": "printed",
            "complexity_score": 7.0,  # Geralmente mais complexos
            "quality_score": 8.0       # Geralmente boa qualidade
        }
    
    def _calculate_processing_priority(self, analysis: Dict[str, Any]) -> str:
        """Calcula prioridade de processamento"""
        complexity = analysis.get("complexity_score", 5.0)
        quality = analysis.get("quality_score", 5.0)
        file_size = analysis.get("file_size", 0)
        
        # Prioridade alta para arquivos pequenos e simples
        if file_size < 1024 * 1024 and complexity < 5.0:  # < 1MB e baixa complexidade
            return "high"
        
        # Prioridade baixa para arquivos grandes e complexos
        if file_size > 10 * 1024 * 1024 or complexity > 8.0:  # > 10MB ou alta complexidade
            return "low"
        
        return "normal"
    
    def _recommend_engines(self, analysis: Dict[str, Any], **kwargs) -> List[str]:
        """Recomenda engines baseado na análise"""
        recommendations = []
        
        # Engine forçado pelo usuário
        if kwargs.get("force_engine"):
            return [kwargs["force_engine"]]
        
        text_type = analysis.get("estimated_text_type", "mixed")
        complexity = analysis.get("complexity_score", 5.0)
        quality = analysis.get("quality_score", 5.0)
        file_category = analysis.get("file_type", {}).get("category", "unknown")
        
        # Recomendações baseadas no tipo de texto
        if text_type == "handwritten":
            recommendations.append("trocr")
            if quality < 5.0:
                recommendations.append("surya")  # Fallback para manuscritos de baixa qualidade
        
        elif text_type == "printed":
            if complexity > 7.0:
                recommendations.append("surya")  # Layout complexo
                recommendations.append("paddleocr")  # Fallback rápido
            else:
                recommendations.append("paddleocr")  # Rápido para texto simples
                recommendations.append("tesseract")   # Fallback confiável
        
        else:  # mixed ou unknown
            if quality < 4.0:
                # Baixa qualidade - usar múltiplos engines
                recommendations.extend(["trocr", "surya", "paddleocr"])
            else:
                # Qualidade OK - engine geral
                recommendations.append("easyocr")
                recommendations.append("paddleocr")
        
        # Recomendações específicas por categoria de arquivo
        if file_category == "pdf":
            if kwargs.get("output_format") == "markdown":
                recommendations.insert(0, "marker")  # Melhor para PDF→Markdown
            else:
                recommendations.insert(0, "surya")   # Boa para PDFs complexos
        
        # Garantir que pelo menos um engine está disponível
        available_engines = get_available_engines()
        filtered_recommendations = [e for e in recommendations if e in available_engines]
        
        if not filtered_recommendations:
            # Fallback para engines disponíveis
            if "paddleocr" in available_engines:
                filtered_recommendations.append("paddleocr")
            elif "tesseract" in available_engines:
                filtered_recommendations.append("tesseract")
            else:
                filtered_recommendations = available_engines[:1]
        
        return filtered_recommendations[:3]  # Máximo 3 engines
    
    def _estimate_processing_time(self, analysis: Dict[str, Any]) -> float:
        """Estima tempo de processamento"""
        base_time = 30.0  # segundos
        
        # Ajustar baseado no tamanho do arquivo
        file_size = analysis.get("file_size", 0)
        if file_size > 10 * 1024 * 1024:  # > 10MB
            base_time *= 3
        elif file_size > 5 * 1024 * 1024:  # > 5MB
            base_time *= 2
        
        # Ajustar baseado na complexidade
        complexity = analysis.get("complexity_score", 5.0)
        complexity_factor = complexity / 5.0
        base_time *= complexity_factor
        
        # Ajustar baseado na qualidade (baixa qualidade = mais tempo)
        quality = analysis.get("quality_score", 5.0)
        if quality < 4.0:
            base_time *= 1.5
        
        # Ajustar baseado no tipo de arquivo
        file_category = analysis.get("file_type", {}).get("category", "unknown")
        if file_category == "pdf":
            pages = analysis.get("total_pages", 1)
            base_time += pages * 5  # 5 segundos por página
        
        return max(10.0, min(300.0, base_time))  # Entre 10s e 5min
    
    def select_optimal_engine(self, analysis: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """
        Seleciona engine ótimo baseado na análise
        
        Returns:
            Dict com estratégia de processamento
        """
        try:
            recommendations = analysis.get("recommended_engines", ["paddleocr"])
            
            # Verificar carga atual dos workers
            worker_loads = self._get_worker_loads()
            
            # Selecionar engine com menor carga
            selected_engine = self._select_least_loaded_engine(recommendations, worker_loads)
            
            # Determinar estratégia
            strategy = {
                "type": "single_engine",
                "primary_engine": selected_engine,
                "fallback_engine": None,
                "confidence": 0.8,
                "estimated_time": analysis.get("estimated_processing_time", 30.0),
                "queue": f"{selected_engine}_queue"
            }
            
            # Adicionar fallback se disponível
            if len(recommendations) > 1 and self.enable_fallback:
                fallback_candidates = [e for e in recommendations if e != selected_engine]
                if fallback_candidates:
                    strategy["fallback_engine"] = fallback_candidates[0]
                    strategy["confidence"] += 0.1
            
            # Considerar multi-engine para casos complexos
            complexity = analysis.get("complexity_score", 5.0)
            quality = analysis.get("quality_score", 5.0)
            
            if (complexity > 8.0 or quality < 3.0) and self.enable_multi_engine and len(recommendations) >= 2:
                strategy["type"] = "multi_engine"
                strategy["engines"] = recommendations[:2]
                strategy["combination_method"] = "best_confidence"
                strategy["confidence"] = 0.9
            
            return strategy
            
        except Exception as e:
            logger.error(f"Engine selection failed: {e}")
            return {
                "type": "single_engine",
                "primary_engine": "paddleocr",
                "confidence": 0.5,
                "estimated_time": 60.0,
                "queue": "paddleocr_queue",
                "error": str(e)
            }
    
    def _get_worker_loads(self) -> Dict[str, float]:
        """Obtém carga atual dos workers"""
        try:
            from app.core.celery_app import celery_app
            
            inspector = celery_app.control.inspect()
            active_tasks = inspector.active() or {}
            
            # Calcular carga por engine
            loads = {}
            for worker_name, tasks in active_tasks.items():
                # Extrair engine do nome do worker
                for engine in get_available_engines():
                    if engine in worker_name.lower():
                        if engine not in loads:
                            loads[engine] = 0
                        loads[engine] += len(tasks)
                        break
            
            # Normalizar cargas
            max_workers_per_engine = 10  # Assumir máximo
            normalized_loads = {}
            for engine in get_available_engines():
                current_load = loads.get(engine, 0)
                normalized_loads[engine] = current_load / max_workers_per_engine
            
            return normalized_loads
            
        except Exception as e:
            logger.warning(f"Failed to get worker loads: {e}")
            return {engine: 0.5 for engine in get_available_engines()}  # Default medium load
    
    def _select_least_loaded_engine(self, candidates: List[str], loads: Dict[str, float]) -> str:
        """Seleciona engine com menor carga"""
        if not candidates:
            return "paddleocr"
        
        # Encontrar engine com menor carga
        min_load = float('inf')
        selected = candidates[0]
        
        for engine in candidates:
            load = loads.get(engine, 0.5)
            if load < min_load:
                min_load = load
                selected = engine
        
        return selected
    
    def _generate_analysis_cache_key(self, file_path: str) -> str:
        """Gera chave de cache para análise"""
        # Hash baseado no caminho e timestamp de modificação
        try:
            file_stat = Path(file_path).stat()
            content = f"{file_path}:{file_stat.st_size}:{file_stat.st_mtime}"
            return f"analysis:{hashlib.md5(content.encode()).hexdigest()}"
        except Exception:
            return f"analysis:{hashlib.md5(file_path.encode()).hexdigest()}"
    
    def orchestrate_request(self, request: OCRRequest) -> Dict[str, Any]:
        """
        Orquestra processamento de uma request OCR
        
        Args:
            request: Request OCR
            
        Returns:
            Dict com plano de execução
        """
        try:
            self.orchestration_count += 1
            
            # Analisar documento
            analysis = self.analyze_document(
                request.file_path,
                **request.parameters.dict()
            )
            
            # Selecionar estratégia
            strategy = self.select_optimal_engine(
                analysis,
                **request.parameters.dict()
            )
            
            # Criar plano de execução
            execution_plan = {
                "request_id": request.task_id,
                "file_path": request.file_path,
                "analysis": analysis,
                "strategy": strategy,
                "priority": request.priority,
                "parameters": request.parameters.dict(),
                "created_at": time.time(),
                "estimated_completion": time.time() + strategy.get("estimated_time", 30.0)
            }
            
            # Registrar métricas
            self._record_orchestration_metrics(execution_plan)
            
            return execution_plan
            
        except Exception as e:
            logger.error(f"Request orchestration failed: {e}")
            raise
    
    def _record_orchestration_metrics(self, plan: Dict[str, Any]):
        """Registra métricas de orquestração"""
        try:
            # Métricas básicas
            self.redis_client.increment_metric("orchestrator_requests")
            
            # Métricas por engine
            strategy = plan.get("strategy", {})
            primary_engine = strategy.get("primary_engine")
            if primary_engine:
                self.redis_client.increment_metric("orchestrator_engine_selections", tags={"engine": primary_engine})
            
            # Métricas por tipo de estratégia
            strategy_type = strategy.get("type", "unknown")
            self.redis_client.increment_metric("orchestrator_strategy_types", tags={"type": strategy_type})
            
            # Métricas por complexidade
            complexity = plan.get("analysis", {}).get("complexity_score", 5.0)
            if complexity > 7.0:
                complexity_level = "high"
            elif complexity < 4.0:
                complexity_level = "low"
            else:
                complexity_level = "medium"
            
            self.redis_client.increment_metric("orchestrator_complexity", tags={"level": complexity_level})
            
        except Exception as e:
            logger.warning(f"Failed to record orchestration metrics: {e}")
    
    def get_orchestration_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de orquestração"""
        try:
            stats = {
                "total_orchestrations": self.orchestration_count,
                "decision_cache_hits": self.decision_hit_count,
                "cache_hit_rate": 0.0,
                "avg_analysis_time": 0.0,
                "engine_selections": {},
                "strategy_distribution": {},
                "complexity_distribution": {}
            }
            
            # Cache hit rate
            if self.orchestration_count > 0:
                stats["cache_hit_rate"] = (self.decision_hit_count / self.orchestration_count) * 100
            
            # Métricas do Redis
            try:
                total_requests = self.redis_client.get_metric("orchestrator_requests") or 0
                stats["total_requests_processed"] = total_requests
                
                # Seleções por engine
                for engine in get_available_engines():
                    selections = self.redis_client.get_metric("orchestrator_engine_selections", tags={"engine": engine}) or 0
                    stats["engine_selections"][engine] = selections
                
                # Distribuição de estratégias
                for strategy_type in ["single_engine", "multi_engine", "pipeline"]:
                    count = self.redis_client.get_metric("orchestrator_strategy_types", tags={"type": strategy_type}) or 0
                    stats["strategy_distribution"][strategy_type] = count
                
                # Distribuição de complexidade
                for level in ["low", "medium", "high"]:
                    count = self.redis_client.get_metric("orchestrator_complexity", tags={"level": level}) or 0
                    stats["complexity_distribution"][level] = count
                    
            except Exception as e:
                logger.warning(f"Failed to get Redis metrics: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get orchestration stats: {e}")
            return {"error": str(e)}


# Instância global do serviço
orchestrator_service = OrchestratorService()


def get_orchestrator_service() -> OrchestratorService:
    """Retorna instância global do serviço de orquestração"""
    return orchestrator_service


if __name__ == "__main__":
    """Teste do serviço de orquestração"""
    import tempfile
    
    print("=== Orchestrator Service Test ===")
    
    service = get_orchestrator_service()
    
    # Criar arquivo de teste
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_file:
        tmp_file.write(b"Test document content")
        test_file = tmp_file.name
    
    try:
        # Teste de análise
        analysis = service.analyze_document(test_file)
        print(f"Analysis completed:")
        print(f"  Complexity: {analysis.get('complexity_score', 0):.1f}")
        print(f"  Quality: {analysis.get('quality_score', 0):.1f}")
        print(f"  Text type: {analysis.get('estimated_text_type', 'unknown')}")
        print(f"  Recommended engines: {analysis.get('recommended_engines', [])}")
        
        # Teste de seleção de engine
        strategy = service.select_optimal_engine(analysis)
        print(f"\nStrategy selected:")
        print(f"  Type: {strategy.get('type', 'unknown')}")
        print(f"  Primary engine: {strategy.get('primary_engine', 'unknown')}")
        print(f"  Confidence: {strategy.get('confidence', 0):.2f}")
        
        # Estatísticas
        stats = service.get_orchestration_stats()
        print(f"\nOrchestration stats:")
        print(f"  Total orchestrations: {stats.get('total_orchestrations', 0)}")
        print(f"  Cache hit rate: {stats.get('cache_hit_rate', 0):.1f}%")
        
    finally:
        # Limpar arquivo de teste
        Path(test_file).unlink(missing_ok=True)
    
    print("\n✅ Orchestrator Service test completed")