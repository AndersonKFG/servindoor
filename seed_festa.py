# -*- coding: utf-8 -*-
import asyncio
import random
import uuid
from datetime import datetime, timedelta
from sqlmodel import select, delete, func
from app.db.session import async_session
from app.models.all_models import (
    Eixo, Secretaria, Usuario, Lote, Ingresso, LogAcesso,
    Premio, Ganhador, ReservaIngresso, UserRole, MovimentoTipo, PremioCategoria
)
from app.core.security import get_password_hash

PRIMEIROS_NOMES = [
    "Lucas", "Gabriel", "Matheus", "Guilherme", "Gustavo", "Felipe", "Rafael", "Leonardo", "Bruno", "Rodrigo",
    "Thiago", "Diego", "Vinicius", "Eduardo", "Danilo", "Alexandre", "Caio", "Renan", "Marcelo", "Fernando",
    "Ana", "Juliana", "Mariana", "Camila", "Larissa", "Beatriz", "Leticia", "Fernanda", "Amanda", "Jessica",
    "Bruna", "Natalia", "Vanessa", "Carolina", "Patricia", "Aline", "Renata", "Debora", "Daniela", "Flavia",
    "Carlos", "Marcos", "Andre", "Paulo", "Ricardo", "Fabio", "Leandro", "Adriano", "Marcio", "Roberto"
]

SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves", "Pereira", "Lima", "Gomes",
    "Costa", "Ribeiro", "Martins", "Carvalho", "Almeida", "Lopes", "Soares", "Fernandes", "Vieira", "Barbosa",
    "Rocha", "Dias", "Nascimento", "Andrade", "Moreira", "Nunes", "Marques", "Machado", "Mendes", "Freitas",
    "Cardoso", "Ramos", "Goncalves", "Santana", "Teixeira", "Araujo", "Castro", "Cavalcanti", "Macedo", "Monteiro"
]

SETORES = [
    "Administrativo", "Recursos Humanos", "Financeiro", "Atendimento ao Cidadão", "Tecnologia da Informação",
    "Jurídico / Contencioso", "Planejamento e Projetos", "Operações e Logística", "Fiscalização e Posturas",
    "Gabinete", "Contabilidade", "Compras e Licitações", "Comunicação e Mídia", "Manutenção e Patrimônio"
]

VINCULOS = ["Efetivo", "Efetivo", "Efetivo", "Comissionado", "Contrato Temporário"]

PREMIO_FOTOS_MAP = {
    "Smart TV 65": "/static/uploads/premios/cat_tv.jpg",
    "Smart TV 55": "/static/uploads/premios/cat_tv.jpg",
    "Smart TV 50": "/static/uploads/premios/cat_tv.jpg",
    "PlayStation": "/static/uploads/premios/cat_ps5.jpg",
    "Xbox": "/static/uploads/premios/cat_xbox.jpg",
    "Nintendo Switch": "/static/uploads/premios/cat_switch.jpg",
    "iPhone": "/static/uploads/premios/cat_iphone.jpg",
    "Galaxy S24": "/static/uploads/premios/cat_samsung_phone.jpg",
    "Galaxy A55": "/static/uploads/premios/cat_samsung_phone.jpg",
    "Redmi": "/static/uploads/premios/cat_redmi.jpg",
    "Dell": "/static/uploads/premios/cat_laptop_dell.jpg",
    "Lenovo": "/static/uploads/premios/cat_laptop_lenovo.jpg",
    "iPad": "/static/uploads/premios/cat_tablet_apple.jpg",
    "Tab S9": "/static/uploads/premios/cat_tablet_samsung.jpg",
    "Boombox": "/static/uploads/premios/cat_speaker_jbl.jpg",
    "PartyBox": "/static/uploads/premios/cat_speaker_jbl.jpg",
    "Charge 5": "/static/uploads/premios/cat_speaker_jbl.jpg",
    "Philco 12L": "/static/uploads/premios/cat_air_fryer.jpg",
    "Mondial": "/static/uploads/premios/cat_air_fryer.jpg",
    "Xiaomi Robot": "/static/uploads/premios/cat_robot_vacuum.jpg",
    "WAP Robot": "/static/uploads/premios/cat_robot_vacuum.jpg",
    "Nespresso": "/static/uploads/premios/cat_coffee_nespresso.jpg",
    "Dolce Gusto": "/static/uploads/premios/cat_coffee_maker.jpg",
    "Micro-ondas": "/static/uploads/premios/cat_microwave.jpg",
    "Aro 29": "/static/uploads/premios/cat_bike.jpg",
    "Bicicleta Elétrica": "/static/uploads/premios/cat_ebike.jpg",
    "Apple Watch": "/static/uploads/premios/cat_smartwatch.jpg",
    "Galaxy Watch": "/static/uploads/premios/cat_smartwatch_samsung.jpg",
    "Sony WH-1000XM4": "/static/uploads/premios/cat_headphones.jpg",
    "AirPods": "/static/uploads/premios/cat_airpods.jpg",
    "Kit Ferramentas": "/static/uploads/premios/cat_tools.jpg",
    "Parafusadeira": "/static/uploads/premios/cat_drill.jpg",
    "Purificador": "/static/uploads/premios/cat_water_purifier.jpg",
    "Climatizador": "/static/uploads/premios/cat_air_cooler.jpg",
    "Mala": "/static/uploads/premios/cat_suitcase.jpg",
    "Kindle": "/static/uploads/premios/cat_kindle.jpg",
    "Cadeira": "/static/uploads/premios/cat_chair.jpg",
    "Mochila": "/static/uploads/premios/cat_backpack.jpg",
    "Echo Show": "/static/uploads/premios/cat_echo_show.jpg",
    "Cafeteira": "/static/uploads/premios/cat_coffee_maker.jpg",
    "Pressão Arterial": "/static/uploads/premios/cat_pressure_monitor.jpg",
    "Bioimpedância": "/static/uploads/premios/cat_smart_scale.jpg",
    "Nutribullet": "/static/uploads/premios/cat_blender.jpg",
    "Massageadora": "/static/uploads/premios/cat_massage_gun.jpg",
    "Umidificador": "/static/uploads/premios/cat_diffuser.jpg",
    "Beach Tennis": "/static/uploads/premios/cat_tennis.jpg",
    "Echo Dot": "/static/uploads/premios/cat_echo_dot.jpg",
    "Bolas": "/static/uploads/premios/cat_balls.jpg",
    "Wacom": "/static/uploads/premios/cat_wacom.jpg",
    "Projetor": "/static/uploads/premios/cat_projector.jpg",
    "Kärcher": "/static/uploads/premios/cat_pressure_washer.jpg",
    "Trena": "/static/uploads/premios/cat_laser_measure.jpg",
    "Compressor": "/static/uploads/premios/cat_tire_pump.jpg",
    "Térmica": "/static/uploads/premios/cat_cooler.jpg",
    "Aspirador de Pó e Água": "/static/uploads/premios/cat_robot_vacuum.jpg",
    "Câmera": "/static/uploads/premios/cat_security_cam.jpg",
    "Fechadura": "/static/uploads/premios/cat_digital_lock.jpg",
    "Lanterna": "/static/uploads/premios/cat_flashlight.jpg",
    "Primeiros Socorros": "/static/uploads/premios/cat_first_aid.jpg",
    "Cofre": "/static/uploads/premios/cat_safe.jpg",
}

def resolver_foto_premio(nome):
    for k, v in PREMIO_FOTOS_MAP.items():
        if k.lower() in nome.lower():
            return v
    return "/static/uploads/premios/cat_tv.jpg"

def gerar_nome_completo():
    p = random.choice(PRIMEIROS_NOMES)
    s1 = random.choice(SOBRENOMES)
    s2 = random.choice(SOBRENOMES)
    if s1 == s2:
        s2 = "Melo"
    return f"{p} {s1} {s2}"

def gerar_cpf(idx):
    # Gera CPF numérico único de 11 dígitos
    # Base determinística para não colidir
    num = 10000000000 + idx
    return str(num)[:11]

async def seed():
    # Garante que todas as tabelas existam automaticamente
    from sqlmodel import SQLModel
    from app.db.session import engine
    import app.models.all_models
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    print("🚀 INICIANDO POVOAMENTO COMPLETO DO BANCO DE DADOS...")
    senha_padrao_hash = get_password_hash("Festa@2026")

    async with async_session() as session:
        

# =========================================================================
        # 1. EIXOS (5 EIXOS ESTRUTURADOS)
        # =========================================================================
        print("\n📌 1. Configurando 5 Eixos...")
        dados_eixos = [
            {"id": 1, "nome": "Eixo 1 - Gestão, Planejamento e Finanças", "descricao": "Secretarias de governança, finanças, compras e planejamento estratégico."},
            {"id": 2, "nome": "Eixo 2 - Saúde e Qualidade de Vida", "descricao": "Atenção primária, vigilância, urgência e assistência farmacêutica."},
            {"id": 3, "nome": "Eixo 3 - Educação, Cultura e Esporte", "descricao": "Rede municipal de ensino, projetos esportivos, turismo e patrimônio histórico."},
            {"id": 4, "nome": "Eixo 4 - Infraestrutura, Obras e Mobilidade", "descricao": "Obras viárias, saneamento, habitação, meio ambiente e serviços públicos."},
            {"id": 5, "nome": "Eixo 5 - Segurança, Cidadania e Assistência Social", "descricao": "Segurança urbana, guarda civil, assistência social e direitos humanos."}
        ]
        
        eixo_map = {}
        for de in dados_eixos:
            eixo = await session.get(Eixo, de["id"])
            if not eixo:
                eixo = Eixo(id=de["id"], nome=de["nome"], descricao=de["descricao"])
                session.add(eixo)
            else:
                eixo.nome = de["nome"]
                eixo.descricao = de["descricao"]
                session.add(eixo)
            eixo_map[de["id"]] = eixo
        await session.commit()
        print("✅ 5 Eixos prontos!")

        # =========================================================================
        # 2. SECRETARIAS (25 SECRETARIAS VINCULADAS AOS EIXOS)
        # =========================================================================
        print("\n📌 2. Configurando 25 Secretarias...")
        dados_secretarias = [
            # Eixo 1
            (1, "Secretaria de Governo", "SEGOV", 1),
            (2, "Secretaria de Administração e Gestão", "SEMAD", 1),
            (3, "Secretaria de Finanças e Tributação", "SEFIN", 1),
            (4, "Secretaria de Planejamento Estratégico", "SEPLAN", 1),
            (5, "Secretaria de Comunicação Social", "SECOM", 1),
            (6, "Controladoria Geral do Município", "CGM", 1),
            (7, "Procuradoria Geral do Município", "PGM", 1),
            # Eixo 2
            (8, "Secretaria Municipal de Saúde", "SMS", 2),
            (9, "Fundo Municipal de Saúde", "FMS", 2),
            (10, "Vigilância Sanitária e Epidemiológica", "VISA", 2),
            (11, "Instituto de Previdência dos Servidores", "IPREV", 2),
            # Eixo 3
            (12, "Secretaria Municipal de Educação", "SEMED", 3),
            (13, "Fundação Cultural e Patrimônio", "FUNCULT", 3),
            (14, "Secretaria de Juventude, Esportes e Lazer", "SEMJEL", 3),
            (15, "Secretaria de Turismo e Eventos", "SETUR", 3),
            # Eixo 4
            (16, "Secretaria de Obras e Serviços Públicos", "SEMOSP", 4),
            (17, "Secretaria de Mobilidade Urbana e Trânsito", "SEMOB", 4),
            (18, "Secretaria de Habitação e Regularização", "SEHAB", 4),
            (19, "Secretaria de Meio Ambiente e Sustentabilidade", "SEMMA", 4),
            (20, "Secretaria de Agricultura e Abastecimento", "SEAGRI", 4),
            # Eixo 5
            (21, "Secretaria de Segurança Pública e Defesa Social", "SEMSP", 5),
            (22, "Guarda Civil Municipal", "GCM", 5),
            (23, "Secretaria de Assistência Social e Família", "SEMAS", 5),
            (24, "Defesa Civil Municipal", "COMPDEC", 5),
            (25, "Secretaria da Mulher e Direitos Humanos", "SEMDH", 5)
        ]

        sec_ids = []
        for s_id, s_nome, s_sigla, s_eixo in dados_secretarias:
            sec = await session.get(Secretaria, s_id)
            if not sec:
                sec = Secretaria(id=s_id, nome=s_nome, sigla=s_sigla, eixo_id=s_eixo)
                session.add(sec)
            else:
                sec.nome = s_nome
                sec.sigla = s_sigla
                sec.eixo_id = s_eixo
                session.add(sec)
            sec_ids.append(s_id)
        await session.commit()
        print("✅ 25 Secretarias prontas e distribuídas nos 5 eixos!")

        # =========================================================================
        # 3. USUÁRIOS DA EQUIPE (20 USUÁRIOS COM PERMISSÕES DIFERENTES)
        # =========================================================================
        print("\n📌 3. Configurando 20 Usuários da Equipe (Admin Geral, Admin, Portaria, Entregador)...")
        # Mantém intacto o superadmin Anderson Kauan (08557025408)
        # Cria os membros adicionais da equipe
        equipe_config = [
            ("08557025408", "Anderson Kauan Ferreira Goveia", UserRole.admin_geral, "admin_geral,admin,portaria,entregador", 1, "Gabinete do Prefeito"),
            ("11122233301", "Mariana Beatriz Fagundes", UserRole.admin_geral, "admin_geral,admin", 1, "Coordenação Geral"),
            ("11122233302", "Renato Augusto Barreto", UserRole.admin, "admin", 2, "Gestão de RH"),
            ("11122233303", "Juliana Paes Vasconcelos", UserRole.admin, "admin", 3, "Auditoria Financeira"),
            ("11122233304", "Felipe Nogueira Siqueira", UserRole.admin, "admin", 4, "Planejamento TI"),
            ("11122233305", "Patricia Helena Gusmão", UserRole.admin, "admin", 8, "Comitê da Saúde"),
            ("11122233306", "Lucas Fontes Cavalcante", UserRole.admin, "admin", 12, "Comitê da Educação"),
            ("11122233307", "Rodrigo Dantas Meireles", UserRole.portaria, "portaria", 21, "Portaria Entrada Principal"),
            ("11122233308", "Camila Vilela Esteves", UserRole.portaria, "portaria", 21, "Portaria VIP / Imprensa"),
            ("11122233309", "Thiago Moura Alencar", UserRole.portaria, "portaria", 22, "Catracas Leste"),
            ("11122233310", "Vanessa Lins Carneiro", UserRole.portaria, "portaria", 22, "Catracas Oeste"),
            ("11122233311", "Diego Pimentel Castro", UserRole.portaria, "portaria", 21, "Recepção Central"),
            ("11122233312", "Bruna Farias Guimarães", UserRole.portaria, "portaria", 21, "Scanner Rápido 01"),
            ("11122233313", "Marcelo Antunes Bittencourt", UserRole.portaria, "portaria", 22, "Scanner Rápido 02"),
            ("11122233314", "Alexandre Neves Coimbra", UserRole.entregador, "entregador", 14, "Palco Principal"),
            ("11122233315", "Debora Silveira Peixoto", UserRole.entregador, "entregador", 14, "Entrega Eixo Saúde"),
            ("11122233316", "Caio Vinicius Meireles", UserRole.entregador, "entregador", 14, "Entrega Eixo Educação"),
            ("11122233317", "Leticia Prates Albuquerque", UserRole.entregador, "entregador", 14, "Entrega Eixo Obras"),
            ("11122233318", "Guilherme Sampaio Teles", UserRole.admin, "admin,portaria", 5, "Supervisão e Portaria"),
            ("11122233319", "Fernanda Brandão Fontenele", UserRole.portaria, "portaria,entregador", 23, "Portaria e Prêmios")
        ]

        for cpf_eq, nome_eq, role_eq, roles_eq, sec_eq, setor_eq in equipe_config:
            stmt_u = select(Usuario).where(Usuario.cpf == cpf_eq)
            res_u = await session.execute(stmt_u)
            user = res_u.scalars().first()
            if not user:
                user = Usuario(
                    cpf=cpf_eq,
                    nome=nome_eq,
                    senha_hash=senha_padrao_hash,
                    role=role_eq,
                    roles=roles_eq,
                    secretaria_id=sec_eq,
                    setor=setor_eq,
                    vinculo="Efetivo",
                    validado=True,
                    ativo=True,
                    email=f"{nome_eq.lower().replace(' ', '.')}@servindoor.com.br",
                    telefone="(11) 98111-2233",
                    ultimo_acesso=None
                )
                session.add(user)
            else:
                user.nome = nome_eq
                user.role = role_eq
                user.roles = roles_eq
                user.secretaria_id = sec_eq
                user.setor = setor_eq
                user.senha_hash = senha_padrao_hash
                user.ativo = True
                user.ultimo_acesso = None
                session.add(user)
        await session.commit()
        print("✅ 20 Usuários de Equipe prontos com credenciais e permissões (Senha: Festa@2026)!")

        # =========================================================================
        # 4. LOTES (EXATAMENTE 3 LOTES)
        # =========================================================================
        print("\n📌 4. Configurando 3 Lotes...")
        # Lote 1: 1000 resgatados de 1000
        # Lote 2: 1000 resgatados de 1000
        # Lote 3: 500 resgatados de 800 (300 vagas livres)
        # Total = 2500 resgatados!
        agora = datetime.now()
        lotes_info = [
            {
                "id": 1,
                "nome": "Lote 01 - Abertura Geral",
                "total": 1000,
                "resgatada": 1000,
                "abertura": agora - timedelta(days=2),
                "fechamento": agora + timedelta(days=10),
                "ativo": True
            },
            {
                "id": 2,
                "nome": "Lote 02 - Saúde, Educação e Obras",
                "total": 1000,
                "resgatada": 1000,
                "abertura": agora - timedelta(days=1),
                "fechamento": agora + timedelta(days=10),
                "ativo": True
            },
            {
                "id": 3,
                "nome": "Lote 03 - Secretarias & Vagas Extras",
                "total": 800,
                "resgatada": 500,
                "abertura": agora - timedelta(hours=2),
                "fechamento": agora + timedelta(days=15),
                "ativo": True
            }
        ]

        # Atualiza ou cria os 3 lotes
        lote_objs = {}
        for l_def in lotes_info:
            lote = await session.get(Lote, l_def["id"])
            if not lote:
                lote = Lote(
                    id=l_def["id"],
                    nome=l_def["nome"],
                    quantidade_total=l_def["total"],
                    quantidade_resgatada=l_def["resgatada"],
                    data_abertura=l_def["abertura"],
                    data_fechamento=l_def["fechamento"],
                    ativo=l_def["ativo"]
                )
                session.add(lote)
            else:
                lote.nome = l_def["nome"]
                lote.quantidade_total = l_def["total"]
                lote.quantidade_resgatada = l_def["resgatada"]
                lote.data_abertura = l_def["abertura"]
                lote.data_fechamento = l_def["fechamento"]
                lote.ativo = l_def["ativo"]
                session.add(lote)
            lote_objs[l_def["id"]] = lote

        # Desativa lotes anteriores extras (se houver, como o lote 10 antigo)
        todos_lotes = (await session.execute(select(Lote))).scalars().all()
        for l_extra in todos_lotes:
            if l_extra.id not in [1, 2, 3]:
                l_extra.ativo = False
                session.add(l_extra)

        await session.commit()
        print("✅ 3 Lotes configurados (1000 + 1000 + 500 = 2500 resgatados, 300 vagas livres no Lote 3)!")

        # =========================================================================
        # 5. 2500 USUÁRIOS SERVIDORES + 2500 INGRESSOS NOMINAIS RESGATADOS
        # =========================================================================
        print("\n📌 5. Gerando 2.500 Servidores e 2.500 Ingressos Resgatados...")
        
        # Limpa ingressos e participantes gerados anteriormente para garantir contagem exata de 2500
        # Preserva os membros da equipe (IDs da equipe ou CPFs de equipe)
        cpfs_equipe = set(c[0] for c in equipe_config)
        
        # Deletar ingressos antigos
        await session.execute(delete(LogAcesso))
        await session.execute(delete(Ganhador))
        await session.execute(delete(ReservaIngresso))
        await session.execute(delete(Ingresso))
        # Deletar usuários servidores
        stmt_del_serv = delete(Usuario).where(Usuario.cpf.notin_(cpfs_equipe))
        await session.execute(stmt_del_serv)
        await session.commit()

        # Agora gera em lote 2500 servidores
        total_a_gerar = 2500
        print(f"   Criando {total_a_gerar} participantes...")

        novos_usuarios = []
        for i in range(total_a_gerar):
            cpf_servidor = f"{20000000000 + i}"[:11]
            nome_servidor = gerar_nome_completo()
            sec_id = random.choice(sec_ids)
            setor = random.choice(SETORES)
            vinculo = random.choice(VINCULOS)
            ano_nasc = random.randint(1968, 2003)
            mes_nasc = random.randint(1, 12)
            dia_nasc = random.randint(1, 28)
            dt_nasc = f"{ano_nasc}-{mes_nasc:02d}-{dia_nasc:02d}"
            email = f"servidor_{i+1}@servindoor.com.br"
            telefone = f"(11) 9{random.randint(7000, 9999)}-{random.randint(1000, 9999)}"

            u = Usuario(
                cpf=cpf_servidor,
                nome=nome_servidor,
                role=UserRole.servidor,
                roles=None,
                secretaria_id=sec_id,
                setor=setor,
                vinculo=vinculo,
                data_nascimento=dt_nasc,
                email=email,
                telefone=telefone,
                validado=True,
                ativo=True,
                foto_rosto_url=f"/static/uploads/fotos/perfil_{(i % 70) + 1}.jpg",
                ultimo_acesso=None
            )
            novos_usuarios.append(u)

        # Inserção em blocos de 500
        for chunk_start in range(0, total_a_gerar, 500):
            chunk = novos_usuarios[chunk_start:chunk_start+500]
            session.add_all(chunk)
            await session.flush()
        await session.commit()
        print(f"   ✅ {total_a_gerar} Usuários servidores cadastrados!")

        # Recupera os IDs dos servidores cadastrados
        stmt_serv = select(Usuario.id).where(Usuario.cpf.notin_(cpfs_equipe)).order_by(Usuario.id.asc())
        res_ids = await session.execute(stmt_serv)
        servidor_ids = res_ids.scalars().all()

        # Criação de 2500 Ingressos:
        # Lote 1: primeiros 1000
        # Lote 2: próximos 1000
        # Lote 3: últimos 500
        print("   Emitindo 2.500 Ingressos Nominais com QR Code...")
        novos_ingressos = []
        logs_acesso = []

        for idx, s_id in enumerate(servidor_ids):
            if idx < 1000:
                l_id = 1
                dt_resgate = agora - timedelta(days=2, hours=random.randint(1, 20), minutes=random.randint(0, 59))
            elif idx < 2000:
                l_id = 2
                dt_resgate = agora - timedelta(days=1, hours=random.randint(1, 20), minutes=random.randint(0, 59))
            else:
                l_id = 3
                dt_resgate = agora - timedelta(hours=random.randint(1, 12), minutes=random.randint(0, 59))

            qr_token = str(uuid.uuid4())
            ing = Ingresso(
                usuario_id=s_id,
                lote_id=l_id,
                qr_code_token=qr_token,
                data_resgate=dt_resgate
            )
            novos_ingressos.append(ing)

            # Simula presença de ~1.200 participantes (48% de presença na portaria)
            if idx % 2 == 0 or idx % 5 == 0:
                dt_entrada = agora - timedelta(hours=random.randint(0, 4), minutes=random.randint(0, 59))
                log = LogAcesso(
                    usuario_id=s_id,
                    tipo=MovimentoTipo.entrada,
                    data_hora=dt_entrada
                )
                logs_acesso.append(log)

        # Inserção em blocos
        for chunk_start in range(0, len(novos_ingressos), 500):
            session.add_all(novos_ingressos[chunk_start:chunk_start+500])
            await session.flush()

        for chunk_start in range(0, len(logs_acesso), 500):
            session.add_all(logs_acesso[chunk_start:chunk_start+500])
            await session.flush()

        await session.commit()
        print(f"✅ 2.500 Ingressos criados com sucesso! ({len(logs_acesso)} check-ins na portaria registrados)")

        # =========================================================================
        # 6. 60 PRÊMIOS (NENHUM SORTEADO)
        # =========================================================================
        print("\n📌 6. Configurando 60 Prêmios (35 Categoria Geral + 25 Prêmios Setoriais por Eixo)...")
        # Remove prêmios existentes para criar a lista oficial de 60
        await session.execute(delete(Premio))
        await session.commit()

        # Lista de 35 Prêmios da Categoria Geral (Categoria 1)
        premios_geral = [
            ("Smart TV 65' 4K UHD Crystal Samsung", "Tela gigante com comando de voz e Gaming Hub"),
            ("Smart TV 55' 4K UHD LG ThinQ AI", "Processador inteligente e HDR10 Pro"),
            ("Smart TV 50' 4K Philips Ambilight", "Efeito de iluminação traseira Ambilight imersivo"),
            ("PlayStation 5 Slim 1TB Sony", "Edição Slim com leitor de disco e controle DualSense"),
            ("Xbox Series X 1TB Microsoft", "O console mais poderoso da nova geração em 4K"),
            ("Nintendo Switch OLED 64GB", "Console híbrido com tela OLED vibrante de 7 polegadas"),
            ("iPhone 15 128GB Apple", "Dynamic Island, câmera principal de 48 MP e chip A16 Bionic"),
            ("Smartphone Galaxy S24 256GB Samsung", "Galaxy AI, câmera de 50MP e tela Dynamic AMOLED 2X"),
            ("Smartphone Galaxy A55 5G 128GB", "Design premium em metal e vidro, tela Super AMOLED 120Hz"),
            ("Smartphone Xiaomi Redmi Note 13 Pro 5G", "Câmera épica de 200MP e carregamento turbo de 67W"),
            ("Notebook Dell Inspiron 15 Core i7 16GB SSD 512GB", "Alto desempenho para trabalho e multitarefas"),
            ("Notebook Lenovo IdeaPad Ryzen 7 16GB SSD 512GB", "Design ultrafino com teclado numérico e bateria de longa duração"),
            ("iPad 10ª Geração 64GB Wi-Fi Apple", "Tela Liquid Retina de 10,9 polegadas e chip A14 Bionic"),
            ("Tablet Samsung Galaxy Tab S9 FE 128GB", "Acompanha Caneta S-Pen e certificação IP68 à prova d'água"),
            ("Caixa de Som JBL Boombox 3 Bluetooth 180W", "Graves monstruosos e bateria com até 24 horas de reprodução"),
            ("Caixa de Som JBL PartyBox Encore Essential", "Som potente de 100W e show de luzes sincronizado"),
            ("Caixa de Som JBL Charge 5 Portátil", "À prova d'água IP67 e powerbank integrado"),
            ("Fritadeira Elétrica Air Fryer Philco 12L Oven", "Frita, assa e desidrata com visor transparente"),
            ("Fritadeira Sem Óleo Air Fryer Mondial 5L", "Capacidade ideal para a família com cesto antiaderente"),
            ("Robô Aspirador e Passa Pano Xiaomi Robot Vacuum", "Mapeamento inteligente a laser e controle via aplicativo"),
            ("Robô Aspirador de Pó WAP Robot W300", "Sensor antiqueda, filtro HEPA e controle remoto"),
            ("Cafeteira Expresso Nespresso Vertuo Pop", "Cafés expressos e longos cremosos com leitura de código de barras"),
            ("Cafeteira Dolce Gusto Genio S Plus Arno", "Mais de 30 tipos de bebidas quentes e geladas"),
            ("Micro-ondas 34L Inox Espelhado Electrolux", "Função tira-odor, receitas pré-programadas e painel touch"),
            ("Bicicleta Aro 29 Alumínio 24 Marchas Freio a Disco", "Quadro esportivo reforçado e suspensão dianteira"),
            ("Bicicleta Elétrica Dobrável Urbana", "Autonomia de até 35km com motor elétrico assistido"),
            ("Smartwatch Apple Watch SE GPS 44mm", "Monitoramento de treinos, sono e saúde cardíaca"),
            ("Smartwatch Samsung Galaxy Watch 6 44mm", "Análise de composição corporal e cristal de safira"),
            ("Fone de Ouvido Sony WH-1000XM4 com Cancelamento de Ruído", "Referência mundial em cancelamento de ruído ativo"),
            ("Fone de Ouvido Apple AirPods 3ª Geração", "Áudio Espacial personalizado com rastreamento dinâmico da cabeça"),
            ("Kit Ferramentas Completo 142 Peças Schulz com Maleta", "Chaves, alicates, soquetes e catracas em cromo vanádio"),
            ("Parafusadeira e Furadeira de Impacto Bosch 12V", "Bateria de lítio, 2 velocidades e maleta de transporte"),
            ("Purificador de Água Refrigerado Electrolux Pure 4X", "Água gelada, natural e fresca com filtro avançado"),
            ("Climatizador de Ar Evaporativo Midea 7L", "Umidifica, ventila e purifica o ambiente com controle"),
            ("Mala de Viagem Grande Rígida 360° Samsonite", "Material ultraleve com trava TSA e 4 rodas multidirecionais")
        ]

        # Lista de 25 Prêmios Setoriais (Categoria 2) - 5 para cada Eixo
        premios_eixos = {
            1: [ # Eixo 1 - Gestão e Finanças
                ("Kindle Paperwhite 16GB Amazon", "Tela antirreflexo de 6,8 pol com temperatura de luz ajustável"),
                ("Cadeira Ergonômica de Escritório Presidente NR17", "Apoio de cabeça 3D, encosto em tela mesh e ajuste lombar"),
                ("Mochila Executiva Antifurto Impermeável com Porta USB", "Compartimento acolchoado para notebook até 17 polegadas"),
                ("Echo Show 8 com Alexa e Tela HD 8'", "Assistente virtual para gestão do dia e chamadas de vídeo"),
                ("Cafeteira Programável Digital Inox Oster", "Programe seu café para a hora que acordar")
            ],
            2: [ # Eixo 2 - Saúde e Bem-Estar
                ("Monitor de Pressão Arterial de Braço Omron Bluetooth", "Conecta ao celular para histórico médico instantâneo"),
                ("Balança de Bioimpedância Smart Xiaomi", "Medição de 13 parâmetros corporais e taxa metabólica"),
                ("Liquidificador Individual Nutribullet 600W", "Extrai nutrientes para sucos, smoothies e vitaminas"),
                ("Pistola Massageadora Muscular Profissional Fascial", "6 velocidades e ponteiras para alívio de dores e relaxamento"),
                ("Umidificador de Ar Ultrassônico e Difusor de Aromas", "Silencioso, com luzes LED cromoterapia e desligamento automático")
            ],
            3: [ # Eixo 3 - Educação, Cultura e Esporte
                ("Kit Esportivo Raquetes de Beach Tennis Carbono", "2 raquetes 3K carbono, capa térmica e 3 bolas oficiais"),
                ("Echo Dot 5ª Geração com Relógio Smart Speaker Alexa", "Voz cristalina e integração total com rotinas diárias"),
                ("Kit 3 Bolas Oficiais Penalty (Futebol, Vôlei e Futsal)", "Bolas com tecnologia Termotec sem costuras"),
                ("Mesa Digitalizadora Wacom One CTL472", "Ideal para anotações, desenhos digitais e ensino interativo"),
                ("Projetor Portátil Full HD Smart Wi-Fi", "Espelhe filmes e apresentações em qualquer parede até 120 polegadas")
            ],
            4: [ # Eixo 4 - Infraestrutura e Obras
                ("Lavadora de Alta Pressão Kärcher K3 1500W", "Limpeza pesada de pisos, garagens e veículos com economia de água"),
                ("Trena Laser Digital Bosch 40 Metros", "Medição precisa instantânea de distância, área e volume"),
                ("Compressor de Ar Portátil Digital Xiaomi para Pneus", "Calibra pneus de carro, moto e bike automaticamente"),
                ("Caixa Térmica Coleman 54 Litros com Rodas", "Mantém gelo por até 4 dias com alça telescópica"),
                ("Aspirador de Pó e Água WAP GTW 10L", "Aspira sólidos e líquidos com motor potente de 1400W")
            ],
            5: [ # Eixo 5 - Segurança e Cidadania
                ("Câmera de Segurança Smart Wi-Fi 360° Intelbras", "Visão noturna colorida, áudio bidirecional e inteligência artificial"),
                ("Fechadura Digital Biométrica com Senha e Cartão", "Abertura por biometria, senha touch e chave mecânica"),
                ("Kit Lanterna Tática Militar LED Cree Recarregável", "Super alcance com zoom tático e bateria recarregável"),
                ("Kit de Primeiros Socorros Completo Profissional com Bolsa", "Mais de 100 itens médicos essenciais para emergências"),
                ("Cofre Eletrônico Digital com Teclado Numérico", "Estrutura em aço reforçado com chave de emergência")
            ]
        }

        todos_premios = []
        ordem_cont = 1

        # 1. Adiciona os 35 Prêmios Gerais
        for nome_p, desc_p in premios_geral:
            p = Premio(
                nome=nome_p,
                descricao=desc_p,
                categoria=PremioCategoria.categoria_1.value,
                eixo_id=None,
                quantidade=1,
                quantidade_sorteada=0,
                ativo=True,
                ordem=ordem_cont,
                foto_url=resolver_foto_premio(nome_p)
            )
            todos_premios.append(p)
            ordem_cont += 1

        # 2. Adiciona os 25 Prêmios de Eixo (5 por eixo)
        for e_id, lista_p in premios_eixos.items():
            for nome_p, desc_p in lista_p:
                p = Premio(
                    nome=nome_p,
                    descricao=desc_p,
                    categoria=PremioCategoria.categoria_2.value,
                    eixo_id=e_id,
                    quantidade=1,
                    quantidade_sorteada=0,
                    ativo=True,
                    ordem=ordem_cont,
                    foto_url=resolver_foto_premio(nome_p)
                )
                todos_premios.append(p)
                ordem_cont += 1

        session.add_all(todos_premios)
        await session.commit()
        print(f"✅ {len(todos_premios)} Prêmios cadastrados com sucesso (Nenhum sorteado, quantidade_sorteada=0)!")

        # =========================================================================
        # 7. VERIFICAÇÃO FINAL DOS NÚMEROS
        # =========================================================================
        c_eixos = (await session.execute(select(func.count(Eixo.id)))).scalar()
        c_secs = (await session.execute(select(func.count(Secretaria.id)))).scalar()
        c_users = (await session.execute(select(func.count(Usuario.id)))).scalar()
        c_lotes = (await session.execute(select(func.count(Lote.id)).where(Lote.ativo == True))).scalar()
        c_ings = (await session.execute(select(func.count(Ingresso.id)))).scalar()
        c_prems = (await session.execute(select(func.count(Premio.id)))).scalar()
        c_ganhs = (await session.execute(select(func.count(Ganhador.id)))).scalar()
        c_pres = (await session.execute(select(func.count(LogAcesso.id)))).scalar()

        print("\n========================================================")
        print("🎉 POVOAMENTO CONCLUÍDO COM SUCESSO TOTAL!")
        print("========================================================")
        print(f"🔹 Eixos:              {c_eixos}")
        print(f"🔹 Secretarias:        {c_secs}")
        print(f"🔹 Lotes Ativos:       {c_lotes}")
        print(f"🔹 Equipe Administrativa: 20 usuários (roles: admin_geral, admin, portaria, entregador)")
        print(f"🔹 Total de Usuários:  {c_users} (20 equipe + 2500 servidores)")
        print(f"🔹 Ingressos Emitidos: {c_ings} (100% nominal aos servidores)")
        print(f"🔹 Check-ins Portaria: {c_pres} registros")
        print(f"🔹 Prêmios Totais:     {c_prems} (35 Gerais + 25 Setoriais por Eixo)")
        print(f"🔹 Prêmios Sorteados:  {c_ganhs} (ZERO sorteados)")
        print("========================================================\n")

if __name__ == "__main__":
    asyncio.run(seed())