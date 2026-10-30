"""Conservative native-document subset with explicit hidden-payload checks."""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from ruler_formats import FormatError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
ET.register_namespace("w", W[1:-1])


def docx_parts(path):
    parts = {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) > 10000 or sum(i.file_size for i in archive.infolist()) > 512 * 1024 * 1024:
            raise FormatError("docx_package_limit_or_duplicate")
        for name in names:
            if ".." in PurePosixPath(name).parts or name.startswith("/") or "\\" in name:
                raise FormatError("invalid_docx_part_name")
            if name.endswith("/"):
                continue
            data = archive.read(name)
            # Office thumbnails are disposable metadata, not document illustrations.
            if name.startswith("docProps/") and not name.endswith(".xml"):
                continue
            if not name.endswith((".xml", ".rels")) or name.startswith(("word/media/", "word/embeddings/", "_xmlsignatures/")):
                raise FormatError("unsupported_document_object")
            if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise FormatError("unsafe_xml")
            root = ET.fromstring(data)
            for element in root.iter():
                local = element.tag.split("}")[-1]
                if local in {"blip", "imagedata", "OLEObject", "object", "altChunk", "subDoc", "chart", "diagram", "movie", "control"}:
                    raise FormatError("unsupported_document_object")
                if local in {"drawing", "pict"} and not any(e.tag == W + "txbxContent" for e in element.iter()):
                    raise FormatError("unsupported_document_object")
            parts[name] = root
    if "word/document.xml" not in parts:
        raise FormatError("docx_main_part_missing")
    return parts


def paragraph_nodes(root):
    # Text boxes contain nested paragraphs: only each text node's nearest p owns it.
    parents = {child: parent for parent in root.iter() for child in parent}
    result = []
    for p in root.iter(W + "p"):
        nodes = []
        for node in p.iter():
            if node.tag not in {W + "t", W + "delText", W + "instrText"}:
                continue
            ancestor = parents.get(node)
            while ancestor is not None and ancestor.tag != W + "p":
                ancestor = parents.get(ancestor)
            if ancestor is p:
                nodes.append(node)
        if nodes:
            result.append(nodes)
    return result


def document_units(path):
    if path.suffix.lower() == ".docx":
        parts = docx_parts(path)
        values = []
        for name, root in parts.items():
            for nodes in paragraph_nodes(root):
                values.append({"id": f"unit-{len(values)}", "part": name, "text": "".join(n.text or "" for n in nodes)})
            # Include properties, settings, style names and attributes for semantic review.
            values.append({"id": f"unit-{len(values)}", "part": name, "text": ET.tostring(root, encoding="unicode")})
        return values, ["revisions_accepted", "comments_and_hidden_content_removed", "identity_metadata_removed", "external_relationships_removed"]
    return pdf_units(path)


def sanitize_docx(parts, replace):
    drop_parts = {n for n in parts if n.startswith(("docProps/", "customXml/")) or "comments" in n.lower() or "people" in n.lower()}
    # Resolve inherited hidden styles before removing hidden runs/paragraphs.
    hidden_styles = set()
    styles = parts.get("word/styles.xml")
    if styles is not None:
        changed = True
        while changed:
            changed = False
            for style in styles.findall(W + "style"):
                ident = style.get(W + "styleId")
                base = style.find(W + "basedOn")
                hidden = any(e.tag in {W + "vanish", W + "webHidden"} and e.get(W + "val", "true") not in {"0", "false", "off"} for e in style.iter())
                if ident not in hidden_styles and (hidden or (base is not None and base.get(W + "val") in hidden_styles)):
                    hidden_styles.add(ident)
                    changed = True
    for name, root in list(parts.items()):
        if name in drop_parts:
            continue
        def clean(parent):
            for child in list(parent):
                local = child.tag.split("}")[-1]
                is_hidden = False
                if child.tag in {W + "r", W + "p"}:
                    prop = child.find(W + ("rPr" if child.tag == W + "r" else "pPr"))
                    if prop is not None:
                        is_hidden = any(e.tag in {W + "vanish", W + "webHidden"} and e.get(W + "val", "true") not in {"0", "false", "off"} for e in prop.iter())
                        is_hidden |= any(e.tag in {W + "rStyle", W + "pStyle"} and e.get(W + "val") in hidden_styles for e in prop.iter())
                remove = (local in {"del", "moveFrom", "commentRangeStart", "commentRangeEnd", "commentReference", "docVars", "rsids", "dataBinding", "instrText", "fldChar", "fldData", "trackRevisions"}
                          or local.endswith("PrChange") or is_hidden)
                if remove:
                    parent.remove(child)
                    continue
                clean(child)
                if local in {"ins", "moveTo", "fldSimple"}:
                    index = list(parent).index(child)
                    parent.remove(child)
                    for offset, grandchild in enumerate(list(child)):
                        parent.insert(index + offset, grandchild)
            for key in list(parent.attrib):
                local = key.split("}")[-1]
                if local in {"author", "initials", "date", "dateUtc", "instr", "Ignorable"} or local.startswith("rsid"):
                    del parent.attrib[key]
                elif local not in {"Type", "ContentType", "Extension", "TargetMode"}:
                    parent.attrib[key] = replace(parent.attrib[key])
        clean(root)
        if name.endswith(".rels"):
            for rel in list(root):
                if rel.get("TargetMode") == "External" or any(v in rel.get("Type", "").lower() for v in ("comments", "people", "customxml", "metadata/core-properties", "extended-properties", "custom-properties", "thumbnail")):
                    root.remove(rel)
        if name == "[Content_Types].xml":
            for entry in list(root):
                if entry.get("PartName", "").lstrip("/") in drop_parts or any(v in entry.get("ContentType", "").lower() for v in ("comments", "thumbnail")):
                    root.remove(entry)
        for nodes in paragraph_nodes(root):
            text = "".join(n.text or "" for n in nodes)
            updated = replace(text)
            if updated != text:
                # Preserve run boundaries by distributing edits over original character spans.
                matches = list(replace.pattern.finditer(text)) if replace.pattern else []
                spans, pos = [], 0
                for node in nodes:
                    spans.append((node, pos, pos + len(node.text or "")))
                    pos += len(node.text or "")
                for match in reversed(matches):
                    first = True
                    for node, start, end in spans:
                        if end <= match.start() or start >= match.end():
                            continue
                        a, b = max(0, match.start() - start), min(end - start, match.end() - start)
                        node.text = (node.text or "")[:a] + (replace.mapping[match[0]] if first else "") + (node.text or "")[b:]
                        first = False
            for node in nodes:
                node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        # Sanitize non-paragraph textual properties too.
        paragraph_text_nodes = {n for group in paragraph_nodes(root) for n in group}
        for node in root.iter():
            if node not in paragraph_text_nodes and node.text:
                node.text = replace(node.text)
        # External relationships have been stripped; retain displayed hyperlink text.
        for node in root.iter():
            if node.tag == W + "hyperlink":
                node.attrib.clear()
    return {n: r for n, r in parts.items() if n not in drop_parts}


def write_document(source, target, replace):
    before = replace.count
    if source.suffix.lower() == ".docx":
        parts = sanitize_docx(docx_parts(source), replace)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, root in parts.items():
                if root.tag in {R + "Relationships", CT + "Types"}:
                    ET.register_namespace("", root.tag.split("}")[0][1:])
                archive.writestr(name, ET.tostring(root, encoding="utf-8", xml_declaration=True))
    else:
        write_pdf(source, target, replace)
    return replace.count - before


def open_pdf(path):
    try:
        import pymupdf
    except ImportError:
        raise FormatError("pdf_dependency_missing") from None
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    doc = pymupdf.open(path)
    if doc.needs_pass or doc.is_encrypted or doc.is_repaired or not doc.is_pdf:
        doc.close()
        raise FormatError("encrypted_damaged_or_non_pdf")
    if doc.embfile_count() or doc.get_ocgs() or doc.get_sigflags() > 0:
        doc.close()
        raise FormatError("unsupported_document_object")
    for page in doc:
        supported_annotations = {"Text", "Link", "FreeText", "Line", "Square", "Circle", "Polygon", "PolyLine", "Highlight", "Underline", "Squiggly", "StrikeOut", "Caret", "Popup"}
        if (page.get_images(full=True) or page.get_image_info() or list(page.widgets())
                or any(a.type[1] not in supported_annotations for a in page.annots())):
            doc.close()
            raise FormatError("unsupported_document_object")
        if not page.get_text().strip():
            doc.close()
            raise FormatError("pdf_page_without_reliable_text")
    return doc


def pdf_units(path):
    with open_pdf(path) as doc:
        values = [{"id": f"page-{i + 1}", "text": p.get_text(sort=True)} for i, p in enumerate(doc)]
        values.append({"id": "metadata", "text": str(doc.metadata) + str(doc.get_toc())})
        # Decode all objects and streams for hidden payload detection/review.
        for i in range(1, doc.xref_length()):
            values.append({"id": f"object-{i}", "text": doc.xref_object(i)})
            if doc.xref_is_stream(i):
                stream = doc.xref_stream(i)
                # Font programs are binary resources; source strings are still checked by check_file.
                values.append({"id": f"stream-{i}", "text": stream.decode("utf-8", errors="replace")})
        return values, ["identity_metadata_removed", "annotations_links_and_outlines_removed", "invisible_text_removed"]


def write_pdf(source, target, replace):
    import pymupdf
    with open_pdf(source) as doc:
        # Remove invisible source content before locating replacements, so it
        # cannot be reintroduced as visible alias text during insertion.
        for page in doc:
            traces = page.get_texttrace()
            hidden = [s for s in traces if s.get("type") == 3 or s.get("opacity", 1) == 0]
            visible = [s for s in traces if s not in hidden]
            for span in hidden:
                rect = pymupdf.Rect(span["bbox"])
                if any(rect.intersects(pymupdf.Rect(s["bbox"])) for s in visible):
                    raise FormatError("pdf_hidden_text_overlaps_visible_content")
                page.add_redact_annot(rect, fill=None, cross_out=False)
            if hidden:
                page.apply_redactions(images=1, graphics=0)
        doc.scrub(hidden_text=True, metadata=True, xml_metadata=True, remove_links=True,
                  attached_files=True, embedded_files=True, javascript=True,
                  reset_fields=True, reset_responses=True, thumbnails=True)
        for page in doc:
            text = page.get_text()
            rects = []
            for match in replace.pattern.finditer(text) if replace.pattern else []:
                boxes = page.search_for(match[0])
                if not boxes:
                    raise FormatError("pdf_text_location_unreliable")
                for box in boxes:
                    key = tuple(box)
                    if any(key == tuple(r) for r, _ in rects):
                        continue
                    if any(box.intersects(r) for r, _ in rects):
                        raise FormatError("pdf_overlapping_redaction")
                    rects.append((box, replace.mapping[match[0]]))
                    page.add_redact_annot(box, fill=(1, 1, 1), cross_out=False)
                    replace.count += 1
            page.apply_redactions(images=1, graphics=0)
            for box, replacement in rects:
                font = "china-s" if any(ord(c) > 127 for c in replacement) else "helv"
                fitted = False
                for size in (10, 9, 8, 7, 6):
                    shape = page.new_shape()
                    if shape.insert_textbox(box + (0, -1, 0, 3), replacement, fontsize=size, fontname=font) >= 0:
                        shape.commit()
                        fitted = True
                        break
                if not fitted:
                    raise FormatError("pdf_replacement_does_not_fit")
        doc.set_toc([])
        doc.scrub(attached_files=True, embedded_files=True, javascript=True, metadata=True,
                  hidden_text=True, remove_links=True, reset_fields=True, reset_responses=True,
                  thumbnails=True, xml_metadata=True)
        for page in doc:
            for annot in list(page.annots()):
                page.delete_annot(annot)
        doc.save(target, garbage=4, clean=True, deflate=True, incremental=False)


def render_candidate(path):
    """Render only sanitized candidates into their private working directory."""
    import pymupdf
    pdf = path
    if path.suffix.lower() == ".docx":
        office = os.environ.get("SOFFICE_PATH") or shutil.which("soffice")
        if not office:
            raise FormatError("docx_renderer_missing")
        profile = path.parent / (path.stem + ".office-profile")
        result = subprocess.run([office, "-env:UserInstallation=" + profile.as_uri(), "--headless", "--convert-to", "pdf", "--outdir", str(path.parent), str(path)], capture_output=True, timeout=90)
        pdf = path.with_suffix(".pdf")
        if result.returncode or not pdf.exists():
            raise FormatError("docx_render_failed")
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc):
            page.get_pixmap(dpi=110).save(path.parent / (path.stem + f".page-{i + 1:04d}.png"))
        return len(doc)
