"""Create a revised copy of the invention disclosure with the requested figure set."""
from io import BytesIO
from pathlib import Path
import copy
import zipfile

from PIL import Image, ImageDraw, ImageFont
from lxml import etree


ROOT = Path(r"C:\Users\gokul\Desktop\PROJECTS\Edge-AI")
SOURCE = ROOT / "docs" / "disclosure_figures" / "SENTINEL_AI_Invention_Disclosure_Reviewed.docx"
OUTPUT = ROOT / "docs" / "disclosure_figures" / "SENTINEL_AI_Invention_Disclosure_Final.docx"
FIGURE = ROOT / "docs" / "disclosure_figures" / "sentinel_ai_architecture_revised.png"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W, "a": A, "r": R}


def font(size: int, bold: bool = False):
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_figure() -> bytes:
    image = Image.new("RGB", (1800, 980), "white")
    draw = ImageDraw.Draw(image)
    navy = "#18324f"
    blue = "#dcecf8"
    gold = "#fff0c7"
    green = "#e2f2e8"
    gray = "#edf1f5"
    draw.rectangle((25, 25, 1775, 955), outline=navy, width=4)
    draw.text((70, 55), "SENTINEL-AI Edge Architecture and Governed Emergency Response", fill=navy, font=font(40, True))
    draw.text((72, 112), "Offline-first multimodal detection with reliability-gated decisions and operator approval", fill="#426485", font=font(23))

    boxes = [
        (70, 205, 395, 445, ["SENSOR ACQUISITION"], ["DHT22 • GY-87 • MQ-2", "INMP441 • GPS • USB camera", "availability and health checks"], blue),
        (470, 205, 795, 445, ["EDGE INFERENCE"], ["audio and vision models", "temporal fusion and OOD", "model ID • version • confidence"], blue),
        (870, 205, 1195, 445, ["RELIABILITY-GATED", "DECISION"], ["risk factors and sensor caps", "assurance state and conflicts", "safety-contract permissions"], gold),
        (1270, 205, 1730, 445, ["OPERATOR WORKFLOW"], ["acknowledge and verify", "approve or reject actions", "escalate • resolve • audit"], green),
    ]
    for x1, y1, x2, y2, title_lines, lines, fill in boxes:
        draw.rounded_rectangle((x1, y1, x2, y2), radius=20, fill=fill, outline="#2d5f91", width=4)
        for title_index, title in enumerate(title_lines):
            draw.text((x1 + 25, y1 + 24 + title_index * 29), title, fill=navy, font=font(22, True))
        for i, line in enumerate(lines):
            draw.text((x1 + 25, y1 + 92 + i * 42 + (len(title_lines) - 1) * 24), line, fill="#263c55", font=font(20))
    for x in (395, 795, 1195):
        draw.line((x, 325, x + 70, 325), fill="#2d5f91", width=7)
        draw.polygon([(x + 70, 325), (x + 52, 313), (x + 52, 337)], fill="#2d5f91")
    draw.line((1030, 445, 1030, 565), fill="#2d5f91", width=7)
    draw.polygon([(1030, 565), (1018, 547), (1042, 547)], fill="#2d5f91")
    draw.rounded_rectangle((250, 565, 1550, 865), radius=20, fill=gray, outline="#73859a", width=4)
    draw.text((290, 605), "AUDITABLE OFFLINE-FIRST RECORD", fill=navy, font=font(30, True))
    audit = [
        "incident timeline • sensor observations • predictions",
        "model/profile and assurance state • OOD reasons",
        "operator actions • evidence files • SHA-256 manifest",
        "local SQLite/WAL outbox • synchronization after connectivity returns",
    ]
    for i, line in enumerate(audit):
        draw.text((290, 670 + i * 42), line, fill="#263c55", font=font(22))
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    FIGURE.write_bytes(out.getvalue())
    return out.getvalue()


def revise_docx(figure_bytes: bytes) -> None:
    with zipfile.ZipFile(SOURCE, "r") as source_zip:
        files = {name: source_zip.read(name) for name in source_zip.namelist()}
    root = etree.fromstring(files["word/document.xml"])
    tables = root.xpath(".//w:tbl", namespaces=NS)
    drawing_cell = tables[0].xpath("./w:tr", namespaces=NS)[24].xpath("./w:tc", namespaces=NS)[-1]
    # Remove the fully-labelled and blank wiring drawings and captions, retaining only the architecture figure.
    for paragraph in list(drawing_cell.xpath("./w:p", namespaces=NS)):
        embeds = [node.get(f"{{{R}}}embed") for node in paragraph.xpath(".//a:blip", namespaces=NS)]
        text = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
        if "rId10" in embeds or "rId11" in embeds or "Fig. 2:" in text or "Fig. 3:" in text:
            drawing_cell.remove(paragraph)
        elif "Fig. 4:" in text:
            for node in paragraph.xpath(".//w:t", namespaces=NS):
                if node.text and "Fig. 4:" in node.text:
                    node.text = node.text.replace("Fig. 4:", "Fig. 2:").replace("System architecture and emergency response flow", "System architecture and governed emergency response flow")
    # Add a compact technical description below the retained figure.
    caption = drawing_cell.xpath("./w:p", namespaces=NS)[-1]
    p = etree.Element(f"{{{W}}}p")
    r = etree.SubElement(p, f"{{{W}}}r")
    t = etree.SubElement(r, f"{{{W}}}t")
    t.text = ("The architecture separates sensing, edge inference, reliability assessment and operator authorization. "
              "Sensor availability, calibration state, model assurance and out-of-distribution indicators are carried with each decision. "
              "A proposed response is recorded before an authorized role confirms it; emergency-service contact remains operator-approved. "
              "The local audit record preserves predictions, evidence hashes and operator actions while an outbox retains events during network loss.")
    drawing_cell.insert(drawing_cell.index(caption) + 1, p)
    files["word/document.xml"] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    files["word/media/image3.png"] = figure_bytes
    for name in ("word/media/image1.png", "word/media/image2.png"):
        files.pop(name, None)
    rels = files["word/_rels/document.xml.rels"].decode("utf-8")
    rel_root = etree.fromstring(files["word/_rels/document.xml.rels"])
    for rel in list(rel_root):
        if rel.get("Id") in ("rId10", "rId11"):
            rel_root.remove(rel)
    files["word/_rels/document.xml.rels"] = etree.tostring(rel_root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as target_zip:
        for name, data in files.items():
            target_zip.writestr(name, data)


if __name__ == "__main__":
    revise_docx(make_figure())
    print(OUTPUT)
