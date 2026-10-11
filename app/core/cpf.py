from typing import Optional

def limpar_cpf(cpf: Optional[str]) -> str:
    """Extrai somente os 11 dígitos numéricos do CPF com preenchimento à esquerda."""
    if not cpf:
        return ""
    digitos = "".join([c for c in str(cpf) if c.isdigit()])
    if not digitos:
        return ""
    return digitos.zfill(11)[-11:]

def formatar_cpf(cpf: Optional[str]) -> str:
    """Formata CPF no padrão 000.000.000-00."""
    c = limpar_cpf(cpf)
    if len(c) == 11:
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
    return cpf or ""

def mascarar_cpf(cpf: Optional[str]) -> str:
    """Mascara o CPF para conformidade LGPD: 000.***.***-00."""
    c = limpar_cpf(cpf)
    if len(c) == 11:
        return f"{c[:3]}.***.***-{c[9:]}"
    return cpf or ""

def validar_cpf_matematico(cpf: Optional[str]) -> bool:
    """
    Validação matemática oficial do CPF brasileiro (Módulo 11 com 2 dígitos verificadores).
    Rejeita valores incompletos ou com todos os dígitos iguais.
    """
    cpf_limpo = limpar_cpf(cpf)
    if len(cpf_limpo) != 11:
        return False
    if len(set(cpf_limpo)) == 1:
        return False

    # 1º Dígito Verificador
    soma = sum(int(cpf_limpo[i]) * (10 - i) for i in range(9))
    resto = (soma * 10) % 11
    d1 = 0 if resto == 10 else resto
    if d1 != int(cpf_limpo[9]):
        return False

    # 2º Dígito Verificador
    soma = sum(int(cpf_limpo[i]) * (11 - i) for i in range(10))
    resto = (soma * 10) % 11
    d2 = 0 if resto == 10 else resto
    if d2 != int(cpf_limpo[10]):
        return False

    return True
