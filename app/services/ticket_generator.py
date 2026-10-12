# Service para geração de ingresso gráfico 9:16 oficial
import os
import io
import math
import logging
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import qrcode

logger = logging.getLogger(__name__)

# Dimensões exatas em proporção 9:16
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')
IMAGES_DIR = os.path.join(STATIC_DIR, 'images')
FONTS_DIR = os.path.join(STATIC_DIR, 'fonts')

def mask_cpf(cpf_raw: Optional[str]) -> str:
    """Garante mascaramento estrito: 000.***.***-00"""
    digits = ''.join(ch for ch in (cpf_raw or '') if ch.isdigit())
    if len(digits) == 11:
        return f"{digits[:3]}.***.***-{digits[-2:]}"
    elif len(digits) >= 5:
        return f"{digits[:3]}.***.***-{digits[-2:]}"
    return "000.***.***-00"

def _get_font(font_name: str, size: int):
    path = os.path.join(FONTS_DIR, font_name)
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    fallback_path = os.path.join(FONTS_DIR, 'DejaVuSans-Bold.ttf')
    if os.path.exists(fallback_path):
        try:
            return ImageFont.truetype(fallback_path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def draw_ticket_outline(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int, r: int, notch_y: int, notch_r: int, color=(255, 255, 255, 180), width=2):
    """Desenha a borda perimetral contínua do ingresso contornando os cantos e os entalhes laterais sem cruzar por dentro deles"""
    draw.line([(x1 + r, y1), (x2 - r, y1)], fill=color, width=width)
    draw.line([(x1 + r, y2), (x2 - r, y2)], fill=color, width=width)
    draw.line([(x1, y1 + r), (x1, notch_y - notch_r)], fill=color, width=width)
    draw.line([(x1, notch_y + notch_r), (x1, y2 - r)], fill=color, width=width)
    draw.line([(x2, y1 + r), (x2, notch_y - notch_r)], fill=color, width=width)
    draw.line([(x2, notch_y + notch_r), (x2, y2 - r)], fill=color, width=width)

    draw.arc([(x1, y1), (x1 + 2 * r, y1 + 2 * r)], 180, 270, fill=color, width=width)
    draw.arc([(x2 - 2 * r, y1), (x2, y1 + 2 * r)], 270, 360, fill=color, width=width)
    draw.arc([(x2 - 2 * r, y2 - 2 * r), (x2, y2)], 0, 90, fill=color, width=width)
    draw.arc([(x1, y2 - 2 * r), (x1 + 2 * r, y2)], 90, 180, fill=color, width=width)

    draw.arc([(x1 - notch_r, notch_y - notch_r), (x1 + notch_r, notch_y + notch_r)], 270, 90, fill=color, width=width)
    draw.arc([(x2 - notch_r, notch_y - notch_r), (x2 + notch_r, notch_y + notch_r)], 90, 270, fill=color, width=width)

def generate_ticket_image(
    nome: str,
    cpf: str,
    ingresso_token: str,
    lote_nome: str,
    secretaria_nome: Optional[str] = None,
    setor: Optional[str] = None,
    data_evento: str = '30 DE OUTUBRO DE 2026',
    local_evento: str = 'CENTRO MULTICULTURAL • CARUARU-PE',
    horario_evento: str = '12:00H'
) -> Image.Image:
    """
    Gera o ingresso oficial em proporção 9:16 (1080x1920) com planos de fundo invertidos:
    - Moldura Externa (ao redor): Azul escuro profundo (#070d1a).
    - Corpo do Ingresso: Fundo holográfico iridescente original (fundo_holografico_template_ingresso.png).
    - QR Code ampliado com logo Servindoor centralizada e informações rente à base.
    - Tipografia de identificação do servidor ampliada para máxima clareza.
    - Parâmetros oficiais de data (30 OUT 2026 / SEXTA-FEIRA), horário (12:00H) e local (CENTRO MULTICULTURAL).
    """
    # 1. Base Externa: Fundo Azul Escuro Profundo (#070d1a)
    canvas = Image.new('RGBA', (CANVAS_WIDTH, CANVAS_HEIGHT), (7, 13, 26, 255))

    # Dimensões Mestras do Cartão do Ingresso
    card_x1 = 52
    card_y1 = 52
    card_x2 = CANVAS_WIDTH - 52
    card_y2 = CANVAS_HEIGHT - 52
    card_r = 34
    notch_y = 750
    notch_r = 26

    # 2. Carregar e ajustar textura holográfica para o corpo do ingresso
    bg_path = os.path.join(IMAGES_DIR, 'fundo_holografico_template_ingresso.png')
    if os.path.exists(bg_path):
        holo_src = Image.open(bg_path).convert('RGBA')
        scale = max(CANVAS_WIDTH / holo_src.width, CANVAS_HEIGHT / holo_src.height)
        new_w, new_h = int(holo_src.width * scale), int(holo_src.height * scale)
        holo_resized = holo_src.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - CANVAS_WIDTH) // 2
        top = (new_h - CANVAS_HEIGHT) // 2
        holo_canvas = holo_resized.crop((left, top, left + CANVAS_WIDTH, top + CANVAS_HEIGHT))
    else:
        holo_canvas = Image.new('RGBA', (CANVAS_WIDTH, CANVAS_HEIGHT), (235, 238, 245, 255))

    # 3. Criar Máscara do Cartão do Ingresso com os Entalhes Vazados
    card_mask = Image.new('L', (CANVAS_WIDTH, CANVAS_HEIGHT), 0)
    draw_card_mask = ImageDraw.Draw(card_mask)

    draw_card_mask.rounded_rectangle(
        [(card_x1, card_y1), (card_x2, card_y2)],
        radius=card_r,
        fill=255
    )

    draw_card_mask.ellipse(
        [(card_x1 - notch_r, notch_y - notch_r), (card_x1 + notch_r, notch_y + notch_r)],
        fill=0
    )
    draw_card_mask.ellipse(
        [(card_x2 - notch_r, notch_y - notch_r), (card_x2 + notch_r, notch_y + notch_r)],
        fill=0
    )

    # Colar o corpo holográfico sobre o fundo azul escuro
    canvas.paste(holo_canvas, (0, 0), card_mask)

    # Camada transparente para elementos gráficos e tipografia
    ticket_layer = Image.new('RGBA', (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    draw_ticket = ImageDraw.Draw(ticket_layer)

    # Desenhar contorno perimetral contínuo contornando os entalhes
    draw_ticket_outline(
        draw_ticket,
        card_x1, card_y1, card_x2, card_y2,
        card_r, notch_y, notch_r,
        color=(255, 255, 255, 180),
        width=2
    )

    # 4. Topo: Tag VIP Dark Navy com Contraste Marcante
    tag_w, tag_h = 390, 42
    tag_x1 = (CANVAS_WIDTH - tag_w) // 2
    tag_y1 = card_y1 + 26
    draw_ticket.rounded_rectangle(
        [(tag_x1, tag_y1), (tag_x1 + tag_w, tag_y1 + tag_h)],
        radius=21,
        fill=(11, 20, 38, 255),
        outline=(14, 165, 233, 220),
        width=2
    )
    font_tag = _get_font('Outfit-Static-Bold.ttf', 16)
    tag_text = 'INGRESSO OFICIAL // PASS VIP'
    bbox_tag = font_tag.getbbox(tag_text)
    tw = bbox_tag[2] - bbox_tag[0]
    th = bbox_tag[3] - bbox_tag[1]
    draw_ticket.text((tag_x1 + (tag_w - tw) // 2, tag_y1 + (tag_h - th) // 2 - 2), tag_text, fill=(56, 189, 248, 255), font=font_tag)

    # Logo Serv indoor
    logo_path = os.path.join(IMAGES_DIR, 'logo_servindoor_sem-fundo.png')
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert('RGBA')
        target_logo_w = 360
        logo_ratio = target_logo_w / logo.width
        target_logo_h = int(logo.height * logo_ratio)
        logo_resized = logo.resize((target_logo_w, target_logo_h), Image.Resampling.LANCZOS)
        logo_x = (CANVAS_WIDTH - target_logo_w) // 2
        logo_y = tag_y1 + tag_h + 12
        ticket_layer.paste(logo_resized, (logo_x, logo_y), logo_resized)
        sub_y = logo_y + target_logo_h + 8
    else:
        font_fest = _get_font('Outfit-Static-Bold.ttf', 44)
        fest_text = 'SERV INDOOR 2026'
        bbox_f = font_fest.getbbox(fest_text)
        draw_ticket.text(((CANVAS_WIDTH - (bbox_f[2] - bbox_f[0])) // 2, tag_y1 + 60), fest_text, fill=(15, 23, 42, 255), font=font_fest)
        sub_y = tag_y1 + 130

    font_sub = _get_font('Outfit-Static-Bold.ttf', 19)
    sub_text = 'A FESTA DO SERVIDOR PÚBLICO • EDIÇÃO 2026'
    bbox_sub = font_sub.getbbox(sub_text)
    draw_ticket.text(((CANVAS_WIDTH - (bbox_sub[2] - bbox_sub[0])) // 2, sub_y), sub_text, fill=(15, 23, 42, 255), font=font_sub)

    # 5. Bloco de Identificação do Servidor (Fontes Aumentadas para Máxima Legibilidade)
    info_box_y1 = sub_y + 20
    info_box_y2 = notch_y - 22
    
    # Sombra sutil projetada
    draw_ticket.rounded_rectangle(
        [(card_x1 + 32, info_box_y1 + 4), (card_x2 - 32, info_box_y2 + 4)],
        radius=18,
        fill=(0, 0, 0, 45)
    )

    draw_ticket.rounded_rectangle(
        [(card_x1 + 32, info_box_y1), (card_x2 - 32, info_box_y2)],
        radius=18,
        fill=(11, 20, 38, 250),
        outline=(14, 165, 233, 90),
        width=2
    )

    font_lbl = _get_font('Outfit-Static-Bold.ttf', 14)

    # Linha 1: Participante (Fonte Aumentada)
    draw_ticket.text((card_x1 + 54, info_box_y1 + 14), 'NOME DO SERVIDOR / PARTICIPANTE', fill=(148, 163, 184, 255), font=font_lbl)

    nome_clean = (nome or 'SERVIDOR PÚBLICO').strip().upper()
    nome_font_size = 35
    if len(nome_clean) > 28:
        nome_font_size = 31
    if len(nome_clean) > 38:
        nome_font_size = 26
    font_nome = _get_font('Outfit-Static-Bold.ttf', nome_font_size)
    draw_ticket.text((card_x1 + 54, info_box_y1 + 36), nome_clean[:46], fill=(255, 255, 255, 255), font=font_nome)

    # Divisória interna 1
    div1_y = info_box_y1 + 86
    draw_ticket.line([(card_x1 + 54, div1_y), (card_x2 - 54, div1_y)], fill=(255, 255, 255, 25), width=1)

    # Linha 2: CPF e Lote (Fontes Aumentadas)
    col1_x = card_x1 + 54
    col2_x = card_x1 + 490
    row2_y = div1_y + 12

    draw_ticket.text((col1_x, row2_y), 'CPF DO TITULAR', fill=(148, 163, 184, 255), font=font_lbl)
    font_cpf = _get_font('DejaVuSansMono-Bold.ttf', 27)
    cpf_mascarado = mask_cpf(cpf)
    draw_ticket.text((col1_x, row2_y + 22), cpf_mascarado, fill=(56, 189, 248, 255), font=font_cpf)

    draw_ticket.text((col2_x, row2_y), 'LOTE DO INGRESSO', fill=(148, 163, 184, 255), font=font_lbl)
    font_lote = _get_font('Outfit-Static-Bold.ttf', 25)
    lote_clean = (lote_nome or 'LOTE GERAL').strip()[:24]
    draw_ticket.text((col2_x, row2_y + 22), lote_clean, fill=(248, 250, 252, 255), font=font_lote)

    # Divisória interna 2
    div2_y = row2_y + 60
    draw_ticket.line([(card_x1 + 54, div2_y), (card_x2 - 54, div2_y)], fill=(255, 255, 255, 25), width=1)

    # Linha 3: Secretaria e Setor (Fontes Aumentadas)
    row3_y = div2_y + 12
    draw_ticket.text((col1_x, row3_y), 'SECRETARIA / ÓRGÃO', fill=(148, 163, 184, 255), font=font_lbl)
    sec_clean = (secretaria_nome or 'PREFEITURA MUNICIPAL').strip()
    font_sec_size = 23
    if len(sec_clean) > 28:
        font_sec_size = 20
    font_sec = _get_font('Outfit-Static-SemiBold.ttf', font_sec_size)
    draw_ticket.text((col1_x, row3_y + 22), sec_clean[:38], fill=(226, 232, 240, 255), font=font_sec)

    draw_ticket.text((col2_x, row3_y), 'SETOR / LOTAÇÃO', fill=(148, 163, 184, 255), font=font_lbl)
    setor_clean = (setor or 'GERAL').strip()
    font_setor_size = 23
    if len(setor_clean) > 26:
        font_setor_size = 20
    font_setor = _get_font('Outfit-Static-SemiBold.ttf', font_setor_size)
    draw_ticket.text((col2_x, row3_y + 22), setor_clean[:32], fill=(203, 213, 225, 255), font=font_setor)

    # 6. QR Code EXTRA GRANDE (Card de 700px com sombra e borda destacada)
    qr_card_size = 700
    qr_card_x1 = (CANVAS_WIDTH - qr_card_size) // 2
    qr_card_y1 = notch_y + 35
    qr_card_x2 = qr_card_x1 + qr_card_size
    qr_card_y2 = qr_card_y1 + qr_card_size

    # Sombra elegante projetada do QR Code sobre o fundo holográfico
    draw_ticket.rounded_rectangle(
        [(qr_card_x1 + 6, qr_card_y1 + 8), (qr_card_x2 + 6, qr_card_y2 + 8)],
        radius=32,
        fill=(0, 0, 0, 45)
    )

    # Card Branco do QR Code
    draw_ticket.rounded_rectangle(
        [(qr_card_x1, qr_card_y1), (qr_card_x2, qr_card_y2)],
        radius=32,
        fill=(255, 255, 255, 255),
        outline=(203, 213, 225, 255),
        width=2
    )

    # Gerar imagem do QR Code com Error Correction H (30% redundância)
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=15,
        border=1,
    )
    qr.add_data(ingresso_token or 'TKT-TESTE-2026')
    qr.make(fit=True)
    qr_pil = qr.make_image(fill_color='black', back_color='white').convert('RGBA')

    qr_inner_size = 630
    qr_resized = qr_pil.resize((qr_inner_size, qr_inner_size), Image.Resampling.LANCZOS)

    # Logo Servindoor no Centro do QR Code
    if os.path.exists(logo_path):
        qr_logo = Image.open(logo_path).convert('RGBA')
        logo_target_w = 150
        logo_ratio = logo_target_w / qr_logo.width
        logo_target_h = int(qr_logo.height * logo_ratio)
        qr_logo_resized = qr_logo.resize((logo_target_w, logo_target_h), Image.Resampling.LANCZOS)

        pad_x = 12
        pad_y = 10
        bg_w = logo_target_w + pad_x * 2
        bg_h = logo_target_h + pad_y * 2
        bg_x = (qr_inner_size - bg_w) // 2
        bg_y = (qr_inner_size - bg_h) // 2

        draw_qr = ImageDraw.Draw(qr_resized)
        draw_qr.rounded_rectangle(
            [(bg_x, bg_y), (bg_x + bg_w, bg_y + bg_h)],
            radius=18,
            fill=(255, 255, 255, 255),
            outline=(226, 232, 240, 255),
            width=2
        )

        logo_cx = (qr_inner_size - logo_target_w) // 2
        logo_cy = (qr_inner_size - logo_target_h) // 2
        qr_resized.paste(qr_logo_resized, (logo_cx, logo_cy), qr_logo_resized)

    qr_x = qr_card_x1 + (qr_card_size - qr_inner_size) // 2
    qr_y = qr_card_y1 + (qr_card_size - qr_inner_size) // 2
    ticket_layer.paste(qr_resized, (qr_x, qr_y), qr_resized)

    # 7. Badge de Validade do QR
    val_w = 500
    val_h = 42
    val_x1 = (CANVAS_WIDTH - val_w) // 2
    val_y1 = qr_card_y2 + 22
    draw_ticket.rounded_rectangle(
        [(val_x1, val_y1), (val_x1 + val_w, val_y1 + val_h)],
        radius=21,
        fill=(6, 78, 59, 245),
        outline=(16, 185, 129, 230),
        width=2
    )
    font_val = _get_font('Outfit-Static-Bold.ttf', 15)
    val_txt = 'LIBERADO // APRESENTE NA PORTARIA OFICIAL'
    bbox_val = font_val.getbbox(val_txt)
    draw_ticket.text((val_x1 + (val_w - (bbox_val[2] - bbox_val[0])) // 2, val_y1 + 11), val_txt, fill=(52, 211, 153, 255), font=font_val)

    # 8. Bloco de Logística do Evento (Atualizado com Data, Horário e Local definidos para todos)
    box_w = (card_x2 - card_x1 - 64 - 24) // 3
    box_y1 = val_y1 + 48
    box_y2 = box_y1 + 116

    boxes_info = [
        ('DATA DO EVENTO', '30 OUT 2026', 'SEXTA-FEIRA', (56, 189, 248)),
        ('HORÁRIO', '12:00H', 'ABERTURA PORTÕES', (255, 255, 255)),
        ('LOCALIZAÇÃO', 'CENTRO MULTICULTURAL', 'CARUARU - PE', (52, 211, 153))
    ]

    for idx, (b_lbl, b_main, b_sub, b_color) in enumerate(boxes_info):
        bx1 = card_x1 + 32 + idx * (box_w + 12)
        bx2 = bx1 + box_w
        
        # Sombra sutil
        draw_ticket.rounded_rectangle(
            [(bx1 + 3, box_y1 + 4), (bx2 + 3, box_y2 + 4)],
            radius=14,
            fill=(0, 0, 0, 40)
        )

        draw_ticket.rounded_rectangle(
            [(bx1, box_y1), (bx2, box_y2)],
            radius=14,
            fill=(11, 20, 38, 250),
            outline=(14, 165, 233, 80),
            width=2
        )
        font_b_lbl = _get_font('Outfit-Static-Bold.ttf', 12)
        bbox_bl = font_b_lbl.getbbox(b_lbl)
        draw_ticket.text((bx1 + (box_w - (bbox_bl[2] - bbox_bl[0])) // 2, box_y1 + 16), b_lbl, fill=(148, 163, 184, 255), font=font_b_lbl)

        font_main_size = 20
        if len(b_main) > 16:
            font_main_size = 18
        font_b_main = _get_font('Outfit-Static-Bold.ttf', font_main_size)
        bbox_bm = font_b_main.getbbox(b_main)
        draw_ticket.text((bx1 + (box_w - (bbox_bm[2] - bbox_bm[0])) // 2, box_y1 + 41), b_main, fill=(*b_color, 255), font=font_b_main)

        font_b_sub = _get_font('Outfit-Static-Medium.ttf', 13)
        bbox_bs = font_b_sub.getbbox(b_sub)
        draw_ticket.text((bx1 + (box_w - (bbox_bs[2] - bbox_bs[0])) // 2, box_y1 + 78), b_sub, fill=(148, 163, 184, 255), font=font_b_sub)

    # 9. Rodapé Legal e de Segurança (Dark Slate de Alto Contraste sobre o Holográfico Claro)
    footer_y = box_y2 + 28
    font_legal1 = _get_font('Outfit-Static-Bold.ttf', 17)
    leg1 = 'INGRESSO INDIVIDUAL, NOMINAL E INTRANSFERÍVEL'
    bbox_l1 = font_legal1.getbbox(leg1)
    draw_ticket.text(((CANVAS_WIDTH - (bbox_l1[2] - bbox_l1[0])) // 2, footer_y), leg1, fill=(15, 23, 42, 255), font=font_legal1)

    font_legal2 = _get_font('Outfit-Static-Bold.ttf', 14)
    leg2 = 'Obrigatória a apresentação de documento oficial com foto na portaria.'
    bbox_l2 = font_legal2.getbbox(leg2)
    draw_ticket.text(((CANVAS_WIDTH - (bbox_l2[2] - bbox_l2[0])) // 2, footer_y + 26), leg2, fill=(51, 65, 85, 255), font=font_legal2)

    font_legal3 = _get_font('Outfit-Static-SemiBold.ttf', 13)
    leg3 = 'A validação do acesso será realizada exclusivamente pelo QR Code oficial.'
    bbox_l3 = font_legal3.getbbox(leg3)
    draw_ticket.text(((CANVAS_WIDTH - (bbox_l3[2] - bbox_l3[0])) // 2, footer_y + 50), leg3, fill=(71, 85, 105, 255), font=font_legal3)

    font_legal4 = _get_font('Outfit-Static-Medium.ttf', 12)
    leg4 = '© 2026 Serv indoor • Sistema Oficial de Gestão de Eventos • servindoor.com.br'
    bbox_l4 = font_legal4.getbbox(leg4)
    draw_ticket.text(((CANVAS_WIDTH - (bbox_l4[2] - bbox_l4[0])) // 2, footer_y + 74), leg4, fill=(100, 116, 139, 255), font=font_legal4)

    # 10. Compor camada de elementos sobre o canvas
    final_img = Image.alpha_composite(canvas, ticket_layer)
    return final_img.convert('RGB')

def generate_ticket_png_bytes(**kwargs) -> bytes:
    img = generate_ticket_image(**kwargs)
    buf = io.BytesIO()
    img.save(buf, format='PNG', quality=95, optimize=True)
    return buf.getvalue()

def generate_ticket_pdf_bytes(**kwargs) -> bytes:
    """
    Gera o PDF oficial do ingresso contendo exclusivamente a imagem PNG do ingresso
    (o mesmo modelo 9:16 enviado por e-mail). A página do PDF contém apenas o PNG do ingresso.
    """
    img = generate_ticket_image(**kwargs)
    buf = io.BytesIO()
    img.save(buf, format='PDF', resolution=180.0)
    return buf.getvalue()
