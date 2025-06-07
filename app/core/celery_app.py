#!/usr/bin/env python3
"""
Configuração Celery para OCR Platform
====================================

Configura Celery com:
- Múltiplas filas especializadas
- Roteamento por tipo de OCR
- Monitoramento e métricas
- Auto-scaling por demanda
"""

import os
import logging
from typing import Dict, Any
from celery import Celery
from celery.signals import task_prerun, task_postrun, worker_ready, worker_shutting_down
from kombu import Queue, Exchange
import time

from .config import settings, get_queue_config, get_available_engines

# Configurar logging
logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))
logger = logging.getLogger(__name__)


def create_celery_app() -> Celery:
    """Cria e configura aplicação Celery"""
    
    app = Celery(
        "ocr_platform",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            'app.workers.trocr_worker',
            'app.workers.surya_worker', 
            'app.workers.paddleocr_worker',
            'app.workers.easyocr_worker',
            'app.workers.tesseract_worker',
            'app.workers.marker_worker',
            'app.workers.orchestrator_worker'
        ]
    )
    
    # Configuração base do Celery
    app.conf.update(
        task_serializer=settings.CELERY_TASK_SERIALIZER,
        result_serializer=settings.CELERY_RESULT_SERIALIZER,
        accept_content=settings.CELERY_ACCEPT_CONTENT,
        timezone=settings.CELERY_TIMEZONE,
        enable_utc=settings.CELERY_ENABLE_UTC,
        
        # Worker configuration
        worker_prefetch_multiplier=settings.WORKER_PREFETCH_MULTIPLIER,
        worker_max_tasks_per_child=settings.WORKER_MAX_TASKS_PER_CHILD,
        task_time_limit=settings.WORKER_TASK_TIME_LIMIT,
        task_soft_time_limit=settings.WORKER_TASK_SOFT_TIME_LIMIT,
        
        # Result backend configuration
        result_expires=3600,  # 1 hour
        result_persistent=True,
        
        # Monitoring
        worker_send_task_events=True,
        task_send_sent_event=True,
        
        # Optimization
        task_acks_late=True,
        worker_disable_rate_limits=True,
        task_compression='gzip',
        result_compression='gzip',
    )
    
    # Configurar filas e exchanges
    setup_queues_and_routing(app)
    
    # Setup monitoring
    setup_monitoring(app)
    
    return app


def setup_queues_and_routing(app: Celery):
    """Configura filas especializadas e roteamento"""
    
    # Exchange principal
    default_exchange = Exchange('ocr_platform', type='direct')
    
    # Criar filas baseadas na configuração
    queues = []
    routes = {}
    
    for queue_name, config in settings.QUEUE_CONFIG.items():
        # Criar fila com configurações específicas
        queue = Queue(
            queue_name,
            exchange=default_exchange,
            routing_key=config['routing_key'],
            queue_arguments={
                'x-max-priority': config['priority'],
                'x-message-ttl': 3600000,  # 1 hour TTL
            }
        )
        queues.append(queue)
        
        # Configurar roteamento por padrão de task
        task_pattern = f"app.workers.{config['routing_key']}_worker.*"
        routes[task_pattern] = {
            'queue': queue_name,
            'routing_key': config['routing_key']
        }
    
    # Atualizar configuração do Celery
    app.conf.update(
        task_queues=queues,
        task_default_queue='orchestrator_queue',
        task_default_exchange='ocr_platform',
        task_default_exchange_type='direct',
        task_default_routing_key='orchestrator',
        task_routes=routes
    )
    
    logger.info(f"Configured {len(queues)} specialized queues")


def setup_monitoring(app: Celery):
    """Configura monitoramento de tasks"""
    
    @task_prerun.connect
    def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
        """Executado antes de cada task"""
        logger.info(f"Task {task.name}[{task_id}] started")
        
        # Marcar início da task no Redis para métricas
        try:
            from .redis_client import get_redis_client
            redis_client = get_redis_client()
            redis_client.hset(
                f"task:{task_id}",
                mapping={
                    "status": "started",
                    "started_at": time.time(),
                    "worker": task.name,
                    "queue": getattr(task.request, 'delivery_info', {}).get('routing_key', 'unknown')
                }
            )
            redis_client.expire(f"task:{task_id}", 3600)  # Expire em 1 hora
        except Exception as e:
            logger.warning(f"Failed to log task start: {e}")
    
    @task_postrun.connect
    def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, 
                           retval=None, state=None, **kwds):
        """Executado após cada task"""
        logger.info(f"Task {task.name}[{task_id}] finished with state: {state}")
        
        # Atualizar métricas no Redis
        try:
            from .redis_client import get_redis_client
            redis_client = get_redis_client()
            
            # Recuperar dados de início
            task_data = redis_client.hgetall(f"task:{task_id}")
            started_at = float(task_data.get("started_at", time.time()))
            duration = time.time() - started_at
            
            # Atualizar informações da task
            redis_client.hset(
                f"task:{task_id}",
                mapping={
                    "status": state,
                    "finished_at": time.time(),
                    "duration": duration,
                    "success": state == "SUCCESS"
                }
            )
            
            # Atualizar estatísticas globais
            stats_key = f"stats:{task.name}:daily:{time.strftime('%Y-%m-%d')}"
            redis_client.hincrby(stats_key, "total_tasks", 1)
            redis_client.hincrby(stats_key, f"{state.lower()}_tasks", 1)
            redis_client.hincrbyfloat(stats_key, "total_duration", duration)
            redis_client.expire(stats_key, 86400 * 7)  # Keep for 7 days
            
            # Estatísticas por fila
            queue_name = task_data.get("queue", "unknown")
            queue_stats_key = f"queue_stats:{queue_name}:daily:{time.strftime('%Y-%m-%d')}"
            redis_client.hincrby(queue_stats_key, "total_tasks", 1)
            redis_client.hincrby(queue_stats_key, f"{state.lower()}_tasks", 1)
            redis_client.hincrbyfloat(queue_stats_key, "total_duration", duration)
            redis_client.expire(queue_stats_key, 86400 * 7)
            
        except Exception as e:
            logger.warning(f"Failed to log task completion: {e}")
    
    @worker_ready.connect
    def worker_ready_handler(sender=None, **kwargs):
        """Executado quando worker fica pronto"""
        worker_name = sender.hostname
        logger.info(f"Worker {worker_name} is ready")
        
        try:
            from .redis_client import get_redis_client
            redis_client = get_redis_client()
            redis_client.hset(
                f"worker:{worker_name}",
                mapping={
                    "status": "ready",
                    "started_at": time.time(),
                    "queues": ",".join(getattr(sender, 'consumer', {}).get('queues', [])),
                    "concurrency": getattr(sender, 'concurrency', 1)
                }
            )
            redis_client.expire(f"worker:{worker_name}", 300)  # Refresh every 5 minutes
        except Exception as e:
            logger.warning(f"Failed to register worker: {e}")
    
    @worker_shutting_down.connect
    def worker_shutting_down_handler(sender=None, **kwargs):
        """Executado quando worker está parando"""
        worker_name = sender.hostname
        logger.info(f"Worker {worker_name} is shutting down")
        
        try:
            from .redis_client import get_redis_client
            redis_client = get_redis_client()
            redis_client.hset(f"worker:{worker_name}", "status", "shutting_down")
        except Exception as e:
            logger.warning(f"Failed to update worker status: {e}")


def get_queue_stats() -> Dict[str, Any]:
    """Retorna estatísticas das filas"""
    try:
        from .redis_client import get_redis_client
        redis_client = get_redis_client()
        
        stats = {}
        today = time.strftime('%Y-%m-%d')
        
        for queue_name in settings.QUEUE_CONFIG.keys():
            stats_key = f"queue_stats:{queue_name}:daily:{today}"
            queue_stats = redis_client.hgetall(stats_key)
            
            if queue_stats:
                total_tasks = int(queue_stats.get("total_tasks", 0))
                success_tasks = int(queue_stats.get("success_tasks", 0))
                total_duration = float(queue_stats.get("total_duration", 0))
                
                stats[queue_name] = {
                    "total_tasks": total_tasks,
                    "success_tasks": success_tasks,
                    "failed_tasks": total_tasks - success_tasks,
                    "success_rate": (success_tasks / total_tasks * 100) if total_tasks > 0 else 0,
                    "avg_duration": (total_duration / total_tasks) if total_tasks > 0 else 0,
                    "total_duration": total_duration
                }
            else:
                stats[queue_name] = {
                    "total_tasks": 0,
                    "success_tasks": 0, 
                    "failed_tasks": 0,
                    "success_rate": 0,
                    "avg_duration": 0,
                    "total_duration": 0
                }
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get queue stats: {e}")
        return {}


def get_worker_stats() -> Dict[str, Any]:
    """Retorna estatísticas dos workers"""
    try:
        from .redis_client import get_redis_client
        redis_client = get_redis_client()
        
        # Buscar todos os workers registrados
        worker_keys = redis_client.keys("worker:*")
        workers = {}
        
        for key in worker_keys:
            worker_name = key.decode().replace("worker:", "")
            worker_data = redis_client.hgetall(key)
            
            if worker_data:
                workers[worker_name] = {
                    "status": worker_data.get("status", "unknown"),
                    "started_at": float(worker_data.get("started_at", 0)),
                    "queues": worker_data.get("queues", "").split(","),
                    "concurrency": int(worker_data.get("concurrency", 1)),
                    "uptime": time.time() - float(worker_data.get("started_at", time.time()))
                }
        
        return workers
        
    except Exception as e:
        logger.error(f"Failed to get worker stats: {e}")
        return {}


def cleanup_old_stats():
    """Limpa estatísticas antigas (>7 dias)"""
    try:
        from .redis_client import get_redis_client
        redis_client = get_redis_client()
        
        # Buscar chaves de estatísticas antigas
        patterns = ["stats:*:daily:*", "queue_stats:*:daily:*"]
        
        for pattern in patterns:
            keys = redis_client.keys(pattern)
            for key in keys:
                # Extrair data da chave
                try:
                    date_part = key.decode().split(":")[-1]
                    key_time = time.mktime(time.strptime(date_part, "%Y-%m-%d"))
                    
                    # Se mais de 7 dias, deletar
                    if time.time() - key_time > 86400 * 7:
                        redis_client.delete(key)
                        logger.debug(f"Cleaned up old stats key: {key}")
                        
                except (ValueError, IndexError):
                    # Chave com formato inválido, ignorar
                    continue
                    
    except Exception as e:
        logger.error(f"Failed to cleanup old stats: {e}")


# Criar instância global do Celery
celery_app = create_celery_app()


# Task para limpeza periódica
@celery_app.task(bind=True)
def cleanup_stats_task(self):
    """Task periódica para limpeza de estatísticas"""
    cleanup_old_stats()
    return "Stats cleanup completed"


# Configurar task periódica de limpeza
celery_app.conf.beat_schedule = {
    'cleanup-stats': {
        'task': 'app.core.celery_app.cleanup_stats_task',
        'schedule': 3600.0,  # A cada hora
    },
}


if __name__ == "__main__":
    """Teste da configuração Celery"""
    print("=== Celery Configuration ===")
    print(f"Broker: {celery_app.conf.broker_url}")
    print(f"Backend: {celery_app.conf.result_backend}")
    print(f"Queues: {[q.name for q in celery_app.conf.task_queues]}")
    print(f"Routes: {celery_app.conf.task_routes}")
    
    # Testar conexão
    try:
        inspector = celery_app.control.inspect()
        active_workers = inspector.active()
        print(f"Active workers: {list(active_workers.keys()) if active_workers else 'None'}")
    except Exception as e:
        print(f"Failed to connect: {e}")