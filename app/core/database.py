#!/usr/bin/env python3
"""
Configuração de Banco de Dados (Opcional)
==========================================

Módulo opcional para persistência em banco de dados.
Por padrão, o sistema usa Redis para cache e estado.
Este módulo adiciona suporte para:
- Armazenamento persistente de tarefas
- Histórico de processamento
- Análise de performance
- Auditoria e logs
"""

import logging
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
from contextlib import asynccontextmanager
import json
from datetime import datetime, timedelta

from app.core.config import settings

logger = logging.getLogger(__name__)

# Variáveis globais
database_engine = None
session_factory = None
Base = None

# Flag para verificar se banco está habilitado
DATABASE_ENABLED = settings.DATABASE_ENABLED
DATABASE_URL = settings.DATABASE_URL


if DATABASE_ENABLED and DATABASE_URL:
    try:
        # Importações condicionais para banco de dados
        from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Text, JSON, Boolean
        from sqlalchemy.ext.declarative import declarative_base
        from sqlalchemy.orm import sessionmaker, Session
        from sqlalchemy.pool import StaticPool
        import sqlalchemy as sa
        
        # Configurar engine
        if DATABASE_URL.startswith("sqlite"):
            # SQLite com configurações específicas
            database_engine = create_engine(
                DATABASE_URL,
                poolclass=StaticPool,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 20
                },
                echo=settings.DEBUG
            )
        else:
            # PostgreSQL, MySQL, etc.
            database_engine = create_engine(
                DATABASE_URL,
                pool_pre_ping=True,
                pool_recycle=300,
                echo=settings.DEBUG
            )
        
        # Session factory
        session_factory = sessionmaker(autocommit=False, autoflush=False, bind=database_engine)
        
        # Base para modelos
        Base = declarative_base()
        
        logger.info(f"✅ Database configured: {DATABASE_URL.split('://')[0]}")
        
    except ImportError as e:
        logger.warning(f"Database dependencies not available: {e}")
        DATABASE_ENABLED = False
    except Exception as e:
        logger.error(f"Database configuration failed: {e}")
        DATABASE_ENABLED = False

else:
    logger.info("Database disabled or URL not configured")


# === MODELOS DE BANCO DE DADOS ===

if DATABASE_ENABLED:
    
    class TaskRecord(Base):
        """Registro de tarefa OCR"""
        __tablename__ = "tasks"
        
        id = Column(String, primary_key=True)
        file_path = Column(String, nullable=False)
        engine = Column(String, nullable=False)
        status = Column(String, nullable=False)
        priority = Column(Integer, default=5)
        
        # Timestamps
        created_at = Column(DateTime, default=datetime.utcnow)
        started_at = Column(DateTime, nullable=True)
        completed_at = Column(DateTime, nullable=True)
        
        # Resultados
        result_text = Column(Text, nullable=True)
        confidence = Column(Float, nullable=True)
        processing_time = Column(Float, nullable=True)
        
        # Metadados
        parameters = Column(JSON, nullable=True)
        metadata = Column(JSON, nullable=True)
        error_message = Column(Text, nullable=True)
        
        # Métricas
        file_size = Column(Integer, nullable=True)
        text_length = Column(Integer, nullable=True)
        blocks_count = Column(Integer, nullable=True)
    
    
    class ProcessingMetrics(Base):
        """Métricas de processamento"""
        __tablename__ = "processing_metrics"
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        
        # Identificação
        task_id = Column(String, nullable=False)
        engine = Column(String, nullable=False)
        timestamp = Column(DateTime, default=datetime.utcnow)
        
        # Métricas de performance
        processing_time = Column(Float, nullable=False)
        queue_wait_time = Column(Float, nullable=True)
        memory_usage = Column(Float, nullable=True)
        cpu_usage = Column(Float, nullable=True)
        
        # Métricas de qualidade
        confidence_score = Column(Float, nullable=True)
        text_length = Column(Integer, nullable=True)
        blocks_detected = Column(Integer, nullable=True)
        
        # Contexto
        file_size = Column(Integer, nullable=True)
        file_type = Column(String, nullable=True)
        complexity_score = Column(Float, nullable=True)
    
    
    class SystemEvents(Base):
        """Eventos do sistema"""
        __tablename__ = "system_events"
        
        id = Column(Integer, primary_key=True, autoincrement=True)
        
        # Identificação
        event_type = Column(String, nullable=False)  # task_start, task_complete, error, etc.
        component = Column(String, nullable=False)   # orchestrator, worker, api, etc.
        timestamp = Column(DateTime, default=datetime.utcnow)
        
        # Dados do evento
        event_data = Column(JSON, nullable=True)
        message = Column(Text, nullable=True)
        severity = Column(String, default="info")  # debug, info, warning, error, critical
        
        # Contexto
        task_id = Column(String, nullable=True)
        user_id = Column(String, nullable=True)
        session_id = Column(String, nullable=True)


# === FUNÇÕES DE ACESSO AO BANCO ===

def get_database_session() -> Optional[Session]:
    """Obtém sessão do banco de dados"""
    if not DATABASE_ENABLED or not session_factory:
        return None
    
    try:
        return session_factory()
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        return None


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[Optional[Session], None]:
    """Context manager para sessão do banco"""
    session = get_database_session()
    try:
        yield session
        if session:
            session.commit()
    except Exception as e:
        logger.error(f"Database session error: {e}")
        if session:
            session.rollback()
        raise
    finally:
        if session:
            session.close()


def init_database() -> bool:
    """
    Inicializa banco de dados criando tabelas
    
    Returns:
        True se inicialização bem-sucedida
    """
    if not DATABASE_ENABLED:
        logger.info("Database not enabled, skipping initialization")
        return False
    
    try:
        # Criar todas as tabelas
        Base.metadata.create_all(bind=database_engine)
        logger.info("✅ Database tables created successfully")
        
        # Teste de conectividade
        with get_database_session() as session:
            # Inserir evento de inicialização
            event = SystemEvents(
                event_type="database_init",
                component="database",
                message="Database initialized successfully",
                severity="info"
            )
            session.add(event)
            session.commit()
        
        return True
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False


# === OPERAÇÕES DE TASK ===

def save_task_record(task_id: str, task_data: Dict[str, Any]) -> bool:
    """
    Salva registro de tarefa no banco
    
    Args:
        task_id: ID da tarefa
        task_data: Dados da tarefa
        
    Returns:
        True se salvo com sucesso
    """
    if not DATABASE_ENABLED:
        return False
    
    try:
        with get_database_session() as session:
            # Verificar se já existe
            existing = session.query(TaskRecord).filter(TaskRecord.id == task_id).first()
            
            if existing:
                # Atualizar registro existente
                for key, value in task_data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
            else:
                # Criar novo registro
                task_record = TaskRecord(
                    id=task_id,
                    file_path=task_data.get("file_path", ""),
                    engine=task_data.get("engine", "unknown"),
                    status=task_data.get("status", "pending"),
                    priority=task_data.get("priority", 5),
                    parameters=task_data.get("parameters"),
                    metadata=task_data.get("metadata"),
                    file_size=task_data.get("file_size"),
                    created_at=datetime.fromtimestamp(task_data.get("created_at", time.time()))
                )
                session.add(task_record)
            
            session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Failed to save task record {task_id}: {e}")
        return False


def update_task_status(task_id: str, status: str, **kwargs) -> bool:
    """
    Atualiza status da tarefa
    
    Args:
        task_id: ID da tarefa
        status: Novo status
        **kwargs: Dados adicionais para atualizar
        
    Returns:
        True se atualizado com sucesso
    """
    if not DATABASE_ENABLED:
        return False
    
    try:
        with get_database_session() as session:
            task = session.query(TaskRecord).filter(TaskRecord.id == task_id).first()
            
            if task:
                task.status = status
                
                # Atualizar timestamps baseado no status
                if status == "processing" and not task.started_at:
                    task.started_at = datetime.utcnow()
                elif status in ["completed", "failed"]:
                    task.completed_at = datetime.utcnow()
                
                # Atualizar outros campos
                for key, value in kwargs.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
                
                session.commit()
                return True
            
    except Exception as e:
        logger.error(f"Failed to update task status {task_id}: {e}")
        return False
    
    return False


def get_task_history(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Obtém histórico de uma tarefa
    
    Args:
        task_id: ID da tarefa
        
    Returns:
        Dict com dados da tarefa ou None
    """
    if not DATABASE_ENABLED:
        return None
    
    try:
        with get_database_session() as session:
            task = session.query(TaskRecord).filter(TaskRecord.id == task_id).first()
            
            if task:
                return {
                    "id": task.id,
                    "file_path": task.file_path,
                    "engine": task.engine,
                    "status": task.status,
                    "priority": task.priority,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "started_at": task.started_at.isoformat() if task.started_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                    "result_text": task.result_text,
                    "confidence": task.confidence,
                    "processing_time": task.processing_time,
                    "parameters": task.parameters,
                    "metadata": task.metadata,
                    "error_message": task.error_message,
                    "file_size": task.file_size,
                    "text_length": task.text_length,
                    "blocks_count": task.blocks_count
                }
            
    except Exception as e:
        logger.error(f"Failed to get task history {task_id}: {e}")
        return None


# === MÉTRICAS E ANÁLISE ===

def save_processing_metrics(task_id: str, engine: str, metrics: Dict[str, Any]) -> bool:
    """Salva métricas de processamento"""
    if not DATABASE_ENABLED:
        return False
    
    try:
        with get_database_session() as session:
            metric_record = ProcessingMetrics(
                task_id=task_id,
                engine=engine,
                processing_time=metrics.get("processing_time", 0),
                queue_wait_time=metrics.get("queue_wait_time"),
                memory_usage=metrics.get("memory_usage"),
                cpu_usage=metrics.get("cpu_usage"),
                confidence_score=metrics.get("confidence_score"),
                text_length=metrics.get("text_length"),
                blocks_detected=metrics.get("blocks_detected"),
                file_size=metrics.get("file_size"),
                file_type=metrics.get("file_type"),
                complexity_score=metrics.get("complexity_score")
            )
            
            session.add(metric_record)
            session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Failed to save processing metrics: {e}")
        return False


def get_performance_stats(engine: str = None, days: int = 7) -> Dict[str, Any]:
    """
    Obtém estatísticas de performance
    
    Args:
        engine: Engine específico (None para todos)
        days: Número de dias para análise
        
    Returns:
        Dict com estatísticas
    """
    if not DATABASE_ENABLED:
        return {}
    
    try:
        with get_database_session() as session:
            # Data de corte
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Query base
            query = session.query(ProcessingMetrics).filter(
                ProcessingMetrics.timestamp >= cutoff_date
            )
            
            if engine:
                query = query.filter(ProcessingMetrics.engine == engine)
            
            metrics = query.all()
            
            if not metrics:
                return {}
            
            # Calcular estatísticas
            processing_times = [m.processing_time for m in metrics if m.processing_time]
            confidence_scores = [m.confidence_score for m in metrics if m.confidence_score]
            
            stats = {
                "total_tasks": len(metrics),
                "avg_processing_time": sum(processing_times) / len(processing_times) if processing_times else 0,
                "min_processing_time": min(processing_times) if processing_times else 0,
                "max_processing_time": max(processing_times) if processing_times else 0,
                "avg_confidence": sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0,
                "engine_distribution": {},
                "daily_counts": {}
            }
            
            # Distribuição por engine
            engine_counts = {}
            for metric in metrics:
                engine_counts[metric.engine] = engine_counts.get(metric.engine, 0) + 1
            stats["engine_distribution"] = engine_counts
            
            # Contagem diária
            daily_counts = {}
            for metric in metrics:
                date_key = metric.timestamp.date().isoformat()
                daily_counts[date_key] = daily_counts.get(date_key, 0) + 1
            stats["daily_counts"] = daily_counts
            
            return stats
            
    except Exception as e:
        logger.error(f"Failed to get performance stats: {e}")
        return {}


def log_system_event(event_type: str, component: str, message: str, 
                    severity: str = "info", **kwargs) -> bool:
    """
    Registra evento do sistema
    
    Args:
        event_type: Tipo do evento
        component: Componente que gerou o evento
        message: Mensagem do evento
        severity: Severidade (debug, info, warning, error, critical)
        **kwargs: Dados adicionais do evento
        
    Returns:
        True se registrado com sucesso
    """
    if not DATABASE_ENABLED:
        return False
    
    try:
        with get_database_session() as session:
            event = SystemEvents(
                event_type=event_type,
                component=component,
                message=message,
                severity=severity,
                event_data=kwargs,
                task_id=kwargs.get("task_id"),
                user_id=kwargs.get("user_id"),
                session_id=kwargs.get("session_id")
            )
            
            session.add(event)
            session.commit()
            return True
            
    except Exception as e:
        logger.error(f"Failed to log system event: {e}")
        return False


# === LIMPEZA E MANUTENÇÃO ===

def cleanup_old_records(days: int = 30) -> Dict[str, int]:
    """
    Remove registros antigos do banco
    
    Args:
        days: Idade máxima dos registros em dias
        
    Returns:
        Dict com contadores de registros removidos
    """
    if not DATABASE_ENABLED:
        return {}
    
    try:
        with get_database_session() as session:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Remover tarefas antigas completadas
            tasks_deleted = session.query(TaskRecord).filter(
                TaskRecord.completed_at < cutoff_date,
                TaskRecord.status.in_(["completed", "failed"])
            ).delete()
            
            # Remover métricas antigas
            metrics_deleted = session.query(ProcessingMetrics).filter(
                ProcessingMetrics.timestamp < cutoff_date
            ).delete()
            
            # Remover eventos antigos (manter apenas errors e warnings por mais tempo)
            events_deleted = session.query(SystemEvents).filter(
                SystemEvents.timestamp < cutoff_date,
                SystemEvents.severity.in_(["debug", "info"])
            ).delete()
            
            session.commit()
            
            return {
                "tasks_deleted": tasks_deleted,
                "metrics_deleted": metrics_deleted,
                "events_deleted": events_deleted
            }
            
    except Exception as e:
        logger.error(f"Failed to cleanup old records: {e}")
        return {}


def get_database_stats() -> Dict[str, Any]:
    """Retorna estatísticas do banco de dados"""
    if not DATABASE_ENABLED:
        return {"enabled": False}
    
    try:
        with get_database_session() as session:
            # Contar registros
            tasks_count = session.query(TaskRecord).count()
            metrics_count = session.query(ProcessingMetrics).count()
            events_count = session.query(SystemEvents).count()
            
            # Estatísticas de tarefas
            completed_tasks = session.query(TaskRecord).filter(
                TaskRecord.status == "completed"
            ).count()
            
            failed_tasks = session.query(TaskRecord).filter(
                TaskRecord.status == "failed"
            ).count()
            
            return {
                "enabled": True,
                "database_url": DATABASE_URL.split("://")[0] + "://***",
                "table_counts": {
                    "tasks": tasks_count,
                    "metrics": metrics_count,
                    "events": events_count
                },
                "task_stats": {
                    "total": tasks_count,
                    "completed": completed_tasks,
                    "failed": failed_tasks,
                    "success_rate": (completed_tasks / max(tasks_count, 1)) * 100
                }
            }
            
    except Exception as e:
        logger.error(f"Failed to get database stats: {e}")
        return {"enabled": True, "error": str(e)}


# Inicialização automática
if DATABASE_ENABLED:
    logger.info("Database module loaded - initializing...")
    init_success = init_database()
    if init_success:
        logger.info("✅ Database initialized successfully")
    else:
        logger.warning("⚠️  Database initialization failed")
else:
    logger.info("Database module loaded - disabled")


if __name__ == "__main__":
    """Teste do módulo de banco de dados"""
    print("=== Database Module Test ===")
    
    print(f"Database enabled: {DATABASE_ENABLED}")
    
    if DATABASE_ENABLED:
        # Teste de inicialização
        init_success = init_database()
        print(f"Database initialization: {'✅ Success' if init_success else '❌ Failed'}")
        
        # Teste de operações
        test_task_id = f"test_task_{int(time.time())}"
        
        # Salvar tarefa de teste
        task_data = {
            "file_path": "/test/file.jpg",
            "engine": "test_engine",
            "status": "pending",
            "priority": 5,
            "created_at": time.time()
        }
        
        save_success = save_task_record(test_task_id, task_data)
        print(f"Save task: {'✅ Success' if save_success else '❌ Failed'}")
        
        # Atualizar status
        update_success = update_task_status(test_task_id, "completed", processing_time=2.5)
        print(f"Update status: {'✅ Success' if update_success else '❌ Failed'}")
        
        # Buscar histórico
        history = get_task_history(test_task_id)
        print(f"Get history: {'✅ Found' if history else '❌ Not found'}")
        
        # Estatísticas
        stats = get_database_stats()
        print(f"Database stats: {stats}")
        
    else:
        print("Database is disabled - no tests performed")
    
    print("\n✅ Database module test completed")