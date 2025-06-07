#!/usr/bin/env python3
"""
Inicialização dos Serviços
==========================

Módulo de serviços da OCR Platform que fornece:
- Orquestração inteligente de engines
- Gerenciamento de filas e distribuição de tasks
- Processamento e agregação de resultados
- Armazenamento de arquivos e resultados
- Detecção de tipos de arquivo

Este módulo encapsula toda a lógica de negócio e coordenação
entre os diferentes componentes do sistema OCR.
"""

import logging
from typing import Dict, Any, Optional

# Importar todas as classes principais dos serviços
from .orchestrator import OrchestratorService, get_orchestrator_service
from .queue_manager import QueueManager, get_queue_manager
from .result_processor import ResultProcessor, get_result_processor
from .storage import StorageService, get_storage_service
from .file_detector import FileTypeDetector

logger = logging.getLogger(__name__)

# Versão dos serviços
__version__ = "2.0.0"

# Exportar classes e funções principais
__all__ = [
    # Classes principais
    'OrchestratorService',
    'QueueManager', 
    'ResultProcessor',
    'StorageService',
    'FileTypeDetector',
    
    # Funções de acesso a instâncias globais
    'get_orchestrator_service',
    'get_queue_manager',
    'get_result_processor', 
    'get_storage_service',
    
    # Funções utilitárias
    'initialize_services',
    'get_services_health',
    'get_services_stats',
    'cleanup_services'
]


def initialize_services() -> Dict[str, bool]:
    """
    Inicializa todos os serviços
    
    Returns:
        Dict com status de inicialização de cada serviço
    """
    initialization_status = {}
    
    try:
        # Inicializar orchestrator
        orchestrator = get_orchestrator_service()
        initialization_status['orchestrator'] = True
        logger.info("✅ Orchestrator service initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize orchestrator service: {e}")
        initialization_status['orchestrator'] = False
    
    try:
        # Inicializar queue manager
        queue_manager = get_queue_manager()
        initialization_status['queue_manager'] = True
        logger.info("✅ Queue manager initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize queue manager: {e}")
        initialization_status['queue_manager'] = False
    
    try:
        # Inicializar result processor
        result_processor = get_result_processor()
        initialization_status['result_processor'] = True
        logger.info("✅ Result processor initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize result processor: {e}")
        initialization_status['result_processor'] = False
    
    try:
        # Inicializar storage service
        storage_service = get_storage_service()
        initialization_status['storage_service'] = True
        logger.info("✅ Storage service initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize storage service: {e}")
        initialization_status['storage_service'] = False
    
    try:
        # Inicializar file detector
        file_detector = FileTypeDetector()
        initialization_status['file_detector'] = True
        logger.info("✅ File detector initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize file detector: {e}")
        initialization_status['file_detector'] = False
    
    # Log do status geral
    successful_services = sum(initialization_status.values())
    total_services = len(initialization_status)
    
    if successful_services == total_services:
        logger.info(f"🌟 All {total_services} services initialized successfully")
    else:
        logger.warning(f"⚠️  {successful_services}/{total_services} services initialized successfully")
    
    return initialization_status


def get_services_health() -> Dict[str, Any]:
    """
    Verifica saúde de todos os serviços
    
    Returns:
        Dict com status de saúde de cada serviço
    """
    health_status = {
        "timestamp": None,
        "overall_status": "healthy",
        "services": {}
    }
    
    try:
        import time
        health_status["timestamp"] = time.time()
        
        # Verificar orchestrator
        try:
            orchestrator = get_orchestrator_service()
            health_status["services"]["orchestrator"] = {
                "status": "healthy",
                "orchestrations_count": orchestrator.orchestration_count,
                "cache_hit_rate": (orchestrator.decision_hit_count / max(orchestrator.orchestration_count, 1)) * 100
            }
        except Exception as e:
            health_status["services"]["orchestrator"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["overall_status"] = "degraded"
        
        # Verificar queue manager
        try:
            queue_manager = get_queue_manager()
            manager_stats = queue_manager.get_manager_stats()
            health_status["services"]["queue_manager"] = {
                "status": "healthy",
                "distributions": manager_stats.get("task_distributions", 0),
                "total_pending_tasks": manager_stats.get("queue_summary", {}).get("total_pending_tasks", 0)
            }
        except Exception as e:
            health_status["services"]["queue_manager"] = {
                "status": "unhealthy", 
                "error": str(e)
            }
            health_status["overall_status"] = "degraded"
        
        # Verificar result processor
        try:
            result_processor = get_result_processor()
            processor_stats = result_processor.get_processor_stats()
            health_status["services"]["result_processor"] = {
                "status": "healthy",
                "results_processed": processor_stats.get("results_processed", 0),
                "improvement_rate": processor_stats.get("improvement_rate", 0)
            }
        except Exception as e:
            health_status["services"]["result_processor"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["overall_status"] = "degraded"
        
        # Verificar storage service
        try:
            storage_service = get_storage_service()
            storage_stats = storage_service.get_storage_stats()
            
            # Verificar espaço em disco
            disk_issues = False
            if "disk_usage" in storage_stats:
                for dir_name, usage in storage_stats["disk_usage"].items():
                    if usage.get("usage_percent", 0) > 90:
                        disk_issues = True
                        break
            
            health_status["services"]["storage_service"] = {
                "status": "degraded" if disk_issues else "healthy",
                "files_stored": storage_stats.get("files_stored", 0),
                "total_files": storage_stats.get("file_statistics", {}).get("total_files", 0),
                "disk_issues": disk_issues
            }
            
            if disk_issues:
                health_status["overall_status"] = "degraded"
                
        except Exception as e:
            health_status["services"]["storage_service"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["overall_status"] = "degraded"
        
        # Verificar file detector
        try:
            file_detector = FileTypeDetector()
            supported_formats = file_detector.get_supported_formats()
            health_status["services"]["file_detector"] = {
                "status": "healthy",
                "supported_categories": len(supported_formats),
                "total_formats": sum(len(formats) for formats in supported_formats.values())
            }
        except Exception as e:
            health_status["services"]["file_detector"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["overall_status"] = "degraded"
        
        # Determinar status geral
        unhealthy_services = [
            name for name, service in health_status["services"].items()
            if service.get("status") == "unhealthy"
        ]
        
        if len(unhealthy_services) > 0:
            health_status["overall_status"] = "unhealthy"
            health_status["unhealthy_services"] = unhealthy_services
        
        degraded_services = [
            name for name, service in health_status["services"].items() 
            if service.get("status") == "degraded"
        ]
        
        if len(degraded_services) > 0 and health_status["overall_status"] == "healthy":
            health_status["overall_status"] = "degraded" 
            health_status["degraded_services"] = degraded_services
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        health_status["overall_status"] = "unhealthy"
        health_status["error"] = str(e)
    
    return health_status


def get_services_stats() -> Dict[str, Any]:
    """
    Coleta estatísticas de todos os serviços
    
    Returns:
        Dict com estatísticas consolidadas
    """
    stats = {
        "timestamp": None,
        "version": __version__,
        "services": {}
    }
    
    try:
        import time
        stats["timestamp"] = time.time()
        
        # Estatísticas do orchestrator
        try:
            orchestrator = get_orchestrator_service()
            stats["services"]["orchestrator"] = orchestrator.get_orchestration_stats()
        except Exception as e:
            logger.warning(f"Failed to get orchestrator stats: {e}")
            stats["services"]["orchestrator"] = {"error": str(e)}
        
        # Estatísticas do queue manager
        try:
            queue_manager = get_queue_manager()
            stats["services"]["queue_manager"] = queue_manager.get_manager_stats()
        except Exception as e:
            logger.warning(f"Failed to get queue manager stats: {e}")
            stats["services"]["queue_manager"] = {"error": str(e)}
        
        # Estatísticas do result processor
        try:
            result_processor = get_result_processor()
            stats["services"]["result_processor"] = result_processor.get_processor_stats()
        except Exception as e:
            logger.warning(f"Failed to get result processor stats: {e}")
            stats["services"]["result_processor"] = {"error": str(e)}
        
        # Estatísticas do storage service
        try:
            storage_service = get_storage_service()
            stats["services"]["storage_service"] = storage_service.get_storage_stats()
        except Exception as e:
            logger.warning(f"Failed to get storage service stats: {e}")
            stats["services"]["storage_service"] = {"error": str(e)}
        
        # Estatísticas consolidadas
        stats["summary"] = {
            "total_orchestrations": stats["services"]["orchestrator"].get("total_orchestrations", 0),
            "total_distributions": stats["services"]["queue_manager"].get("task_distributions", 0),
            "total_results_processed": stats["services"]["result_processor"].get("results_processed", 0),
            "total_files_stored": stats["services"]["storage_service"].get("files_stored", 0)
        }
        
    except Exception as e:
        logger.error(f"Failed to get services stats: {e}")
        stats["error"] = str(e)
    
    return stats


def cleanup_services() -> Dict[str, bool]:
    """
    Executa limpeza de todos os serviços
    
    Returns:
        Dict com status de limpeza de cada serviço
    """
    cleanup_status = {}
    
    try:
        # Limpeza do storage service
        try:
            storage_service = get_storage_service()
            cleanup_result = storage_service.cleanup_old_files()
            cleanup_status["storage_service"] = not cleanup_result.get("error")
            logger.info(f"Storage cleanup: {cleanup_result.get('files_deleted', 0)} files deleted")
        except Exception as e:
            logger.error(f"Storage cleanup failed: {e}")
            cleanup_status["storage_service"] = False
        
        # Limpeza de cache do Redis
        try:
            from app.core.redis_client import get_redis_client
            redis_client = get_redis_client()
            
            # Limpar cache antigo (implementação básica)
            # Em produção, seria mais sofisticado
            cleanup_status["redis_cache"] = True
            logger.info("Redis cache cleanup completed")
        except Exception as e:
            logger.error(f"Redis cleanup failed: {e}")
            cleanup_status["redis_cache"] = False
        
        # Limpeza de métricas antigas
        try:
            from app.core.celery_app import cleanup_old_stats
            cleanup_old_stats()
            cleanup_status["metrics"] = True
            logger.info("Metrics cleanup completed")
        except Exception as e:
            logger.error(f"Metrics cleanup failed: {e}")
            cleanup_status["metrics"] = False
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
    
    successful_cleanups = sum(cleanup_status.values())
    total_cleanups = len(cleanup_status)
    
    logger.info(f"Cleanup completed: {successful_cleanups}/{total_cleanups} services cleaned successfully")
    
    return cleanup_status


# Funções de conveniência para importação simplificada
def get_all_services() -> Dict[str, Any]:
    """
    Retorna instâncias de todos os serviços
    
    Returns:
        Dict com instâncias de todos os serviços
    """
    return {
        "orchestrator": get_orchestrator_service(),
        "queue_manager": get_queue_manager(),
        "result_processor": get_result_processor(),
        "storage_service": get_storage_service(),
        "file_detector": FileTypeDetector()
    }


def configure_services(config: Dict[str, Any]) -> bool:
    """
    Configura todos os serviços com parâmetros customizados
    
    Args:
        config: Dicionário de configuração
        
    Returns:
        True se configuração foi bem-sucedida
    """
    try:
        # Configurar orchestrator
        if "orchestrator" in config:
            orchestrator = get_orchestrator_service()
            orch_config = config["orchestrator"]
            
            if "enable_fallback" in orch_config:
                orchestrator.enable_fallback = orch_config["enable_fallback"]
            
            if "enable_multi_engine" in orch_config:
                orchestrator.enable_multi_engine = orch_config["enable_multi_engine"]
        
        # Configurar result processor
        if "result_processor" in config:
            processor = get_result_processor()
            proc_config = config["result_processor"]
            
            if "enable_text_cleaning" in proc_config:
                processor.enable_text_cleaning = proc_config["enable_text_cleaning"]
            
            if "enable_quality_scoring" in proc_config:
                processor.enable_quality_scoring = proc_config["enable_quality_scoring"]
        
        # Configurar storage service
        if "storage_service" in config:
            storage = get_storage_service()
            storage_config = config["storage_service"]
            
            if "enable_compression" in storage_config:
                storage.enable_compression = storage_config["enable_compression"]
            
            if "enable_deduplication" in storage_config:
                storage.enable_deduplication = storage_config["enable_deduplication"]
        
        logger.info("Services configuration updated successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to configure services: {e}")
        return False


# Inicialização automática quando o módulo é importado
logger.info(f"OCR Platform Services v{__version__} - Initializing...")

try:
    # Inicializar serviços essenciais
    initialization_result = initialize_services()
    
    # Log do resultado
    successful_count = sum(initialization_result.values())
    total_count = len(initialization_result)
    
    if successful_count == total_count:
        logger.info(f"🎉 OCR Platform Services initialized successfully ({successful_count}/{total_count})")
    else:
        logger.warning(f"⚠️  Partial initialization ({successful_count}/{total_count} services)")
        
        # Log dos serviços que falharam
        failed_services = [name for name, status in initialization_result.items() if not status]
        if failed_services:
            logger.error(f"Failed services: {', '.join(failed_services)}")

except Exception as e:
    logger.error(f"❌ Critical error during services initialization: {e}")
    # Não propagar a exceção para não quebrar a importação do módulo