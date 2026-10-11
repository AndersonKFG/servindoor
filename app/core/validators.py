import re
from datetime import datetime
from typing import Optional

def normalizar_data_nascimento(data_str: Optional[str]) -> Optional[str]:
    """
    Normaliza a data de nascimento para o padrão ISO YYYY-MM-DD.
    Aceita YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY.
    Valida a consistência matemática da data e faixa plausível de idade.
    """
    if not data_str:
        return None
    data_limpa = str(data_str).strip()
    if not data_limpa:
        return None

    iso_str = None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", data_limpa):
        iso_str = data_limpa
    else:
        match_br = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", data_limpa)
        if match_br:
            dia, mes, ano = match_br.groups()
            iso_str = f"{ano}-{mes.zfill(2)}-{dia.zfill(2)}"

    if not iso_str:
        raise ValueError("Data de nascimento inválida. Use o formato AAAA-MM-DD ou DD/MM/AAAA.")

    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Data de nascimento inválida (dia ou mês inexistente).")

    hoje = datetime.now().date()
    if dt > hoje:
        raise ValueError("A data de nascimento não pode estar no futuro.")
    if dt.year < 1900:
        raise ValueError("Ano de nascimento inválido (deve ser posterior a 1900).")

    return iso_str


def formatar_telefone(telefone: Optional[str]) -> Optional[str]:
    """
    Valida e formata o telefone para o padrão brasileiro (XX) XXXXX-XXXX ou (XX) XXXX-XXXX.
    """
    if not telefone:
        return None
    tel_limpo = str(telefone).strip()
    if not tel_limpo:
        return None

    digitos = "".join([c for c in tel_limpo if c.isdigit()])
    if not digitos:
        return None

    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"

    raise ValueError("Telefone inválido. Informe o DDD e os 8 ou 9 dígitos do número.")


def validar_email(email: Optional[str]) -> Optional[str]:
    """
    Valida sintaxe básica e sanitiza endereço de e-mail.
    """
    if not email:
        return None
    email_limpo = str(email).strip().lower()
    if not email_limpo:
        return None

    if "@" not in email_limpo or "." not in email_limpo.split("@")[-1]:
        raise ValueError("Endereço de e-mail inválido.")
    if len(email_limpo) < 5 or " " in email_limpo:
        raise ValueError("Endereço de e-mail inválido.")

    return email_limpo
