import io
import base64
import smtplib
import asyncio
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger(__name__)

def gerar_qrcode_base64(data: str) -> str:
    """Gera imagem de QR Code em Base64 inline localmente sem depender de APIs externas"""
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
        img_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        logger.warning(f"Fallback para QR Code URL externo: {e}")
        return f"https://api.qrserver.com/v1/create-qr-code/?size=260x260&data={data}&margin=10"


def _send_smtp_email_sync(to_email: str, subject: str, html_body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM}>"
        msg["To"] = to_email

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        server.starttls()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
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
    """Envia o ingresso digital por e-mail em background com QR Code e design premium"""
    if not usuario_email or "@" not in usuario_email:
        return False

    subject = "🎟️ Seu Ingresso Garantido! - Servindoor"
    qr_url = gerar_qrcode_base64(ingresso_token)

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Ingresso Servindoor</title>
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
                🎉 Vaga Confirmada
              </span>
              <h1 style="margin: 0; color: #ffffff; font-size: 26px; font-weight: 800; letter-spacing: -0.5px;">
                Servindoor
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                Servindoor &bull; Seu ingresso nominal está pronto!
              </p>
            </td>
          </tr>

          <!-- Corpo do Ingresso -->
          <tr>
            <td style="padding: 30px 25px; text-align: center;">
              <p style="font-size: 16px; color: #cbd5e1; margin-top: 0; margin-bottom: 20px;">
                Olá, <strong style="color: #ffffff; font-size: 18px;">{usuario_nome}</strong>!
              </p>
              <p style="font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 25px;">
                Parabéns! Seu resgate foi efetuado com sucesso. Apresente este QR Code na portaria do evento junto com seu documento de identificação oficial com foto.
              </p>

              <!-- Card Branco do QR Code -->
              <table role="presentation" align="center" style="background: #ffffff; border-radius: 16px; padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); margin: 0 auto 25px; text-align: center;">
                <tr>
                  <td align="center">
                    <img src="{qr_url}" alt="QR Code Ingresso" width="220" height="220" style="display: block; margin: 0 auto; border-radius: 8px;" />
                    <div style="margin-top: 14px; padding-top: 12px; border-top: 1px solid #e2e8f0;">
                      <span style="display: block; font-size: 10px; font-weight: 800; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;">
                        Token Portaria
                      </span>
                      <code style="font-size: 15px; font-weight: 800; color: #0f172a; font-family: monospace; display: block; margin-top: 3px;">
                        {ingresso_token}
                      </code>
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Detalhes do Servidor -->
              <table role="presentation" width="100%" style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 18px; text-align: left; margin-bottom: 25px;">
                <tr>
                  <td style="padding: 6px 10px; font-size: 13px; color: #94a3b8;">Lote:</td>
                  <td style="padding: 6px 10px; font-size: 13px; color: #ffffff; font-weight: 600;" align="right">{lote_nome}</td>
                </tr>
                <tr>
                  <td style="padding: 6px 10px; font-size: 13px; color: #94a3b8;">CPF:</td>
                  <td style="padding: 6px 10px; font-size: 13px; color: #38bdf8; font-weight: 600; font-family: monospace;" align="right">{cpf_formatado or "Cadastrado"}</td>
                </tr>
                {f'<tr><td style="padding: 6px 10px; font-size: 13px; color: #94a3b8;">Secretaria:</td><td style="padding: 6px 10px; font-size: 13px; color: #ffffff;" align="right">{secretaria_nome}</td></tr>' if secretaria_nome else ''}
                {f'<tr><td style="padding: 6px 10px; font-size: 13px; color: #94a3b8;">Setor:</td><td style="padding: 6px 10px; font-size: 13px; color: #ffffff;" align="right">{setor}</td></tr>' if setor else ''}
              </table>

              <p style="font-size: 12px; color: #64748b; line-height: 1.5; margin-bottom: 0;">
                🔒 Ingresso individual, nominal e intransferível. A validação na portaria será realizada através da leitura do QR Code acima.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background: #0b1220; padding: 20px; text-align: center; border-top: 1px solid rgba(255,255,255,0.05);">
              <p style="margin: 0; font-size: 12px; color: #475569;">
                &copy; 2026 Servindoor &bull; Sistema Oficial de Gestão de Eventos
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

    return await asyncio.to_thread(_send_smtp_email_sync, usuario_email, subject, html)

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
                Servindoor
              </h1>
              <p style="margin: 8px 0 0; color: rgba(255,255,255,0.9); font-size: 14px;">
                Servindoor &bull; Mensagem da Organização
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
                &copy; 2026 Servindoor &bull; Sistema Oficial de Gestão de Eventos
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

    return await asyncio.to_thread(_send_smtp_email_sync, usuario_email, assunto, html)
