#!/usr/bin/env python3
"""
Script de Benchmark - OCR Platform
==================================

Executa testes de performance e benchmark de todos os engines OCR:
- Testa velocidade de processamento
- Mede precisão e qualidade
- Compara engines em diferentes cenários
- Gera relatórios detalhados
- Testa throughput e escalabilidade
"""

import os
import sys
import time
import json
import tempfile
import statistics
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

# Adicionar o diretório raiz ao Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import requests
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    import matplotlib.pyplot as plt
    import seaborn as sns
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress, TaskID
    from rich.panel import Panel
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Install with: pip install requests numpy pillow matplotlib seaborn rich")
    sys.exit(1)

try:
    from app.core.config import settings, get_available_engines
    from app.core.redis_client import get_redis_client
    from app.models.schemas import OCRRequest, OCREngine, OutputFormat
    from app.services import get_orchestrator_service
except ImportError as e:
    print(f"❌ Failed to import application modules: {e}")
    print("Make sure you're in the project root and dependencies are installed")
    sys.exit(1)

# Configurar logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

console = Console()


class BenchmarkSuite:
    """Suite completa de benchmark para OCR Platform"""
    
    def __init__(self, api_url: str = None):
        self.api_url = api_url or f"http://{settings.API_HOST}:{settings.API_PORT}"
        self.available_engines = get_available_engines()
        self.test_images = []
        self.results = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "api_url": self.api_url,
                "available_engines": self.available_engines,
                "system_info": self._get_system_info()
            },
            "tests": {}
        }
    
    def _get_system_info(self) -> Dict[str, Any]:
        """Coleta informações do sistema"""
        try:
            import psutil
            import platform
            
            system_info = {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "cpu_count": psutil.cpu_count(),
                "memory_gb": psutil.virtual_memory().total / (1024**3),
                "python_version": platform.python_version()
            }
            
            # GPU info se disponível
            try:
                import torch
                if torch.cuda.is_available():
                    gpu_info = []
                    for i in range(torch.cuda.device_count()):
                        props = torch.cuda.get_device_properties(i)
                        gpu_info.append({
                            "name": props.name,
                            "memory_gb": props.total_memory / (1024**3)
                        })
                    system_info["gpu"] = gpu_info
                else:
                    system_info["gpu"] = "Not available"
            except ImportError:
                system_info["gpu"] = "PyTorch not available"
            
            return system_info
            
        except Exception as e:
            return {"error": str(e)}
    
    def generate_test_images(self, count: int = 10) -> List[str]:
        """Gera imagens de teste sintéticas"""
        console.print("🎨 Generating synthetic test images...", style="blue")
        
        test_texts = [
            "The quick brown fox jumps over the lazy dog.",
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "1234567890 !@#$%^&*() ABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "Simple text for testing OCR accuracy and speed.",
            "This is a longer text with multiple sentences. It contains various punctuation marks! And numbers like 42, 100, and 2023.",
            "Mixed CASE text with Numbers 123 and Symbols @#$%",
            "Handwritten style text simulation",
            "Table data: Item | Price | Quantity\nApple | $2.50 | 10\nBread | $1.99 | 5",
            "Technical text: def main():\n    print('Hello World')\n    return 0",
            "International: café, naïve, résumé, piñata"
        ]
        
        image_paths = []
        
        for i, text in enumerate(test_texts[:count]):
            # Criar imagem
            width, height = 800, 200
            image = Image.new('RGB', (width, height), 'white')
            draw = ImageDraw.Draw(image)
            
            try:
                # Tentar usar fonte melhor
                font = ImageFont.truetype("arial.ttf", 24)
            except:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 24)
                except:
                    font = ImageFont.load_default()
            
            # Adicionar texto
            draw.text((20, 50), text, fill='black', font=font)
            
            # Adicionar ruído para simular diferentes qualidades
            if i % 3 == 1:  # Adicionar ruído leve
                pixels = np.array(image)
                noise = np.random.randint(0, 50, pixels.shape)
                pixels = np.clip(pixels + noise, 0, 255)
                image = Image.fromarray(pixels.astype(np.uint8))
            elif i % 3 == 2:  # Rotacionar levemente
                image = image.rotate(1.5, fillcolor='white')
            
            # Salvar
            filename = f"test_image_{i:02d}.png"
            temp_path = Path(tempfile.gettempdir()) / filename
            image.save(temp_path)
            image_paths.append(str(temp_path))
            
            self.test_images.append({
                "path": str(temp_path),
                "text": text,
                "type": "synthetic",
                "complexity": "simple" if i < 3 else "medium" if i < 7 else "complex"
            })
        
        console.print(f"✅ Generated {len(image_paths)} test images")
        return image_paths
    
    def test_api_health(self) -> bool:
        """Testa se a API está funcionando"""
        try:
            response = requests.get(f"{self.api_url}/api/v1/health", timeout=10)
            if response.status_code == 200:
                health_data = response.json()
                console.print(f"✅ API is healthy: {health_data.get('status', 'unknown')}")
                return True
            else:
                console.print(f"❌ API health check failed: {response.status_code}")
                return False
        except Exception as e:
            console.print(f"❌ API connection failed: {e}")
            return False
    
    def benchmark_single_image(self, image_path: str, engine: str, 
                             parameters: Dict[str, Any] = None) -> Dict[str, Any]:
        """Benchmark de uma única imagem com um engine"""
        start_time = time.time()
        
        try:
            # Preparar dados
            files = {'file': open(image_path, 'rb')}
            data = {
                'engine': engine,
                'async_processing': 'false'
            }
            
            if parameters:
                data.update(parameters)
            
            # Fazer request
            response = requests.post(
                f"{self.api_url}/api/v1/ocr",
                files=files,
                data=data,
                timeout=300
            )
            
            processing_time = time.time() - start_time
            
            files['file'].close()
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "processing_time": processing_time,
                    "response_time": processing_time,
                    "text": result.get("text", ""),
                    "confidence": result.get("confidence", 0.0),
                    "blocks": len(result.get("blocks", [])),
                    "engine_time": result.get("processing_time", 0.0),
                    "text_length": len(result.get("text", "")),
                    "word_count": len(result.get("text", "").split())
                }
            else:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                    "processing_time": processing_time,
                    "response_time": processing_time
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "processing_time": time.time() - start_time,
                "response_time": time.time() - start_time
            }
    
    def benchmark_engine_performance(self, engine: str, iterations: int = 5) -> Dict[str, Any]:
        """Benchmark de performance de um engine específico"""
        console.print(f"🔧 Benchmarking {engine} engine ({iterations} iterations)...")
        
        results = {
            "engine": engine,
            "iterations": iterations,
            "total_images": len(self.test_images),
            "results": [],
            "summary": {}
        }
        
        all_times = []
        all_confidences = []
        successful_runs = 0
        total_characters = 0
        total_words = 0
        
        with Progress() as progress:
            task = progress.add_task(f"Testing {engine}", total=iterations * len(self.test_images))
            
            for iteration in range(iterations):
                for img_idx, test_image in enumerate(self.test_images):
                    result = self.benchmark_single_image(test_image["path"], engine)
                    
                    if result["success"]:
                        all_times.append(result["processing_time"])
                        all_confidences.append(result["confidence"])
                        total_characters += result["text_length"]
                        total_words += result["word_count"]
                        successful_runs += 1
                    
                    result["iteration"] = iteration
                    result["image_index"] = img_idx
                    result["expected_text"] = test_image["text"]
                    result["complexity"] = test_image["complexity"]
                    
                    results["results"].append(result)
                    progress.advance(task)
        
        # Calcular estatísticas
        if all_times:
            results["summary"] = {
                "success_rate": successful_runs / (iterations * len(self.test_images)) * 100,
                "avg_processing_time": statistics.mean(all_times),
                "median_processing_time": statistics.median(all_times),
                "min_processing_time": min(all_times),
                "max_processing_time": max(all_times),
                "std_processing_time": statistics.stdev(all_times) if len(all_times) > 1 else 0,
                "avg_confidence": statistics.mean(all_confidences) if all_confidences else 0,
                "throughput_images_per_second": successful_runs / sum(all_times) if sum(all_times) > 0 else 0,
                "throughput_chars_per_second": total_characters / sum(all_times) if sum(all_times) > 0 else 0,
                "total_successful_runs": successful_runs,
                "total_failed_runs": (iterations * len(self.test_images)) - successful_runs
            }
        else:
            results["summary"] = {
                "success_rate": 0,
                "total_failed_runs": iterations * len(self.test_images)
            }
        
        return results
    
    def benchmark_accuracy(self, engine: str) -> Dict[str, Any]:
        """Benchmark de precisão de um engine"""
        console.print(f"🎯 Testing accuracy for {engine}...")
        
        accuracy_results = {
            "engine": engine,
            "tests": [],
            "summary": {}
        }
        
        total_accuracy = 0
        successful_tests = 0
        
        for test_image in self.test_images:
            result = self.benchmark_single_image(test_image["path"], engine)
            
            if result["success"]:
                expected_text = test_image["text"].lower().strip()
                actual_text = result["text"].lower().strip()
                
                # Calcular precisão simples (caracteres corretos)
                accuracy = self._calculate_text_similarity(expected_text, actual_text)
                
                test_result = {
                    "expected_text": test_image["text"],
                    "actual_text": result["text"],
                    "accuracy": accuracy,
                    "confidence": result["confidence"],
                    "complexity": test_image["complexity"],
                    "processing_time": result["processing_time"]
                }
                
                total_accuracy += accuracy
                successful_tests += 1
            else:
                test_result = {
                    "expected_text": test_image["text"],
                    "actual_text": "",
                    "accuracy": 0.0,
                    "error": result.get("error", "Unknown error"),
                    "complexity": test_image["complexity"]
                }
            
            accuracy_results["tests"].append(test_result)
        
        # Calcular estatísticas de precisão
        if successful_tests > 0:
            accuracy_results["summary"] = {
                "avg_accuracy": total_accuracy / successful_tests,
                "successful_tests": successful_tests,
                "failed_tests": len(self.test_images) - successful_tests,
                "success_rate": successful_tests / len(self.test_images) * 100
            }
        else:
            accuracy_results["summary"] = {
                "avg_accuracy": 0.0,
                "successful_tests": 0,
                "failed_tests": len(self.test_images),
                "success_rate": 0.0
            }
        
        return accuracy_results
    
    def _calculate_text_similarity(self, expected: str, actual: str) -> float:
        """Calcula similaridade entre textos esperado e atual"""
        if not expected and not actual:
            return 1.0
        if not expected or not actual:
            return 0.0
        
        # Algoritmo simples de distância de Levenshtein
        def levenshtein_distance(s1, s2):
            if len(s1) < len(s2):
                return levenshtein_distance(s2, s1)
            
            if len(s2) == 0:
                return len(s1)
            
            previous_row = list(range(len(s2) + 1))
            for i, c1 in enumerate(s1):
                current_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = previous_row[j + 1] + 1
                    deletions = current_row[j] + 1
                    substitutions = previous_row[j] + (c1 != c2)
                    current_row.append(min(insertions, deletions, substitutions))
                previous_row = current_row
            
            return previous_row[-1]
        
        distance = levenshtein_distance(expected, actual)
        max_len = max(len(expected), len(actual))
        similarity = 1.0 - (distance / max_len) if max_len > 0 else 1.0
        
        return max(0.0, similarity)
    
    def benchmark_concurrent_load(self, max_workers: int = 10, duration_seconds: int = 60) -> Dict[str, Any]:
        """Benchmark de carga concorrente"""
        console.print(f"⚡ Testing concurrent load ({max_workers} workers, {duration_seconds}s)...")
        
        start_time = time.time()
        end_time = start_time + duration_seconds
        
        completed_requests = []
        errors = []
        
        def worker_task():
            while time.time() < end_time:
                # Escolher engine e imagem aleatórios
                import random
                engine = random.choice(self.available_engines)
                test_image = random.choice(self.test_images)
                
                result = self.benchmark_single_image(test_image["path"], engine)
                
                if result["success"]:
                    completed_requests.append(result)
                else:
                    errors.append(result)
        
        # Executar workers concorrentes
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker_task) for _ in range(max_workers)]
            
            # Aguardar conclusão
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    errors.append({"error": str(e)})
        
        total_time = time.time() - start_time
        
        # Calcular estatísticas
        load_results = {
            "max_workers": max_workers,
            "duration_seconds": duration_seconds,
            "actual_duration": total_time,
            "completed_requests": len(completed_requests),
            "errors": len(errors),
            "success_rate": len(completed_requests) / (len(completed_requests) + len(errors)) * 100 if (len(completed_requests) + len(errors)) > 0 else 0,
            "requests_per_second": len(completed_requests) / total_time if total_time > 0 else 0
        }
        
        if completed_requests:
            response_times = [r["response_time"] for r in completed_requests]
            load_results.update({
                "avg_response_time": statistics.mean(response_times),
                "median_response_time": statistics.median(response_times),
                "min_response_time": min(response_times),
                "max_response_time": max(response_times),
                "p95_response_time": np.percentile(response_times, 95),
                "p99_response_time": np.percentile(response_times, 99)
            })
        
        return load_results
    
    def run_full_benchmark(self, iterations: int = 3, include_accuracy: bool = True, 
                          include_load_test: bool = True) -> Dict[str, Any]:
        """Executa benchmark completo"""
        console.print("🚀 Starting comprehensive OCR Platform benchmark...", style="bold blue")
        
        # Verificar saúde da API
        if not self.test_api_health():
            raise RuntimeError("API is not healthy, cannot proceed with benchmark")
        
        # Gerar imagens de teste
        self.generate_test_images()
        
        # Benchmark de performance por engine
        console.print("\n📊 Performance Benchmarks", style="bold green")
        for engine in self.available_engines:
            self.results["tests"][f"{engine}_performance"] = self.benchmark_engine_performance(engine, iterations)
        
        # Benchmark de precisão
        if include_accuracy:
            console.print("\n🎯 Accuracy Benchmarks", style="bold green")
            for engine in self.available_engines:
                self.results["tests"][f"{engine}_accuracy"] = self.benchmark_accuracy(engine)
        
        # Teste de carga
        if include_load_test:
            console.print("\n⚡ Load Testing", style="bold green")
            self.results["tests"]["concurrent_load"] = self.benchmark_concurrent_load()
        
        return self.results
    
    def generate_report(self, output_file: str = None) -> str:
        """Gera relatório do benchmark"""
        console.print("\n📋 Generating benchmark report...", style="blue")
        
        # Relatório em texto
        report_lines = [
            "=" * 80,
            "OCR PLATFORM BENCHMARK REPORT",
            "=" * 80,
            f"Generated: {self.results['metadata']['timestamp']}",
            f"API URL: {self.results['metadata']['api_url']}",
            f"Available Engines: {', '.join(self.results['metadata']['available_engines'])}",
            "",
            "SYSTEM INFORMATION:",
            f"  Platform: {self.results['metadata']['system_info'].get('platform', 'Unknown')}",
            f"  CPU Cores: {self.results['metadata']['system_info'].get('cpu_count', 'Unknown')}",
            f"  Memory: {self.results['metadata']['system_info'].get('memory_gb', 0):.1f} GB",
            f"  GPU: {self.results['metadata']['system_info'].get('gpu', 'Unknown')}",
            "",
            "PERFORMANCE RESULTS:",
            "-" * 40
        ]
        
        # Resumo de performance por engine
        performance_table = Table(title="Engine Performance Summary")
        performance_table.add_column("Engine", style="cyan")
        performance_table.add_column("Success Rate", style="green")
        performance_table.add_column("Avg Time (s)", style="yellow")
        performance_table.add_column("Throughput (img/s)", style="blue")
        performance_table.add_column("Avg Confidence", style="magenta")
        
        for engine in self.available_engines:
            perf_key = f"{engine}_performance"
            if perf_key in self.results["tests"]:
                summary = self.results["tests"][perf_key]["summary"]
                performance_table.add_row(
                    engine,
                    f"{summary.get('success_rate', 0):.1f}%",
                    f"{summary.get('avg_processing_time', 0):.2f}",
                    f"{summary.get('throughput_images_per_second', 0):.2f}",
                    f"{summary.get('avg_confidence', 0):.2f}"
                )
                
                # Adicionar ao relatório de texto
                report_lines.extend([
                    f"{engine.upper()}:",
                    f"  Success Rate: {summary.get('success_rate', 0):.1f}%",
                    f"  Avg Processing Time: {summary.get('avg_processing_time', 0):.2f}s",
                    f"  Throughput: {summary.get('throughput_images_per_second', 0):.2f} images/s",
                    f"  Avg Confidence: {summary.get('avg_confidence', 0):.2f}",
                    ""
                ])
        
        console.print(performance_table)
        
        # Precisão se disponível
        if any(f"{engine}_accuracy" in self.results["tests"] for engine in self.available_engines):
            report_lines.extend([
                "ACCURACY RESULTS:",
                "-" * 40
            ])
            
            accuracy_table = Table(title="Engine Accuracy Summary")
            accuracy_table.add_column("Engine", style="cyan")
            accuracy_table.add_column("Avg Accuracy", style="green")
            accuracy_table.add_column("Success Rate", style="yellow")
            
            for engine in self.available_engines:
                acc_key = f"{engine}_accuracy"
                if acc_key in self.results["tests"]:
                    summary = self.results["tests"][acc_key]["summary"]
                    accuracy_table.add_row(
                        engine,
                        f"{summary.get('avg_accuracy', 0):.1f}%",
                        f"{summary.get('success_rate', 0):.1f}%"
                    )
                    
                    report_lines.extend([
                        f"{engine.upper()}:",
                        f"  Avg Accuracy: {summary.get('avg_accuracy', 0):.1f}%",
                        f"  Success Rate: {summary.get('success_rate', 0):.1f}%",
                        ""
                    ])
            
            console.print(accuracy_table)
        
        # Teste de carga se disponível
        if "concurrent_load" in self.results["tests"]:
            load_results = self.results["tests"]["concurrent_load"]
            
            report_lines.extend([
                "LOAD TEST RESULTS:",
                "-" * 40,
                f"  Max Workers: {load_results.get('max_workers', 0)}",
                f"  Duration: {load_results.get('duration_seconds', 0)}s",
                f"  Completed Requests: {load_results.get('completed_requests', 0)}",
                f"  Requests/Second: {load_results.get('requests_per_second', 0):.2f}",
                f"  Success Rate: {load_results.get('success_rate', 0):.1f}%",
                f"  Avg Response Time: {load_results.get('avg_response_time', 0):.2f}s",
                f"  P95 Response Time: {load_results.get('p95_response_time', 0):.2f}s",
                ""
            ])
            
            load_table = Table(title="Load Test Results")
            load_table.add_column("Metric", style="cyan")
            load_table.add_column("Value", style="white")
            
            load_table.add_row("Requests/Second", f"{load_results.get('requests_per_second', 0):.2f}")
            load_table.add_row("Success Rate", f"{load_results.get('success_rate', 0):.1f}%")
            load_table.add_row("Avg Response Time", f"{load_results.get('avg_response_time', 0):.2f}s")
            load_table.add_row("P95 Response Time", f"{load_results.get('p95_response_time', 0):.2f}s")
            
            console.print(load_table)
        
        report_lines.append("=" * 80)
        
        # Salvar relatório
        report_text = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(report_text)
            console.print(f"📄 Report saved to: {output_file}")
        
        return report_text
    
    def save_results(self, filename: str):
        """Salva resultados em JSON"""
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        console.print(f"💾 Results saved to: {filename}")
    
    def cleanup(self):
        """Limpa arquivos temporários"""
        for test_image in self.test_images:
            try:
                Path(test_image["path"]).unlink(missing_ok=True)
            except Exception:
                pass


def main():
    """Função principal"""
    parser = argparse.ArgumentParser(description="OCR Platform Benchmark Suite")
    parser.add_argument("--api-url", help="API URL (default: from config)")
    parser.add_argument("--iterations", type=int, default=3, help="Number of iterations per engine")
    parser.add_argument("--images", type=int, default=10, help="Number of test images to generate")
    parser.add_argument("--no-accuracy", action="store_true", help="Skip accuracy tests")
    parser.add_argument("--no-load", action="store_true", help="Skip load tests")
    parser.add_argument("--load-workers", type=int, default=10, help="Concurrent workers for load test")
    parser.add_argument("--load-duration", type=int, default=60, help="Load test duration (seconds)")
    parser.add_argument("--output-json", help="Save JSON results to file")
    parser.add_argument("--output-report", help="Save text report to file")
    parser.add_argument("--engines", nargs="+", help="Specific engines to test")
    
    args = parser.parse_args()
    
    # Banner
    console.print("🏁 OCR Platform Benchmark Suite", style="bold blue")
    console.print("=" * 60)
    
    try:
        # Inicializar benchmark
        benchmark = BenchmarkSuite(args.api_url)
        
        # Filtrar engines se especificado
        if args.engines:
            available = set(benchmark.available_engines)
            requested = set(args.engines)
            invalid = requested - available
            
            if invalid:
                console.print(f"❌ Invalid engines: {', '.join(invalid)}", style="red")
                console.print(f"Available engines: {', '.join(available)}")
                sys.exit(1)
            
            benchmark.available_engines = list(requested & available)
        
        # Configurar número de imagens
        if args.images != 10:
            benchmark.test_images = []  # Reset for custom count
        
        # Executar benchmark
        results = benchmark.run_full_benchmark(
            iterations=args.iterations,
            include_accuracy=not args.no_accuracy,
            include_load_test=not args.no_load
        )
        
        # Gerar relatório
        report = benchmark.generate_report(args.output_report)
        
        # Salvar resultados JSON
        if args.output_json:
            benchmark.save_results(args.output_json)
        else:
            # Salvar com timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            benchmark.save_results(f"benchmark_results_{timestamp}.json")
        
        console.print("\n✅ Benchmark completed successfully!", style="bold green")
        
    except KeyboardInterrupt:
        console.print("\n⏹️  Benchmark interrupted by user", style="yellow")
    except Exception as e:
        console.print(f"\n❌ Benchmark failed: {e}", style="red")
        sys.exit(1)
    finally:
        # Limpeza
        try:
            benchmark.cleanup()
        except:
            pass


if __name__ == "__main__":
    main()