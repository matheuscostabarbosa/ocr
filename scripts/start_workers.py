#!/usr/bin/env python3
"""
Script de Inicialização dos Workers
===================================

Inicia workers Celery especializados para processamento OCR
com configurações otimizadas para cada tipo de engine.
"""

import os
import sys
import signal
import logging
import argparse
import subprocess
import time
import multiprocessing
from pathlib import Path
from typing import List, Dict, Any

# Adicionar o diretório raiz ao Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app.core.config import settings, get_available_engines, get_queue_config
    from app.core.redis_client import get_redis_client
    from app.services import initialize_services
except ImportError as e:
    print(f"❌ Failed to import application modules: {e}")
    print("Make sure you're in the project root and dependencies are installed")
    sys.exit(1)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Worker processes storage
worker_processes = []


def check_prerequisites():
    """Verifica pré-requisitos antes de iniciar workers"""
    logger.info("🔍 Checking worker prerequisites...")
    
    issues = []
    
    # Verificar Redis
    try:
        redis_client = get_redis_client()
        if not redis_client.ping():
            issues.append("Redis is not responding")
    except Exception as e:
        issues.append(f"Redis connection failed: {e}")
    
    # Verificar engines disponíveis
    available_engines = get_available_engines()
    if not available_engines:
        issues.append("No OCR engines are available")
    else:
        logger.info(f"🔧 Available engines: {', '.join(available_engines)}")
    
    # Verificar dependências por engine
    engine_checks = {
        "trocr": ["transformers", "torch"],
        "surya": ["surya", "torch"],
        "paddleocr": ["paddleocr", "paddlepaddle"],
        "easyocr": ["easyocr"],
        "tesseract": ["pytesseract"],
        "marker": ["marker"]
    }
    
    for engine in available_engines:
        if engine in engine_checks:
            for module in engine_checks[engine]:
                try:
                    __import__(module)
                except ImportError:
                    issues.append(f"Engine {engine} missing dependency: {module}")
    
    # Verificar recursos do sistema
    try:
        import psutil
        
        # Verificar memória
        memory = psutil.virtual_memory()
        if memory.available < 2 * 1024 * 1024 * 1024:  # 2GB
            issues.append("Insufficient memory (< 2GB available)")
        
        # Verificar CPU
        cpu_count = psutil.cpu_count()
        if cpu_count < 2:
            issues.append("Insufficient CPU cores (< 2 cores)")
            
    except ImportError:
        logger.warning("psutil not available - skipping resource check")
    
    # Verificar GPU (opcional)
    try:
        import torch
        if torch.cuda.is_available():
            gpu_count = torch.cuda.device_count()
            logger.info(f"🎮 GPU available: {gpu_count} device(s)")
            
            for i in range(gpu_count):
                props = torch.cuda.get_device_properties(i)
                memory_gb = props.total_memory / (1024**3)
                logger.info(f"  GPU {i}: {props.name} ({memory_gb:.1f}GB)")
        else:
            logger.info("🖥️  No GPU available - using CPU only")
    except ImportError:
        logger.info("🖥️  PyTorch not available - using CPU only")
    
    if issues:
        logger.error("❌ Prerequisites check failed:")
        for issue in issues:
            logger.error(f"  - {issue}")
        return False
    
    logger.info("✅ Prerequisites check passed")
    return True


def get_worker_configurations() -> Dict[str, Dict[str, Any]]:
    """Retorna configurações otimizadas para cada tipo de worker"""
    
    # Detectar recursos do sistema
    cpu_count = multiprocessing.cpu_count()
    
    try:
        import psutil
        memory_gb = psutil.virtual_memory().total / (1024**3)
    except ImportError:
        memory_gb = 8  # Default assumption
    
    # Verificar GPU
    gpu_available = False
    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except ImportError:
        pass
    
    configurations = {}
    
    # Orchestrator - Coordenação geral
    configurations["orchestrator"] = {
        "queue": "orchestrator_queue",
        "concurrency": min(4, cpu_count),
        "pool": "prefork",
        "autoscale": "2,6",
        "max_tasks_per_child": 100,
        "prefetch_multiplier": 1,
        "description": "Orchestration and routing worker"
    }
    
    # TrOCR - GPU intensivo, poucos workers
    configurations["trocr"] = {
        "queue": "trocr_queue",
        "concurrency": 2 if gpu_available else 1,
        "pool": "prefork",
        "autoscale": "1,3",
        "max_tasks_per_child": 50,
        "prefetch_multiplier": 1,
        "description": "TrOCR handwriting recognition worker"
    }
    
    # Surya - GPU intensivo, análise de layout
    configurations["surya"] = {
        "queue": "surya_queue",
        "concurrency": 3 if gpu_available else 2,
        "pool": "prefork",
        "autoscale": "2,5",
        "max_tasks_per_child": 100,
        "prefetch_multiplier": 1,
        "description": "Surya layout analysis worker"
    }
    
    # PaddleOCR - Rápido, mais workers
    configurations["paddleocr"] = {
        "queue": "paddleocr_queue",
        "concurrency": min(8, cpu_count * 2),
        "pool": "prefork",
        "autoscale": "4,12",
        "max_tasks_per_child": 200,
        "prefetch_multiplier": 2,
        "description": "PaddleOCR production worker"
    }
    
    # EasyOCR - Uso geral
    configurations["easyocr"] = {
        "queue": "easyocr_queue",
        "concurrency": min(6, cpu_count * 1.5),
        "pool": "prefork",
        "autoscale": "3,9",
        "max_tasks_per_child": 150,
        "prefetch_multiplier": 2,
        "description": "EasyOCR general purpose worker"
    }
    
    # Tesseract - CPU only, muitos workers
    configurations["tesseract"] = {
        "queue": "tesseract_queue",
        "concurrency": min(10, cpu_count * 2),
        "pool": "prefork",
        "autoscale": "5,15",
        "max_tasks_per_child": 500,
        "prefetch_multiplier": 3,
        "description": "Tesseract fallback worker"
    }
    
    # Marker - PDF to Markdown
    configurations["marker"] = {
        "queue": "marker_queue",
        "concurrency": 4 if gpu_available else 2,
        "pool": "prefork",
        "autoscale": "2,6",
        "max_tasks_per_child": 50,
        "prefetch_multiplier": 1,
        "description": "Marker PDF conversion worker"
    }
    
    # Post-processing worker
    configurations["postprocess"] = {
        "queue": "postprocess_queue",
        "concurrency": min(6, cpu_count),
        "pool": "prefork",
        "autoscale": "3,9",
        "max_tasks_per_child": 200,
        "prefetch_multiplier": 2,
        "description": "Result post-processing worker"
    }
    
    return configurations


def start_single_worker(worker_type: str, config: Dict[str, Any], log_level: str = "info"):
    """Inicia um worker específico"""
    
    # Comando base do Celery
    cmd = [
        "celery",
        "-A", "app.core.celery_app",
        "worker",
        "--loglevel", log_level,
        "--queues", config["queue"],
        "--concurrency", str(config["concurrency"]),
        "--pool", config["pool"],
        "--max-tasks-per-child", str(config["max_tasks_per_child"]),
        "--prefetch-multiplier", str(config["prefetch_multiplier"]),
        "--hostname", f"{worker_type}@%h",
    ]
    
    # Adicionar autoscale se especificado
    if "autoscale" in config:
        cmd.extend(["--autoscale", config["autoscale"]])
    
    # Configurações específicas
    cmd.extend([
        "--time-limit", str(settings.WORKER_TASK_TIME_LIMIT),
        "--soft-time-limit", str(settings.WORKER_TASK_SOFT_TIME_LIMIT),
    ])
    
    # Variables de ambiente específicas
    env = os.environ.copy()
    env["WORKER_TYPE"] = worker_type
    
    logger.info(f"🚀 Starting {worker_type} worker: {config['description']}")
    logger.info(f"   Queue: {config['queue']}")
    logger.info(f"   Concurrency: {config['concurrency']}")
    logger.info(f"   Pool: {config['pool']}")
    
    try:
        process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        worker_processes.append({
            "type": worker_type,
            "process": process,
            "cmd": cmd,
            "config": config
        })
        
        return process
        
    except FileNotFoundError:
        logger.error(f"❌ Celery not found. Install with: pip install celery")
        return None
    except Exception as e:
        logger.error(f"❌ Failed to start {worker_type} worker: {e}")
        return None


def start_flower_monitoring(port: int = 5555):
    """Inicia Flower para monitoramento"""
    logger.info(f"🌸 Starting Flower monitoring on port {port}")
    
    cmd = [
        "celery",
        "-A", "app.core.celery_app",
        "flower",
        "--port", str(port),
        "--basic_auth", f"admin:admin",  # Default auth
    ]
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True
        )
        
        worker_processes.append({
            "type": "flower",
            "process": process,
            "cmd": cmd,
            "config": {"port": port}
        })
        
        logger.info(f"🌸 Flower available at: http://localhost:{port}")
        logger.info(f"   Username: admin")
        logger.info(f"   Password: admin")
        
        return process
        
    except FileNotFoundError:
        logger.error("❌ Flower not found. Install with: pip install flower")
        return None
    except Exception as e:
        logger.error(f"❌ Failed to start Flower: {e}")
        return None


def monitor_workers():
    """Monitora workers em execução"""
    logger.info("👀 Monitoring workers...")
    
    try:
        while True:
            time.sleep(10)  # Check every 10 seconds
            
            # Verificar se todos os processes estão rodando
            for worker_info in worker_processes[:]:  # Copy list for safe iteration
                process = worker_info["process"]
                worker_type = worker_info["type"]
                
                if process.poll() is not None:  # Process finished
                    logger.error(f"❌ {worker_type} worker crashed (exit code: {process.returncode})")
                    
                    # Remover da lista
                    worker_processes.remove(worker_info)
                    
                    # Tentar reiniciar se não foi shutdown intencional
                    if process.returncode != 0:
                        logger.info(f"🔄 Attempting to restart {worker_type} worker...")
                        # Implementar lógica de restart aqui se necessário
            
            # Log status
            active_workers = len([w for w in worker_processes if w["process"].poll() is None])
            if active_workers > 0:
                logger.debug(f"✅ {active_workers} workers running")
                
    except KeyboardInterrupt:
        logger.info("🛑 Monitoring interrupted")


def shutdown_workers():
    """Para todos os workers gracefully"""
    logger.info("🛑 Shutting down all workers...")
    
    for worker_info in worker_processes:
        process = worker_info["process"]
        worker_type = worker_info["type"]
        
        if process.poll() is None:  # Still running
            logger.info(f"🛑 Stopping {worker_type} worker...")
            
            try:
                # Tentar SIGTERM primeiro
                process.terminate()
                
                # Aguardar um pouco
                try:
                    process.wait(timeout=30)
                    logger.info(f"✅ {worker_type} worker stopped gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill se necessário
                    logger.warning(f"⚠️  Force killing {worker_type} worker")
                    process.kill()
                    process.wait()
                    
            except Exception as e:
                logger.error(f"❌ Error stopping {worker_type} worker: {e}")


def setup_signal_handlers():
    """Configura handlers de sinal para shutdown graceful"""
    def signal_handler(signum, frame):
        logger.info(f"🛑 Received signal {signum}, shutting down workers...")
        shutdown_workers()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(description="OCR Platform Workers")
    parser.add_argument("--workers", nargs="+", 
                       choices=["orchestrator", "trocr", "surya", "paddleocr", 
                               "easyocr", "tesseract", "marker", "postprocess", "all"],
                       default=["all"], help="Worker types to start")
    parser.add_argument("--flower", action="store_true", help="Start Flower monitoring")
    parser.add_argument("--flower-port", type=int, default=5555, help="Flower port")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"], 
                       default="info", help="Log level")
    parser.add_argument("--no-check", action="store_true", help="Skip prerequisites check")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    
    args = parser.parse_args()
    
    # Banner
    print("=" * 60)
    print("🔧 OCR Platform Workers")
    print(f"   Version: {settings.VERSION}")
    print(f"   Environment: {settings.ENVIRONMENT}")
    print("=" * 60)
    
    # Configurar signal handlers
    setup_signal_handlers()
    
    # Verificar pré-requisitos
    if not args.no_check and not check_prerequisites():
        logger.error("❌ Prerequisites check failed. Use --no-check to skip.")
        sys.exit(1)
    
    # Inicializar aplicação
    logger.info("🚀 Initializing OCR Platform services...")
    if not initialize_services():
        logger.error("❌ Service initialization failed")
        sys.exit(1)
    
    # Obter configurações dos workers
    configurations = get_worker_configurations()
    
    # Determinar workers a iniciar
    if "all" in args.workers:
        workers_to_start = list(configurations.keys())
    else:
        workers_to_start = args.workers
    
    # Filtrar workers disponíveis
    available_engines = get_available_engines()
    filtered_workers = []
    
    for worker_type in workers_to_start:
        if worker_type in ["orchestrator", "postprocess"]:
            filtered_workers.append(worker_type)
        elif worker_type in available_engines:
            filtered_workers.append(worker_type)
        else:
            logger.warning(f"⚠️  Skipping {worker_type} - engine not available")
    
    if not filtered_workers:
        logger.error("❌ No workers to start")
        sys.exit(1)
    
    logger.info(f"🚀 Starting workers: {', '.join(filtered_workers)}")
    
    # Mostrar comandos se dry-run
    if args.dry_run:
        logger.info("🔍 Dry run - showing commands:")
        for worker_type in filtered_workers:
            config = configurations[worker_type]
            cmd = [
                "celery", "-A", "app.core.celery_app", "worker",
                "--loglevel", args.log_level,
                "--queues", config["queue"],
                "--concurrency", str(config["concurrency"]),
                "--hostname", f"{worker_type}@%h"
            ]
            logger.info(f"  {worker_type}: {' '.join(cmd)}")
        return
    
    # Iniciar workers
    started_workers = []
    for worker_type in filtered_workers:
        config = configurations[worker_type]
        process = start_single_worker(worker_type, config, args.log_level)
        if process:
            started_workers.append(worker_type)
            time.sleep(2)  # Delay between starts
    
    if not started_workers:
        logger.error("❌ No workers started successfully")
        sys.exit(1)
    
    # Iniciar Flower se solicitado
    if args.flower:
        start_flower_monitoring(args.flower_port)
    
    logger.info(f"✅ Started {len(started_workers)} workers successfully")
    logger.info("📊 Worker summary:")
    for worker_type in started_workers:
        config = configurations[worker_type]
        logger.info(f"  {worker_type}: {config['description']}")
    
    # Monitorar workers
    try:
        monitor_workers()
    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal")
    finally:
        shutdown_workers()


if __name__ == "__main__":
    main()