#!/usr/bin/env python3
"""
Cliente Redis para OCR Platform
==============================

Gerencia conexões Redis para:
- Cache de resultados
- Armazenamento de métricas  
- Estado de workers
- Configurações dinâmicas
"""

import redis
import json
import pickle
import logging
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

from .config import settings, redis_settings

logger = logging.getLogger(__name__)


class RedisClient:
    """Cliente Redis com funcionalidades específicas para OCR"""
    
    def __init__(self):
        self._client = None
        self._connection_pool = None
        self._setup_connection()
    
    def _setup_connection(self):
        """Configura pool de conexões Redis"""
        try:
            self._connection_pool = redis.ConnectionPool(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                db=settings.REDIS_DB,
                max_connections=redis_settings.REDIS_MAX_CONNECTIONS,
                retry_on_timeout=redis_settings.REDIS_RETRY_ON_TIMEOUT,
                socket_timeout=redis_settings.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=redis_settings.REDIS_SOCKET_CONNECT_TIMEOUT,
                **redis_settings.REDIS_CONNECTION_POOL_KWARGS
            )
            
            self._client = redis.Redis(connection_pool=self._connection_pool)
            
            # Testar conexão
            self._client.ping()
            logger.info("Redis connection established successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    @property
    def client(self) -> redis.Redis:
        """Retorna cliente Redis"""
        if not self._client:
            self._setup_connection()
        return self._client
    
    def ping(self) -> bool:
        """Testa conexão Redis"""
        try:
            return self.client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False
    
    def close(self):
        """Fecha conexões Redis"""
        if self._connection_pool:
            self._connection_pool.disconnect()
    
    # === CACHE METHODS ===
    
    def cache_set(self, key: str, value: Any, expires: int = None) -> bool:
        """Armazena valor no cache"""
        try:
            expires = expires or redis_settings.CACHE_EXPIRES
            serialized_value = json.dumps(value, default=str)
            return self.client.setex(f"cache:{key}", expires, serialized_value)
        except Exception as e:
            logger.error(f"Failed to set cache {key}: {e}")
            return False
    
    def cache_get(self, key: str, default: Any = None) -> Any:
        """Recupera valor do cache"""
        try:
            value = self.client.get(f"cache:{key}")
            if value:
                return json.loads(value)
            return default
        except Exception as e:
            logger.error(f"Failed to get cache {key}: {e}")
            return default
    
    def cache_delete(self, key: str) -> bool:
        """Remove valor do cache"""
        try:
            return bool(self.client.delete(f"cache:{key}"))
        except Exception as e:
            logger.error(f"Failed to delete cache {key}: {e}")
            return False
    
    def cache_exists(self, key: str) -> bool:
        """Verifica se chave existe no cache"""
        try:
            return bool(self.client.exists(f"cache:{key}"))
        except Exception as e:
            logger.error(f"Failed to check cache existence {key}: {e}")
            return False
    
    # === TASK RESULT METHODS ===
    
    def store_task_result(self, task_id: str, result: Dict[str, Any]) -> bool:
        """Armazena resultado de task"""
        try:
            serialized_result = pickle.dumps(result)
            return self.client.setex(
                f"task_result:{task_id}", 
                redis_settings.TASK_RESULT_EXPIRES, 
                serialized_result
            )
        except Exception as e:
            logger.error(f"Failed to store task result {task_id}: {e}")
            return False
    
    def get_task_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Recupera resultado de task"""
        try:
            result = self.client.get(f"task_result:{task_id}")
            if result:
                return pickle.loads(result)
            return None
        except Exception as e:
            logger.error(f"Failed to get task result {task_id}: {e}")
            return None
    
    def delete_task_result(self, task_id: str) -> bool:
        """Remove resultado de task"""
        try:
            return bool(self.client.delete(f"task_result:{task_id}"))
        except Exception as e:
            logger.error(f"Failed to delete task result {task_id}: {e}")
            return False
    
    # === METRICS METHODS ===
    
    def increment_metric(self, metric_name: str, value: int = 1, tags: Dict[str, str] = None) -> bool:
        """Incrementa métrica"""
        try:
            key = self._build_metric_key(metric_name, tags)
            return bool(self.client.hincrby(key, "value", value))
        except Exception as e:
            logger.error(f"Failed to increment metric {metric_name}: {e}")
            return False
    
    def set_metric(self, metric_name: str, value: Union[int, float], tags: Dict[str, str] = None) -> bool:
        """Define valor de métrica"""
        try:
            key = self._build_metric_key(metric_name, tags)
            return bool(self.client.hset(key, "value", value))
        except Exception as e:
            logger.error(f"Failed to set metric {metric_name}: {e}")
            return False
    
    def get_metric(self, metric_name: str, tags: Dict[str, str] = None) -> Optional[float]:
        """Recupera valor de métrica"""
        try:
            key = self._build_metric_key(metric_name, tags)
            value = self.client.hget(key, "value")
            return float(value) if value else None
        except Exception as e:
            logger.error(f"Failed to get metric {metric_name}: {e}")
            return None
    
    def _build_metric_key(self, metric_name: str, tags: Dict[str, str] = None) -> str:
        """Constrói chave de métrica com tags"""
        key = f"metric:{metric_name}"
        if tags:
            tag_string = ",".join([f"{k}={v}" for k, v in sorted(tags.items())])
            key += f":{tag_string}"
        return key
    
    # === WORKER STATE METHODS ===
    
    def register_worker(self, worker_name: str, worker_info: Dict[str, Any]) -> bool:
        """Registra worker ativo"""
        try:
            key = f"worker:{worker_name}"
            return bool(self.client.hset(key, mapping=worker_info))
        except Exception as e:
            logger.error(f"Failed to register worker {worker_name}: {e}")
            return False
    
    def update_worker_heartbeat(self, worker_name: str) -> bool:
        """Atualiza heartbeat do worker"""
        try:
            key = f"worker:{worker_name}"
            return bool(self.client.hset(key, "last_heartbeat", int(time.time())))
        except Exception as e:
            logger.error(f"Failed to update worker heartbeat {worker_name}: {e}")
            return False
    
    def get_active_workers(self) -> Dict[str, Dict[str, Any]]:
        """Retorna workers ativos"""
        try:
            workers = {}
            for key in self.client.scan_iter(match="worker:*"):
                worker_name = key.decode().replace("worker:", "")
                worker_data = self.client.hgetall(key)
                
                if worker_data:
                    # Converter bytes para strings
                    worker_info = {k.decode(): v.decode() for k, v in worker_data.items()}
                    workers[worker_name] = worker_info
            
            return workers
        except Exception as e:
            logger.error(f"Failed to get active workers: {e}")
            return {}
    
    def remove_worker(self, worker_name: str) -> bool:
        """Remove worker da lista de ativos"""
        try:
            return bool(self.client.delete(f"worker:{worker_name}"))
        except Exception as e:
            logger.error(f"Failed to remove worker {worker_name}: {e}")
            return False
    
    # === QUEUE METHODS ===
    
    def get_queue_length(self, queue_name: str) -> int:
        """Retorna tamanho da fila"""
        try:
            return self.client.llen(queue_name)
        except Exception as e:
            logger.error(f"Failed to get queue length {queue_name}: {e}")
            return 0
    
    def get_all_queue_lengths(self) -> Dict[str, int]:
        """Retorna tamanho de todas as filas"""
        queue_lengths = {}
        for queue_name in settings.QUEUE_CONFIG.keys():
            queue_lengths[queue_name] = self.get_queue_length(queue_name)
        return queue_lengths
    
    # === CONFIGURATION METHODS ===
    
    def set_config(self, config_key: str, config_value: Any) -> bool:
        """Armazena configuração dinâmica"""
        try:
            serialized_value = json.dumps(config_value, default=str)
            return bool(self.client.set(f"config:{config_key}", serialized_value))
        except Exception as e:
            logger.error(f"Failed to set config {config_key}: {e}")
            return False
    
    def get_config(self, config_key: str, default: Any = None) -> Any:
        """Recupera configuração dinâmica"""
        try:
            value = self.client.get(f"config:{config_key}")
            if value:
                return json.loads(value)
            return default
        except Exception as e:
            logger.error(f"Failed to get config {config_key}: {e}")
            return default
    
    # === RATE LIMITING METHODS ===
    
    def check_rate_limit(self, identifier: str, limit: int, window: int) -> bool:
        """Verifica rate limiting"""
        try:
            key = f"rate_limit:{identifier}"
            current = self.client.get(key)
            
            if current is None:
                # Primeira requisição na janela
                self.client.setex(key, window, 1)
                return True
            
            current_count = int(current)
            if current_count >= limit:
                return False
            
            # Incrementar contador
            self.client.incr(key)
            return True
            
        except Exception as e:
            logger.error(f"Failed to check rate limit {identifier}: {e}")
            return True  # Em caso de erro, permitir
    
    # === HEALTH CHECK METHODS ===
    
    def health_check(self) -> Dict[str, Any]:
        """Verifica saúde do Redis"""
        try:
            start_time = time.time()
            
            # Teste de ping
            ping_success = self.ping()
            ping_time = time.time() - start_time
            
            # Informações de memória
            memory_info = self.client.info('memory')
            
            # Informações de conexões
            clients_info = self.client.info('clients')
            
            # Estatísticas gerais
            stats_info = self.client.info('stats')
            
            return {
                "status": "healthy" if ping_success else "unhealthy",
                "ping_time_ms": round(ping_time * 1000, 2),
                "memory": {
                    "used_memory_human": memory_info.get('used_memory_human'),
                    "used_memory_peak_human": memory_info.get('used_memory_peak_human'),
                    "memory_fragmentation_ratio": memory_info.get('mem_fragmentation_ratio')
                },
                "connections": {
                    "connected_clients": clients_info.get('connected_clients'),
                    "blocked_clients": clients_info.get('blocked_clients')
                },
                "stats": {
                    "total_commands_processed": stats_info.get('total_commands_processed'),
                    "instantaneous_ops_per_sec": stats_info.get('instantaneous_ops_per_sec')
                }
            }
            
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e)
            }


# Instância global do cliente Redis
_redis_client = None


def get_redis_client() -> RedisClient:
    """Retorna instância global do Redis client"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client


@contextmanager
def redis_lock(lock_name: str, timeout: int = 10):
    """Context manager para locks distribuídos"""
    client = get_redis_client()
    lock_key = f"lock:{lock_name}"
    
    try:
        # Tentar adquirir lock
        acquired = client.client.set(lock_key, "locked", nx=True, ex=timeout)
        if not acquired:
            raise RuntimeError(f"Could not acquire lock: {lock_name}")
        
        yield
        
    finally:
        # Liberar lock
        try:
            client.client.delete(lock_key)
        except Exception as e:
            logger.warning(f"Failed to release lock {lock_name}: {e}")


if __name__ == "__main__":
    """Teste do cliente Redis"""
    import time
    
    print("=== Redis Client Test ===")
    
    client = get_redis_client()
    
    # Teste de conexão
    if client.ping():
        print("✅ Redis connection successful")
    else:
        print("❌ Redis connection failed")
        exit(1)
    
    # Teste de cache
    print("\n--- Cache Test ---")
    client.cache_set("test_key", {"message": "Hello Redis!"}, 60)
    cached_value = client.cache_get("test_key")
    print(f"Cached value: {cached_value}")
    
    # Teste de métricas
    print("\n--- Metrics Test ---")
    client.increment_metric("test_metric", 5, {"engine": "test"})
    metric_value = client.get_metric("test_metric", {"engine": "test"})
    print(f"Metric value: {metric_value}")
    
    # Teste de health check
    print("\n--- Health Check ---")
    health = client.health_check()
    print(f"Health status: {health['status']}")
    print(f"Ping time: {health['ping_time_ms']}ms")
    
    # Teste de lock
    print("\n--- Lock Test ---")
    try:
        with redis_lock("test_lock", 5):
            print("Lock acquired successfully")
            time.sleep(1)
        print("Lock released successfully")
    except Exception as e:
        print(f"Lock test failed: {e}")
    
    print("\n✅ All tests completed")