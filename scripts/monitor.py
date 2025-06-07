#!/usr/bin/env python3
"""
Script de Monitoramento do Sistema OCR
======================================

Monitora em tempo real:
- Status da API e workers
- Métricas de performance
- Uso de recursos do sistema
- Filas de processamento
- Health checks automáticos
"""

import os
import sys
import time
import json
import logging
import argparse
import threading
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

# Adicionar o diretório raiz ao Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psutil
    import requests
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
    from rich.layout import Layout
    from rich.text import Text
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Install with: pip install psutil rich requests")
    sys.exit(1)

try:
    from app.core.config import settings
    from app.core.redis_client import get_redis_client
    from app.services import get_services_health, get_services_stats
except ImportError as e:
    print(f"❌ Failed to import application modules: {e}")
    print("Make sure you're in the project root and dependencies are installed")
    sys.exit(1)

# Configurar logging
logging.basicConfig(level=logging.WARNING)  # Reduzir logs para não poluir display
logger = logging.getLogger(__name__)

# Console para output rico
console = Console()

# Variáveis globais
monitoring_active = True
refresh_interval = 2.0  # segundos


class SystemMonitor:
    """Monitor do sistema OCR"""
    
    def __init__(self):
        self.api_url = f"http://{settings.API_HOST}:{settings.API_PORT}"
        self.redis_client = None
        self.last_stats = {}
        self.alerts = []
        
        # Inicializar Redis
        try:
            self.redis_client = get_redis_client()
        except Exception as e:
            self.alerts.append(f"Redis connection failed: {e}")
    
    def check_api_status(self) -> Dict[str, Any]:
        """Verifica status da API"""
        try:
            # Health check
            response = requests.get(f"{self.api_url}/api/v1/health", timeout=5)
            if response.status_code == 200:
                health_data = response.json()
                
                # Ping simples
                ping_response = requests.get(f"{self.api_url}/ping", timeout=2)
                ping_time = ping_response.elapsed.total_seconds() * 1000
                
                return {
                    "status": "healthy",
                    "health_data": health_data,
                    "response_time_ms": ping_time,
                    "uptime": health_data.get("uptime", 0)
                }
            else:
                return {
                    "status": "unhealthy",
                    "error": f"HTTP {response.status_code}",
                    "response_time_ms": 0
                }
                
        except requests.exceptions.ConnectionError:
            return {
                "status": "offline",
                "error": "Connection refused",
                "response_time_ms": 0
            }
        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "error": "Request timeout",
                "response_time_ms": 0
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time_ms": 0
            }
    
    def check_celery_workers(self) -> Dict[str, Any]:
        """Verifica status dos workers Celery"""
        try:
            from app.core.celery_app import celery_app
            
            inspector = celery_app.control.inspect()
            
            # Workers ativos
            active_workers = inspector.active() or {}
            registered_tasks = inspector.registered() or {}
            stats = inspector.stats() or {}
            
            # Processar dados
            worker_info = {}
            for worker_name in active_workers.keys():
                worker_stats = stats.get(worker_name, {})
                worker_info[worker_name] = {
                    "active_tasks": len(active_workers[worker_name]),
                    "registered_tasks": len(registered_tasks.get(worker_name, [])),
                    "total_tasks": worker_stats.get("total", {}),
                    "pool": worker_stats.get("pool", {}),
                    "rusage": worker_stats.get("rusage", {})
                }
            
            return {
                "status": "healthy" if active_workers else "no_workers",
                "worker_count": len(active_workers),
                "workers": worker_info
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "worker_count": 0,
                "workers": {}
            }
    
    def check_redis_status(self) -> Dict[str, Any]:
        """Verifica status do Redis"""
        try:
            if not self.redis_client:
                return {"status": "disconnected"}
            
            # Ping
            start_time = time.time()
            ping_result = self.redis_client.ping()
            ping_time = (time.time() - start_time) * 1000
            
            if not ping_result:
                return {"status": "unhealthy", "ping_time_ms": 0}
            
            # Info do Redis
            info = self.redis_client.client.info()
            
            return {
                "status": "healthy",
                "ping_time_ms": ping_time,
                "memory_used": info.get("used_memory_human", "N/A"),
                "memory_peak": info.get("used_memory_peak_human", "N/A"),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands": info.get("total_commands_processed", 0),
                "uptime_seconds": info.get("uptime_in_seconds", 0)
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "ping_time_ms": 0
            }
    
    def get_system_resources(self) -> Dict[str, Any]:
        """Obtém uso de recursos do sistema"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            load_avg = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
            
            # Memória
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disco
            disk_usage = psutil.disk_usage('/')
            
            # Rede
            net_io = psutil.net_io_counters()
            
            # Processos OCR
            ocr_processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    if any(keyword in proc.info['name'].lower() 
                          for keyword in ['celery', 'uvicorn', 'gunicorn', 'python']):
                        # Verificar se é processo OCR
                        cmdline = proc.cmdline()
                        if any('ocr' in arg.lower() or 'app' in arg for arg in cmdline):
                            ocr_processes.append({
                                "pid": proc.info['pid'],
                                "name": proc.info['name'],
                                "cpu_percent": proc.info['cpu_percent'],
                                "memory_percent": proc.info['memory_percent']
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            return {
                "cpu": {
                    "percent": cpu_percent,
                    "count": cpu_count,
                    "load_avg": load_avg
                },
                "memory": {
                    "total_gb": memory.total / (1024**3),
                    "used_gb": memory.used / (1024**3),
                    "available_gb": memory.available / (1024**3),
                    "percent": memory.percent
                },
                "swap": {
                    "total_gb": swap.total / (1024**3),
                    "used_gb": swap.used / (1024**3),
                    "percent": swap.percent
                },
                "disk": {
                    "total_gb": disk_usage.total / (1024**3),
                    "used_gb": disk_usage.used / (1024**3),
                    "free_gb": disk_usage.free / (1024**3),
                    "percent": (disk_usage.used / disk_usage.total) * 100
                },
                "network": {
                    "bytes_sent": net_io.bytes_sent,
                    "bytes_recv": net_io.bytes_recv,
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                },
                "ocr_processes": ocr_processes
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """Obtém estatísticas das filas"""
        try:
            from app.services import get_queue_manager
            
            queue_manager = get_queue_manager()
            
            # Status de todas as filas
            queue_statuses = queue_manager.get_all_queue_status()
            
            # Resumo
            total_pending = sum(q.pending_tasks for q in queue_statuses)
            total_active = sum(q.active_tasks for q in queue_statuses)
            total_workers = sum(q.active_workers for q in queue_statuses)
            
            return {
                "queues": {q.queue_name: {
                    "pending": q.pending_tasks,
                    "active": q.active_tasks,
                    "completed": q.completed_tasks,
                    "failed": q.failed_tasks,
                    "workers": q.active_workers,
                    "max_workers": q.max_workers,
                    "throughput": q.throughput,
                    "avg_time": q.avg_processing_time
                } for q in queue_statuses},
                "summary": {
                    "total_pending": total_pending,
                    "total_active": total_active,
                    "total_workers": total_workers,
                    "queue_count": len(queue_statuses)
                }
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def check_alerts(self, stats: Dict[str, Any]):
        """Verifica condições de alerta"""
        new_alerts = []
        
        # CPU alto
        cpu_percent = stats.get("system", {}).get("cpu", {}).get("percent", 0)
        if cpu_percent > 90:
            new_alerts.append(f"HIGH CPU: {cpu_percent:.1f}%")
        
        # Memória alta
        memory_percent = stats.get("system", {}).get("memory", {}).get("percent", 0)
        if memory_percent > 90:
            new_alerts.append(f"HIGH MEMORY: {memory_percent:.1f}%")
        
        # Disco cheio
        disk_percent = stats.get("system", {}).get("disk", {}).get("percent", 0)
        if disk_percent > 90:
            new_alerts.append(f"DISK FULL: {disk_percent:.1f}%")
        
        # API offline
        api_status = stats.get("api", {}).get("status", "")
        if api_status in ["offline", "timeout", "error"]:
            new_alerts.append(f"API {api_status.upper()}")
        
        # Sem workers
        worker_count = stats.get("celery", {}).get("worker_count", 0)
        if worker_count == 0:
            new_alerts.append("NO WORKERS ACTIVE")
        
        # Redis com problemas
        redis_status = stats.get("redis", {}).get("status", "")
        if redis_status != "healthy":
            new_alerts.append(f"REDIS {redis_status.upper()}")
        
        # Filas congestionadas
        queue_stats = stats.get("queues", {})
        for queue_name, queue_data in queue_stats.get("queues", {}).items():
            pending = queue_data.get("pending", 0)
            if pending > 100:  # Mais de 100 tasks pendentes
                new_alerts.append(f"QUEUE {queue_name}: {pending} pending")
        
        # Atualizar lista de alertas (manter apenas os últimos 10)
        self.alerts = new_alerts[-10:]
    
    def collect_all_stats(self) -> Dict[str, Any]:
        """Coleta todas as estatísticas"""
        stats = {
            "timestamp": datetime.now().isoformat(),
            "api": self.check_api_status(),
            "celery": self.check_celery_workers(),
            "redis": self.check_redis_status(),
            "system": self.get_system_resources(),
            "queues": self.get_queue_stats()
        }
        
        # Verificar alertas
        self.check_alerts(stats)
        
        return stats


def create_status_display(monitor: SystemMonitor) -> Layout:
    """Cria display de status em tempo real"""
    
    def update_display():
        """Atualiza o display"""
        stats = monitor.collect_all_stats()
        
        # Layout principal
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="footer", size=3)
        )
        
        layout["main"].split_row(
            Layout(name="left"),
            Layout(name="right")
        )
        
        layout["left"].split_column(
            Layout(name="api_status"),
            Layout(name="system_resources")
        )
        
        layout["right"].split_column(
            Layout(name="workers"),
            Layout(name="queues")
        )
        
        # Header
        header_text = Text.assemble(
            ("🔧 OCR Platform Monitor", "bold blue"),
            f" | {datetime.now().strftime('%H:%M:%S')}",
            f" | Refresh: {refresh_interval}s"
        )
        layout["header"] = Panel(header_text, style="blue")
        
        # Status da API
        api_stats = stats["api"]
        api_color = "green" if api_stats["status"] == "healthy" else "red"
        api_panel = Panel(
            f"Status: [{api_color}]{api_stats['status'].upper()}[/{api_color}]\n"
            f"Response Time: {api_stats.get('response_time_ms', 0):.1f}ms\n"
            f"Uptime: {api_stats.get('uptime', 0):.1f}s",
            title="API Status",
            border_style=api_color
        )
        layout["api_status"] = api_panel
        
        # Recursos do sistema
        sys_stats = stats["system"]
        if "error" not in sys_stats:
            cpu_color = "red" if sys_stats["cpu"]["percent"] > 80 else "yellow" if sys_stats["cpu"]["percent"] > 60 else "green"
            mem_color = "red" if sys_stats["memory"]["percent"] > 80 else "yellow" if sys_stats["memory"]["percent"] > 60 else "green"
            
            system_panel = Panel(
                f"CPU: [{cpu_color}]{sys_stats['cpu']['percent']:.1f}%[/{cpu_color}] ({sys_stats['cpu']['count']} cores)\n"
                f"Memory: [{mem_color}]{sys_stats['memory']['percent']:.1f}%[/{mem_color}] "
                f"({sys_stats['memory']['used_gb']:.1f}/{sys_stats['memory']['total_gb']:.1f}GB)\n"
                f"Disk: {sys_stats['disk']['percent']:.1f}% "
                f"({sys_stats['disk']['used_gb']:.1f}/{sys_stats['disk']['total_gb']:.1f}GB)\n"
                f"OCR Processes: {len(sys_stats['ocr_processes'])}",
                title="System Resources",
                border_style="blue"
            )
        else:
            system_panel = Panel(f"Error: {sys_stats['error']}", title="System Resources", border_style="red")
        
        layout["system_resources"] = system_panel
        
        # Workers
        celery_stats = stats["celery"]
        worker_color = "green" if celery_stats["status"] == "healthy" else "red"
        
        if celery_stats["status"] == "healthy":
            worker_text = f"Active Workers: {celery_stats['worker_count']}\n"
            for worker_name, worker_info in celery_stats["workers"].items():
                worker_text += f"  {worker_name}: {worker_info['active_tasks']} tasks\n"
        else:
            worker_text = f"Status: {celery_stats['status']}\nError: {celery_stats.get('error', 'Unknown')}"
        
        worker_panel = Panel(
            worker_text.strip(),
            title="Celery Workers",
            border_style=worker_color
        )
        layout["workers"] = worker_panel
        
        # Filas
        queue_stats = stats["queues"]
        if "error" not in queue_stats:
            queue_text = f"Total Pending: {queue_stats['summary']['total_pending']}\n"
            queue_text += f"Total Active: {queue_stats['summary']['total_active']}\n"
            queue_text += f"Active Workers: {queue_stats['summary']['total_workers']}\n\n"
            
            for queue_name, queue_data in queue_stats["queues"].items():
                queue_text += f"{queue_name}: {queue_data['pending']}P {queue_data['active']}A\n"
        else:
            queue_text = f"Error: {queue_stats['error']}"
        
        queue_panel = Panel(
            queue_text.strip(),
            title="Queue Status",
            border_style="blue"
        )
        layout["queues"] = queue_panel
        
        # Footer com alertas
        if monitor.alerts:
            alert_text = " | ".join(monitor.alerts)
            footer_panel = Panel(f"🚨 ALERTS: {alert_text}", style="red")
        else:
            footer_panel = Panel("✅ All systems operational", style="green")
        
        layout["footer"] = footer_panel
        
        return layout
    
    return update_display


def save_stats_to_file(stats: Dict[str, Any], filename: str):
    """Salva estatísticas em arquivo"""
    try:
        with open(filename, 'a') as f:
            f.write(json.dumps(stats) + '\n')
    except Exception as e:
        logger.error(f"Failed to save stats: {e}")


def run_continuous_monitoring(monitor: SystemMonitor, save_to_file: bool = False):
    """Executa monitoramento contínuo"""
    global monitoring_active
    
    # Criar display
    update_display = create_status_display(monitor)
    
    with Live(update_display(), refresh_per_second=1/refresh_interval, screen=True) as live:
        while monitoring_active:
            try:
                # Atualizar display
                live.update(update_display())
                
                # Salvar em arquivo se solicitado
                if save_to_file:
                    stats = monitor.collect_all_stats()
                    filename = f"monitor_log_{datetime.now().strftime('%Y%m%d')}.jsonl"
                    save_stats_to_file(stats, filename)
                
                time.sleep(refresh_interval)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                time.sleep(5)


def run_single_check(monitor: SystemMonitor, output_format: str = "table"):
    """Executa verificação única"""
    stats = monitor.collect_all_stats()
    
    if output_format == "json":
        console.print_json(json.dumps(stats, indent=2))
        return
    
    # Formato tabela
    console.print("\n🔧 OCR Platform Status Report", style="bold blue")
    console.print(f"Timestamp: {stats['timestamp']}")
    
    # API Status
    api_table = Table(title="API Status")
    api_table.add_column("Metric", style="cyan")
    api_table.add_column("Value", style="white")
    
    api_stats = stats["api"]
    api_table.add_row("Status", api_stats["status"])
    api_table.add_row("Response Time", f"{api_stats.get('response_time_ms', 0):.1f}ms")
    api_table.add_row("Uptime", f"{api_stats.get('uptime', 0):.1f}s")
    
    console.print(api_table)
    
    # System Resources
    sys_stats = stats["system"]
    if "error" not in sys_stats:
        system_table = Table(title="System Resources")
        system_table.add_column("Resource", style="cyan")
        system_table.add_column("Usage", style="white")
        system_table.add_column("Details", style="white")
        
        system_table.add_row(
            "CPU", 
            f"{sys_stats['cpu']['percent']:.1f}%",
            f"{sys_stats['cpu']['count']} cores"
        )
        system_table.add_row(
            "Memory",
            f"{sys_stats['memory']['percent']:.1f}%",
            f"{sys_stats['memory']['used_gb']:.1f}/{sys_stats['memory']['total_gb']:.1f}GB"
        )
        system_table.add_row(
            "Disk",
            f"{sys_stats['disk']['percent']:.1f}%",
            f"{sys_stats['disk']['used_gb']:.1f}/{sys_stats['disk']['total_gb']:.1f}GB"
        )
        
        console.print(system_table)
    
    # Workers
    celery_stats = stats["celery"]
    if celery_stats["status"] == "healthy":
        worker_table = Table(title="Celery Workers")
        worker_table.add_column("Worker", style="cyan")
        worker_table.add_column("Active Tasks", style="white")
        worker_table.add_column("Registered Tasks", style="white")
        
        for worker_name, worker_info in celery_stats["workers"].items():
            worker_table.add_row(
                worker_name,
                str(worker_info["active_tasks"]),
                str(worker_info["registered_tasks"])
            )
        
        console.print(worker_table)
    
    # Queues
    queue_stats = stats["queues"]
    if "error" not in queue_stats:
        queue_table = Table(title="Queue Status")
        queue_table.add_column("Queue", style="cyan")
        queue_table.add_column("Pending", style="yellow")
        queue_table.add_column("Active", style="green")
        queue_table.add_column("Workers", style="blue")
        queue_table.add_column("Throughput", style="white")
        
        for queue_name, queue_data in queue_stats["queues"].items():
            queue_table.add_row(
                queue_name,
                str(queue_data["pending"]),
                str(queue_data["active"]),
                f"{queue_data['workers']}/{queue_data['max_workers']}",
                f"{queue_data['throughput']:.1f}/min"
            )
        
        console.print(queue_table)
    
    # Alerts
    if monitor.alerts:
        console.print("\n🚨 Active Alerts:", style="bold red")
        for alert in monitor.alerts:
            console.print(f"  • {alert}", style="red")
    else:
        console.print("\n✅ No active alerts", style="green")


def setup_signal_handlers():
    """Configura handlers de sinal"""
    global monitoring_active
    
    def signal_handler(signum, frame):
        global monitoring_active
        monitoring_active = False
        console.print("\n🛑 Monitoring stopped", style="yellow")
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def main():
    """Função principal"""
    global refresh_interval
    
    parser = argparse.ArgumentParser(description="OCR Platform System Monitor")
    parser.add_argument("--continuous", "-c", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", "-i", type=float, default=2.0, help="Refresh interval (seconds)")
    parser.add_argument("--save-logs", action="store_true", help="Save stats to file")
    parser.add_argument("--output", choices=["table", "json"], default="table", help="Output format")
    parser.add_argument("--no-clear", action="store_true", help="Don't clear screen")
    
    args = parser.parse_args()
    
    refresh_interval = args.interval
    
    # Setup
    setup_signal_handlers()
    monitor = SystemMonitor()
    
    if args.continuous:
        console.print("🔧 Starting OCR Platform Monitor...", style="bold blue")
        console.print(f"Refresh interval: {refresh_interval}s")
        console.print("Press Ctrl+C to stop\n")
        
        run_continuous_monitoring(monitor, args.save_logs)
    else:
        run_single_check(monitor, args.output)


if __name__ == "__main__":
    main()