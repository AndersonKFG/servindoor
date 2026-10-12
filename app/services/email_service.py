import io
import base64
import smtplib
import asyncio
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from typing import Optional
from app.core.config import settings
from app.services.email_queue import enqueue_email

logger = logging.getLogger(__name__)

def gerar_qrcode_png_bytes(data: str) -> Optional[bytes]:
    """Gera imagem de QR Code em bytes PNG puros localmente"""
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"Erro ao gerar QR Code PNG: {e}")
        return None


def _send_smtp_email_sync(
    to_email: str,
    subject: str,
    html_body: str,
    qr_image_bytes: Optional[bytes] = None,
    ticket_image_bytes: Optional[bytes] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
) -> bool:
    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = subject
        from_email = from_email or settings.SMTP_FROM
        msg["From"] = f"{from_name or settings.SMTP_FROM_NAME} <{from_email}>"
        msg["To"] = to_email

        msg_alternative = MIMEMultipart("alternative")
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(html_body, "html", "utf-8"))

        if qr_image_bytes:
            img = MIMEImage(qr_image_bytes, "png")
            img.add_header("Content-ID", "<qrcode_ingresso>")
            img.add_header("Content-Disposition", "inline", filename="qrcode_ingresso.png")
            msg.attach(img)

        if ticket_image_bytes:
            ticket_img = MIMEImage(ticket_image_bytes, "png")
            ticket_img.add_header("Content-ID", "<ticket_oficial_png>")
            ticket_img.add_header("Content-Disposition", "inline", filename="ingresso_servindoor_2026.png")
            msg.attach(ticket_img)

        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        logger.info(f"E-mail enviado com sucesso para {to_email}")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar e-mail via Amazon SES para {to_email}: {e}")
        return False

async def send_ticket_email_async(
    usuario_nome: str,
    usuario_email: str,
    ingresso_token: str,
    lote_nome: str,
    secretaria_nome: str = None,
    setor: str = None,
    cpf_formatado: str = None
) -> bool:
    """Envia o ingresso digital 9:16 por e-mail em background com apresentação limpa e focada exclusivamente no ingresso"""
    if not usuario_email or "@" not in usuario_email:
        return False

    from app.services.ticket_generator import generate_ticket_png_bytes, mask_cpf

    subject = "🎟️ Seu Ingresso Oficial • Serv indoor 2026"
    cpf_mascarado = mask_cpf(cpf_formatado)
    
    try:
        ticket_bytes = generate_ticket_png_bytes(
            nome=usuario_nome,
            cpf=cpf_mascarado,
            ingresso_token=ingresso_token,
            lote_nome=lote_nome,
            secretaria_nome=secretaria_nome,
            setor=setor
        )
    except Exception as err:
        logger.error(f"Erro ao gerar modelo 9:16 do ingresso: {err}")
        ticket_bytes = None

    if not ticket_bytes:
        return False

    html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Seu Ingresso • Serv indoor 2026</title>
</head>
<body style="margin: 0; padding: 0; background-color: #07090e; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; text-align: center;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #07090e; padding: 25px 10px;">
    <tr>
      <td align="center">
        <!-- Ingresso Oficial 9:16 Direto e Limpo -->
        <table role="presentation" cellspacing="0" cellpadding="0" style="max-width: 500px; width: 100%;">
          <tr>
            <td align="center" style="padding: 0;">
              <img
                src="cid:ticket_oficial_png"
                alt="Ingresso Oficial Serv indoor 2026"
                style="width: 100%; max-width: 480px; height: auto; border-radius: 20px; display: block; margin: 0 auto; box-shadow: 0 25px 60px rgba(0,0,0,0.85);"
              />
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return await enqueue_email(usuario_email, subject, html, "ticket", ticket_image=ticket_bytes)


async def send_custom_message_email_async(
    usuario_nome: str,
    usuario_email: str,
    assunto: str,
    mensagem: str,
    badge_texto: str = "COMUNICADO OFICIAL"
) -> bool:
    """Envia uma mensagem personalizada ou comunicado oficial para o usuário via Amazon SES"""
    if not usuario_email or "@" not in usuario_email:
        return False

    mensagem_formatada = "<br>".join(line.strip() for line in mensagem.strip().split("\n") if line.strip())

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{assunto}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #090d16; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #f8fafc;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 30px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background: #131d31; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
          
          <!-- Header Gradiente -->
          <tr>
            <td style="background: linear-gradient(135deg, #1d4ed8 0%, #7c3aed 100%); padding: 35px 25px; text-align: center;">
              <span style="background: rgba(255,255,255,0.2); color: #ffffff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 999px; text-transform: uppercase; letter-spacing: 1px; display: inline-block; margin-bottom: 12px;">
                📢 {badge_texto}
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">
                Serv indoor
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                Serv indoor &bull; Mensagem da Organização
              </p>
            </td>
          </tr>

          <!-- Corpo da Mensagem -->
          <tr>
            <td style="padding: 30px 25px;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 20px;">
                Olá, <strong style="color: #ffffff; font-size: 17px;">{usuario_nome}</strong>!
              </p>

              <div style="background: rgba(255,255,255,0.04); border-left: 4px solid #3b82f6; border-radius: 8px; padding: 20px; margin: 20px 0; color: #e2e8f0; font-size: 15px; line-height: 1.7;">
                {mensagem_formatada}
              </div>

              <p style="font-size: 13px; color: #94a3b8; line-height: 1.5; margin-top: 25px; margin-bottom: 0;">
                Em caso de dúvidas ou necessidade de suporte, responda diretamente a este e-mail ou procure a comissão organizadora.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Serv indoor &bull; Sistema Oficial de Gestão de Eventos
              </p>
              <p style="margin: 5px 0 0; font-size: 11px; color: #334155;">
                Enviado através do domínio oficial <strong>servindoor.com.br</strong> via Amazon SES.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return await enqueue_email(usuario_email, assunto, html, "communications")


async def send_cancellation_code_email_async(
    usuario_nome: str,
    usuario_email: str,
    codigo: str
) -> bool:
    """Envia código de verificação para confirmação de cancelamento de ingresso via Amazon SES"""
    if not usuario_email or "@" not in usuario_email:
        return False

    assunto = f"Código de Confirmação: {codigo} - Cancelamento de Ingresso | Serv indoor"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{assunto}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #090d16; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #f8fafc;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 30px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background: #131d31; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
          
          <!-- Header Gradiente Vermelho/Laranja de Segurança -->
          <tr>
            <td style="background: linear-gradient(135deg, #dc2626 0%, #ea580c 100%); padding: 35px 25px; text-align: center;">
              <span style="background: rgba(255,255,255,0.2); color: #ffffff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 999px; text-transform: uppercase; letter-spacing: 1px; display: inline-block; margin-bottom: 12px;">
                🔐 CÓDIGO DE SEGURANÇA 2FA
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">
                Serv indoor &bull; Festa do Servidor 2026
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                Solicitação de Cancelamento de Ingresso
              </p>
            </td>
          </tr>

          <!-- Corpo do Email -->
          <tr>
            <td style="padding: 30px 25px; text-align: center;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 16px; text-align: left;">
                Olá, <strong style="color: #ffffff; font-size: 17px;">{usuario_nome}</strong>!
              </p>
              
              <p style="font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 25px; text-align: left;">
                Recebemos um pedido para cancelar o seu ingresso oficial para a Festa do Servidor 2026. Para dar continuidade e passar à etapa de conferência facial ao vivo, utilize o código de autorização abaixo:
              </p>

              <!-- Caixa do Código -->
              <div style="background: rgba(255,255,255,0.05); border: 2px dashed #f97316; border-radius: 16px; padding: 25px 15px; margin: 25px auto; max-width: 320px; text-align: center;">
                <span style="display: block; font-size: 11px; font-weight: 800; color: #fb923c; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px;">
                  Seu Código de Confirmação
                </span>
                <span style="font-family: monospace, 'Courier New', Courier; font-size: 38px; font-weight: 900; letter-spacing: 8px; color: #ffffff; display: block;">
                  {codigo}
                </span>
                <span style="display: block; font-size: 12px; color: #94a3b8; margin-top: 10px;">
                  ⏳ Válido por 15 minutos
                </span>
              </div>

              <!-- Aviso de Segurança -->
              <div style="background: rgba(239, 68, 68, 0.08); border-left: 4px solid #ef4444; border-radius: 8px; padding: 14px 18px; margin: 25px 0; text-align: left;">
                <strong style="color: #fca5a5; font-size: 13px; display: block; margin-bottom: 4px;">
                  ⚠️ Não foi você quem solicitou?
                </strong>
                <p style="margin: 0; font-size: 12px; color: #cbd5e1; line-height: 1.5;">
                  Se você não iniciou este cancelamento, <strong>não compartilhe este código com ninguém</strong>. Seu ingresso permanece ativo e seguro.
                </p>
              </div>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Serv indoor &bull; Sistema Oficial de Gestão de Eventos
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return await enqueue_email(usuario_email, assunto, html, "security")


async def send_cancellation_result_email_async(
    usuario_nome: str,
    usuario_email: str,
    aprovado: bool,
    motivo: Optional[str] = None
) -> bool:
    """Envia e-mail informando o resultado da conferência facial e status final do cancelamento"""
    if not usuario_email or "@" not in usuario_email:
        return False

    if aprovado:
        assunto = "Ingresso Cancelado com Sucesso - Serv indoor 2026"
        badge_header = "✅ CANCELAMENTO CONCLUÍDO"
        header_gradient = "linear-gradient(135deg, #10b981 0%, #059669 100%)"
        subtitulo = "Sua solicitação foi aprovada pela organização"
        mensagem_corpo = """
        <p style="font-size: 15px; color: #e2e8f0; line-height: 1.6; margin-bottom: 20px;">
          Informamos que a validação facial da sua foto ao vivo foi <strong>concluída com sucesso</strong> por nossa equipe administrativa.
        </p>
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 12px; padding: 18px; margin: 20px 0;">
          <strong style="color: #34d399; font-size: 14px; display: block; margin-bottom: 6px;">
            🎫 Status do Ingresso: CANCELADO
          </strong>
          <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
            Seu ingresso anterior foi anulado e a vaga foi devolvida ao lote do evento. O QR Code anterior foi desativado na portaria.
          </p>
        </div>
        """
    else:
        assunto = "Solicitação de Cancelamento Não Aprovada - Serv indoor 2026"
        badge_header = "❌ SOLICITAÇÃO REJEITADA"
        header_gradient = "linear-gradient(135deg, #ef4444 0%, #b91c1c 100%)"
        subtitulo = "A conferência facial não pôde ser confirmada"
        motivo_texto = motivo if motivo else "A foto enviada ao vivo não conferiu com a foto registrada no cadastro do titular."
        mensagem_corpo = f"""
        <p style="font-size: 15px; color: #e2e8f0; line-height: 1.6; margin-bottom: 20px;">
          Informamos que a sua solicitação de cancelamento de ingresso <strong>não foi aprovada</strong> pela comissão organizadora.
        </p>
        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 12px; padding: 18px; margin: 20px 0;">
          <strong style="color: #fca5a5; font-size: 14px; display: block; margin-bottom: 6px;">
            Motivo informado pelo Administrador:
          </strong>
          <p style="margin: 0; font-size: 13px; color: #f1f5f9; line-height: 1.5;">
            {motivo_texto}
          </p>
        </div>
        <p style="font-size: 13px; color: #94a3b8; line-height: 1.5;">
          <strong>Seu ingresso permanece ativo e válido!</strong> Caso ainda deseje cancelar, realize um novo pedido garantindo boa iluminação e posicionamento central do seu rosto na câmera.
        </p>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{assunto}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #090d16; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #f8fafc;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 30px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background: #131d31; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
          
          <!-- Header Gradiente -->
          <tr>
            <td style="background: {header_gradient}; padding: 35px 25px; text-align: center;">
              <span style="background: rgba(255,255,255,0.2); color: #ffffff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 999px; text-transform: uppercase; letter-spacing: 1px; display: inline-block; margin-bottom: 12px;">
                {badge_header}
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">
                Serv indoor &bull; Festa do Servidor 2026
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                {subtitulo}
              </p>
            </td>
          </tr>

          <!-- Corpo do Email -->
          <tr>
            <td style="padding: 30px 25px;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 20px;">
                Olá, <strong style="color: #ffffff; font-size: 17px;">{usuario_nome}</strong>!
              </p>

              {mensagem_corpo}

              <p style="font-size: 12px; color: #64748b; line-height: 1.5; margin-top: 25px; margin-bottom: 0;">
                Em caso de dúvidas, procure a organização ou responda a este comunicado.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Serv indoor &bull; Sistema Oficial de Gestão de Eventos
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return await enqueue_email(usuario_email, assunto, html, "security")


async def send_lote_deletion_code_email_async(
    admin_nome: str,
    admin_email: str,
    lote_nome: str,
    total_ingressos: int,
    codigo: str
) -> bool:
    """Envia código de segurança para autorização de exclusão crítica de lote com participantes"""
    if not admin_email or "@" not in admin_email:
        return False

    assunto = f"🚨 CÓDIGO DE SEGURANÇA: {codigo} - Exclusão de Lote '{lote_nome}' | Serv indoor"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{assunto}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #090d16; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #f8fafc;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 30px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background: #131d31; border-radius: 20px; overflow: hidden; border: 1px solid rgba(239, 68, 68, 0.4); box-shadow: 0 20px 50px rgba(0,0,0,0.7);">
          
          <!-- Header Alerta Crítico Vermelho -->
          <tr>
            <td style="background: linear-gradient(135deg, #b91c1c 0%, #7f1d1d 100%); padding: 35px 25px; text-align: center;">
              <span style="background: rgba(255,255,255,0.2); color: #ffffff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 999px; text-transform: uppercase; letter-spacing: 1.5px; display: inline-block; margin-bottom: 12px;">
                ⚠️ AÇÃO CRÍTICA DE ADMINISTRADOR
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">
                Autorização de Exclusão de Lote
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                Serv indoor &bull; Festa do Servidor 2026
              </p>
            </td>
          </tr>

          <!-- Corpo do Email -->
          <tr>
            <td style="padding: 30px 25px; text-align: center;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 16px; text-align: left;">
                Olá, Administrador <strong style="color: #ffffff; font-size: 17px;">{admin_nome}</strong>!
              </p>
              
              <div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; border-radius: 8px; padding: 14px 18px; margin: 20px 0; text-align: left;">
                <strong style="color: #fca5a5; font-size: 14px; display: block; margin-bottom: 4px;">
                  Atenção: Exclusão com Participantes
                </strong>
                <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                  Você solicitou a exclusão do lote <strong>"{lote_nome}"</strong>, que possui <strong>{total_ingressos} participante(s) com ingresso(s) resgatado(s)</strong>.
                </p>
              </div>

              <p style="font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 25px; text-align: left;">
                Para confirmar esta operação de alto impacto, digite o código de segurança abaixo no painel de administração:
              </p>

              <!-- Caixa do Código -->
              <div style="background: rgba(0,0,0,0.4); border: 2px dashed #ef4444; border-radius: 16px; padding: 22px 15px; margin: 25px auto; max-width: 320px; text-align: center;">
                <span style="display: block; font-size: 11px; font-weight: 800; color: #fca5a5; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px;">
                  Código de Autorização 2FA
                </span>
                <span style="font-family: monospace, 'Courier New', Courier; font-size: 38px; font-weight: 900; letter-spacing: 8px; color: #ffffff; display: block;">
                  {codigo}
                </span>
                <span style="display: block; font-size: 12px; color: #94a3b8; margin-top: 10px;">
                  ⏳ Válido por 10 minutos
                </span>
              </div>

              <!-- Retenção de 3 dias -->
              <div style="background: rgba(56, 189, 248, 0.08); border-left: 4px solid #0284c7; border-radius: 8px; padding: 12px 16px; margin: 20px 0; text-align: left;">
                <p style="margin: 0; font-size: 12px; color: #bae6fd; line-height: 1.5;">
                  🔒 <strong>Garantia de Recuperação:</strong> Após a exclusão, todos os dados deste lote e seus ingressos ficarão salvos na <strong>Lixeira / Backups Protegidos por 3 dias</strong> e não poderão ser descartados antes desse prazo.
                </p>
              </div>

              <p style="font-size: 12px; color: #64748b; line-height: 1.5; margin-top: 25px; margin-bottom: 0; text-align: left;">
                Se você <strong>NÃO</strong> realizou esta solicitação, feche o painel e altere sua senha imediatamente.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Serv indoor &bull; Gestão VIP de Alta Segurança
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    return await enqueue_email(admin_email, assunto, html, "security")


async def send_validation_pending_email_async(
    usuario_nome: str,
    usuario_email: str,
    lote_nome: str,
    secretaria_nome: str = None
) -> bool:
    """Informa ao participante que o resgate foi realizado e está sob validação em até 72h"""
    if not usuario_email or "@" not in usuario_email:
        return False

    assunto = "⏳ Resgate Realizado com Sucesso • Validação em Andamento (Até 72h) • Serv indoor"
    sec_info = f"<p style='margin: 6px 0 0; color: #94a3b8; font-size: 13px;'>Secretaria: <strong style='color: #cbd5e1;'>{secretaria_nome}</strong></p>" if secretaria_nome else ""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{assunto}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #090d16; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #f8fafc;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 30px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background: #131d31; border-radius: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
          <tr>
            <td style="background: linear-gradient(135deg, #0284c7 0%, #38bdf8 100%); padding: 35px 25px; text-align: center;">
              <span style="background: rgba(0,0,0,0.25); color: #ffffff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 999px; text-transform: uppercase; letter-spacing: 1px; display: inline-block; margin-bottom: 12px;">
                ✅ Resgate Registrado com Sucesso
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">
                Serv indoor &bull; Festa do Servidor 2026
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                Lote: {lote_nome}
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding: 30px 25px;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 16px;">
                Olá, <strong style="color: #ffffff; font-size: 17px;">{usuario_nome}</strong>!
              </p>

              <!-- Card com os 4 pontos obrigatórios -->
              <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 14px; padding: 20px; margin: 20px 0;">
                <div style="margin-bottom: 14px;">
                  <strong style="color: #38bdf8; font-size: 15px; display: block; margin-bottom: 4px;">
                    1. Resgate realizado com sucesso!
                  </strong>
                  <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                    Sua solicitação de ingresso foi devidamente registrada e sua vaga está retida no lote.
                  </p>
                  {sec_info}
                </div>

                <div style="margin-bottom: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);">
                  <strong style="color: #fbbf24; font-size: 15px; display: block; margin-bottom: 4px;">
                    2. Validação de Vínculo
                  </strong>
                  <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                    O sistema e a equipe da <strong>Servindoor</strong> irão validar se você é servidor(a) público(a).
                  </p>
                </div>

                <div style="margin-bottom: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);">
                  <strong style="color: #34d399; font-size: 15px; display: block; margin-bottom: 4px;">
                    3. Notificação Posterior
                  </strong>
                  <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                    Após a validação, você receberá uma mensagem informando eventuais problemas ou contendo seu ingresso oficial com QR Code.
                  </p>
                </div>

                <div style="padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06);">
                  <strong style="color: #a78bfa; font-size: 15px; display: block; margin-bottom: 4px;">
                    4. Prazo de Processamento
                  </strong>
                  <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                    Todo esse processo de conferência ocorrerá em <strong>até 72 horas</strong>.
                  </p>
                </div>
              </div>

              <p style="font-size: 12px; color: #64748b; line-height: 1.5; margin-top: 25px; margin-bottom: 0; text-align: center;">
                Em caso de dúvidas, acompanhe o status em <a href="https://servindoor.com.br/meu-ingresso" style="color: #38bdf8; text-decoration: none;">servindoor.com.br/meu-ingresso</a>.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Serv indoor &bull; Gestão Oficial de Eventos
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return await enqueue_email(usuario_email, assunto, html, "communications")


async def send_validation_rejection_email_async(
    usuario_nome: str,
    usuario_email: str,
    lote_nome: str,
    motivo: str = None
) -> bool:
    """Informa ao participante que sua solicitação de ingresso foi indeferida na validação manual"""
    if not usuario_email or "@" not in usuario_email:
        return False

    assunto = "❌ Informação sobre sua Solicitação de Ingresso • Serv indoor"
    motivo_texto = motivo or "Vínculo de servidor público municipal não confirmado pela secretaria responsável."

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{assunto}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #090d16; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #f8fafc;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #090d16; padding: 30px 10px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width: 580px; background: #131d31; border-radius: 20px; overflow: hidden; border: 1px solid rgba(239, 68, 68, 0.3); box-shadow: 0 20px 50px rgba(0,0,0,0.6);">
          <tr>
            <td style="background: linear-gradient(135deg, #ef4444 0%, #991b1b 100%); padding: 35px 25px; text-align: center;">
              <span style="background: rgba(255,255,255,0.2); color: #ffffff; font-size: 11px; font-weight: 800; padding: 5px 14px; border-radius: 999px; text-transform: uppercase; letter-spacing: 1px; display: inline-block; margin-bottom: 12px;">
                Resultado da Validação
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;">
                Serv indoor &bull; Festa do Servidor 2026
              </h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 30px 25px;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 16px;">
                Olá, <strong style="color: #ffffff; font-size: 17px;">{usuario_nome}</strong>.
              </p>
              <div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; border-radius: 8px; padding: 14px 18px; margin: 20px 0;">
                <strong style="color: #fca5a5; font-size: 14px; display: block; margin-bottom: 4px;">
                  Solicitação de Ingresso Não Concluída
                </strong>
                <p style="margin: 0; font-size: 13px; color: #cbd5e1; line-height: 1.5;">
                  A comissão validadora da secretaria informou o seguinte motivo: <em>{motivo_texto}</em>
                </p>
              </div>
              <p style="font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 20px;">
                Conforme as diretrizes oficiais do evento, o resgate de ingressos deste evento é exclusivo para servidores públicos municipais ativos e cadastrados.
              </p>
              <p style="font-size: 12px; color: #64748b; line-height: 1.5; margin-top: 25px; margin-bottom: 0;">
                Caso considere que houve equívoco na checagem cadastral, procure diretamente o setor de Recursos Humanos ou a organização.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Serv indoor &bull; Gestão Oficial de Eventos
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return await enqueue_email(usuario_email, assunto, html, "communications")


async def send_team_credentials_email_async(
    to_email: str,
    nome: str,
    cpf: str,
    senha_provisoria: str,
    roles_str: str,
    is_reset: bool = False
) -> bool:
    """Envia credenciais de acesso com senha provisória para um membro da equipe"""
    titulo = "Redefinição de Senha - Equipe Serv indoor 2026" if is_reset else "Acesso à Equipe - Serv indoor 2026"
    subtitulo = "Sua nova senha de acesso foi gerada" if is_reset else "Seu acesso à equipe foi cadastrado com sucesso"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #07090e; color: #f8fafc; margin: 0; padding: 20px; }}
        .card {{ max-width: 520px; margin: 0 auto; background: #0f172a; border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 32px 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); }}
        .logo {{ font-size: 22px; font-weight: 800; color: #06b6d4; text-align: center; margin-bottom: 16px; letter-spacing: 0.5px; }}
        .title {{ font-size: 19px; font-weight: 700; color: #ffffff; margin-bottom: 6px; text-align: center; }}
        .sub {{ font-size: 13px; color: #94a3b8; margin-bottom: 22px; text-align: center; }}
        .box {{ background: rgba(6,182,212,0.08); border: 1px solid rgba(6,182,212,0.3); border-radius: 12px; padding: 18px; margin: 20px 0; }}
        .label {{ font-size: 11px; text-transform: uppercase; color: #94a3b8; font-weight: 700; letter-spacing: 0.5px; }}
        .val {{ font-size: 17px; font-weight: 700; color: #ffffff; font-family: monospace; margin-top: 4px; }}
        .notice {{ background: rgba(245,158,11,0.1); border-left: 4px solid #f59e0b; padding: 12px 14px; border-radius: 6px; font-size: 13px; color: #fbbf24; margin: 18px 0; line-height: 1.4; }}
        .footer {{ font-size: 11px; color: #64748b; text-align: center; margin-top: 24px; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 14px; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="logo">SERV INDOOR 2026</div>
        <div class="title">{titulo}</div>
        <div class="sub">{subtitulo}</div>
        <p style="font-size: 14px; line-height: 1.5; color: #e2e8f0;">Olá, <strong>{nome}</strong>.</p>
        <p style="font-size: 14px; line-height: 1.5; color: #cbd5e1;">Você possui acesso à área restrita da organização com as seguintes permissões: <strong>{roles_str}</strong>.</p>
        
        <div class="box">
          <div class="label">CPF de Acesso</div>
          <div class="val">{cpf}</div>
          <div style="height: 12px;"></div>
          <div class="label">Senha Provisória</div>
          <div class="val" style="color: #38bdf8;">{senha_provisoria}</div>
        </div>

        <div class="notice">
          <strong>Atenção:</strong> Por motivos de segurança, esta é uma <strong>senha provisória</strong>. Ao realizar seu primeiro login, o sistema exigirá obrigatoriamente que você defina uma nova senha pessoal definitiva.
        </div>

        <p style="font-size: 13px; color: #94a3b8; text-align: center;">Acesse a plataforma oficial para realizar seu primeiro acesso.</p>
        <div class="footer">Prefeitura de Caruaru &bull; Organização Serv indoor 2026</div>
      </div>
    </body>
    </html>
    """

    return await enqueue_email(to_email, f"{titulo} - Serv indoor 2026", html_content, "team")
