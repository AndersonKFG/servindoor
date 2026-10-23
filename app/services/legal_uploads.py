"""Validação estrutural conservadora. Não extrai HTML nem executa conteúdo."""
import io
import zipfile
from pathlib import PurePosixPath

from defusedxml.ElementTree import fromstring
from fastapi import HTTPException
from pypdf import PdfReader
from pypdf.generic import DictionaryObject, ArrayObject, IndirectObject

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_EXPANDED_BYTES = 20 * 1024 * 1024


def validate_document(content: bytes, filename: str) -> str:
    extension = PurePosixPath(filename.lower()).suffix
    if not content or len(content) > MAX_FILE_BYTES:
        raise HTTPException(413, "O documento deve ter até 5 MB e não pode estar vazio.")
    try:
        if extension == ".pdf":
            _validate_pdf(content)
        elif extension == ".docx":
            _validate_docx(content)
        else:
            raise ValueError("extensão")
    except Exception:
        raise HTTPException(400, "Envie um PDF ou DOCX válido, sem criptografia, macros, anexos ou conteúdo ativo.") from None
    return extension[1:]


def _validate_pdf(content):
    if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise ValueError("assinatura PDF")
    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 500:
        raise ValueError("PDF criptografado ou páginas")
    forbidden = {"/OpenAction", "/AA", "/JS", "/JavaScript", "/Launch", "/RichMedia",
                 "/EmbeddedFiles", "/EmbeddedFile", "/Filespec", "/XFA", "/SubmitForm",
                 "/ImportData", "/GoToR", "/GoToE", "/Sound", "/Movie"}
    visited = set()
    budget = 0

    def inspect(obj):
        nonlocal budget
        if isinstance(obj, IndirectObject):
            key = (obj.idnum, obj.generation)
            if key in visited:
                return
            visited.add(key)
            obj = obj.get_object()
        budget += 1
        if budget > 100000:
            raise ValueError("complexidade PDF")
        if isinstance(obj, DictionaryObject):
            if forbidden.intersection(str(key) for key in obj.keys()):
                raise ValueError("conteúdo ativo")
            if str(obj.get("/S", "")) in forbidden or str(obj.get("/Type", "")) in forbidden:
                raise ValueError("ação PDF")
            for value in obj.values():
                inspect(value)
        elif isinstance(obj, ArrayObject):
            for value in obj:
                inspect(value)

    inspect(reader.trailer)
    # Inspeciona também objetos não alcançados pela árvore principal.
    for generation, entries in reader.xref.items():
        for object_id in entries:
            if object_id:
                inspect(IndirectObject(object_id, generation, reader))
    for object_id in reader.xref_objStm:
        inspect(IndirectObject(object_id, 0, reader))


def _validate_docx(content):
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("assinatura DOCX")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        names = [item.filename for item in entries]
        if len(entries) > 1000 or len(names) != len(set(names)):
            raise ValueError("estrutura ZIP")
        if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}.issubset(names):
            raise ValueError("estrutura DOCX")
        if sum(item.file_size for item in entries) > MAX_EXPANDED_BYTES:
            raise ValueError("ZIP expandido")
        for item in entries:
            name = item.filename.lower()
            path = PurePosixPath(name)
            suffix = ".rels" if path.name == ".rels" else path.suffix
            if path.is_absolute() or ".." in path.parts or "\\" in name or item.flag_bits & 1:
                raise ValueError("caminho ZIP")
            if any(part in name for part in ("vbaproject", "embeddings/", "activex/", "customui/")):
                raise ValueError("conteúdo ativo")
            if not item.is_dir() and suffix not in {".xml", ".rels", ".png", ".jpg", ".jpeg", ".gif"}:
                raise ValueError("tipo interno")
            data = archive.read(item)
            if suffix in {".xml", ".rels"}:
                tree = fromstring(data)
                for node in tree.iter():
                    if node.attrib.get("TargetMode", "").lower() == "external":
                        raise ValueError("relação externa")
                    if any(word in str(value).lower() for value in node.attrib.values()
                           for word in ("macroenabled", "oleobject", "activex")):
                        raise ValueError("macro")
                    if node.tag.split("}")[-1] in {"altChunk", "object", "fldSimple", "instrText"}:
                        raise ValueError("campo ativo")
        types = archive.read("[Content_Types].xml")
        if b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml" not in types:
            raise ValueError("tipo DOCX")
