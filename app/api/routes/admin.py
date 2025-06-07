#!/usr/bin/env python3
"""
Rotas Administrativas
====================

Endpoints para:
- Monitoramento de workers e filas
- Métricas e estatísticas
- Configuração dinâmica
- Operações administrativas
- Limpeza e manutenção
"""

import time
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import settings, get_queue_config, get_engine_config
from app.core.redis_client import get_redis_client
from app.models.schemas import QueueStatus, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()


def admin_required():
    """Dependency para verificar permissões de admin"""
    # Por simplicidade, não implementaremos autenticação completa aqui
    # Em produção, adicionar verificação de API key ou JWT
    if not settings.DEBUG:
        # Em produção, verificar autenticação
        pass
    return True


@router.get(
    "/stats",
    summary="System statistics",
    description="Estatísticas gerais do sistema",
    dependencies=[Depends(admin_required)]
)
async def get_system_stats():
    """Estatísticas gerais do sistema"""
    
    try:
        redis_client = get_redis_client()
        
        # Estatísticas de hoje
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        stats = {
            "overview": {
                "timestamp": datetime.now().isoformat(),
                "environment": settings.ENVIRONMENT,
                "version": settings.VERSION,
                "uptime_hours": (time.time() - redis_client.get_metric("api_start_time", 0)) / 3600
            },
            "today": {},
            "yesterday": {},
            "totals": {},
            "engines": {},
            "queues": {}
        }
        
        # Estatísticas por engine
        for engine in ["trocr", "surya", "paddleocr", "easyocr", "tesseract", "marker"]:
            engine_stats = {}
            
            # Estatísticas de hoje
            today_key = f"stats:{engine}:daily:{today}"
            today_data = redis_client.client.hgetall(today_key)
            
            if today_data:
                engine_stats["today"] = {
                    "total_tasks": int(today_data.get(b"total_tasks", 0)),
                    "success_tasks": int(today_data.get(b"success_tasks", 0)),
                    "failed_tasks": int(today_data.get(b"failed_tasks", 0)),
                    "total_duration": float(today_data.get(b"total_duration", 0))
                }
                
                if engine_stats["today"]["total_tasks"] > 0:
                    engine_stats["today"]["avg_duration"] = engine_stats["today"]["total_duration"] / engine_stats["today"]["total_tasks"]
                    engine_stats["today"]["success_rate"] = (engine_stats["today"]["success_tasks"] / engine_stats["today"]["total_tasks"]) * 100
                else:
                    engine_stats["today"]["avg_duration"] = 0
                    engine_stats["today"]["success_rate"] = 0
            else:
                engine_stats["today"] = {"total_tasks": 0, "success_tasks": 0, "failed_tasks": 0, "total_duration": 0, "avg_duration": 0, "success_rate": 0}
            
            # Estatísticas de ontem
            yesterday_key = f"stats:{engine}:daily:{yesterday}"
            yesterday_data = redis_client.client.hgetall(yesterday_key)
            
            if yesterday_data:
                engine_stats["yesterday"] = {
                    "total_tasks": int(yesterday_data.get(b"total_tasks", 0)),
                    "success_tasks": int(yesterday_data.get(b"success_tasks", 0)),
                    "failed_tasks": int(yesterday_data.get(b"failed_tasks", 0)),
                    "total_duration": float(yesterday_data.get(b"total_duration", 0))
                }
                
                if engine_stats["yesterday"]["total_tasks"] > 0:
                    engine_stats["yesterday"]["avg_duration"] = engine_stats["yesterday"]["total_duration"] / engine_stats["yesterday"]["total_tasks"]
                    engine_stats["yesterday"]["success_rate"] = (engine_stats["yesterday"]["success_tasks"] / engine_stats["yesterday"]["total_tasks"]) * 100
                else:
                    engine_stats["yesterday"]["avg_duration"] = 0
                    engine_stats["yesterday"]["success_rate"] = 0
            else:
                engine_stats["yesterday"] = {"total_tasks": 0, "success_tasks": 0, "failed_tasks": 0, "total_duration": 0, "avg_duration": 0, "success_rate": 0}
            
            # Métricas em tempo real
            engine_stats["realtime"] = {
                "cache_hits": redis_client.get_metric(f"{engine}_cache_hits") or 0,
                "cache_misses": redis_client.get_metric(f"{engine}_cache_misses") or 0,
                "last_processing_time": redis_client.get_metric(f"{engine}_last_processing_time") or 0,
                "total_processed": redis_client.get_metric(f"{engine}_total_processed") or 0
            }
            
            # Calcular cache hit rate
            total_cache_requests = engine_stats["realtime"]["cache_hits"] + engine_stats["realtime"]["cache_misses"]
            if total_cache_requests > 0:
                engine_stats["realtime"]["cache_hit_rate"] = (engine_stats["realtime"]["cache_hits"] / total_cache_requests) * 100
            else:
                engine_stats["realtime"]["cache_hit_rate"] = 0
            
            stats["engines"][engine] = engine_stats
        
        # Estatísticas das filas
        from app.core.celery_app import get_queue_stats
        queue_stats = get_queue_stats()
        stats["queues"] = queue_stats
        
        # Totais
        stats["today"]["total_tasks"] = sum(engine["today"]["total_tasks"] for engine in stats["engines"].values())
        stats["today"]["success_tasks"] = sum(engine["today"]["success_tasks"] for engine in stats["engines"].values())
        stats["today"]["failed_tasks"] = sum(engine["today"]["failed_tasks"] for engine in stats["engines"].values())
        
        stats["yesterday"]["total_tasks"] = sum(engine["yesterday"]["total_tasks"] for engine in stats["engines"].values())
        stats["yesterday"]["success_tasks"] = sum(engine["yesterday"]["success_tasks"] for engine in stats["engines"].values())
        stats["yesterday"]["failed_tasks"] = sum(engine["yesterday"]["failed_tasks"] for engine in stats["engines"].values())
        
        # Calcular taxas de sucesso totais
        if stats["today"]["total_tasks"] > 0:
            stats["today"]["success_rate"] = (stats["today"]["success_tasks"] / stats["today"]["total_tasks"]) * 100
        else:
            stats["today"]["success_rate"] = 0
            
        if stats["yesterday"]["total_tasks"] > 0:
            stats["yesterday"]["success_rate"] = (stats["yesterday"]["success_tasks"] / stats["yesterday"]["total_tasks"]) * 100
        else:
            stats["yesterday"]["success_rate"] = 0
        
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get system stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system statistics")


@router.get(
    "/workers",
    summary="Worker status",
    description="Status de todos os workers ativos",
    dependencies=[Depends(admin_required)]
)
async def get_worker_status():
    """Status dos workers"""
    
    try:
        from app.core.celery_app import celery_app, get_worker_stats
        
        # Obter workers ativos do Celery
        inspector = celery_app.control.inspect()
        
        active_workers = inspector.active() or {}
        registered_tasks = inspector.registered() or {}
        stats = inspector.stats() or {}
        
        # Obter estatísticas do Redis
        redis_workers = get_worker_stats()
        
        worker_info = {
            "summary": {
                "total_workers": len(active_workers),
                "active_workers": list(active_workers.keys()),
                "total_active_tasks": sum(len(tasks) for tasks in active_workers.values()),
                "timestamp": datetime.now().isoformat()
            },
            "workers": {}
        }
        
        # Combinar informações
        for worker_name in active_workers.keys():
            worker_data = {
                "name": worker_name,
                "status": "active",
                "active_tasks": len(active_workers.get(worker_name, [])),
                "registered_tasks": registered_tasks.get(worker_name, []),
                "stats": stats.get(worker_name, {}),
                "redis_info": redis_workers.get(worker_name, {})
            }
            
            # Extrair informações específicas
            if worker_name in stats:
                worker_stats = stats[worker_name]
                worker_data["pool"] = worker_stats.get("pool", {})
                worker_data["rusage"] = worker_stats.get("rusage", {})
                worker_data["total_tasks"] = worker_stats.get("total", {})
            
            worker_info["workers"][worker_name] = worker_data
        
        # Adicionar workers do Redis que podem não estar no Celery
        for worker_name, redis_data in redis_workers.items():
            if worker_name not in worker_info["workers"]:
                worker_info["workers"][worker_name] = {
                    "name": worker_name,
                    "status": redis_data.get("status", "unknown"),
                    "redis_info": redis_data,
                    "note": "Only in Redis (may be offline)"
                }
        
        return worker_info
        
    except Exception as e:
        logger.error(f"Failed to get worker status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get worker status")


@router.get(
    "/queues",
    summary="Queue status",
    description="Status de todas as filas",
    dependencies=[Depends(admin_required)]
)
async def get_queue_status():
    """Status das filas"""
    
    try:
        from app.core.celery_app import celery_app
        
        # Obter informações das filas do Celery
        inspector = celery_app.control.inspect()
        
        # Informações das filas ativas
        active_queues = inspector.active_queues() or {}
        
        # Estatísticas das filas do Redis
        redis_client = get_redis_client()
        queue_lengths = redis_client.get_all_queue_lengths()
        
        queue_info = {
            "summary": {
                "total_queues": len(settings.QUEUE_CONFIG),
                "active_queues": len(active_queues),
                "timestamp": datetime.now().isoformat()
            },
            "queues": {}
        }
        
        # Processar cada fila configurada
        for queue_name, queue_config in settings.QUEUE_CONFIG.items():
            queue_data = {
                "name": queue_name,
                "config": queue_config,
                "length": queue_lengths.get(queue_name, 0),
                "workers_assigned": [],
                "active": False
            }
            
            # Verificar quais workers estão atribuídos a esta fila
            for worker_name, worker_queues in active_queues.items():
                for queue_info_item in worker_queues:
                    if queue_info_item.get("name") == queue_name:
                        queue_data["workers_assigned"].append(worker_name)
                        queue_data["active"] = True
            
            # Obter estatísticas do Redis
            today = datetime.now().strftime("%Y-%m-%d")
            stats_key = f"queue_stats:{queue_name}:daily:{today}"
            queue_stats = redis_client.client.hgetall(stats_key)
            
            if queue_stats:
                queue_data["today_stats"] = {
                    "total_tasks": int(queue_stats.get(b"total_tasks", 0)),
                    "success_tasks": int(queue_stats.get(b"success_tasks", 0)),
                    "failed_tasks": int(queue_stats.get(b"failed_tasks", 0)),
                    "total_duration": float(queue_stats.get(b"total_duration", 0))
                }
                
                if queue_data["today_stats"]["total_tasks"] > 0:
                    queue_data["today_stats"]["avg_duration"] = queue_data["today_stats"]["total_duration"] / queue_data["today_stats"]["total_tasks"]
                    queue_data["today_stats"]["success_rate"] = (queue_data["today_stats"]["success_tasks"] / queue_data["today_stats"]["total_tasks"]) * 100
                else:
                    queue_data["today_stats"]["avg_duration"] = 0
                    queue_data["today_stats"]["success_rate"] = 0
            else:
                queue_data["today_stats"] = {
                    "total_tasks": 0,
                    "success_tasks": 0,
                    "failed_tasks": 0,
                    "total_duration": 0,
                    "avg_duration": 0,
                    "success_rate": 0
                }
            
            queue_info["queues"][queue_name] = queue_data
        
        return queue_info
        
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get queue status")


@router.get(
    "/metrics",
    summary="System metrics",
    description="Métricas detalhadas do sistema",
    dependencies=[Depends(admin_required)]
)
async def get_system_metrics():
    """Métricas do sistema"""
    
    try:
        redis_client = get_redis_client()
        
        # Métricas da API
        api_metrics = {
            "total_requests": redis_client.get_metric("api_total_requests") or 0,
            "total_errors": redis_client.get_metric("api_errors") or 0,
            "last_response_time": redis_client.get_metric("api_last_response_time") or 0,
            "start_time": redis_client.get_metric("api_start_time") or 0,
            "starts": redis_client.get_metric("api_starts") or 0
        }
        
        if api_metrics["total_requests"] > 0:
            api_metrics["error_rate"] = (api_metrics["total_errors"] / api_metrics["total_requests"]) * 100
        else:
            api_metrics["error_rate"] = 0
        
        # Métricas do Redis
        redis_health = redis_client.health_check()
        
        # Métricas por engine
        engine_metrics = {}
        for engine in ["trocr", "surya", "paddleocr", "easyocr", "tesseract", "marker"]:
            engine_metrics[engine] = {
                "cache_hits": redis_client.get_metric(f"{engine}_cache_hits") or 0,
                "cache_misses": redis_client.get_metric(f"{engine}_cache_misses") or 0,
                "total_processed": redis_client.get_metric(f"{engine}_total_processed") or 0,
                "failures": redis_client.get_metric(f"{engine}_failures") or 0,
                "successes": redis_client.get_metric(f"{engine}_successes") or 0,
                "retries": redis_client.get_metric(f"{engine}_retries") or 0,
                "avg_confidence": redis_client.get_metric(f"{engine}_avg_confidence") or 0,
                "last_processing_time": redis_client.get_metric(f"{engine}_last_processing_time") or 0
            }
            
            # Calcular taxas
            total_cache = engine_metrics[engine]["cache_hits"] + engine_metrics[engine]["cache_misses"]
            if total_cache > 0:
                engine_metrics[engine]["cache_hit_rate"] = (engine_metrics[engine]["cache_hits"] / total_cache) * 100
            else:
                engine_metrics[engine]["cache_hit_rate"] = 0
            
            total_tasks = engine_metrics[engine]["successes"] + engine_metrics[engine]["failures"]
            if total_tasks > 0:
                engine_metrics[engine]["success_rate"] = (engine_metrics[engine]["successes"] / total_tasks) * 100
            else:
                engine_metrics[engine]["success_rate"] = 0
        
        # Throughput (tasks por minuto) para cada engine
        throughput_metrics = {}
        for engine in engine_metrics.keys():
            throughput_key = f"{engine}_throughput_1min"
            try:
                timestamps = redis_client.client.lrange(throughput_key, 0, -1)
                current_time = time.time()
                
                # Contar tasks no último minuto
                recent_tasks = [ts for ts in timestamps if current_time - float(ts) <= 60]
                throughput_metrics[engine] = len(recent_tasks)
                
            except Exception:
                throughput_metrics[engine] = 0
        
        return {
            "timestamp": datetime.now().isoformat(),
            "api": api_metrics,
            "redis": redis_health,
            "engines": engine_metrics,
            "throughput_per_minute": throughput_metrics,
            "system": {
                "environment": settings.ENVIRONMENT,
                "version": settings.VERSION,
                "debug": settings.DEBUG
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get system metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system metrics")


@router.post(
    "/cache/clear",
    summary="Clear cache",
    description="Limpa cache do Redis",
    dependencies=[Depends(admin_required)]
)
async def clear_cache(
    pattern: str = Query("cache:*", description="Padrão de chaves para limpar")
):
    """Limpa cache do Redis"""
    
    try:
        redis_client = get_redis_client()
        
        # Buscar chaves que correspondem ao padrão
        keys = redis_client.client.keys(pattern)
        
        if keys:
            deleted_count = redis_client.client.delete(*keys)
            return {
                "message": f"Cleared {deleted_count} cache entries",
                "pattern": pattern,
                "deleted_count": deleted_count
            }
        else:
            return {
                "message": "No cache entries found to clear",
                "pattern": pattern,
                "deleted_count": 0
            }
            
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cache")


@router.post(
    "/tasks/purge",
    summary="Purge old tasks",
    description="Remove tasks antigas do Redis",
    dependencies=[Depends(admin_required)]
)
async def purge_old_tasks(
    days: int = Query(7, description="Dias para manter", ge=1, le=30)
):
    """Remove tasks antigas"""
    
    try:
        redis_client = get_redis_client()
        
        # Buscar todas as chaves de task
        task_keys = redis_client.client.keys("task:*")
        result_keys = redis_client.client.keys("task_result:*")
        
        cutoff_time = time.time() - (days * 24 * 3600)
        deleted_count = 0
        
        # Verificar tasks
        for key in task_keys:
            try:
                task_data = redis_client.client.hgetall(key)
                if task_data:
                    started_at = float(task_data.get(b"started_at", 0))
                    if started_at < cutoff_time:
                        redis_client.client.delete(key)
                        deleted_count += 1
            except Exception:
                continue
        
        # Verificar resultados
        for key in result_keys:
            try:
                # Para chaves de resultado, usar TTL se disponível
                ttl = redis_client.client.ttl(key)
                if ttl == -1:  # Chave sem TTL
                    # Verificar idade baseada no nome se possível
                    redis_client.client.expire(key, 86400)  # Definir TTL de 1 dia
            except Exception:
                continue
        
        return {
            "message": f"Purged {deleted_count} old tasks",
            "cutoff_days": days,
            "deleted_count": deleted_count
        }
        
    except Exception as e:
        logger.error(f"Failed to purge old tasks: {e}")
        raise HTTPException(status_code=500, detail="Failed to purge old tasks")


@router.post(
    "/workers/restart",
    summary="Restart workers",
    description="Reinicia workers específicos",
    dependencies=[Depends(admin_required)]
)
async def restart_workers(
    worker_names: Optional[List[str]] = Query(None, description="Nomes dos workers para reiniciar"),
    queue_name: Optional[str] = Query(None, description="Reiniciar workers de uma fila específica")
):
    """Reinicia workers"""
    
    try:
        from app.core.celery_app import celery_app
        
        if worker_names:
            # Reiniciar workers específicos
            for worker_name in worker_names:
                celery_app.control.broadcast('pool_restart', destination=[worker_name])
        
        elif queue_name:
            # Reiniciar workers de uma fila específica
            inspector = celery_app.control.inspect()
            active_queues = inspector.active_queues() or {}
            
            workers_to_restart = []
            for worker_name, queues in active_queues.items():
                for queue_info in queues:
                    if queue_info.get("name") == queue_name:
                        workers_to_restart.append(worker_name)
            
            if workers_to_restart:
                celery_app.control.broadcast('pool_restart', destination=workers_to_restart)
                return {
                    "message": f"Restarted workers for queue {queue_name}",
                    "workers_restarted": workers_to_restart
                }
            else:
                return {
                    "message": f"No workers found for queue {queue_name}",
                    "workers_restarted": []
                }
        
        else:
            # Reiniciar todos os workers
            celery_app.control.broadcast('pool_restart')
            return {
                "message": "Restart signal sent to all workers"
            }
        
        return {
            "message": "Restart signal sent",
            "workers": worker_names or ["all"]
        }
        
    except Exception as e:
        logger.error(f"Failed to restart workers: {e}")
        raise HTTPException(status_code=500, detail="Failed to restart workers")


@router.get(
    "/config",
    summary="Get configuration",
    description="Configuração atual do sistema",
    dependencies=[Depends(admin_required)]
)
async def get_configuration():
    """Configuração do sistema"""
    
    try:
        config = {
            "api": {
                "host": settings.API_HOST,
                "port": settings.API_PORT,
                "workers": settings.API_WORKERS,
                "prefix": settings.API_PREFIX,
                "debug": settings.DEBUG,
                "environment": settings.ENVIRONMENT
            },
            "redis": {
                "host": settings.REDIS_HOST,
                "port": settings.REDIS_PORT,
                "db": settings.REDIS_DB,
                "url": settings.REDIS_URL
            },
            "celery": {
                "broker_url": settings.CELERY_BROKER_URL,
                "result_backend": settings.CELERY_RESULT_BACKEND,
                "task_serializer": settings.CELERY_TASK_SERIALIZER
            },
            "queues": settings.QUEUE_CONFIG,
            "engines": settings.ENGINES_CONFIG,
            "storage": {
                "upload_dir": settings.UPLOAD_DIR,
                "result_dir": settings.RESULT_DIR,
                "temp_dir": settings.TEMP_DIR,
                "max_file_size_mb": settings.MAX_FILE_SIZE / (1024 * 1024)
            },
            "monitoring": {
                "flower_enabled": settings.FLOWER_ENABLED,
                "prometheus_enabled": settings.PROMETHEUS_ENABLED,
                "log_level": settings.LOG_LEVEL
            }
        }
        
        return config
        
    except Exception as e:
        logger.error(f"Failed to get configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to get configuration")


@router.get(
    "/logs/stream",
    summary="Stream logs",
    description="Stream de logs em tempo real",
    dependencies=[Depends(admin_required)]
)
async def stream_logs(
    level: str = Query("INFO", description="Nível de log"),
    lines: int = Query(100, description="Número de linhas", ge=1, le=1000)
):
    """Stream de logs"""
    
    try:
        # Em uma implementação real, isso se conectaria aos logs
        # Por simplicidade, retornamos logs do Redis
        
        redis_client = get_redis_client()
        
        def generate_logs():
            # Gerar logs fictícios para demonstração
            import time
            
            for i in range(lines):
                log_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "level": level,
                    "message": f"Log entry {i + 1}",
                    "logger": "ocr_platform"
                }
                
                yield f"data: {json.dumps(log_entry)}\n\n"
                time.sleep(0.1)  # Simular delay
        
        return StreamingResponse(
            generate_logs(),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )
        
    except Exception as e:
        logger.error(f"Failed to stream logs: {e}")
        raise HTTPException(status_code=500, detail="Failed to stream logs")


@router.get(
    "/export/stats",
    summary="Export statistics", 
    description="Exporta estatísticas em formato JSON",
    dependencies=[Depends(admin_required)]
)
async def export_statistics(
    days: int = Query(7, description="Número de dias", ge=1, le=30),
    format: str = Query("json", description="Formato de exportação")
):
    """Exporta estatísticas"""
    
    try:
        redis_client = get_redis_client()
        
        # Coletar dados dos últimos N dias
        export_data = {
            "export_info": {
                "timestamp": datetime.now().isoformat(),
                "days": days,
                "format": format,
                "version": settings.VERSION
            },
            "daily_stats": {},
            "engine_stats": {},
            "queue_stats": {}
        }
        
        # Coletar dados diários
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            day_stats = {}
            
            # Stats por engine
            for engine in ["trocr", "surya", "paddleocr", "easyocr", "tesseract", "marker"]:
                stats_key = f"stats:{engine}:daily:{date}"
                engine_data = redis_client.client.hgetall(stats_key)
                
                if engine_data:
                    day_stats[engine] = {
                        "total_tasks": int(engine_data.get(b"total_tasks", 0)),
                        "success_tasks": int(engine_data.get(b"success_tasks", 0)),
                        "failed_tasks": int(engine_data.get(b"failed_tasks", 0)),
                        "total_duration": float(engine_data.get(b"total_duration", 0))
                    }
            
            if day_stats:
                export_data["daily_stats"][date] = day_stats
        
        # Retornar como download
        if format == "json":
            return JSONResponse(
                content=export_data,
                headers={"Content-Disposition": f"attachment; filename=ocr_stats_{days}days.json"}
            )
        else:
            raise HTTPException(status_code=400, detail="Unsupported format")
            
    except Exception as e:
        logger.error(f"Failed to export statistics: {e}")
        raise HTTPException(status_code=500, detail="Failed to export statistics")