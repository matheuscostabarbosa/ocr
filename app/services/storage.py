#!/usr/bin/env python3
"""
Serviço de Armazenamento
========================

Gerencia armazenamento de arquivos e resultados:
- Armazenamento local e em nuvem
- Gestão de uploads e downloads
- Limpeza automática de arquivos temporários
- Backup e versionamento
- Compressão e otimização
- Cache de arquivos
"""

import os
import shutil
import tempfile
import gzip
import zipfile
import hashlib
import time
import json
import logging
from typing import Dict, Any, List, Optional, Union, BinaryIO
from pathlib import Path
from datetime import datetime, timedelta
import mimetypes

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.models.schemas import FileInfo, FileCategory

logger = logging.getLogger(__name__)


class StorageService:
    """Serviço de armazenamento de arquivos"""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        
        # Configurações
        self.storage_type = settings.STORAGE_TYPE
        self.upload_dir = Path(settings.UPLOAD_DIR)
        self.result_dir = Path(settings.RESULT_DIR)
        self.temp_dir = Path(settings.TEMP_DIR)
        
        # Configurações avançadas
        self.enable_compression = True
        self.enable_deduplication = True
        self.enable_auto_cleanup = True
        self.max_file_age_days = 7
        self.cleanup_interval_hours = 6
        
        # Cache de metadados
        self.file_metadata_cache = {}
        self.cache_ttl = 3600  # 1 hora
        
        # Métricas
        self.files_stored = 0
        self.files_retrieved = 0
        self.bytes_stored = 0
        self.bytes_retrieved = 0
        self.deduplication_saves = 0
        
        # Criar diretórios
        self._ensure_directories()
        
        # Inicializar storage específico
        self._init_storage_backend()
    
    def _ensure_directories(self):
        """Garante que diretórios necessários existem"""
        for directory in [self.upload_dir, self.result_dir, self.temp_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")
    
    def _init_storage_backend(self):
        """Inicializa backend de storage específico"""
        if self.storage_type == "local":
            self.backend = LocalStorageBackend(self.upload_dir, self.result_dir, self.temp_dir)
        elif self.storage_type == "s3":
            self.backend = S3StorageBackend()
        elif self.storage_type == "gcs":
            self.backend = GCSStorageBackend()
        else:
            logger.warning(f"Unknown storage type: {self.storage_type}, falling back to local")
            self.backend = LocalStorageBackend(self.upload_dir, self.result_dir, self.temp_dir)
    
    def store_file(self, file_content: Union[bytes, BinaryIO], filename: str, 
                   category: str = "upload", metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Armazena arquivo
        
        Args:
            file_content: Conteúdo do arquivo ou file-like object
            filename: Nome do arquivo
            category: Categoria (upload, result, temp)
            metadata: Metadados adicionais
            
        Returns:
            Dict com informações do arquivo armazenado
        """
        try:
            self.files_stored += 1
            start_time = time.time()
            
            # Ler conteúdo se for file-like object
            if hasattr(file_content, 'read'):
                content = file_content.read()
            else:
                content = file_content
            
            # Calcular hash para deduplicação
            content_hash = hashlib.sha256(content).hexdigest()
            
            # Verificar deduplicação
            if self.enable_deduplication:
                existing_file = self._check_deduplication(content_hash, category)
                if existing_file:
                    self.deduplication_saves += 1
                    logger.debug(f"File deduplicated: {filename} -> {existing_file['file_path']}")
                    return existing_file
            
            # Determinar caminho de armazenamento
            file_path = self._generate_file_path(filename, category, content_hash)
            
            # Aplicar compressão se habilitada
            if self.enable_compression and self._should_compress(filename, len(content)):
                content, compressed = self._compress_content(content, filename)
                if compressed:
                    file_path = file_path + ".gz"
            else:
                compressed = False
            
            # Armazenar arquivo
            stored_path = self.backend.store_file(content, file_path)
            
            # Criar metadados
            file_metadata = {
                "file_id": content_hash[:16],
                "original_filename": filename,
                "stored_path": stored_path,
                "file_path": file_path,
                "category": category,
                "size": len(content),
                "content_hash": content_hash,
                "compressed": compressed,
                "mime_type": mimetypes.guess_type(filename)[0],
                "stored_at": time.time(),
                "access_count": 0,
                "last_accessed": time.time(),
                "metadata": metadata or {}
            }
            
            # Salvar metadados
            self._save_file_metadata(content_hash, file_metadata)
            
            # Atualizar métricas
            self.bytes_stored += len(content)
            storage_time = time.time() - start_time
            
            # Registrar métricas
            self._record_storage_metrics("store", len(content), storage_time, category)
            
            logger.info(f"File stored: {filename} -> {stored_path} ({len(content)} bytes)")
            
            return {
                "file_id": file_metadata["file_id"],
                "file_path": stored_path,
                "size": len(content),
                "compressed": compressed,
                "storage_time": storage_time,
                "deduplicated": False
            }
            
        except Exception as e:
            logger.error(f"File storage failed for {filename}: {e}")
            raise
    
    def retrieve_file(self, file_id: str, decompress: bool = True) -> Dict[str, Any]:
        """
        Recupera arquivo
        
        Args:
            file_id: ID do arquivo
            decompress: Se deve descomprimir automaticamente
            
        Returns:
            Dict com conteúdo e metadados do arquivo
        """
        try:
            self.files_retrieved += 1
            start_time = time.time()
            
            # Obter metadados
            metadata = self._get_file_metadata(file_id)
            if not metadata:
                raise FileNotFoundError(f"File not found: {file_id}")
            
            # Recuperar arquivo
            content = self.backend.retrieve_file(metadata["stored_path"])
            
            # Descomprimir se necessário
            if decompress and metadata.get("compressed", False):
                content = self._decompress_content(content)
            
            # Atualizar metadados de acesso
            metadata["access_count"] = metadata.get("access_count", 0) + 1
            metadata["last_accessed"] = time.time()
            self._save_file_metadata(metadata["content_hash"], metadata)
            
            # Atualizar métricas
            self.bytes_retrieved += len(content)
            retrieval_time = time.time() - start_time
            
            # Registrar métricas
            self._record_storage_metrics("retrieve", len(content), retrieval_time, metadata["category"])
            
            logger.debug(f"File retrieved: {file_id} ({len(content)} bytes)")
            
            return {
                "content": content,
                "metadata": metadata,
                "retrieval_time": retrieval_time
            }
            
        except Exception as e:
            logger.error(f"File retrieval failed for {file_id}: {e}")
            raise
    
    def store_result(self, result_data: Dict[str, Any], task_id: str, 
                    format: str = "json") -> Dict[str, Any]:
        """
        Armazena resultado de processamento
        
        Args:
            result_data: Dados do resultado
            task_id: ID da task
            format: Formato de armazenamento
            
        Returns:
            Dict com informações do resultado armazenado
        """
        try:
            # Serializar dados
            if format == "json":
                content = json.dumps(result_data, default=str, ensure_ascii=False, indent=2).encode('utf-8')
                filename = f"result_{task_id}.json"
            else:
                raise ValueError(f"Unsupported result format: {format}")
            
            # Armazenar
            result = self.store_file(
                content, 
                filename, 
                category="result",
                metadata={
                    "task_id": task_id,
                    "format": format,
                    "type": "ocr_result"
                }
            )
            
            # Salvar referência no Redis
            self.redis_client.cache_set(f"result_file:{task_id}", {
                "file_id": result["file_id"],
                "file_path": result["file_path"],
                "format": format
            }, ttl=86400 * 7)  # 7 dias
            
            return result
            
        except Exception as e:
            logger.error(f"Result storage failed for task {task_id}: {e}")
            raise
    
    def retrieve_result(self, task_id: str) -> Dict[str, Any]:
        """
        Recupera resultado de processamento
        
        Args:
            task_id: ID da task
            
        Returns:
            Dict com dados do resultado
        """
        try:
            # Buscar referência no Redis
            result_ref = self.redis_client.cache_get(f"result_file:{task_id}")
            if not result_ref:
                raise FileNotFoundError(f"Result not found for task: {task_id}")
            
            # Recuperar arquivo
            file_data = self.retrieve_file(result_ref["file_id"])
            
            # Deserializar dados
            if result_ref["format"] == "json":
                result_data = json.loads(file_data["content"].decode('utf-8'))
            else:
                raise ValueError(f"Unsupported result format: {result_ref['format']}")
            
            return {
                "data": result_data,
                "metadata": file_data["metadata"],
                "retrieval_time": file_data["retrieval_time"]
            }
            
        except Exception as e:
            logger.error(f"Result retrieval failed for task {task_id}: {e}")
            raise
    
    def delete_file(self, file_id: str) -> bool:
        """
        Remove arquivo
        
        Args:
            file_id: ID do arquivo
            
        Returns:
            True se removido com sucesso
        """
        try:
            # Obter metadados
            metadata = self._get_file_metadata(file_id)
            if not metadata:
                logger.warning(f"File not found for deletion: {file_id}")
                return False
            
            # Remover arquivo físico
            success = self.backend.delete_file(metadata["stored_path"])
            
            if success:
                # Remover metadados
                self._delete_file_metadata(metadata["content_hash"])
                logger.info(f"File deleted: {file_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"File deletion failed for {file_id}: {e}")
            return False
    
    def cleanup_old_files(self, max_age_days: int = None) -> Dict[str, Any]:
        """
        Limpa arquivos antigos
        
        Args:
            max_age_days: Idade máxima em dias
            
        Returns:
            Dict com estatísticas da limpeza
        """
        try:
            max_age = max_age_days or self.max_file_age_days
            cutoff_time = time.time() - (max_age * 24 * 3600)
            
            cleanup_stats = {
                "files_checked": 0,
                "files_deleted": 0,
                "bytes_freed": 0,
                "errors": 0,
                "start_time": time.time()
            }
            
            # Buscar todos os arquivos
            all_files = self._list_all_files()
            
            for file_id, metadata in all_files.items():
                cleanup_stats["files_checked"] += 1
                
                try:
                    # Verificar idade
                    stored_at = metadata.get("stored_at", 0)
                    last_accessed = metadata.get("last_accessed", stored_at)
                    
                    # Usar último acesso ou data de armazenamento, o que for mais recente
                    file_age = max(stored_at, last_accessed)
                    
                    if file_age < cutoff_time:
                        # Arquivo antigo - deletar
                        if self.delete_file(file_id):
                            cleanup_stats["files_deleted"] += 1
                            cleanup_stats["bytes_freed"] += metadata.get("size", 0)
                        else:
                            cleanup_stats["errors"] += 1
                
                except Exception as e:
                    logger.warning(f"Error processing file {file_id} during cleanup: {e}")
                    cleanup_stats["errors"] += 1
            
            cleanup_stats["cleanup_time"] = time.time() - cleanup_stats["start_time"]
            
            logger.info(f"Cleanup completed: {cleanup_stats['files_deleted']} files deleted, "
                       f"{cleanup_stats['bytes_freed']} bytes freed")
            
            # Registrar métricas
            self._record_cleanup_metrics(cleanup_stats)
            
            return cleanup_stats
            
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            return {"error": str(e)}
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de armazenamento"""
        try:
            # Estatísticas básicas
            stats = {
                "files_stored": self.files_stored,
                "files_retrieved": self.files_retrieved,
                "bytes_stored": self.bytes_stored,
                "bytes_retrieved": self.bytes_retrieved,
                "deduplication_saves": self.deduplication_saves,
                "storage_type": self.storage_type,
                "directories": {
                    "upload_dir": str(self.upload_dir),
                    "result_dir": str(self.result_dir),
                    "temp_dir": str(self.temp_dir)
                }
            }
            
            # Estatísticas de disco
            try:
                disk_stats = {}
                for name, path in stats["directories"].items():
                    if Path(path).exists():
                        disk_usage = shutil.disk_usage(path)
                        disk_stats[name] = {
                            "total_gb": disk_usage.total / (1024**3),
                            "used_gb": (disk_usage.total - disk_usage.free) / (1024**3),
                            "free_gb": disk_usage.free / (1024**3),
                            "usage_percent": ((disk_usage.total - disk_usage.free) / disk_usage.total) * 100
                        }
                stats["disk_usage"] = disk_stats
            except Exception as e:
                logger.warning(f"Failed to get disk usage: {e}")
            
            # Estatísticas de arquivos
            try:
                all_files = self._list_all_files()
                file_stats = {
                    "total_files": len(all_files),
                    "total_size_bytes": sum(f.get("size", 0) for f in all_files.values()),
                    "by_category": defaultdict(int),
                    "by_type": defaultdict(int),
                    "compressed_files": 0,
                    "avg_file_size": 0
                }
                
                for metadata in all_files.values():
                    category = metadata.get("category", "unknown")
                    file_stats["by_category"][category] += 1
                    
                    mime_type = metadata.get("mime_type", "unknown")
                    if mime_type:
                        main_type = mime_type.split("/")[0]
                        file_stats["by_type"][main_type] += 1
                    
                    if metadata.get("compressed", False):
                        file_stats["compressed_files"] += 1
                
                if file_stats["total_files"] > 0:
                    file_stats["avg_file_size"] = file_stats["total_size_bytes"] / file_stats["total_files"]
                
                stats["file_statistics"] = dict(file_stats)
                stats["file_statistics"]["by_category"] = dict(file_stats["by_category"])
                stats["file_statistics"]["by_type"] = dict(file_stats["by_type"])
                
            except Exception as e:
                logger.warning(f"Failed to get file statistics: {e}")
            
            # Métricas do Redis
            try:
                redis_metrics = {
                    "total_store_operations": self.redis_client.get_metric("storage_store_operations") or 0,
                    "total_retrieve_operations": self.redis_client.get_metric("storage_retrieve_operations") or 0,
                    "total_bytes_stored": self.redis_client.get_metric("storage_bytes_stored") or 0,
                    "total_bytes_retrieved": self.redis_client.get_metric("storage_bytes_retrieved") or 0,
                    "last_cleanup_time": self.redis_client.get_metric("storage_last_cleanup") or 0
                }
                stats["redis_metrics"] = redis_metrics
            except Exception as e:
                logger.warning(f"Failed to get Redis metrics: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {"error": str(e)}
    
    def _generate_file_path(self, filename: str, category: str, content_hash: str) -> str:
        """Gera caminho único para arquivo"""
        # Usar primeiros caracteres do hash para distribuição
        prefix = content_hash[:2]
        
        # Manter extensão original
        ext = Path(filename).suffix
        
        # Gerar nome único
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_name = f"{timestamp}_{content_hash[:8]}{ext}"
        
        return f"{category}/{prefix}/{unique_name}"
    
    def _should_compress(self, filename: str, file_size: int) -> bool:
        """Determina se arquivo deve ser comprimido"""
        # Não comprimir arquivos pequenos
        if file_size < 1024:  # < 1KB
            return False
        
        # Não comprimir arquivos já comprimidos
        compressed_extensions = {'.gz', '.zip', '.rar', '.7z', '.bz2', '.xz'}
        if Path(filename).suffix.lower() in compressed_extensions:
            return False
        
        # Não comprimir imagens já comprimidas
        image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
        if Path(filename).suffix.lower() in image_extensions:
            return False
        
        return True
    
    def _compress_content(self, content: bytes, filename: str) -> Tuple[bytes, bool]:
        """Comprime conteúdo"""
        try:
            compressed = gzip.compress(content, compresslevel=6)
            
            # Só usar compressão se economizar pelo menos 10%
            if len(compressed) < len(content) * 0.9:
                return compressed, True
            else:
                return content, False
                
        except Exception as e:
            logger.warning(f"Compression failed for {filename}: {e}")
            return content, False
    
    def _decompress_content(self, content: bytes) -> bytes:
        """Descomprime conteúdo"""
        try:
            return gzip.decompress(content)
        except Exception as e:
            logger.warning(f"Decompression failed: {e}")
            return content
    
    def _check_deduplication(self, content_hash: str, category: str) -> Optional[Dict[str, Any]]:
        """Verifica se arquivo já existe (deduplicação)"""
        try:
            metadata = self._get_file_metadata_by_hash(content_hash)
            if metadata and metadata.get("category") == category:
                # Arquivo existe na mesma categoria
                return {
                    "file_id": metadata["content_hash"][:16],
                    "file_path": metadata["stored_path"],
                    "size": metadata["size"],
                    "compressed": metadata.get("compressed", False),
                    "storage_time": 0.0,
                    "deduplicated": True
                }
            return None
        except Exception:
            return None
    
    def _save_file_metadata(self, content_hash: str, metadata: Dict[str, Any]):
        """Salva metadados do arquivo"""
        try:
            # Cache local
            self.file_metadata_cache[content_hash] = metadata
            
            # Redis
            self.redis_client.cache_set(f"file_metadata:{content_hash}", metadata, ttl=86400 * 30)  # 30 dias
            
        except Exception as e:
            logger.warning(f"Failed to save file metadata: {e}")
    
    def _get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Obtém metadados por file_id"""
        # file_id são os primeiros 16 chars do hash
        for content_hash, metadata in self.file_metadata_cache.items():
            if content_hash.startswith(file_id):
                return metadata
        
        # Buscar no Redis
        try:
            keys = self.redis_client.client.keys(f"file_metadata:*")
            for key in keys:
                content_hash = key.decode().replace("file_metadata:", "")
                if content_hash.startswith(file_id):
                    metadata = self.redis_client.cache_get(f"file_metadata:{content_hash}")
                    if metadata:
                        return metadata
        except Exception as e:
            logger.warning(f"Failed to get file metadata from Redis: {e}")
        
        return None
    
    def _get_file_metadata_by_hash(self, content_hash: str) -> Optional[Dict[str, Any]]:
        """Obtém metadados por hash completo"""
        # Cache local
        if content_hash in self.file_metadata_cache:
            return self.file_metadata_cache[content_hash]
        
        # Redis
        try:
            metadata = self.redis_client.cache_get(f"file_metadata:{content_hash}")
            if metadata:
                self.file_metadata_cache[content_hash] = metadata
            return metadata
        except Exception as e:
            logger.warning(f"Failed to get file metadata by hash: {e}")
            return None
    
    def _delete_file_metadata(self, content_hash: str):
        """Remove metadados do arquivo"""
        try:
            # Cache local
            self.file_metadata_cache.pop(content_hash, None)
            
            # Redis
            self.redis_client.cache_delete(f"file_metadata:{content_hash}")
            
        except Exception as e:
            logger.warning(f"Failed to delete file metadata: {e}")
    
    def _list_all_files(self) -> Dict[str, Dict[str, Any]]:
        """Lista todos os arquivos e seus metadados"""
        try:
            all_files = {}
            
            # Cache local
            for content_hash, metadata in self.file_metadata_cache.items():
                file_id = content_hash[:16]
                all_files[file_id] = metadata
            
            # Redis
            try:
                keys = self.redis_client.client.keys("file_metadata:*")
                for key in keys:
                    content_hash = key.decode().replace("file_metadata:", "")
                    file_id = content_hash[:16]
                    
                    if file_id not in all_files:
                        metadata = self.redis_client.cache_get(f"file_metadata:{content_hash}")
                        if metadata:
                            all_files[file_id] = metadata
            except Exception as e:
                logger.warning(f"Failed to list files from Redis: {e}")
            
            return all_files
            
        except Exception as e:
            logger.warning(f"Failed to list all files: {e}")
            return {}
    
    def _record_storage_metrics(self, operation: str, bytes_count: int, duration: float, category: str):
        """Registra métricas de storage"""
        try:
            self.redis_client.increment_metric(f"storage_{operation}_operations")
            self.redis_client.set_metric(f"storage_bytes_{operation}d", bytes_count)
            self.redis_client.set_metric(f"storage_last_{operation}_time", duration)
            self.redis_client.increment_metric(f"storage_{operation}_by_category", tags={"category": category})
            
        except Exception as e:
            logger.warning(f"Failed to record storage metrics: {e}")
    
    def _record_cleanup_metrics(self, stats: Dict[str, Any]):
        """Registra métricas de limpeza"""
        try:
            self.redis_client.set_metric("storage_last_cleanup", time.time())
            self.redis_client.set_metric("storage_last_cleanup_files_deleted", stats["files_deleted"])
            self.redis_client.set_metric("storage_last_cleanup_bytes_freed", stats["bytes_freed"])
            self.redis_client.increment_metric("storage_cleanup_runs")
            
        except Exception as e:
            logger.warning(f"Failed to record cleanup metrics: {e}")


class LocalStorageBackend:
    """Backend de armazenamento local"""
    
    def __init__(self, upload_dir: Path, result_dir: Path, temp_dir: Path):
        self.upload_dir = upload_dir
        self.result_dir = result_dir
        self.temp_dir = temp_dir
        
        # Mapeamento de categorias para diretórios
        self.category_dirs = {
            "upload": upload_dir,
            "result": result_dir,
            "temp": temp_dir
        }
    
    def store_file(self, content: bytes, file_path: str) -> str:
        """Armazena arquivo localmente"""
        # Determinar diretório baseado na categoria
        category = file_path.split("/")[0]
        base_dir = self.category_dirs.get(category, self.temp_dir)
        
        # Caminho completo
        full_path = base_dir / file_path
        
        # Criar diretórios pai
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Escrever arquivo
        with open(full_path, 'wb') as f:
            f.write(content)
        
        return str(full_path)
    
    def retrieve_file(self, file_path: str) -> bytes:
        """Recupera arquivo local"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(path, 'rb') as f:
            return f.read()
    
    def delete_file(self, file_path: str) -> bool:
        """Remove arquivo local"""
        try:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete local file {file_path}: {e}")
            return False


class S3StorageBackend:
    """Backend de armazenamento S3 (placeholder)"""
    
    def __init__(self):
        # Inicialização do cliente S3
        logger.warning("S3 backend not implemented")
    
    def store_file(self, content: bytes, file_path: str) -> str:
        raise NotImplementedError("S3 backend not implemented")
    
    def retrieve_file(self, file_path: str) -> bytes:
        raise NotImplementedError("S3 backend not implemented")
    
    def delete_file(self, file_path: str) -> bool:
        raise NotImplementedError("S3 backend not implemented")


class GCSStorageBackend:
    """Backend de armazenamento Google Cloud Storage (placeholder)"""
    
    def __init__(self):
        # Inicialização do cliente GCS
        logger.warning("GCS backend not implemented")
    
    def store_file(self, content: bytes, file_path: str) -> str:
        raise NotImplementedError("GCS backend not implemented")
    
    def retrieve_file(self, file_path: str) -> bytes:
        raise NotImplementedError("GCS backend not implemented")
    
    def delete_file(self, file_path: str) -> bool:
        raise NotImplementedError("GCS backend not implemented")


# Instância global do serviço
storage_service = StorageService()


def get_storage_service() -> StorageService:
    """Retorna instância global do serviço de armazenamento"""
    return storage_service


if __name__ == "__main__":
    """Teste do serviço de armazenamento"""
    print("=== Storage Service Test ===")
    
    service = get_storage_service()
    
    # Teste de armazenamento
    test_content = b"This is a test file content for storage testing."
    test_filename = "test_file.txt"
    
    try:
        # Armazenar arquivo
        store_result = service.store_file(test_content, test_filename, category="temp")
        print(f"File stored:")
        print(f"  File ID: {store_result['file_id']}")
        print(f"  Size: {store_result['size']} bytes")
        print(f"  Compressed: {store_result['compressed']}")
        print(f"  Deduplicated: {store_result['deduplicated']}")
        
        # Recuperar arquivo
        file_id = store_result["file_id"]
        retrieve_result = service.retrieve_file(file_id)
        print(f"\nFile retrieved:")
        print(f"  Content length: {len(retrieve_result['content'])} bytes")
        print(f"  Content matches: {retrieve_result['content'] == test_content}")
        print(f"  Access count: {retrieve_result['metadata']['access_count']}")
        
        # Teste de resultado
        test_result = {
            "text": "Extracted text",
            "confidence": 0.95,
            "processing_time": 2.5
        }
        
        task_id = "test_task_123"
        result_store = service.store_result(test_result, task_id)
        print(f"\nResult stored:")
        print(f"  File ID: {result_store['file_id']}")
        print(f"  Size: {result_store['size']} bytes")
        
        # Recuperar resultado
        result_retrieve = service.retrieve_result(task_id)
        print(f"\nResult retrieved:")
        print(f"  Text: {result_retrieve['data']['text']}")
        print(f"  Confidence: {result_retrieve['data']['confidence']}")
        
        # Estatísticas
        stats = service.get_storage_stats()
        print(f"\nStorage statistics:")
        print(f"  Files stored: {stats['files_stored']}")
        print(f"  Files retrieved: {stats['files_retrieved']}")
        print(f"  Bytes stored: {stats['bytes_stored']}")
        print(f"  Storage type: {stats['storage_type']}")
        
        if 'file_statistics' in stats:
            file_stats = stats['file_statistics']
            print(f"  Total files: {file_stats['total_files']}")
            print(f"  Total size: {file_stats['total_size_bytes']} bytes")
        
        # Limpar arquivos de teste
        service.delete_file(file_id)
        service.delete_file(result_store["file_id"])
        print(f"\nTest files cleaned up")
        
    except Exception as e:
        print(f"❌ Storage test failed: {e}")
        raise
    
    print("\n✅ Storage Service test completed")