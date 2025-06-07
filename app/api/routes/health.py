#!/usr/bin/env python3
"""
Rotas de Health Check
====================

Endpoints para:
- Health check geral do sistema
- Status de componentes individuais
- Métricas de performance
- Diagnósticos
"""

import time
import logging
from typing import Dict, Any, List
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings, get_available_engines, get_queue_config
from app.core.redis_client import get_redis_client
from app.models.schemas import HealthCheckResponse, SystemHealth, QueueStatus

logger = logging.getLogger(__name__)
router = APIRouter()

# Tempo de início da aplicação (será definido no startup)
app_start_time = time.time()


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Basic health check",
    description="Health check básico para load balancers e monitoramento"
)
async def health_check():
    """Health check básico"""
    
    checks = {}
    overall_status = "healthy"
    
    try:
        # Verificar Redis
        redis_client = get_redis_client()
        redis_ping = redis_client.ping()
        checks["redis"] = redis_ping
        
        if not redis_ping:
            overall_status = "unhealthy"
        
        # Verificar Celery
        try:
            from app.core.celery_app import celery_app
            inspector = celery_app.control.inspect()
            active_workers = inspector.active()
            checks["celery"] = active_workers is not None
            
            if active_workers is None:
                overall_status = "degraded"
                
        except Exception as e:
            logger.warning(f"Celery check failed: {e}")
            checks["celery"] = False
            overall_status = "degraded"
        
        # Verificar engines
        available_engines = get_available_engines()
        checks["engines_available"] = len(available_engines) > 0
        
        if len(available_engines) == 0:
            overall_status = "degraded"
        
        # Verificar sistema de arquivos
        try:
            import tempfile
            with tempfile.NamedTemporaryFile() as tmp:
                tmp.write(b"health_check")
                checks["filesystem"] = True
        except Exception:
            checks["filesystem"] = False
            overall_status = "unhealthy"
        
        uptime = time.time() - app_start_time
        
        return HealthCheckResponse(
            status=overall_status,
            version=settings.VERSION,
            uptime=uptime,
            checks=checks,
            details={
                "environment": settings.ENVIRONMENT,
                "debug": settings.DEBUG,
                "available_engines": available_engines
            }
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthCheckResponse(
            status="unhealthy",
            version=settings.VERSION,
            uptime=time.time() - app_start_time,
            checks={"error": False},
            details={"error": str(e)}
        )


@router.get(
    "/health/detailed",
    response_model=SystemHealth,
    summary="Detailed system health",
    description="Health check detalhado com métricas e status de componentes"
)
async def detailed_health_check():
    """Health check detalhado"""
    
    try:
        redis_client = get_redis_client()
        
        # Status básico
        health = SystemHealth(
            status="healthy",
            available_engines=get_available_engines()
        )
        
        # Verificar API
        health.api_status = "healthy"
        
        # Verificar Redis
        redis_health = redis_client.health_check()
        health.redis_status = redis_health.get("status", "unknown")
        
        if health.redis_status != "healthy":
            health.status = "degraded"
        
        # Verificar Celery e workers
        try:
            from app.core.celery_app import celery_app, get_worker_stats, get_queue_stats
            
            inspector = celery_app.control.inspect()
            active_workers = inspector.active()
            
            if active_workers:
                health.celery_status = "healthy"
                
                # Obter estatísticas dos workers
                worker_stats = get_worker_stats()
                
                # Verificar health de cada engine
                for engine in health.available_engines:
                    try:
                        # Tentar executar health check do engine
                        from app.workers import (
                            trocr_worker, surya_worker, paddleocr_worker,
                            easyocr_worker, tesseract_worker, marker_worker
                        )
                        
                        engine_map = {
                            "trocr": trocr_worker.trocr_health_check,
                            "surya": surya_worker.surya_health_check,
                            "paddleocr": paddleocr_worker.paddleocr_health_check,
                            "easyocr": easyocr_worker.easyocr_health_check,
                            "tesseract": tesseract_worker.tesseract_health_check,
                            "marker": marker_worker.marker_health_check
                        }
                        
                        if engine in engine_map:
                            # Tentar health check com timeout curto
                            result = engine_map[engine].apply_async().get(timeout=10)
                            health.engine_health[engine] = result.get("status", "unknown")
                        else:
                            health.engine_health[engine] = "unknown"
                            
                    except Exception as e:
                        logger.warning(f"Engine {engine} health check failed: {e}")
                        health.engine_health[engine] = "unhealthy"
                
                # Obter estatísticas das filas
                queue_stats = get_queue_stats()
                for queue_name, stats in queue_stats.items():
                    queue_status = QueueStatus(
                        queue_name=queue_name,
                        pending_tasks=0,  # Seria obtido do Celery/Redis
                        active_tasks=stats.get("success_tasks", 0),
                        completed_tasks=stats.get("success_tasks", 0),
                        failed_tasks=stats.get("failed_tasks", 0),
                        avg_processing_time=stats.get("avg_duration", 0),
                        throughput=0,  # Calculado baseado em timestamps
                        active_workers=len([w for w in worker_stats.values() if queue_name in w.get("queues", [])]),
                        max_workers=get_queue_config(queue_name).get("max_workers", 1)
                    )
                    health.queue_status.append(queue_status)
            
            else:
                health.celery_status = "unhealthy"
                health.status = "degraded"
                
        except Exception as e:
            logger.warning(f"Celery health check failed: {e}")
            health.celery_status = "unhealthy"
            health.status = "degraded"
        
        # Métricas de performance
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Total de tasks hoje
            total_tasks = 0
            error_count = 0
            
            for queue_name in settings.QUEUE_CONFIG.keys():
                stats_key = f"queue_stats:{queue_name}:daily:{today}"
                queue_data = redis_client.client.hgetall(stats_key)
                
                if queue_data:
                    total_tasks += int(queue_data.get(b"total_tasks", 0))
                    failed_tasks = int(queue_data.get(b"failed_tasks", 0))
                    error_count += failed_tasks
            
            health.total_tasks_today = total_tasks
            health.error_rate = (error_count / max(total_tasks, 1)) * 100
            
            # Tempo médio de resposta
            last_response_time = redis_client.get_metric("api_last_response_time")
            health.avg_response_time = last_response_time or 0.0
            
        except Exception as e:
            logger.warning(f"Performance metrics failed: {e}")
        
        # Determinar status final
        unhealthy_engines = [e for e, s in health.engine_health.items() if s == "unhealthy"]
        if len(unhealthy_engines) > len(health.available_engines) / 2:
            health.status = "degraded"
        
        if health.redis_status == "unhealthy" or health.celery_status == "unhealthy":
            health.status = "unhealthy"
        
        return health
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return SystemHealth(
            status="unhealthy",
            error_rate=100.0
        )


@router.get(
    "/health/redis",
    summary="Redis health check",
    description="Health check específico do Redis"
)
async def redis_health_check():
    """Health check do Redis"""
    
    try:
        redis_client = get_redis_client()
        health_data = redis_client.health_check()
        
        return JSONResponse(content=health_data)
        
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        raise HTTPException(status_code=503, detail="Redis unavailable")


@router.get(
    "/health/celery",
    summary="Celery health check", 
    description="Health check específico do Celery"
)
async def celery_health_check():
    """Health check do Celery"""
    
    try:
        from app.core.celery_app import celery_app
        
        # Verificar broker
        inspector = celery_app.control.inspect()
        
        # Obter workers ativos
        active_workers = inspector.active()
        registered_tasks = inspector.registered()
        stats = inspector.stats()
        
        if active_workers is None:
            raise HTTPException(status_code=503, detail="No Celery workers available")
        
        return {
            "status": "healthy",
            "broker_url": celery_app.conf.broker_url,
            "result_backend": celery_app.conf.result_backend,
            "active_workers": list(active_workers.keys()),
            "worker_count": len(active_workers),
            "registered_tasks": registered_tasks,
            "worker_stats": stats
        }
        
    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        raise HTTPException(status_code=503, detail="Celery unavailable")


@router.get(
    "/health/engines",
    summary="Engines health check",
    description="Health check de todos os engines OCR"
)
async def engines_health_check():
    """Health check dos engines OCR"""
    
    try:
        engine_status = {}
        overall_healthy = True
        
        available_engines = get_available_engines()
        
        for engine in available_engines:
            try:
                # Importar e executar health check específico
                if engine == "trocr":
                    from app.workers.trocr_worker import trocr_health_check
                    result = trocr_health_check.apply_async().get(timeout=15)
                elif engine == "surya":
                    from app.workers.surya_worker import surya_health_check
                    result = surya_health_check.apply_async().get(timeout=15)
                elif engine == "paddleocr":
                    from app.workers.paddleocr_worker import paddleocr_health_check
                    result = surya_health_check.apply_async().get(timeout=10)
                elif engine == "easyocr":
                    from app.workers.easyocr_worker import easyocr_health_check
                    result = easyocr_health_check.apply_async().get(timeout=10)
                elif engine == "tesseract":
                    from app.workers.tesseract_worker import tesseract_health_check
                    result = tesseract_health_check.apply_async().get(timeout=5)
                elif engine == "marker":
                    from app.workers.marker_worker import marker_health_check
                    result = marker_health_check.apply_async().get(timeout=15)
                else:
                    result = {"status": "unknown", "engine": engine}
                
                engine_status[engine] = result
                
                if result.get("status") != "healthy":
                    overall_healthy = False
                    
            except Exception as e:
                logger.warning(f"Engine {engine} health check failed: {e}")
                engine_status[engine] = {
                    "status": "unhealthy",
                    "error": str(e),
                    "engine": engine
                }
                overall_healthy = False
        
        return {
            "status": "healthy" if overall_healthy else "degraded",
            "engines": engine_status,
            "available_engines": available_engines,
            "healthy_engines": [e for e, s in engine_status.items() if s.get("status") == "healthy"],
            "unhealthy_engines": [e for e, s in engine_status.items() if s.get("status") != "healthy"]
        }
        
    except Exception as e:
        logger.error(f"Engines health check failed: {e}")
        raise HTTPException(status_code=503, detail="Engines health check failed")


@router.get(
    "/health/system",
    summary="System resources check",
    description="Health check dos recursos do sistema"
)
async def system_health_check():
    """Health check dos recursos do sistema"""
    
    try:
        import psutil
        import shutil
        
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # Memória
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_available_gb = memory.available / (1024**3)
        
        # Disco
        disk_usage = shutil.disk_usage(settings.TEMP_DIR)
        disk_free_gb = disk_usage.free / (1024**3)
        disk_total_gb = disk_usage.total / (1024**3)
        disk_percent = ((disk_usage.total - disk_usage.free) / disk_usage.total) * 100
        
        # GPU (se disponível)
        gpu_info = {}
        try:
            import torch
            if torch.cuda.is_available():
                gpu_count = torch.cuda.device_count()
                gpu_info["available"] = True
                gpu_info["device_count"] = gpu_count
                gpu_info["devices"] = []
                
                for i in range(gpu_count):
                    props = torch.cuda.get_device_properties(i)
                    memory_allocated = torch.cuda.memory_allocated(i) / (1024**3)
                    memory_total = props.total_memory / (1024**3)
                    
                    gpu_info["devices"].append({
                        "id": i,
                        "name": props.name,
                        "memory_total_gb": memory_total,
                        "memory_allocated_gb": memory_allocated,
                        "memory_free_gb": memory_total - memory_allocated,
                        "memory_percent": (memory_allocated / memory_total) * 100
                    })
            else:
                gpu_info["available"] = False
        except ImportError:
            gpu_info["available"] = False
            gpu_info["error"] = "PyTorch not available"
        
        # Determinar status
        status = "healthy"
        warnings = []
        
        if cpu_percent > 90:
            status = "degraded"
            warnings.append("High CPU usage")
        
        if memory_percent > 90:
            status = "degraded"
            warnings.append("High memory usage")
        
        if disk_percent > 90:
            status = "degraded"
            warnings.append("Low disk space")
        
        if memory_available_gb < 1:
            status = "unhealthy"
            warnings.append("Critical memory shortage")
        
        if disk_free_gb < 1:
            status = "unhealthy"
            warnings.append("Critical disk space shortage")
        
        return {
            "status": status,
            "warnings": warnings,
            "cpu": {
                "usage_percent": cpu_percent,
                "core_count": cpu_count
            },
            "memory": {
                "usage_percent": memory_percent,
                "available_gb": round(memory_available_gb, 2),
                "total_gb": round(memory.total / (1024**3), 2)
            },
            "disk": {
                "usage_percent": round(disk_percent, 2),
                "free_gb": round(disk_free_gb, 2),
                "total_gb": round(disk_total_gb, 2)
            },
            "gpu": gpu_info
        }
        
    except ImportError:
        return {
            "status": "degraded",
            "error": "psutil not available for system monitoring"
        }
    except Exception as e:
        logger.error(f"System health check failed: {e}")
        raise HTTPException(status_code=503, detail="System health check failed")


@router.get(
    "/ping",
    summary="Simple ping",
    description="Ping simples para verificar se a API está respondendo"
)
async def ping():
    """Ping simples"""
    return {
        "message": "pong",
        "timestamp": datetime.now().isoformat(),
        "version": settings.VERSION
    }


@router.get(
    "/readiness",
    summary="Readiness probe",
    description="Readiness probe para Kubernetes"
)
async def readiness_probe():
    """Readiness probe para Kubernetes"""
    
    try:
        # Verificar componentes críticos
        redis_client = get_redis_client()
        
        if not redis_client.ping():
            raise HTTPException(status_code=503, detail="Redis not ready")
        
        # Verificar se há pelo menos um worker ativo
        from app.core.celery_app import celery_app
        inspector = celery_app.control.inspect()
        active_workers = inspector.active()
        
        if not active_workers:
            raise HTTPException(status_code=503, detail="No workers ready")
        
        return {"status": "ready"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")


@router.get(
    "/liveness", 
    summary="Liveness probe",
    description="Liveness probe para Kubernetes"
)
async def liveness_probe():
    """Liveness probe para Kubernetes"""
    
    try:
        # Verificar se a aplicação está funcionando
        # Teste simples de funcionalidade básica
        
        import tempfile
        import os
        
        # Teste de I/O
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"liveness_test")
            tmp_path = tmp.name
        
        # Verificar se pode ler
        with open(tmp_path, 'rb') as f:
            content = f.read()
        
        # Limpar
        os.unlink(tmp_path)
        
        if content != b"liveness_test":
            raise Exception("I/O test failed")
        
        return {"status": "alive"}
        
    except Exception as e:
        logger.error(f"Liveness probe failed: {e}")
        raise HTTPException(status_code=503, detail="Service not alive")