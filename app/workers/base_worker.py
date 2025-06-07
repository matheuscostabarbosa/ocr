#!/usr/bin/env python3
"""
Base Worker para OCR Platform
=============================

Classe base para todos os workers OCR com:
- Gerenciamento de modelos
- Métricas e logging
- Tratamento de erros
- Cache de resultados
- Validação de entrada
"""

import os
import time
import hashlib
import tempfile
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import traceback

from celery import Task
from PIL import Image
import numpy as np

from app.core.config import settings, get_engine_config
from app.core.redis_client import get_redis_client
from app.models.schemas import OCRRequest, OCRResponse, TaskStatus

logger = logging.getLogger(__name__)


class BaseOCRWorker(Task, ABC):
    """Classe base para todos os workers OCR"""
    
    def __init__(self):
        self.engine_name = None
        self.model = None
        self.processor = None
        self.redis_client = get_redis_client()
        self.config = {}
        self._model_loaded = False
        self._setup_logging()
    
    def _setup_logging(self):
        """Configura logging específico do worker"""
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    @abstractmethod
    def load_model(self):
        """Carrega modelo específico do engine (implementar em subclasses)"""
        pass
    
    @abstractmethod
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Processa imagem (implementar em subclasses)"""
        pass
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Executado quando task falha"""
        self.logger.error(f"Task {task_id} failed: {exc}")
        self.logger.debug(f"Traceback: {einfo}")
        
        # Registrar falha no Redis
        self.redis_client.increment_metric(
            f"{self.engine_name}_failures", 
            tags={"error_type": type(exc).__name__}
        )
        
        # Atualizar status da task
        self._update_task_status(task_id, TaskStatus.FAILED, error=str(exc))
    
    def on_success(self, retval, task_id, args, kwargs):
        """Executado quando task é bem-sucedida"""
        self.logger.info(f"Task {task_id} completed successfully")
        
        # Registrar sucesso no Redis
        self.redis_client.increment_metric(f"{self.engine_name}_successes")
        
        # Atualizar status da task
        self._update_task_status(task_id, TaskStatus.COMPLETED, result=retval)
    
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Executado quando task é reenviada"""
        self.logger.warning(f"Task {task_id} retry: {exc}")
        
        # Registrar retry no Redis
        self.redis_client.increment_metric(f"{self.engine_name}_retries")
        
        # Atualizar status da task
        self._update_task_status(task_id, TaskStatus.RETRYING, error=str(exc))
    
    def _update_task_status(self, task_id: str, status: TaskStatus, **kwargs):
        """Atualiza status da task no Redis"""
        try:
            task_data = {
                "status": status.value,
                "updated_at": time.time(),
                "engine": self.engine_name,
                **kwargs
            }
            
            self.redis_client.client.hset(f"task:{task_id}", mapping=task_data)
            self.redis_client.client.expire(f"task:{task_id}", 3600)  # 1 hour
            
        except Exception as e:
            self.logger.warning(f"Failed to update task status: {e}")
    
    def _ensure_model_loaded(self):
        """Garante que o modelo está carregado"""
        if not self._model_loaded:
            self.logger.info(f"Loading {self.engine_name} model...")
            start_time = time.time()
            
            try:
                self.load_model()
                self._model_loaded = True
                load_time = time.time() - start_time
                
                self.logger.info(f"{self.engine_name} model loaded in {load_time:.2f}s")
                
                # Registrar tempo de carregamento
                self.redis_client.set_metric(
                    f"{self.engine_name}_model_load_time", 
                    load_time
                )
                
            except Exception as e:
                self.logger.error(f"Failed to load {self.engine_name} model: {e}")
                raise
    
    def _generate_cache_key(self, file_path: str, **kwargs) -> str:
        """Gera chave de cache baseada no arquivo e parâmetros"""
        # Hash do conteúdo do arquivo
        hasher = hashlib.sha256()
        
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hasher.update(chunk)
            file_hash = hasher.hexdigest()
        except Exception:
            # Fallback para timestamp se não conseguir ler arquivo
            file_hash = str(int(time.time()))
        
        # Hash dos parâmetros
        params_str = str(sorted(kwargs.items()))
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        
        return f"{self.engine_name}:{file_hash}:{params_hash}"
    
    def _check_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Verifica se resultado está em cache"""
        try:
            cached_result = self.redis_client.cache_get(cache_key)
            if cached_result:
                self.logger.debug(f"Cache hit for key: {cache_key}")
                self.redis_client.increment_metric(f"{self.engine_name}_cache_hits")
                return cached_result
            
            self.redis_client.increment_metric(f"{self.engine_name}_cache_misses")
            return None
            
        except Exception as e:
            self.logger.warning(f"Cache check failed: {e}")
            return None
    
    def _store_in_cache(self, cache_key: str, result: Dict[str, Any]):
        """Armazena resultado no cache"""
        try:
            cache_ttl = self.config.get('cache_ttl', 3600)  # 1 hour default
            self.redis_client.cache_set(cache_key, result, cache_ttl)
            self.logger.debug(f"Result cached with key: {cache_key}")
            
        except Exception as e:
            self.logger.warning(f"Failed to cache result: {e}")
    
    def _validate_image(self, image_path: str) -> bool:
        """Valida se arquivo é uma imagem válida"""
        try:
            with Image.open(image_path) as img:
                # Verificar se pode ser carregada
                img.verify()
                
                # Verificar formato suportado
                if img.format.lower() not in ['jpeg', 'jpg', 'png', 'bmp', 'tiff', 'webp']:
                    self.logger.warning(f"Unsupported image format: {img.format}")
                    return False
                
                return True
                
        except Exception as e:
            self.logger.error(f"Image validation failed: {e}")
            return False
    
    def _preprocess_image(self, image_path: str, **kwargs) -> str:
        """Pré-processa imagem se necessário"""
        try:
            # Carregar imagem
            with Image.open(image_path) as img:
                modified = False
                
                # Converter para RGB se necessário
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                    modified = True
                
                # Redimensionar se muito grande
                max_size = kwargs.get('max_size', 2048)
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                    modified = True
                
                # Aplicar melhorias se especificado
                if kwargs.get('enhance', False):
                    from PIL import ImageEnhance
                    
                    # Aumentar contraste
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.2)
                    
                    # Aumentar nitidez
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(1.1)
                    
                    modified = True
                
                # Salvar se modificada
                if modified:
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                        img.save(tmp_file.name, 'JPEG', quality=95)
                        return tmp_file.name
                
                return image_path
                
        except Exception as e:
            self.logger.warning(f"Image preprocessing failed: {e}")
            return image_path
    
    def _post_process_result(self, result: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Pós-processa resultado"""
        try:
            # Adicionar metadados do engine
            result['engine'] = self.engine_name
            result['processed_at'] = time.time()
            result['version'] = settings.VERSION
            
            # Aplicar filtros de confiança se especificado
            min_confidence = kwargs.get('min_confidence', 0.0)
            if min_confidence > 0 and 'blocks' in result:
                filtered_blocks = [
                    block for block in result['blocks']
                    if block.get('confidence', 1.0) >= min_confidence
                ]
                result['blocks'] = filtered_blocks
                
                # Reconstruir texto com blocos filtrados
                if filtered_blocks:
                    result['text'] = '\n'.join([block['text'] for block in filtered_blocks])
                else:
                    result['text'] = ''
            
            # Aplicar limpeza de texto se especificado
            if kwargs.get('clean_text', True):
                result['text'] = self._clean_text(result.get('text', ''))
            
            # Calcular estatísticas
            if 'blocks' in result:
                confidences = [block.get('confidence', 0) for block in result['blocks']]
                if confidences:
                    result['statistics'] = {
                        'total_blocks': len(result['blocks']),
                        'avg_confidence': sum(confidences) / len(confidences),
                        'min_confidence': min(confidences),
                        'max_confidence': max(confidences),
                        'char_count': len(result.get('text', '')),
                        'word_count': len(result.get('text', '').split())
                    }
            
            return result
            
        except Exception as e:
            self.logger.warning(f"Post-processing failed: {e}")
            return result
    
    def _clean_text(self, text: str) -> str:
        """Limpa texto extraído"""
        if not text:
            return text
        
        # Remove caracteres de controle
        import re
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', text)
        
        # Normaliza espaços em branco
        text = re.sub(r'\s+', ' ', text)
        
        # Remove espaços no início e fim
        text = text.strip()
        
        return text
    
    def _record_metrics(self, start_time: float, result: Dict[str, Any]):
        """Registra métricas de performance"""
        try:
            processing_time = time.time() - start_time
            
            # Métricas básicas
            self.redis_client.set_metric(
                f"{self.engine_name}_last_processing_time", 
                processing_time
            )
            
            self.redis_client.increment_metric(f"{self.engine_name}_total_processed")
            
            # Métricas de qualidade
            if 'statistics' in result:
                stats = result['statistics']
                self.redis_client.set_metric(
                    f"{self.engine_name}_avg_confidence",
                    stats.get('avg_confidence', 0)
                )
                
                self.redis_client.set_metric(
                    f"{self.engine_name}_avg_char_count",
                    stats.get('char_count', 0)
                )
            
            # Métricas de throughput
            throughput_key = f"{self.engine_name}_throughput_1min"
            self.redis_client.client.lpush(throughput_key, time.time())
            self.redis_client.client.ltrim(throughput_key, 0, 60)  # Keep last 60 entries
            self.redis_client.client.expire(throughput_key, 120)  # Expire in 2 minutes
            
        except Exception as e:
            self.logger.warning(f"Failed to record metrics: {e}")
    
    def execute_ocr(self, request: OCRRequest) -> OCRResponse:
        """Executa OCR com cache e métricas"""
        start_time = time.time()
        task_id = self.request.id if hasattr(self, 'request') else str(int(time.time()))
        
        try:
            # Atualizar status
            self._update_task_status(task_id, TaskStatus.PROCESSING)
            
            # Garantir que modelo está carregado
            self._ensure_model_loaded()
            
            # Validar entrada
            if not self._validate_image(request.file_path):
                raise ValueError("Invalid image file")
            
            # Gerar chave de cache
            cache_key = self._generate_cache_key(
                request.file_path,
                **request.parameters
            )
            
            # Verificar cache
            if request.use_cache:
                cached_result = self._check_cache(cache_key)
                if cached_result:
                    self._record_metrics(start_time, cached_result)
                    return OCRResponse(**cached_result)
            
            # Pré-processar imagem
            processed_image_path = self._preprocess_image(
                request.file_path, 
                **request.parameters
            )
            
            try:
                # Executar OCR
                result = self.process_image(processed_image_path, **request.parameters)
                
                # Pós-processar resultado
                result = self._post_process_result(result, **request.parameters)
                
                # Armazenar em cache
                if request.use_cache:
                    self._store_in_cache(cache_key, result)
                
                # Registrar métricas
                self._record_metrics(start_time, result)
                
                return OCRResponse(**result)
                
            finally:
                # Limpar arquivo temporário se foi criado
                if processed_image_path != request.file_path:
                    try:
                        os.unlink(processed_image_path)
                    except Exception:
                        pass
        
        except Exception as e:
            self.logger.error(f"OCR execution failed: {e}")
            self.logger.debug(traceback.format_exc())
            
            # Registrar erro
            self.redis_client.increment_metric(
                f"{self.engine_name}_errors",
                tags={"error_type": type(e).__name__}
            )
            
            raise
    
    def get_engine_info(self) -> Dict[str, Any]:
        """Retorna informações do engine"""
        config = get_engine_config(self.engine_name)
        
        return {
            "name": self.engine_name,
            "version": settings.VERSION,
            "model_loaded": self._model_loaded,
            "use_cases": config.get("use_cases", []),
            "accuracy_rating": config.get("accuracy_rating", 0),
            "avg_processing_time": config.get("avg_processing_time", 0),
            "gpu_required": config.get("gpu_memory_required", 0) > 0,
            "memory_required": config.get("gpu_memory_required", 0)
        }
    
    def health_check(self) -> Dict[str, Any]:
        """Verifica saúde do worker"""
        try:
            health_status = {
                "engine": self.engine_name,
                "status": "healthy",
                "model_loaded": self._model_loaded,
                "timestamp": time.time()
            }
            
            # Verificar se modelo pode ser carregado
            if not self._model_loaded:
                try:
                    self._ensure_model_loaded()
                    health_status["model_load_test"] = "passed"
                except Exception as e:
                    health_status["status"] = "unhealthy"
                    health_status["model_load_test"] = "failed"
                    health_status["error"] = str(e)
            
            # Verificar Redis
            if not self.redis_client.ping():
                health_status["status"] = "degraded"
                health_status["redis_connection"] = "failed"
            else:
                health_status["redis_connection"] = "ok"
            
            return health_status
            
        except Exception as e:
            return {
                "engine": self.engine_name,
                "status": "unhealthy",
                "error": str(e),
                "timestamp": time.time()
            }


if __name__ == "__main__":
    """Teste da classe base"""
    print("BaseOCRWorker - This is an abstract base class")
    print("Use specific worker implementations like TrOCRWorker, SuryaWorker, etc.")