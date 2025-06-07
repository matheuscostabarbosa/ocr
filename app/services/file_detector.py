#!/usr/bin/env python3
"""
Serviço de Detecção de Tipos de Arquivo
=======================================

Detecta tipos de arquivo usando:
- Magic bytes (assinatura de arquivo)
- Extensões de arquivo
- Análise de conteúdo
- Validação de formato
"""

import os
import mimetypes
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import logging

from app.models.schemas import FileCategory

# Detectores de magic bytes
try:
    import magic
    HAS_PYTHON_MAGIC = True
except ImportError:
    HAS_PYTHON_MAGIC = False

try:
    import filetype
    HAS_FILETYPE = True
except ImportError:
    HAS_FILETYPE = False

logger = logging.getLogger(__name__)


class FileTypeDetector:
    """Detector de tipos de arquivo robusto"""
    
    # Mapeamento de extensões para categorias
    CATEGORY_MAPPING = {
        FileCategory.IMAGE: [
            'jpg', 'jpeg', 'png', 'bmp', 'gif', 'tiff', 'tif', 'webp', 
            'svg', 'ico', 'heic', 'heif', 'raw', 'cr2', 'nef', 'arw'
        ],
        FileCategory.PDF: [
            'pdf'
        ],
        FileCategory.OFFICE: [
            'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
            'rtf', 'pages', 'numbers', 'key'
        ],
        FileCategory.TEXT: [
            'txt', 'html', 'htm', 'xml', 'csv', 'json', 'yaml', 'yml',
            'md', 'markdown', 'rst', 'tex', 'log'
        ],
        FileCategory.ARCHIVE: [
            'zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'z', 'lzh', 'arc'
        ]
    }
    
    # Magic bytes para detecção precisa
    MAGIC_SIGNATURES = {
        # Images
        b'\xff\xd8\xff': ('jpg', 'image/jpeg'),
        b'\x89PNG\r\n\x1a\n': ('png', 'image/png'),
        b'BM': ('bmp', 'image/bmp'),
        b'GIF8': ('gif', 'image/gif'),
        b'II*\x00': ('tiff', 'image/tiff'),
        b'MM\x00*': ('tiff', 'image/tiff'),
        b'RIFF': ('webp', 'image/webp'),  # Precisa verificar mais bytes
        
        # PDF
        b'%PDF': ('pdf', 'application/pdf'),
        
        # Office (modern)
        b'PK\x03\x04': ('office_zip', 'application/zip'),  # Pode ser docx, xlsx, etc
        
        # Office (legacy)
        b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1': ('office_ole', 'application/msword'),
        
        # Archives
        b'PK\x03\x04': ('zip', 'application/zip'),
        b'Rar!\x1a\x07\x00': ('rar', 'application/x-rar-compressed'),
        b'7z\xbc\xaf\x27\x1c': ('7z', 'application/x-7z-compressed'),
        b'\x1f\x8b': ('gz', 'application/gzip'),
        
        # Text (alguns)
        b'<?xml': ('xml', 'text/xml'),
        b'<!DOCTYPE html': ('html', 'text/html'),
        b'<html': ('html', 'text/html'),
    }
    
    def __init__(self):
        self.magic_detector = None
        self._setup_magic_detector()
    
    def _setup_magic_detector(self):
        """Configura detector de magic bytes"""
        if HAS_PYTHON_MAGIC:
            try:
                self.magic_detector = magic.Magic(mime=True)
                logger.debug("python-magic detector initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize python-magic: {e}")
                self.magic_detector = None
        
        if not self.magic_detector and not HAS_FILETYPE:
            logger.warning("No magic byte detector available. Install python-magic or filetype.")
    
    def detect_file_type(self, file_path: str) -> Dict[str, Any]:
        """
        Detecta tipo de arquivo de forma robusta
        
        Args:
            file_path: Caminho do arquivo
            
        Returns:
            Dict com informações do tipo de arquivo
        """
        try:
            path = Path(file_path)
            
            # Informações básicas
            result = {
                'filename': path.name,
                'extension': path.suffix.lower().lstrip('.'),
                'file_size': path.stat().st_size if path.exists() else 0,
                'exists': path.exists(),
                'mime_type': None,
                'category': FileCategory.UNKNOWN,
                'supported': False,
                'detection_method': [],
                'confidence': 0.0
            }
            
            if not path.exists():
                result['error'] = 'File does not exist'
                return result
            
            # 1. Detecção por magic bytes
            magic_result = self._detect_by_magic_bytes(file_path)
            if magic_result:
                result.update(magic_result)
                result['detection_method'].append('magic_bytes')
            
            # 2. Detecção por extensão (fallback ou confirmação)
            extension_result = self._detect_by_extension(result['extension'])
            if extension_result and not result['mime_type']:
                result.update(extension_result)
                result['detection_method'].append('extension')
            elif extension_result and result['mime_type']:
                # Verificar consistência
                if self._is_consistent(result, extension_result):
                    result['confidence'] += 0.2
                else:
                    result['detection_method'].append('extension_conflict')
            
            # 3. Detecção por análise de conteúdo
            content_result = self._detect_by_content_analysis(file_path, result)
            if content_result:
                result.update(content_result)
                result['detection_method'].append('content_analysis')
            
            # 4. Finalizar categorização
            result['category'] = self._determine_category(result)
            result['supported'] = self._is_supported(result)
            
            # 5. Calcular confiança final
            result['confidence'] = self._calculate_confidence(result)
            
            return result
            
        except Exception as e:
            logger.error(f"File type detection failed for {file_path}: {e}")
            return {
                'filename': Path(file_path).name,
                'extension': Path(file_path).suffix.lower().lstrip('.'),
                'error': str(e),
                'category': FileCategory.UNKNOWN,
                'supported': False,
                'confidence': 0.0
            }
    
    def _detect_by_magic_bytes(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Detecta tipo por magic bytes"""
        try:
            # Tentar python-magic primeiro
            if self.magic_detector:
                mime_type = self.magic_detector.from_file(file_path)
                if mime_type and mime_type != 'application/octet-stream':
                    return {
                        'mime_type': mime_type,
                        'magic_detection': 'python-magic'
                    }
            
            # Tentar filetype
            if HAS_FILETYPE:
                kind = filetype.guess(file_path)
                if kind:
                    return {
                        'mime_type': kind.mime,
                        'extension_detected': kind.extension,
                        'magic_detection': 'filetype'
                    }
            
            # Fallback para detecção manual
            return self._detect_manual_magic_bytes(file_path)
            
        except Exception as e:
            logger.warning(f"Magic bytes detection failed: {e}")
            return None
    
    def _detect_manual_magic_bytes(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Detecção manual de magic bytes"""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(64)  # Ler primeiros 64 bytes
            
            for signature, (ext, mime) in self.MAGIC_SIGNATURES.items():
                if header.startswith(signature):
                    # Verificações específicas
                    if signature == b'RIFF':
                        # Verificar se é WebP
                        if len(header) >= 12 and header[8:12] == b'WEBP':
                            return {
                                'mime_type': 'image/webp',
                                'extension_detected': 'webp',
                                'magic_detection': 'manual'
                            }
                    elif signature == b'PK\x03\x04':
                        # Pode ser ZIP, DOCX, XLSX, etc.
                        office_type = self._detect_office_format(file_path)
                        if office_type:
                            return office_type
                        else:
                            return {
                                'mime_type': 'application/zip',
                                'extension_detected': 'zip',
                                'magic_detection': 'manual'
                            }
                    else:
                        return {
                            'mime_type': mime,
                            'extension_detected': ext,
                            'magic_detection': 'manual'
                        }
            
            return None
            
        except Exception as e:
            logger.warning(f"Manual magic bytes detection failed: {e}")
            return None
    
    def _detect_office_format(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Detecta formato específico de documento Office"""
        try:
            import zipfile
            
            with zipfile.ZipFile(file_path, 'r') as zf:
                filenames = zf.namelist()
                
                # DOCX
                if 'word/document.xml' in filenames:
                    return {
                        'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'extension_detected': 'docx',
                        'magic_detection': 'office_analysis'
                    }
                
                # XLSX
                if 'xl/workbook.xml' in filenames:
                    return {
                        'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'extension_detected': 'xlsx',
                        'magic_detection': 'office_analysis'
                    }
                
                # PPTX
                if 'ppt/presentation.xml' in filenames:
                    return {
                        'mime_type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                        'extension_detected': 'pptx',
                        'magic_detection': 'office_analysis'
                    }
            
            return None
            
        except Exception:
            return None
    
    def _detect_by_extension(self, extension: str) -> Optional[Dict[str, Any]]:
        """Detecta tipo por extensão"""
        if not extension:
            return None
        
        # Usar mimetypes da biblioteca padrão
        mime_type, _ = mimetypes.guess_type(f"file.{extension}")
        
        if mime_type:
            return {
                'mime_type': mime_type,
                'extension_detection': True
            }
        
        # Fallback para extensões conhecidas
        extension_mapping = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        }
        
        if extension in extension_mapping:
            return {
                'mime_type': extension_mapping[extension],
                'extension_detection': True
            }
        
        return None
    
    def _detect_by_content_analysis(self, file_path: str, current_result: Dict) -> Optional[Dict[str, Any]]:
        """Análise adicional baseada no conteúdo"""
        try:
            # Para arquivos de texto, tentar detectar encoding e tipo específico
            if current_result.get('mime_type', '').startswith('text/'):
                return self._analyze_text_file(file_path)
            
            # Para imagens, verificar se são válidas
            if current_result.get('category') == FileCategory.IMAGE:
                return self._validate_image_file(file_path)
            
            return None
            
        except Exception as e:
            logger.warning(f"Content analysis failed: {e}")
            return None
    
    def _analyze_text_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Analisa arquivo de texto"""
        try:
            # Detectar encoding
            with open(file_path, 'rb') as f:
                raw_data = f.read(8192)  # Ler primeiros 8KB
            
            # Tentar detectar encoding
            try:
                import chardet
                encoding_result = chardet.detect(raw_data)
                encoding = encoding_result.get('encoding', 'utf-8')
            except ImportError:
                encoding = 'utf-8'
            
            # Ler como texto
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read(4096)  # Primeiras linhas
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='latin1') as f:
                    content = f.read(4096)
            
            # Analisar conteúdo
            analysis = {
                'encoding': encoding,
                'text_analysis': True
            }
            
            # Detectar tipos específicos
            if content.strip().startswith('<?xml'):
                analysis['mime_type'] = 'text/xml'
            elif content.strip().startswith(('<!DOCTYPE html', '<html')):
                analysis['mime_type'] = 'text/html'
            elif content.strip().startswith('{') and content.strip().endswith('}'):
                try:
                    import json
                    json.loads(content)
                    analysis['mime_type'] = 'application/json'
                except:
                    pass
            
            return analysis
            
        except Exception as e:
            logger.warning(f"Text analysis failed: {e}")
            return None
    
    def _validate_image_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Valida se arquivo de imagem é válido"""
        try:
            from PIL import Image
            
            with Image.open(file_path) as img:
                # Verificar se pode ser carregada
                img.verify()
                
                return {
                    'image_validation': True,
                    'image_format': img.format,
                    'image_mode': img.mode,
                    'image_size': img.size
                }
                
        except Exception as e:
            logger.warning(f"Image validation failed: {e}")
            return {
                'image_validation': False,
                'validation_error': str(e)
            }
    
    def _determine_category(self, result: Dict[str, Any]) -> FileCategory:
        """Determina categoria do arquivo"""
        mime_type = result.get('mime_type', '')
        extension = result.get('extension', '')
        
        # Por MIME type
        if mime_type.startswith('image/'):
            return FileCategory.IMAGE
        elif mime_type == 'application/pdf':
            return FileCategory.PDF
        elif mime_type.startswith('text/'):
            return FileCategory.TEXT
        elif 'officedocument' in mime_type or mime_type in [
            'application/msword', 'application/vnd.ms-excel', 'application/vnd.ms-powerpoint'
        ]:
            return FileCategory.OFFICE
        elif mime_type in ['application/zip', 'application/x-rar-compressed', 'application/x-7z-compressed']:
            return FileCategory.ARCHIVE
        
        # Por extensão
        for category, extensions in self.CATEGORY_MAPPING.items():
            if extension in extensions:
                return category
        
        return FileCategory.UNKNOWN
    
    def _is_supported(self, result: Dict[str, Any]) -> bool:
        """Verifica se tipo é suportado"""
        category = result.get('category', FileCategory.UNKNOWN)
        
        # Todas as categorias conhecidas são suportadas
        return category != FileCategory.UNKNOWN
    
    def _is_consistent(self, magic_result: Dict, extension_result: Dict) -> bool:
        """Verifica consistência entre detecções"""
        magic_mime = magic_result.get('mime_type', '')
        ext_mime = extension_result.get('mime_type', '')
        
        # Verificar se são do mesmo tipo geral
        if magic_mime.split('/')[0] == ext_mime.split('/')[0]:
            return True
        
        # Verificar casos específicos conhecidos
        consistent_pairs = [
            ('application/zip', 'application/vnd.openxmlformats-officedocument'),
            ('text/plain', 'text/'),
        ]
        
        for pair in consistent_pairs:
            if (magic_mime.startswith(pair[0]) and ext_mime.startswith(pair[1])) or \
               (magic_mime.startswith(pair[1]) and ext_mime.startswith(pair[0])):
                return True
        
        return False
    
    def _calculate_confidence(self, result: Dict[str, Any]) -> float:
        """Calcula confiança da detecção"""
        confidence = 0.0
        
        # Base por método de detecção
        methods = result.get('detection_method', [])
        
        if 'magic_bytes' in methods:
            confidence += 0.6
        
        if 'extension' in methods:
            confidence += 0.3
        
        if 'content_analysis' in methods:
            confidence += 0.2
        
        # Bonificações
        if result.get('image_validation') is True:
            confidence += 0.1
        
        if result.get('magic_detection') == 'python-magic':
            confidence += 0.1
        
        if 'extension_conflict' not in methods:
            confidence += 0.1
        
        # Penalizações
        if result.get('validation_error'):
            confidence -= 0.2
        
        if result.get('category') == FileCategory.UNKNOWN:
            confidence -= 0.3
        
        return max(0.0, min(1.0, confidence))
    
    def batch_detect(self, file_paths: List[str]) -> List[Dict[str, Any]]:
        """Detecta tipos de múltiplos arquivos"""
        results = []
        
        for file_path in file_paths:
            try:
                result = self.detect_file_type(file_path)
                results.append(result)
            except Exception as e:
                logger.error(f"Batch detection failed for {file_path}: {e}")
                results.append({
                    'filename': Path(file_path).name,
                    'error': str(e),
                    'category': FileCategory.UNKNOWN,
                    'supported': False
                })
        
        return results
    
    def get_supported_formats(self) -> Dict[str, List[str]]:
        """Retorna formatos suportados por categoria"""
        return dict(self.CATEGORY_MAPPING)
    
    def is_supported_file(self, file_path: str) -> bool:
        """Verifica rapidamente se arquivo é suportado"""
        try:
            result = self.detect_file_type(file_path)
            return result.get('supported', False)
        except Exception:
            return False


if __name__ == "__main__":
    """Teste do detector de tipos de arquivo"""
    import tempfile
    
    print("=== File Type Detector Test ===")
    
    detector = FileTypeDetector()
    
    # Teste com arquivo temporário
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp_file:
        tmp_file.write(b"Hello, world!")
        tmp_path = tmp_file.name
    
    try:
        # Detectar tipo
        result = detector.detect_file_type(tmp_path)
        print(f"File: {result['filename']}")
        print(f"Extension: {result['extension']}")
        print(f"MIME type: {result['mime_type']}")
        print(f"Category: {result['category']}")
        print(f"Supported: {result['supported']}")
        print(f"Confidence: {result['confidence']:.2f}")
        print(f"Detection methods: {result['detection_method']}")
        
        # Teste de formatos suportados
        print(f"\nSupported formats:")
        for category, extensions in detector.get_supported_formats().items():
            print(f"  {category}: {len(extensions)} formats")
        
    finally:
        # Limpar arquivo temporário
        os.unlink(tmp_path)
    
    print("\n✅ File Type Detector test completed")