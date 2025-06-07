#!/usr/bin/env python3
"""
Inicialização do Core
====================

Módulo core da OCR Platform que fornece:
- Configurações centralizadas
- Cliente Redis
- Aplicação Celery  
- Banco de dados (opcional)
- Utilitários e helpers
"""

import logging
import time
from typing import Dict, Any, Optional

# Importar componentes principais do core
from .config import (
    settings,
    worker_settings, 
    redis_settings,
    get_queue_config,
    get_engine_config,
    is_engine_enabled,
    get_available_engines,
    get_gpu_engines,
    get_cpu_engines,
    create_directories,
    validate_gpu_memory
)

from .redis_client import (
    RedisClient,
    get_redis_client,
    redis_lock
)

from .celery_app import (
    celery_app,
    get_queue_stats,
    get_worker_stats,
    cleanup_old_stats
)

# Importação condicional do banco de dados
try:
    from .database import (
        DATABASE_ENABLED,
        init_database,
        get_database_session,
        save_task_record,
        update_task_status,
        get_task_history,
        save_processing_metrics,
        get_performance_stats,
        log_system_event,
        cleanup_old_records,
        get_database_stats
    )
except ImportError:
    DATABASE_ENABLED = False
    init_database = None
    get_database_session = None

logger = logging.getLogger(__name__)

# Versão do core
__version__ = "2.0.0"

# Exportar tudo
__all__ = [
    # Configurações
    'settings',
    'worker_settings', 
    'redis_settings',
    'get_queue_config',
    'get_engine_config', 
    'is_engine_enabled',
    'get_available_engines',
    'get_gpu_engines',
    'get_cpu_engines',
    'create_directories',
    'validate_gpu_memory',
    
    # Redis
    'RedisClient',
    'get_redis_client',
    'redis_lock',
    
    # Celery
    'celery_app',
    'get_queue_stats',
    'get_worker_stats',
    'cleanup_old_stats',
    
    # Database (se habilitado)
    'DATABASE_ENABLED',
    'init_database',
    'get_database_session',
    'save_task_record',
    'update_task_status', 
    'get_task_history',
    'save_processing_metrics',
    'get_performance_stats',
    'log_system_event',
    'cleanup_old_records',
    'get_database_stats',
    
    # Utilitários
    'initialize_core',
    'get_core_health',
    'get_core_stats',
    'shutdown_core'
]


def initialize_core() -> Dict[str, bool]:
    """
    Inicializa todos os componentes do core
    
    Returns:
        Dict com status de inicialização de cada componente
    """
    initialization_status = {}
    
    logger.info(f"🚀 Initializing OCR Platform Core v{__version__}")
    
    # 1. Configurações
    try:
        # Criar diretórios necessários
        create_directories()
        initialization_status['directories'] = True
        logger.info("✅ Directories created")
    except Exception as e:
        logger.error(f"❌ Failed to create directories: {e}")
        initialization_status['directories'] = False
    
    # 2. Redis
    try:
        redis_client = get_redis_client()
        if redis_client.ping():
            initialization_status['redis'] = True
            logger.info("✅ Redis connection established")
        else:
            initialization_status['redis'] = False
            logger.error("❌ Redis connection failed")
    except Exception as e:
        logger.error(f"❌ Redis initialization failed: {e}")
        initialization_status['redis'] = False
    
    # 3. Celery
    try:
        # Verificar se Celery está funcional
        inspector = celery_app.control.inspect()
        # Tentar obter workers ativos (pode retornar None se nenhum worker ativo)
        active_workers = inspector.active()
        initialization_status['celery'] = True
        logger.info("✅ Celery configured")
        
        worker_count = len(active_workers) if active_workers else 0
        if worker_count > 0:
            logger.info(f"✅ Found {worker_count} active Celery workers")
        else:
            logger.warning("⚠️  No active Celery workers found")
            
    except Exception as e:
        logger.error(f"❌ Celery initialization failed: {e}")
        initialization_status['celery'] = False
    
    # 4. Banco de dados (opcional)
    if DATABASE_ENABLED:
        try:
            if init_database:
                db_success = init_database()
                initialization_status['database'] = db_success
                if db_success:
                    logger.info("✅ Database initialized")
                else:
                    logger.error("❌ Database initialization failed")
            else:
                initialization_status['database'] = False
                logger.error("❌ Database functions not available")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            initialization_status['database'] = False
    else:
        initialization_status['database'] = None  # Disabled
        logger.info("ℹ️  Database disabled")
    
    # 5. Validação de GPU (se necessário)
    try:
        gpu_status = validate_gpu_memory()
        gpu_engines = get_gpu_engines()
        
        if gpu_engines:
            gpu_available = any(gpu_status.values())
            initialization_status['gpu'] = gpu_available
            
            if gpu_available:
                available_gpu_engines = [engine for engine, status in gpu_status.items() if status]
                logger.info(f"✅ GPU available for engines: {available_gpu_engines}")
            else:
                logger.warning("⚠️  GPU not available or insufficient memory for GPU engines")
        else:
            initialization_status['gpu'] = None  # No GPU engines configured
            logger.info("ℹ️  No GPU engines configured")
            
    except Exception as e:
        logger.warning(f"⚠️  GPU validation failed: {e}")
        initialization_status['gpu'] = False
    
    # 6. Validação de engines
    try:
        available_engines = get_available_engines()
        if available_engines:
            initialization_status['engines'] = True
            logger.info(f"✅ Available engines: {available_engines}")
        else:
            initialization_status['engines'] = False
            logger.error("❌ No engines available")
    except Exception as e:
        logger.error(f"❌ Engine validation failed: {e}")
        initialization_status['engines'] = False
    
    # Status final
    successful_components = sum(1 for status in initialization_status.values() if status is True)
    total_components = sum(1 for status in initialization_status.values() if status is not None)
    
    if successful_components == total_components:
        logger.info(f"🎉 Core initialization successful ({successful_components}/{total_components} components)")
    else:
        logger.warning(f"⚠️  Partial core initialization ({successful_components}/{total_components} components)")
        
        # Log dos componentes que falharam
        failed_components = [name for name, status in initialization_status.items() if status is False]
        if failed_components:
            logger.error(f"Failed components: {', '.join(failed_components)}")
    
    return initialization_status


def get_core_health() -> Dict[str, Any]:
    """
    Verifica saúde de todos os componentes do core
    
    Returns:
        Dict com status de saúde
    """
    health_status = {
        "timestamp": time.time(),
        "version": __version__,
        "overall_status": "healthy",
        "components": {}
    }
    
    # 1. Redis
    try:
        redis_client = get_redis_client()
        redis_health = redis_client.health_check()
        health_status["components"]["redis"] = {
            "status": redis_health.get("status", "unknown"),
            "ping_time_ms": redis_health.get("ping_time_ms", 0),
            "memory_usage": redis_health.get("memory", {}).get("used_memory_human", "unknown")
        }
        
        if redis_health.get("status") != "healthy":
            health_status["overall_status"] = "degraded"
            
    except Exception as e:
        health_status["components"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["overall_status"] = "unhealthy"
    
    # 2. Celery
    try:
        inspector = celery_app.control.inspect()
        active_workers = inspector.active()
        
        if active_workers:
            worker_count = len(active_workers)
            health_status["components"]["celery"] = {
                "status": "healthy",
                "active_workers": worker_count,
                "workers": list(active_workers.keys())
            }
        else:
            health_status["components"]["celery"] = {
                "status": "degraded",
                "active_workers": 0,
                "message": "No active workers"
            }
            if health_status["overall_status"] == "healthy":
                health_status["overall_status"] = "degraded"
                
    except Exception as e:
        health_status["components"]["celery"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["overall_status"] = "unhealthy"
    
    # 3. Database (se habilitado)
    if DATABASE_ENABLED:
        try:
            db_stats = get_database_stats()
            if "error" in db_stats:
                health_status["components"]["database"] = {
                    "status": "unhealthy",
                    "error": db_stats["error"]
                }
                health_status["overall_status"] = "degraded"
            else:
                health_status["components"]["database"] = {
                    "status": "healthy",
                    "total_tasks": db_stats.get("table_counts", {}).get("tasks", 0),
                    "success_rate": db_stats.get("task_stats", {}).get("success_rate", 0)
                }
        except Exception as e:
            health_status["components"]["database"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["overall_status"] = "degraded"
    else:
        health_status["components"]["database"] = {
            "status": "disabled"
        }
    
    # 4. Engines
    try:
        available_engines = get_available_engines()
        gpu_engines = get_gpu_engines()
        
        health_status["components"]["engines"] = {
            "status": "healthy" if available_engines else "unhealthy",
            "available_engines": available_engines,
            "gpu_engines": gpu_engines,
            "total_engines": len(available_engines)
        }
        
        if not available_engines:
            health_status["overall_status"] = "unhealthy"
            
    except Exception as e:
        health_status["components"]["engines"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["overall_status"] = "unhealthy"
    
    # 5. File system
    try:
        import shutil
        
        # Verificar espaço em disco
        disk_usage = shutil.disk_usage(settings.TEMP_DIR)
        free_gb = disk_usage.free / (1024**3)
        total_gb = disk_usage.total / (1024**3)
        usage_percent = ((disk_usage.total - disk_usage.free) / disk_usage.total) * 100
        
        if usage_percent > 95:
            fs_status = "unhealthy"
            health_status["overall_status"] = "unhealthy"
        elif usage_percent > 85:
            fs_status = "degraded"
            if health_status["overall_status"] == "healthy":
                health_status["overall_status"] = "degraded"
        else:
            fs_status = "healthy"
        
        health_status["components"]["filesystem"] = {
            "status": fs_status,
            "free_gb": round(free_gb, 2),
            "total_gb": round(total_gb, 2),
            "usage_percent": round(usage_percent, 2)
        }
        
    except Exception as e:
        health_status["components"]["filesystem"] = {
            "status": "unknown",
            "error": str(e)
        }
    
    return health_status


def get_core_stats() -> Dict[str, Any]:
    """
    Coleta estatísticas de todos os componentes do core
    
    Returns:
        Dict com estatísticas consolidadas
    """
    stats = {
        "timestamp": time.time(),
        "version": __version__,
        "environment": settings.ENVIRONMENT,
        "components": {}
    }
    
    # 1. Configurações
    stats["components"]["config"] = {
        "project_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "debug": settings.DEBUG,
        "api_workers": settings.API_WORKERS,
        "available_engines": len(get_available_engines()),
        "queue_count": len(settings.QUEUE_CONFIG)
    }
    
    # 2. Redis
    try:
        redis_client = get_redis_client()
        redis_health = redis_client.health_check()
        stats["components"]["redis"] = {
            "status": redis_health.get("status", "unknown"),
            "memory_usage": redis_health.get("memory", {}),
            "connections": redis_health.get("connections", {}),
            "commands_processed": redis_health.get("stats", {}).get("total_commands_processed", 0)
        }
    except Exception as e:
        stats["components"]["redis"] = {"error": str(e)}
    
    # 3. Celery
    try:
        queue_stats = get_queue_stats()
        worker_stats = get_worker_stats()
        
        stats["components"]["celery"] = {
            "queue_stats": queue_stats,
            "worker_count": len(worker_stats),
            "worker_stats": worker_stats
        }
    except Exception as e:
        stats["components"]["celery"] = {"error": str(e)}
    
    # 4. Database
    if DATABASE_ENABLED:
        try:
            db_stats = get_database_stats()
            stats["components"]["database"] = db_stats
        except Exception as e:
            stats["components"]["database"] = {"error": str(e)}
    else:
        stats["components"]["database"] = {"enabled": False}
    
    # 5. GPU
    try:
        gpu_status = validate_gpu_memory()
        stats["components"]["gpu"] = {
            "engines": gpu_status,
            "available": any(gpu_status.values()),
            "gpu_engines": get_gpu_engines()
        }
    except Exception as e:
        stats["components"]["gpu"] = {"error": str(e)}
    
    return stats


def shutdown_core() -> Dict[str, bool]:
    """
    Executa shutdown graceful de todos os componentes
    
    Returns:
        Dict com status de shutdown de cada componente
    """
    shutdown_status = {}
    
    logger.info("🛑 Shutting down OCR Platform Core...")
    
    # 1. Parar workers Celery
    try:
        celery_app.control.shutdown()
        shutdown_status['celery_workers'] = True
        logger.info("✅ Celery workers shutdown")
    except Exception as e:
        logger.warning(f"⚠️  Celery workers shutdown failed: {e}")
        shutdown_status['celery_workers'] = False
    
    # 2. Fechar conexões Redis
    try:
        redis_client = get_redis_client()
        redis_client.close()
        shutdown_status['redis'] = True
        logger.info("✅ Redis connections closed")
    except Exception as e:
        logger.warning(f"⚠️  Redis shutdown failed: {e}")
        shutdown_status['redis'] = False
    
    # 3. Limpeza de arquivos temporários
    try:
        import shutil
        import tempfile
        
        # Limpar diretório temporário do sistema
        temp_dir = settings.TEMP_DIR
        if temp_dir.exists():
            # Remover apenas arquivos criados pela aplicação
            for file_path in temp_dir.glob("*"):
                if file_path.is_file() and file_path.stat().st_size < 100 * 1024 * 1024:  # < 100MB
                    try:
                        file_path.unlink()
                    except Exception:
                        pass
        
        shutdown_status['cleanup'] = True
        logger.info("✅ Temporary files cleaned")
    except Exception as e:
        logger.warning(f"⚠️  Cleanup failed: {e}")
        shutdown_status['cleanup'] = False
    
    # 4. Log de estatísticas finais
    try:
        if DATABASE_ENABLED and log_system_event:
            log_system_event(
                "system_shutdown",
                "core",
                f"OCR Platform Core v{__version__} shutdown completed",
                "info",
                shutdown_status=shutdown_status
            )
        shutdown_status['final_log'] = True
    except Exception as e:
        logger.warning(f"⚠️  Final logging failed: {e}")
        shutdown_status['final_log'] = False
    
    successful_shutdowns = sum(shutdown_status.values())
    total_shutdowns = len(shutdown_status)
    
    logger.info(f"🏁 Core shutdown completed ({successful_shutdowns}/{total_shutdowns} components)")
    
    return shutdown_status


# Utilitários adicionais
def get_system_info() -> Dict[str, Any]:
    """Retorna informações do sistema"""
    import platform
    import sys
    
    return {
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": sys.version
        },
        "core": {
            "version": __version__,
            "settings_version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "debug_mode": settings.DEBUG
        },
        "features": {
            "database_enabled": DATABASE_ENABLED,
            "gpu_engines_available": len(get_gpu_engines()) > 0,
            "total_engines": len(get_available_engines()),
            "queue_count": len(settings.QUEUE_CONFIG)
        }
    }


def validate_core_dependencies() -> Dict[str, bool]:
    """Valida dependências do core"""
    dependencies = {}
    
    # Redis
    try:
        import redis
        dependencies['redis'] = True
    except ImportError:
        dependencies['redis'] = False
    
    # Celery
    try:
        import celery
        dependencies['celery'] = True
    except ImportError:
        dependencies['celery'] = False
    
    # PIL/Pillow
    try:
        from PIL import Image
        dependencies['pillow'] = True
    except ImportError:
        dependencies['pillow'] = False
    
    # OpenCV
    try:
        import cv2
        dependencies['opencv'] = True
    except ImportError:
        dependencies['opencv'] = False
    
    # Pydantic
    try:
        import pydantic
        dependencies['pydantic'] = True
    except ImportError:
        dependencies['pydantic'] = False
    
    # FastAPI
    try:
        import fastapi
        dependencies['fastapi'] = True
    except ImportError:
        dependencies['fastapi'] = False
    
    return dependencies


# Informações do módulo
def get_core_info() -> Dict[str, Any]:
    """Retorna informações completas do módulo core"""
    return {
        "version": __version__,
        "components": [
            "config", "redis_client", "celery_app", "database"
        ],
        "available_engines": get_available_engines(),
        "queue_configurations": list(settings.QUEUE_CONFIG.keys()),
        "dependencies": validate_core_dependencies(),
        "system_info": get_system_info(),
        "database_enabled": DATABASE_ENABLED
    }


# Log de inicialização
logger.info(f"OCR Platform Core v{__version__} loaded")

if __name__ == "__main__":
    """Teste do módulo core"""
    print("=== Core Module Test ===")
    
    # Informações do core
    core_info = get_core_info()
    print(f"Core version: {core_info['version']}")
    print(f"Available engines: {core_info['available_engines']}")
    print(f"Database enabled: {core_info['database_enabled']}")
    
    # Validar dependências
    deps = validate_core_dependencies()
    print(f"Dependencies: {deps}")
    
    # Teste de inicialização
    print("\n--- Testing Core Initialization ---")
    init_result = initialize_core()
    for component, status in init_result.items():
        status_icon = "✅" if status else "❌" if status is False else "ℹ️"
        print(f"  {component}: {status_icon}")
    
    # Health check
    print("\n--- Testing Health Check ---")
    health = get_core_health()
    print(f"Overall status: {health['overall_status']}")
    for component, info in health['components'].items():
        print(f"  {component}: {info.get('status', 'unknown')}")
    
    print("\n✅ Core module test completed")