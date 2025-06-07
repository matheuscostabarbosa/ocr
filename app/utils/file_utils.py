#!/usr/bin/env python3
"""
Utilitários de Arquivo
=====================

Funções utilitárias para manipulação de arquivos:
- Validação de arquivos
- Conversão de formatos
- Extração de metadados
- Operações de arquivo seguras
- Compressão e descompressão
- Backup e limpeza
"""

import os
import shutil
import tempfile
import hashlib
import mimetypes
import zipfile
import gzip
import time
import json
import logging
from typing import Dict, Any, List, Optional, Union, Tuple, BinaryIO
from pathlib import Path
import magic
from PIL import Image

logger = logging.getLogger(__name__)


def validate_file_path(file_path: str) -> bool:
    """
    Valida se caminho do arquivo é válido e seguro
    
    Args:
        file_path: Caminho do arquivo
        
    Returns:
        True se válido
    """
    try:
        path = Path(file_path)
        
        # Verificar se existe
        if not path.exists():
            return False
        
        # Verificar se é arquivo (não diretório)
        if not path.is_file():
            return False
        
        # Verificar se é legível
        if not os.access(str(path), os.R_OK):
            return False
        
        # Verificar se caminho não contém caracteres perigosos
        normalized = os.path.normpath(str(path))
        if ".." in normalized or normalized.startswith("/"):
            return False
        
        return True
        
    except Exception as e:
        logger.warning(f"File validation failed for {file_path}: {e}")
        return False


def get_file_info(file_path: str) -> Dict[str, Any]:
    """
    Obtém informações detalhadas do arquivo
    
    Args:
        file_path: Caminho do arquivo
        
    Returns:
        Dict com informações do arquivo
    """
    try:
        path = Path(file_path)
        stat = path.stat()
        
        # Informações básicas
        info = {
            "name": path.name,
            "path": str(path.absolute()),
            "size": stat.st_size,
            "size_human": format_file_size(stat.st_size),
            "extension": path.suffix.lower(),
            "stem": path.stem,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "accessed": stat.st_atime,
            "is_readable": os.access(str(path), os.R_OK),
            "is_writable": os.access(str(path), os.W_OK)
        }
        
        # MIME type
        mime_type, encoding = mimetypes.guess_type(str(path))
        info["mime_type"] = mime_type
        info["encoding"] = encoding
        
        # Hash do arquivo
        info["md5"] = calculate_file_hash(file_path, "md5")
        info["sha256"] = calculate_file_hash(file_path, "sha256")
        
        # Informações específicas por tipo
        if mime_type and mime_type.startswith("image/"):
            info["image_info"] = get_image_info(file_path)
        elif mime_type == "application/pdf":
            info["pdf_info"] = get_pdf_info(file_path)
        elif mime_type and mime_type.startswith("text/"):
            info["text_info"] = get_text_info(file_path)
        
        return info
        
    except Exception as e:
        logger.error(f"Failed to get file info for {file_path}: {e}")
        return {"error": str(e), "path": file_path}


def format_file_size(size_bytes: int) -> str:
    """
    Formata tamanho do arquivo em formato legível
    
    Args:
        size_bytes: Tamanho em bytes
        
    Returns:
        String formatada (ex: "1.5 MB")
    """
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def calculate_file_hash(file_path: str, algorithm: str = "sha256") -> str:
    """
    Calcula hash do arquivo
    
    Args:
        file_path: Caminho do arquivo
        algorithm: Algoritmo (md5, sha1, sha256)
        
    Returns:
        Hash hexadecimal
    """
    try:
        hash_algo = hashlib.new(algorithm)
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_algo.update(chunk)
        
        return hash_algo.hexdigest()
        
    except Exception as e:
        logger.error(f"Hash calculation failed for {file_path}: {e}")
        return ""


def safe_copy_file(src: str, dst: str, overwrite: bool = False) -> bool:
    """
    Copia arquivo de forma segura
    
    Args:
        src: Arquivo origem
        dst: Arquivo destino
        overwrite: Se deve sobrescrever arquivo existente
        
    Returns:
        True se copiado com sucesso
    """
    try:
        src_path = Path(src)
        dst_path = Path(dst)
        
        # Validações
        if not src_path.exists():
            logger.error(f"Source file does not exist: {src}")
            return False
        
        if dst_path.exists() and not overwrite:
            logger.error(f"Destination file exists and overwrite=False: {dst}")
            return False
        
        # Criar diretório destino se não existir
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copiar arquivo
        shutil.copy2(str(src_path), str(dst_path))
        
        # Verificar se cópia foi bem-sucedida
        if dst_path.exists() and dst_path.stat().st_size == src_path.stat().st_size:
            logger.debug(f"File copied successfully: {src} -> {dst}")
            return True
        else:
            logger.error(f"File copy verification failed: {src} -> {dst}")
            return False
            
    except Exception as e:
        logger.error(f"File copy failed: {src} -> {dst}: {e}")
        return False


def safe_move_file(src: str, dst: str, overwrite: bool = False) -> bool:
    """
    Move arquivo de forma segura
    
    Args:
        src: Arquivo origem
        dst: Arquivo destino
        overwrite: Se deve sobrescrever arquivo existente
        
    Returns:
        True se movido com sucesso
    """
    try:
        # Primeiro copiar
        if safe_copy_file(src, dst, overwrite):
            # Depois remover original
            return safe_delete_file(src)
        return False
        
    except Exception as e:
        logger.error(f"File move failed: {src} -> {dst}: {e}")
        return False


def safe_delete_file(file_path: str) -> bool:
    """
    Remove arquivo de forma segura
    
    Args:
        file_path: Caminho do arquivo
        
    Returns:
        True se removido com sucesso
    """
    try:
        path = Path(file_path)
        
        if not path.exists():
            return True  # Já não existe
        
        if not path.is_file():
            logger.error(f"Path is not a file: {file_path}")
            return False
        
        # Remover arquivo
        path.unlink()
        
        # Verificar se foi removido
        if not path.exists():
            logger.debug(f"File deleted successfully: {file_path}")
            return True
        else:
            logger.error(f"File deletion verification failed: {file_path}")
            return False
            
    except Exception as e:
        logger.error(f"File deletion failed: {file_path}: {e}")
        return False


def create_temp_file(suffix: str = "", prefix: str = "tmp", content: bytes = None) -> str:
    """
    Cria arquivo temporário
    
    Args:
        suffix: Sufixo do arquivo
        prefix: Prefixo do arquivo
        content: Conteúdo inicial
        
    Returns:
        Caminho do arquivo temporário
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, prefix=prefix, delete=False) as tmp:
            if content:
                tmp.write(content)
            return tmp.name
            
    except Exception as e:
        logger.error(f"Temp file creation failed: {e}")
        raise


def create_temp_directory(suffix: str = "", prefix: str = "tmp") -> str:
    """
    Cria diretório temporário
    
    Args:
        suffix: Sufixo do diretório
        prefix: Prefixo do diretório
        
    Returns:
        Caminho do diretório temporário
    """
    try:
        return tempfile.mkdtemp(suffix=suffix, prefix=prefix)
        
    except Exception as e:
        logger.error(f"Temp directory creation failed: {e}")
        raise


def compress_file(file_path: str, output_path: str = None, method: str = "gzip") -> str:
    """
    Comprime arquivo
    
    Args:
        file_path: Arquivo a comprimir
        output_path: Caminho do arquivo comprimido
        method: Método de compressão (gzip, zip)
        
    Returns:
        Caminho do arquivo comprimido
    """
    try:
        if not output_path:
            if method == "gzip":
                output_path = file_path + ".gz"
            elif method == "zip":
                output_path = Path(file_path).with_suffix(".zip")
        
        if method == "gzip":
            with open(file_path, 'rb') as f_in:
                with gzip.open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        
        elif method == "zip":
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(file_path, Path(file_path).name)
        
        else:
            raise ValueError(f"Unsupported compression method: {method}")
        
        logger.debug(f"File compressed: {file_path} -> {output_path} ({method})")
        return str(output_path)
        
    except Exception as e:
        logger.error(f"File compression failed: {file_path}: {e}")
        raise


def decompress_file(compressed_path: str, output_path: str = None) -> str:
    """
    Descomprime arquivo
    
    Args:
        compressed_path: Arquivo comprimido
        output_path: Caminho do arquivo descomprimido
        
    Returns:
        Caminho do arquivo descomprimido
    """
    try:
        compressed_path = Path(compressed_path)
        
        if not output_path:
            if compressed_path.suffix == ".gz":
                output_path = compressed_path.with_suffix("")
            elif compressed_path.suffix == ".zip":
                output_path = compressed_path.parent / compressed_path.stem
        
        if compressed_path.suffix == ".gz":
            with gzip.open(str(compressed_path), 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
        
        elif compressed_path.suffix == ".zip":
            with zipfile.ZipFile(str(compressed_path), 'r') as zipf:
                # Extrair primeiro arquivo
                names = zipf.namelist()
                if names:
                    with zipf.open(names[0]) as f_in:
                        with open(output_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
        
        else:
            raise ValueError(f"Unsupported compressed file: {compressed_path}")
        
        logger.debug(f"File decompressed: {compressed_path} -> {output_path}")
        return str(output_path)
        
    except Exception as e:
        logger.error(f"File decompression failed: {compressed_path}: {e}")
        raise


def backup_file(file_path: str, backup_dir: str = None) -> str:
    """
    Cria backup do arquivo
    
    Args:
        file_path: Arquivo a fazer backup
        backup_dir: Diretório de backup
        
    Returns:
        Caminho do arquivo de backup
    """
    try:
        path = Path(file_path)
        
        if not backup_dir:
            backup_dir = path.parent / "backups"
        
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Nome do backup com timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.stem}_{timestamp}{path.suffix}"
        backup_path = backup_dir / backup_name
        
        # Copiar arquivo
        shutil.copy2(str(path), str(backup_path))
        
        logger.debug(f"File backed up: {file_path} -> {backup_path}")
        return str(backup_path)
        
    except Exception as e:
        logger.error(f"File backup failed: {file_path}: {e}")
        raise


def get_image_info(file_path: str) -> Dict[str, Any]:
    """
    Obtém informações específicas de imagem
    
    Args:
        file_path: Caminho da imagem
        
    Returns:
        Dict com informações da imagem
    """
    try:
        with Image.open(file_path) as img:
            info = {
                "format": img.format,
                "mode": img.mode,
                "size": img.size,
                "width": img.width,
                "height": img.height,
                "aspect_ratio": img.width / img.height if img.height > 0 else 0,
                "has_transparency": img.mode in ("RGBA", "LA") or "transparency" in img.info
            }
            
            # Informações EXIF se disponível
            if hasattr(img, '_getexif') and img._getexif():
                info["has_exif"] = True
                # Não extrair EXIF completo por privacidade
            else:
                info["has_exif"] = False
            
            return info
            
    except Exception as e:
        logger.warning(f"Failed to get image info for {file_path}: {e}")
        return {"error": str(e)}


def get_pdf_info(file_path: str) -> Dict[str, Any]:
    """
    Obtém informações específicas de PDF
    
    Args:
        file_path: Caminho do PDF
        
    Returns:
        Dict com informações do PDF
    """
    try:
        import fitz  # PyMuPDF
        
        doc = fitz.open(file_path)
        
        info = {
            "page_count": len(doc),
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
            "subject": doc.metadata.get("subject", ""),
            "creator": doc.metadata.get("creator", ""),
            "producer": doc.metadata.get("producer", ""),
            "creation_date": doc.metadata.get("creationDate", ""),
            "modification_date": doc.metadata.get("modDate", ""),
            "encrypted": doc.needs_pass,
            "has_links": False,
            "has_bookmarks": len(doc.get_toc()) > 0
        }
        
        # Verificar se há links (amostra de algumas páginas)
        sample_pages = min(3, len(doc))
        for page_num in range(sample_pages):
            page = doc.load_page(page_num)
            if page.get_links():
                info["has_links"] = True
                break
        
        doc.close()
        return info
        
    except Exception as e:
        logger.warning(f"Failed to get PDF info for {file_path}: {e}")
        return {"error": str(e)}


def get_text_info(file_path: str) -> Dict[str, Any]:
    """
    Obtém informações específicas de arquivo de texto
    
    Args:
        file_path: Caminho do arquivo de texto
        
    Returns:
        Dict com informações do texto
    """
    try:
        # Detectar encoding
        with open(file_path, 'rb') as f:
            raw_data = f.read(8192)
        
        try:
            import chardet
            encoding_result = chardet.detect(raw_data)
            encoding = encoding_result.get('encoding', 'utf-8')
            encoding_confidence = encoding_result.get('confidence', 0.0)
        except ImportError:
            encoding = 'utf-8'
            encoding_confidence = 0.5
        
        # Ler conteúdo
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin1') as f:
                content = f.read()
            encoding = 'latin1'
        
        # Analisar conteúdo
        lines = content.split('\n')
        words = content.split()
        
        info = {
            "encoding": encoding,
            "encoding_confidence": encoding_confidence,
            "line_count": len(lines),
            "word_count": len(words),
            "char_count": len(content),
            "char_count_no_spaces": len(content.replace(' ', '')),
            "empty_lines": sum(1 for line in lines if not line.strip()),
            "max_line_length": max(len(line) for line in lines) if lines else 0,
            "avg_line_length": sum(len(line) for line in lines) / len(lines) if lines else 0
        }
        
        return info
        
    except Exception as e:
        logger.warning(f"Failed to get text info for {file_path}: {e}")
        return {"error": str(e)}


def find_files(directory: str, pattern: str = "*", recursive: bool = True) -> List[str]:
    """
    Encontra arquivos baseado em padrão
    
    Args:
        directory: Diretório para buscar
        pattern: Padrão de busca (glob)
        recursive: Busca recursiva
        
    Returns:
        Lista de caminhos de arquivo
    """
    try:
        path = Path(directory)
        
        if recursive:
            files = list(path.rglob(pattern))
        else:
            files = list(path.glob(pattern))
        
        # Filtrar apenas arquivos
        return [str(f) for f in files if f.is_file()]
        
    except Exception as e:
        logger.error(f"File search failed in {directory}: {e}")
        return []


def cleanup_directory(directory: str, max_age_days: int = 7, pattern: str = "*") -> Dict[str, Any]:
    """
    Limpa arquivos antigos de um diretório
    
    Args:
        directory: Diretório para limpar
        max_age_days: Idade máxima em dias
        pattern: Padrão de arquivos para limpar
        
    Returns:
        Dict com estatísticas da limpeza
    """
    try:
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        
        stats = {
            "files_checked": 0,
            "files_deleted": 0,
            "bytes_freed": 0,
            "errors": 0
        }
        
        files = find_files(directory, pattern, recursive=True)
        
        for file_path in files:
            stats["files_checked"] += 1
            
            try:
                path = Path(file_path)
                if path.stat().st_mtime < cutoff_time:
                    file_size = path.stat().st_size
                    
                    if safe_delete_file(file_path):
                        stats["files_deleted"] += 1
                        stats["bytes_freed"] += file_size
                    else:
                        stats["errors"] += 1
                        
            except Exception as e:
                logger.warning(f"Error processing file {file_path}: {e}")
                stats["errors"] += 1
        
        logger.info(f"Directory cleanup completed: {stats['files_deleted']} files deleted, "
                   f"{format_file_size(stats['bytes_freed'])} freed")
        
        return stats
        
    except Exception as e:
        logger.error(f"Directory cleanup failed: {e}")
        return {"error": str(e)}


def ensure_directory(directory: str, permissions: int = 0o755) -> bool:
    """
    Garante que diretório existe
    
    Args:
        directory: Caminho do diretório
        permissions: Permissões do diretório
        
    Returns:
        True se diretório existe ou foi criado
    """
    try:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        
        # Definir permissões se especificado
        if permissions != 0o755:
            os.chmod(str(path), permissions)
        
        return path.exists() and path.is_dir()
        
    except Exception as e:
        logger.error(f"Directory creation failed: {directory}: {e}")
        return False


def atomic_write(file_path: str, content: Union[str, bytes], encoding: str = "utf-8") -> bool:
    """
    Escreve arquivo de forma atômica
    
    Args:
        file_path: Caminho do arquivo
        content: Conteúdo a escrever
        encoding: Encoding para texto
        
    Returns:
        True se escrito com sucesso
    """
    try:
        path = Path(file_path)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        
        # Escrever em arquivo temporário
        if isinstance(content, str):
            with open(temp_path, 'w', encoding=encoding) as f:
                f.write(content)
        else:
            with open(temp_path, 'wb') as f:
                f.write(content)
        
        # Mover para posição final (operação atômica)
        temp_path.replace(path)
        
        return True
        
    except Exception as e:
        logger.error(f"Atomic write failed: {file_path}: {e}")
        return False


if __name__ == "__main__":
    """Teste dos utilitários de arquivo"""
    print("=== File Utils Test ===")
    
    # Criar arquivo de teste
    test_content = b"This is a test file for file utilities testing."
    test_file = create_temp_file(suffix=".txt", content=test_content)
    
    try:
        print(f"Test file created: {test_file}")
        
        # Teste de validação
        print(f"File is valid: {validate_file_path(test_file)}")
        
        # Teste de informações
        info = get_file_info(test_file)
        print(f"File size: {info.get('size_human', 'unknown')}")
        print(f"File hash: {info.get('sha256', 'unknown')[:16]}...")
        
        # Teste de cópia
        backup_file_path = backup_file(test_file)
        print(f"Backup created: {backup_file_path}")
        
        # Teste de compressão
        compressed_file = compress_file(test_file, method="gzip")
        print(f"File compressed: {compressed_file}")
        
        # Teste de descompressão
        decompressed_file = decompress_file(compressed_file)
        print(f"File decompressed: {decompressed_file}")
        
        # Limpeza
        for f in [test_file, backup_file_path, compressed_file, decompressed_file]:
            safe_delete_file(f)
        
        print("✅ All file operations completed successfully")
        
    except Exception as e:
        print(f"❌ File utils test failed: {e}")
        # Limpeza em caso de erro
        safe_delete_file(test_file)
    
    print("\n✅ File Utils test completed")