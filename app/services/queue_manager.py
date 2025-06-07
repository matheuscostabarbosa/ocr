#!/usr/bin/env python3
"""
Gerenciador de Filas
===================

Gerencia filas de processamento OCR:
- Distribuição inteligente de tasks
- Balanceamento de carga
- Priorização
- Monitoramento de filas
- Auto-scaling (conceitual)
"""

import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import json

from app.core.config import settings, get_queue_config, get_available_engines
from app.core.redis_client import get_redis_client
from app.models.schemas import TaskStatus, QueueStatus

logger = logging.getLogger(__name__)


class QueueManager:
    """Gerenciador de filas OCR"""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        
        # Configurações
        self.max_queue_size = 1000
        self.high_priority_threshold = 8
        self.low_priority_threshold = 3
        
        # Métricas
        self.task_distribution_count = 0
        self.load_balancing_decisions = 0
        
        # Cache de status das filas
        self.queue_status_cache = {}
        self.cache_ttl = 30  # 30 segundos
        self.last_cache_update = 0
    
    def distribute_task(self, task_data: Dict[str, Any], target_engine: str, priority: int = 5) -> Dict[str, Any]:
        """
        Distribui task para a fila apropriada
        
        Args:
            task_data: Dados da task
            target_engine: Engine alvo
            priority: Prioridade da task (1-10)
            
        Returns:
            Dict com informações da distribuição
        """
        try:
            self.task_distribution_count += 1
            
            # Determinar fila alvo
            target_queue = f"{target_engine}_queue"
            
            # Verificar se fila existe
            if target_queue not in settings.QUEUE_CONFIG:
                logger.error(f"Queue {target_queue} not configured")
                # Fallback para fila padrão
                target_queue = "orchestrator_queue"
            
            # Verificar capacidade da fila
            queue_length = self.get_queue_length(target_queue)
            queue_config = get_queue_config(target_queue)
            max_capacity = queue_config.get("max_capacity", self.max_queue_size)
            
            if queue_length >= max_capacity:
                # Fila cheia - tentar redistribuir
                alternative_queue = self._find_alternative_queue(target_engine, priority)
                if alternative_queue:
                    target_queue = alternative_queue
                    logger.warning(f"Queue {target_queue} full, redistributing to {alternative_queue}")
                else:
                    logger.warning(f"All queues for {target_engine} are full")
            
            # Ajustar prioridade baseada na carga
            adjusted_priority = self._adjust_priority_by_load(priority, target_queue)
            
            # Criar informações da distribuição
            distribution_info = {
                "task_id": task_data.get("task_id"),
                "target_queue": target_queue,
                "original_engine": target_engine,
                "priority": priority,
                "adjusted_priority": adjusted_priority,
                "queue_length_before": queue_length,
                "timestamp": time.time(),
                "estimated_wait_time": self._estimate_wait_time(target_queue)
            }
            
            # Registrar métricas
            self._record_distribution_metrics(distribution_info)
            
            return distribution_info
            
        except Exception as e:
            logger.error(f"Task distribution failed: {e}")
            return {
                "error": str(e),
                "target_queue": "orchestrator_queue",
                "priority": priority,
                "timestamp": time.time()
            }
    
    def _find_alternative_queue(self, original_engine: str, priority: int) -> Optional[str]:
        """Encontra fila alternativa quando a original está cheia"""
        try:
            # Buscar filas relacionadas ou similares
            alternative_engines = []
            
            # Mapeamento de engines similares
            engine_alternatives = {
                "trocr": ["surya", "easyocr"],
                "surya": ["paddleocr", "easyocr"],
                "paddleocr": ["easyocr", "tesseract"],
                "easyocr": ["paddleocr", "tesseract"],
                "tesseract": ["paddleocr", "easyocr"],
                "marker": ["surya", "paddleocr"]
            }
            
            alternatives = engine_alternatives.get(original_engine, ["paddleocr", "tesseract"])
            
            # Verificar capacidade das alternativas
            for alt_engine in alternatives:
                alt_queue = f"{alt_engine}_queue"
                if alt_queue in settings.QUEUE_CONFIG:
                    queue_length = self.get_queue_length(alt_queue)
                    max_capacity = get_queue_config(alt_queue).get("max_capacity", self.max_queue_size)
                    
                    if queue_length < max_capacity * 0.8:  # 80% da capacidade
                        return alt_queue
            
            # Se prioridade alta, usar fila de orquestração
            if priority >= self.high_priority_threshold:
                return "orchestrator_queue"
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to find alternative queue: {e}")
            return None
    
    def _adjust_priority_by_load(self, original_priority: int, queue_name: str) -> int:
        """Ajusta prioridade baseada na carga da fila"""
        try:
            queue_length = self.get_queue_length(queue_name)
            queue_config = get_queue_config(queue_name)
            
            # Se fila está muito carregada, aumentar prioridade de tasks importantes
            if queue_length > 50:
                if original_priority >= 7:
                    return min(10, original_priority + 1)
                elif original_priority <= 3:
                    return max(1, original_priority - 1)
            
            return original_priority
            
        except Exception:
            return original_priority
    
    def _estimate_wait_time(self, queue_name: str) -> float:
        """Estima tempo de espera na fila"""
        try:
            queue_length = self.get_queue_length(queue_name)
            queue_config = get_queue_config(queue_name)
            
            # Tempo médio de processamento por task
            avg_processing_time = queue_config.get("avg_processing_time", 30.0)
            max_workers = queue_config.get("max_workers", 1)
            
            # Estimar tempo de espera
            if max_workers > 0:
                estimated_wait = (queue_length * avg_processing_time) / max_workers
            else:
                estimated_wait = queue_length * avg_processing_time
            
            return max(0.0, estimated_wait)
            
        except Exception:
            return 60.0  # Default 1 minute
    
    def get_queue_length(self, queue_name: str) -> int:
        """Obtém tamanho atual da fila"""
        try:
            return self.redis_client.get_queue_length(queue_name)
        except Exception as e:
            logger.warning(f"Failed to get queue length for {queue_name}: {e}")
            return 0
    
    def get_all_queue_lengths(self) -> Dict[str, int]:
        """Obtém tamanho de todas as filas"""
        try:
            return self.redis_client.get_all_queue_lengths()
        except Exception as e:
            logger.warning(f"Failed to get all queue lengths: {e}")
            return {}
    
    def get_queue_status(self, queue_name: str) -> QueueStatus:
        """Obtém status detalhado de uma fila"""
        try:
            # Verificar cache
            now = time.time()
            if (now - self.last_cache_update < self.cache_ttl and 
                queue_name in self.queue_status_cache):
                return self.queue_status_cache[queue_name]
            
            # Obter dados da fila
            queue_length = self.get_queue_length(queue_name)
            queue_config = get_queue_config(queue_name)
            
            # Obter estatísticas do Redis
            today = datetime.now().strftime("%Y-%m-%d")
            stats_key = f"queue_stats:{queue_name}:daily:{today}"
            queue_stats = self.redis_client.client.hgetall(stats_key)
            
            # Processar estatísticas
            if queue_stats:
                total_tasks = int(queue_stats.get(b"total_tasks", 0))
                success_tasks = int(queue_stats.get(b"success_tasks", 0))
                failed_tasks = int(queue_stats.get(b"failed_tasks", 0))
                total_duration = float(queue_stats.get(b"total_duration", 0))
                
                avg_processing_time = total_duration / total_tasks if total_tasks > 0 else 0
                throughput = self._calculate_throughput(queue_name)
            else:
                total_tasks = success_tasks = failed_tasks = 0
                avg_processing_time = throughput = 0
            
            # Obter workers ativos
            active_workers = self._get_active_workers_for_queue(queue_name)
            
            status = QueueStatus(
                queue_name=queue_name,
                pending_tasks=queue_length,
                active_tasks=len(active_workers),  # Aproximação
                completed_tasks=success_tasks,
                failed_tasks=failed_tasks,
                avg_processing_time=avg_processing_time,
                throughput=throughput,
                active_workers=len(active_workers),
                max_workers=queue_config.get("max_workers", 1)
            )
            
            # Cachear resultado
            self.queue_status_cache[queue_name] = status
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get queue status for {queue_name}: {e}")
            return QueueStatus(
                queue_name=queue_name,
                pending_tasks=0,
                active_tasks=0,
                completed_tasks=0,
                failed_tasks=0,
                avg_processing_time=0,
                throughput=0,
                active_workers=0,
                max_workers=1
            )
    
    def get_all_queue_status(self) -> List[QueueStatus]:
        """Obtém status de todas as filas"""
        statuses = []
        
        for queue_name in settings.QUEUE_CONFIG.keys():
            status = self.get_queue_status(queue_name)
            statuses.append(status)
        
        # Atualizar cache timestamp
        self.last_cache_update = time.time()
        
        return statuses
    
    def _calculate_throughput(self, queue_name: str) -> float:
        """Calcula throughput da fila (tasks por minuto)"""
        try:
            # Buscar timestamps de tasks processadas no último minuto
            throughput_key = f"queue_throughput:{queue_name}"
            current_time = time.time()
            
            # Obter timestamps do Redis
            timestamps = self.redis_client.client.lrange(throughput_key, 0, -1)
            
            # Contar tasks no último minuto
            recent_tasks = [
                ts for ts in timestamps 
                if current_time - float(ts) <= 60
            ]
            
            return len(recent_tasks)
            
        except Exception as e:
            logger.warning(f"Failed to calculate throughput for {queue_name}: {e}")
            return 0.0
    
    def _get_active_workers_for_queue(self, queue_name: str) -> List[str]:
        """Obtém workers ativos para uma fila específica"""
        try:
            from app.core.celery_app import celery_app
            
            inspector = celery_app.control.inspect()
            active_queues = inspector.active_queues() or {}
            
            workers_for_queue = []
            for worker_name, queues in active_queues.items():
                for queue_info in queues:
                    if queue_info.get("name") == queue_name:
                        workers_for_queue.append(worker_name)
                        break
            
            return workers_for_queue
            
        except Exception as e:
            logger.warning(f"Failed to get active workers for {queue_name}: {e}")
            return []
    
    def balance_load(self) -> Dict[str, Any]:
        """
        Executa balanceamento de carga entre filas
        
        Returns:
            Dict com resultados do balanceamento
        """
        try:
            self.load_balancing_decisions += 1
            
            # Obter status de todas as filas
            queue_statuses = self.get_all_queue_status()
            
            # Analisar desbalanceamento
            overloaded_queues = []
            underloaded_queues = []
            
            for status in queue_statuses:
                utilization = self._calculate_queue_utilization(status)
                
                if utilization > 0.9:  # 90% de utilização
                    overloaded_queues.append(status)
                elif utilization < 0.3:  # 30% de utilização
                    underloaded_queues.append(status)
            
            # Sugestões de balanceamento
            suggestions = []
            
            for overloaded in overloaded_queues:
                # Encontrar fila subutilizada compatível
                compatible_queue = self._find_compatible_queue(
                    overloaded.queue_name, 
                    underloaded_queues
                )
                
                if compatible_queue:
                    suggestions.append({
                        "action": "redistribute",
                        "from_queue": overloaded.queue_name,
                        "to_queue": compatible_queue.queue_name,
                        "estimated_tasks": min(10, overloaded.pending_tasks // 2),
                        "reason": f"Queue {overloaded.queue_name} overloaded ({overloaded.pending_tasks} pending)"
                    })
            
            # Sugestões de scaling
            for status in queue_statuses:
                if status.pending_tasks > status.max_workers * 10:  # Muitas tasks por worker
                    suggestions.append({
                        "action": "scale_up",
                        "queue": status.queue_name,
                        "current_workers": status.active_workers,
                        "suggested_workers": min(status.max_workers, status.active_workers + 2),
                        "reason": f"High task-to-worker ratio: {status.pending_tasks}/{status.active_workers}"
                    })
            
            result = {
                "timestamp": time.time(),
                "total_queues": len(queue_statuses),
                "overloaded_queues": len(overloaded_queues),
                "underloaded_queues": len(underloaded_queues),
                "suggestions": suggestions,
                "queue_utilizations": {
                    status.queue_name: self._calculate_queue_utilization(status)
                    for status in queue_statuses
                }
            }
            
            # Registrar métricas
            self._record_load_balancing_metrics(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Load balancing failed: {e}")
            return {
                "error": str(e),
                "timestamp": time.time(),
                "suggestions": []
            }
    
    def _calculate_queue_utilization(self, status: QueueStatus) -> float:
        """Calcula utilização da fila (0.0 a 1.0)"""
        if status.max_workers == 0:
            return 0.0
        
        # Considerar workers ativos e tasks pendentes
        worker_utilization = status.active_workers / status.max_workers
        
        # Penalizar se há muitas tasks pendentes
        if status.pending_tasks > 0:
            queue_pressure = min(1.0, status.pending_tasks / (status.max_workers * 5))
            return min(1.0, worker_utilization + queue_pressure)
        
        return worker_utilization
    
    def _find_compatible_queue(self, overloaded_queue: str, underloaded_queues: List[QueueStatus]) -> Optional[QueueStatus]:
        """Encontra fila compatível para redistribuição"""
        # Mapeamento de compatibilidade entre engines
        compatibility_map = {
            "trocr_queue": ["surya_queue", "easyocr_queue"],
            "surya_queue": ["paddleocr_queue", "easyocr_queue"],
            "paddleocr_queue": ["easyocr_queue", "tesseract_queue"],
            "easyocr_queue": ["paddleocr_queue", "tesseract_queue"],
            "tesseract_queue": ["paddleocr_queue", "easyocr_queue"],
            "marker_queue": ["surya_queue"]
        }
        
        compatible_names = compatibility_map.get(overloaded_queue, [])
        
        for queue_status in underloaded_queues:
            if queue_status.queue_name in compatible_names:
                return queue_status
        
        return None
    
    def prioritize_tasks(self, queue_name: str, criteria: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Reorganiza prioridades das tasks em uma fila
        
        Args:
            queue_name: Nome da fila
            criteria: Critérios de priorização
            
        Returns:
            Dict com resultados da priorização
        """
        try:
            # Este seria implementado com funcionalidade real do Celery/Redis
            # Por agora, retornamos uma simulação
            
            criteria = criteria or {}
            
            # Critérios padrão
            default_criteria = {
                "prioritize_small_files": True,
                "prioritize_simple_documents": True,
                "boost_vip_users": True,
                "age_factor": 0.1  # Aumentar prioridade com idade
            }
            default_criteria.update(criteria)
            
            # Simular reorganização
            queue_length = self.get_queue_length(queue_name)
            
            result = {
                "queue_name": queue_name,
                "tasks_before": queue_length,
                "criteria_applied": default_criteria,
                "reordered_tasks": min(queue_length, 50),  # Máximo 50 tasks reordenadas
                "timestamp": time.time()
            }
            
            logger.info(f"Prioritized {result['reordered_tasks']} tasks in {queue_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"Task prioritization failed for {queue_name}: {e}")
            return {
                "error": str(e),
                "queue_name": queue_name,
                "timestamp": time.time()
            }
    
    def get_queue_health(self, queue_name: str) -> Dict[str, Any]:
        """Avalia saúde de uma fila"""
        try:
            status = self.get_queue_status(queue_name)
            config = get_queue_config(queue_name)
            
            # Indicadores de saúde
            health_indicators = {
                "queue_length": status.pending_tasks,
                "worker_availability": status.active_workers / max(status.max_workers, 1),
                "throughput": status.throughput,
                "error_rate": 0.0,
                "avg_processing_time": status.avg_processing_time
            }
            
            # Calcular taxa de erro
            total_tasks = status.completed_tasks + status.failed_tasks
            if total_tasks > 0:
                health_indicators["error_rate"] = status.failed_tasks / total_tasks
            
            # Determinar saúde geral
            health_score = 10.0
            warnings = []
            
            # Penalizar por fila muito cheia
            if status.pending_tasks > 100:
                health_score -= 3.0
                warnings.append("High queue length")
            
            # Penalizar por baixa disponibilidade de workers
            if health_indicators["worker_availability"] < 0.5:
                health_score -= 2.0
                warnings.append("Low worker availability")
            
            # Penalizar por alta taxa de erro
            if health_indicators["error_rate"] > 0.1:
                health_score -= 2.0
                warnings.append("High error rate")
            
            # Penalizar por baixo throughput
            if status.throughput < 1.0:  # Menos de 1 task por minuto
                health_score -= 1.0
                warnings.append("Low throughput")
            
            # Determinar status
            if health_score >= 8.0:
                health_status = "healthy"
            elif health_score >= 6.0:
                health_status = "degraded"
            else:
                health_status = "unhealthy"
            
            return {
                "queue_name": queue_name,
                "health_status": health_status,
                "health_score": max(0.0, health_score),
                "indicators": health_indicators,
                "warnings": warnings,
                "recommendations": self._generate_health_recommendations(health_indicators, warnings),
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"Queue health check failed for {queue_name}: {e}")
            return {
                "queue_name": queue_name,
                "health_status": "unknown",
                "error": str(e),
                "timestamp": time.time()
            }
    
    def _generate_health_recommendations(self, indicators: Dict[str, Any], warnings: List[str]) -> List[str]:
        """Gera recomendações baseadas na saúde da fila"""
        recommendations = []
        
        if "High queue length" in warnings:
            recommendations.append("Consider scaling up workers or redistributing tasks")
        
        if "Low worker availability" in warnings:
            recommendations.append("Check worker health and restart if necessary")
        
        if "High error rate" in warnings:
            recommendations.append("Investigate task failures and validate input data")
        
        if "Low throughput" in warnings:
            recommendations.append("Monitor worker performance and optimize processing")
        
        if indicators["avg_processing_time"] > 120:  # > 2 minutes
            recommendations.append("Review task complexity and consider engine optimization")
        
        return recommendations
    
    def _record_distribution_metrics(self, distribution_info: Dict[str, Any]):
        """Registra métricas de distribuição"""
        try:
            self.redis_client.increment_metric("queue_manager_distributions")
            
            queue_name = distribution_info.get("target_queue")
            if queue_name:
                self.redis_client.increment_metric("queue_manager_queue_assignments", tags={"queue": queue_name})
            
            priority = distribution_info.get("priority", 5)
            priority_level = "high" if priority >= 8 else "low" if priority <= 3 else "medium"
            self.redis_client.increment_metric("queue_manager_priority_assignments", tags={"level": priority_level})
            
        except Exception as e:
            logger.warning(f"Failed to record distribution metrics: {e}")
    
    def _record_load_balancing_metrics(self, result: Dict[str, Any]):
        """Registra métricas de balanceamento de carga"""
        try:
            self.redis_client.increment_metric("queue_manager_load_balancing_runs")
            
            suggestions_count = len(result.get("suggestions", []))
            self.redis_client.set_metric("queue_manager_last_suggestions_count", suggestions_count)
            
            overloaded_count = result.get("overloaded_queues", 0)
            self.redis_client.set_metric("queue_manager_overloaded_queues", overloaded_count)
            
        except Exception as e:
            logger.warning(f"Failed to record load balancing metrics: {e}")
    
    def get_manager_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do gerenciador de filas"""
        try:
            stats = {
                "task_distributions": self.task_distribution_count,
                "load_balancing_decisions": self.load_balancing_decisions,
                "cache_entries": len(self.queue_status_cache),
                "last_cache_update": self.last_cache_update,
                "queue_summary": {}
            }
            
            # Resumo das filas
            all_statuses = self.get_all_queue_status()
            total_pending = sum(status.pending_tasks for status in all_statuses)
            total_workers = sum(status.active_workers for status in all_statuses)
            
            stats["queue_summary"] = {
                "total_queues": len(all_statuses),
                "total_pending_tasks": total_pending,
                "total_active_workers": total_workers,
                "avg_queue_length": total_pending / len(all_statuses) if all_statuses else 0
            }
            
            # Métricas do Redis
            try:
                stats["total_distributions"] = self.redis_client.get_metric("queue_manager_distributions") or 0
                stats["total_load_balancing_runs"] = self.redis_client.get_metric("queue_manager_load_balancing_runs") or 0
                stats["last_suggestions_count"] = self.redis_client.get_metric("queue_manager_last_suggestions_count") or 0
                
            except Exception as e:
                logger.warning(f"Failed to get Redis metrics: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get manager stats: {e}")
            return {"error": str(e)}


# Instância global do gerenciador
queue_manager = QueueManager()


def get_queue_manager() -> QueueManager:
    """Retorna instância global do gerenciador de filas"""
    return queue_manager


if __name__ == "__main__":
    """Teste do gerenciador de filas"""
    print("=== Queue Manager Test ===")
    
    manager = get_queue_manager()
    
    # Teste de distribuição de task
    test_task = {
        "task_id": "test_123",
        "file_path": "/test/file.jpg",
        "engine": "paddleocr"
    }
    
    distribution = manager.distribute_task(test_task, "paddleocr", priority=7)
    print(f"Task distribution:")
    print(f"  Target queue: {distribution.get('target_queue')}")
    print(f"  Priority: {distribution.get('priority')} -> {distribution.get('adjusted_priority')}")
    print(f"  Estimated wait: {distribution.get('estimated_wait_time', 0):.1f}s")
    
    # Teste de status das filas
    print(f"\nQueue lengths:")
    lengths = manager.get_all_queue_lengths()
    for queue_name, length in lengths.items():
        print(f"  {queue_name}: {length} tasks")
    
    # Teste de balanceamento de carga
    balance_result = manager.balance_load()
    print(f"\nLoad balancing:")
    print(f"  Overloaded queues: {balance_result.get('overloaded_queues', 0)}")
    print(f"  Suggestions: {len(balance_result.get('suggestions', []))}")
    
    # Estatísticas do gerenciador
    stats = manager.get_manager_stats()
    print(f"\nManager stats:")
    print(f"  Task distributions: {stats.get('task_distributions', 0)}")
    print(f"  Total pending tasks: {stats.get('queue_summary', {}).get('total_pending_tasks', 0)}")
    
    print("\n✅ Queue Manager test completed")