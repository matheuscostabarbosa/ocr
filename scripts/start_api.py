#!/usr/bin/env python3
"""
Script de Inicialização da API
==============================

Inicia a API FastAPI com configurações otimizadas
para desenvolvimento ou produção.
"""

import os
import sys
import signal
import logging
import argparse
import subprocess
from pathlib import Path

# Adicionar o diretório raiz ao Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app.core.config import settings
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


def check_prerequisites():
    """Verifica pré-requisitos antes de iniciar"""
    logger.info("🔍 Checking prerequisites...")
    
    issues = []
    
    # Verificar Redis
    try:
        redis_client = get_redis_client()
        if not redis_client.ping():
            issues.append("Redis is not responding")
    except Exception as e:
        issues.append(f"Redis connection failed: {e}")
    
    # Verificar diretórios
    required_dirs = [settings.UPLOAD_DIR, settings.RESULT_DIR, settings.TEMP_DIR]
    for directory in required_dirs:
        if not Path(directory).exists():
            try:
                Path(directory).mkdir(parents=True, exist_ok=True)
                logger.info(f"📁 Created directory: {directory}")
            except Exception as e:
                issues.append(f"Cannot create directory {directory}: {e}")
    
    # Verificar arquivo .env
    if not Path(".env").exists() and not os.getenv("REDIS_HOST"):
        issues.append("No .env file found and no environment variables set")
    
    # Verificar portas
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((settings.API_HOST, settings.API_PORT))
        sock.close()
        if result == 0:
            issues.append(f"Port {settings.API_PORT} is already in use")
    except Exception:
        pass
    
    if issues:
        logger.error("❌ Prerequisites check failed:")
        for issue in issues:
            logger.error(f"  - {issue}")
        return False
    
    logger.info("✅ Prerequisites check passed")
    return True


def initialize_application():
    """Inicializa aplicação e serviços"""
    logger.info("🚀 Initializing OCR Platform services...")
    
    try:
        # Inicializar serviços
        init_result = initialize_services()
        
        successful = sum(init_result.values())
        total = len(init_result)
        
        if successful == total:
            logger.info(f"✅ All {total} services initialized successfully")
            return True
        else:
            logger.warning(f"⚠️  {successful}/{total} services initialized")
            failed_services = [name for name, status in init_result.items() if not status]
            logger.warning(f"Failed services: {', '.join(failed_services)}")
            return successful > 0  # Continue if at least some services work
            
    except Exception as e:
        logger.error(f"❌ Service initialization failed: {e}")
        return False


def start_uvicorn_server(host: str, port: int, workers: int, reload: bool = False):
    """Inicia servidor Uvicorn"""
    logger.info(f"🌟 Starting OCR Platform API on {host}:{port}")
    
    try:
        import uvicorn
        
        # Configurações do servidor
        config = {
            "app": "app.api.main:app",
            "host": host,
            "port": port,
            "log_level": settings.LOG_LEVEL.lower(),
            "access_log": settings.DEBUG,
            "reload": reload,
            "workers": workers if not reload else 1,  # Reload não funciona com múltiplos workers
        }
        
        # Configurações adicionais para produção
        if not settings.DEBUG:
            config.update({
                "proxy_headers": True,
                "forwarded_allow_ips": "*",
                "timeout_keep_alive": 30,
                "timeout_graceful_shutdown": 30,
            })
        
        logger.info(f"📊 Server configuration:")
        logger.info(f"  Host: {host}")
        logger.info(f"  Port: {port}")
        logger.info(f"  Workers: {config['workers']}")
        logger.info(f"  Reload: {reload}")
        logger.info(f"  Debug: {settings.DEBUG}")
        logger.info(f"  Environment: {settings.ENVIRONMENT}")
        
        # Iniciar servidor
        uvicorn.run(**config)
        
    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal")
    except Exception as e:
        logger.error(f"❌ Server failed to start: {e}")
        sys.exit(1)


def start_gunicorn_server(host: str, port: int, workers: int):
    """Inicia servidor Gunicorn (produção)"""
    logger.info(f"🏭 Starting production server with Gunicorn")
    
    try:
        # Comando Gunicorn
        cmd = [
            "gunicorn",
            "app.api.main:app",
            "-w", str(workers),
            "-k", "uvicorn.workers.UvicornWorker",
            "-b", f"{host}:{port}",
            "--timeout", "300",
            "--keep-alive", "30",
            "--max-requests", "1000",
            "--max-requests-jitter", "100",
            "--preload",
            "--log-level", settings.LOG_LEVEL.lower(),
        ]
        
        # Configurações adicionais para produção
        if not settings.DEBUG:
            cmd.extend([
                "--worker-class", "uvicorn.workers.UvicornWorker",
                "--worker-connections", "1000",
            ])
        
        logger.info(f"📊 Gunicorn configuration:")
        logger.info(f"  Command: {' '.join(cmd)}")
        
        # Executar
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        logger.info("🛑 Received shutdown signal")
    except FileNotFoundError:
        logger.error("❌ Gunicorn not found. Install with: pip install gunicorn")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Gunicorn failed to start: {e}")
        sys.exit(1)


def setup_signal_handlers():
    """Configura handlers de sinal para shutdown graceful"""
    def signal_handler(signum, frame):
        logger.info(f"🛑 Received signal {signum}, shutting down gracefully...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(description="OCR Platform API Server")
    parser.add_argument("--host", default=settings.API_HOST, help="Host to bind")
    parser.add_argument("--port", type=int, default=settings.API_PORT, help="Port to bind")
    parser.add_argument("--workers", type=int, default=settings.API_WORKERS, help="Number of workers")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (development)")
    parser.add_argument("--no-check", action="store_true", help="Skip prerequisites check")
    parser.add_argument("--server", choices=["uvicorn", "gunicorn"], default="uvicorn", help="Server type")
    
    args = parser.parse_args()
    
    # Banner
    print("=" * 60)
    print("🚀 OCR Platform API Server")
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
    if not initialize_application():
        logger.error("❌ Application initialization failed")
        sys.exit(1)
    
    # Informações úteis
    logger.info("📚 API Documentation:")
    logger.info(f"  OpenAPI: http://{args.host}:{args.port}/docs")
    logger.info(f"  ReDoc: http://{args.host}:{args.port}/redoc")
    logger.info(f"  Health: http://{args.host}:{args.port}/api/v1/health")
    
    # Iniciar servidor
    try:
        if args.server == "gunicorn" and not args.reload:
            start_gunicorn_server(args.host, args.port, args.workers)
        else:
            start_uvicorn_server(args.host, args.port, args.workers, args.reload)
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()