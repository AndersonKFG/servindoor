"""Popula dados de demonstração de forma aditiva e idempotente."""
import asyncio
import uuid
from datetime import datetime, timedelta
from sqlalchemy import func, select, text
from app.core.security import get_password_hash
from app.db.session import async_session
from app.models.all_models import Eixo, Ingresso, Lote, LogAcesso, Premio, Secretaria, SolicitacaoValidacao, UserRole, Usuario

EIXOS = ["Gestão, Planejamento e Finanças", "Saúde e Qualidade de Vida", "Educação, Cultura e Esporte", "Infraestrutura, Obras e Mobilidade", "Segurança, Cidadania e Assistência Social"]
SECS = [("Secretaria de Governo","SEGOV",1),("Administração e Gestão","SEMAD",1),("Finanças e Tributação","SEFIN",1),("Planejamento Estratégico","SEPLAN",1),("Comunicação Social","SECOM",1),("Controladoria Geral","CGM",1),("Procuradoria Geral","PGM",1),("Secretaria Municipal de Saúde","SMS",2),("Fundo Municipal de Saúde","FMS",2),("Vigilância Sanitária","VISA",2),("Previdência dos Servidores","IPREV",2),("Secretaria Municipal de Educação","SEMED",3),("Fundação Cultural","FUNCULT",3),("Juventude, Esportes e Lazer","SEMJEL",3),("Turismo e Eventos","SETUR",3),("Obras e Serviços Públicos","SEMOSP",4),("Mobilidade Urbana e Trânsito","SEMOB",4),("Habitação e Regularização","SEHAB",4),("Meio Ambiente","SEMMA",4),("Agricultura e Abastecimento","SEAGRI",4),("Segurança Pública","SEMSP",5),("Guarda Civil Municipal","GCM",5),("Assistência Social e Família","SEMAS",5),("Defesa Civil","COMPDEC",5),("Mulher e Direitos Humanos","SEMDH",5)]
NOMES = ["Ana Silva","Bruno Santos","Carla Oliveira","Diego Souza","Eva Rodrigues","Felipe Ferreira","Giovana Alves","Hugo Pereira","Isabela Lima","João Costa"]

async def seed():
    async with async_session() as s:
        # Corrige sequências eventualmente atrasadas por carga manual/importações.
        for table in ["usuarios", "eixos", "secretarias", "lotes", "premios", "solicitacoes_validacao", "ingressos", "logs_acesso"]:
            await s.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), GREATEST(COALESCE((SELECT MAX(id) FROM {table}), 1), 1), true)"))
        for n, nome in enumerate(EIXOS, 1):
            if not await s.get(Eixo, n): s.add(Eixo(id=n, nome=f"Eixo {n} - {nome}", descricao=nome))
        await s.flush()
        for index, (nome, sigla, eixo_id) in enumerate(SECS, 1):
            sec = await s.get(Secretaria, index)
            if sec:
                sec.nome, sec.sigla, sec.eixo_id = nome, sigla, eixo_id
            else:
                s.add(Secretaria(id=index, nome=nome, sigla=sigla, eixo_id=eixo_id))
        await s.flush()
        secs = (await s.execute(select(Secretaria.id).order_by(Secretaria.id))).scalars().all()
        roles = [UserRole.admin_geral, UserRole.admin, UserRole.portaria, UserRole.entregador, UserRole.validador]
        for role_index, role in enumerate(roles, 1):
            count = (await s.execute(select(func.count(Usuario.id)).where(Usuario.role == role, Usuario.deleted_at.is_(None)))).scalar_one()
            for i in range(count, 10):
                cpf=f"88{role_index}{i:08d}"
                if not (await s.execute(select(Usuario.id).where(Usuario.cpf == cpf))).first():
                    s.add(Usuario(cpf=cpf,nome=f"Usuário Teste {role.value} {i+1:02d}",senha_hash=get_password_hash("Festa@2026"),role=role,roles=role.value,secretaria_id=secs[i%len(secs)],setor="Equipe de teste",vinculo="Efetivo",validado=True,ativo=True,email=f"teste.{role.value}.{i+1}@servindoor.com.br"))
        await s.flush()
        lots=(await s.execute(select(Lote).where(Lote.ativo.is_(True),Lote.deleted_at.is_(None)).order_by(Lote.id))).scalars().all()
        now=datetime.now()
        while len(lots)<3:
            lot=Lote(nome=f"Lote {len(lots)+1:02d} - Participantes",quantidade_total=1000,quantidade_resgatada=0,data_abertura=now-timedelta(days=1),data_fechamento=now+timedelta(days=30),ativo=True)
            s.add(lot); await s.flush(); lots.append(lot)
        for lot in lots: lot.quantidade_total=max(lot.quantidade_total,1000)
        current=(await s.execute(select(Usuario).where(Usuario.role==UserRole.servidor,Usuario.deleted_at.is_(None)).order_by(Usuario.id))).scalars().all()
        cpfs=set((await s.execute(select(Usuario.cpf))).scalars().all()); idx=0
        while len(current)<3000:
            cpf=f"700{idx:08d}"; idx+=1
            if cpf in cpfs: continue
            n=len(current)+1
            u=Usuario(cpf=cpf,nome=f"Participante Teste {n:04d} {NOMES[len(current)%10]}",role=UserRole.servidor,secretaria_id=secs[len(current)%len(secs)],setor="Setor de teste",vinculo="Efetivo",data_nascimento="1985-06-15",email=f"participante.teste.{n}@servindoor.com.br",telefone=f"(11) 90000-{n:04d}",validado=True,ativo=True)
            s.add(u); current.append(u); cpfs.add(cpf)
            if len(current)%300==0: await s.flush()
        await s.flush()
        ticket_users=set((await s.execute(select(Ingresso.usuario_id).where(Ingresso.deleted_at.is_(None)))).scalars().all())
        validation_users=set((await s.execute(select(SolicitacaoValidacao.usuario_id))).scalars().all())
        new_people=[u for u in current if u.id not in ticket_users and u.id not in validation_users]
        issued=0
        for i,u in enumerate(new_people):
            if i>=2850:
                status=["pendente_analise","aprovado","rejeitado"][i%3]
                s.add(SolicitacaoValidacao(usuario_id=u.id,lote_id=lots[i%3].id,secretaria_id=u.secretaria_id,status=status,motivo_rejeicao="Dados de teste" if status=="rejeitado" else None,criado_em=now-timedelta(days=1)))
                continue
            lot=lots[i%3]
            ticket=Ingresso(usuario_id=u.id,lote_id=lot.id,qr_code_token=str(uuid.uuid4()),data_resgate=now-timedelta(days=1))
            s.add(ticket); lot.quantidade_resgatada+=1; issued+=1
            if i%2==0:
                await s.flush(); s.add(LogAcesso(usuario_id=u.id,tipo="entrada",data_hora=now-timedelta(hours=2),ingresso_id=ticket.id,metodo_validacao="qr_code"))
            if i%500==0: await s.flush()
        await s.flush()
        for lot in lots:
            lot.quantidade_resgatada = (await s.execute(select(func.count(Ingresso.id)).where(Ingresso.lote_id == lot.id, Ingresso.deleted_at.is_(None)))).scalar_one()
        prize_count=(await s.execute(select(func.count(Premio.id)))).scalar_one()
        for i in range(prize_count,40):
            geral=i<30
            s.add(Premio(nome=f"Prêmio de Teste {i+1:02d} - {['Smart TV','Notebook','Eletrodomésticos','Bicicleta','Fone Bluetooth'][i%5]}",descricao="Item de demonstração para testes de sorteio.",categoria="categoria_1" if geral else "categoria_2",eixo_id=None if geral else i%5+1,quantidade=1,quantidade_sorteada=0,ativo=True,ordem=i+1))
        await s.commit()
        print(f"Concluído: {len(current)} participantes servidores, {issued} novos ingressos, 3 lotes ativos, 25 secretarias, 5 eixos, 40 prêmios.")

if __name__=="__main__": asyncio.run(seed())
