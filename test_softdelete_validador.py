import asyncio
import urllib.request
import json
from datetime import datetime
from sqlmodel import select
from app.db.session import async_session
from app.models.all_models import Usuario, Ingresso, Lote, UserRole
from app.core import security

async def test_all():
    print("=== 1. VERIFICAR BANCO DE DADOS SEM VALIDADOR ===")
    async with async_session() as session:
        # Check users
        stmt = select(Usuario)
        res = await session.execute(stmt)
        users = res.scalars().all()
        for u in users:
            print(f"User #{u.id}: {u.nome} | Role: {u.role} | Roles: {u.roles} | Ativo: {u.ativo} | DeletedAt: {u.deleted_at}")

        # Check superadmin token
        stmt_admin = select(Usuario).where(Usuario.cpf == "08557025408")
        res_admin = await session.execute(stmt_admin)
        superadmin = res_admin.scalars().first()
        token = security.create_access_token(data={"sub": superadmin.cpf, "role": "admin_geral", "roles": superadmin.roles})

    print("\n=== 2. TESTAR SOFT-DELETE DE USUÁRIO ===")
    # 2.1 Criar usuário temporário para testar exclusão
    async with async_session() as session:
        test_u = Usuario(
            cpf="99988877766",
            nome="Usuário Teste Soft Delete",
            role=UserRole.portaria,
            roles="portaria",
            setor="Operação",
            vinculo="Staff",
            validado=True,
            ativo=True
        )
        session.add(test_u)
        await session.commit()
        await session.refresh(test_u)
        test_id = test_u.id
        print(f"Criado usuário de teste ID={test_id}")

    # 2.2 Chamar DELETE /api/admin/usuarios/{test_id}
    req = urllib.request.Request(f"http://localhost:8000/api/admin/usuarios/{test_id}", method="DELETE")
    req.add_header("Cookie", f"access_token=Bearer {token}")
    with urllib.request.urlopen(req) as resp:
        del_data = json.loads(resp.read().decode())
        print(f"Resposta DELETE: {del_data}")

    # 2.3 Checar no banco se o registro ainda existe com deleted_at preenchido e ativo=False
    async with async_session() as session:
        check_u = await session.get(Usuario, test_id)
        print(f"Registro no BD pós-delete: ID={check_u.id} | Ativo={check_u.ativo} | DeletedAt={check_u.deleted_at}")
        assert check_u.deleted_at is not None, "ERRO: deleted_at não foi preenchido!"
        assert check_u.ativo is False, "ERRO: ativo não foi setado para False!"

    # 2.4 Checar listagem da equipe para garantir que ele NÃO aparece mais
    req_list = urllib.request.Request("http://localhost:8000/api/admin/usuarios-equipe")
    req_list.add_header("Cookie", f"access_token=Bearer {token}")
    with urllib.request.urlopen(req_list) as resp:
        equipe_data = json.loads(resp.read().decode())
        ids_equipe = [u["id"] for u in equipe_data.get("usuarios", [])]
        print(f"IDs na listagem da equipe: {ids_equipe}")
        assert test_id not in ids_equipe, "ERRO: Usuário soft-deleted apareceu na listagem da equipe!"
        print("✅ Soft delete de usuário funcionando 100%!")

    print("\n=== 3. TESTAR SOFT-DELETE DE INGRESSO / PARTICIPANTE ===")
    async with async_session() as session:
        stmt_ing = select(Ingresso).where(Ingresso.deleted_at.is_(None))
        res_ing = await session.execute(stmt_ing)
        active_ing = res_ing.scalars().first()
        if active_ing:
            ing_id = active_ing.id
            print(f"Testando cancelamento do ingresso ID={ing_id}")
            req_cancel = urllib.request.Request(f"http://localhost:8000/api/admin/ingressos/{ing_id}/cancelar", method="POST")
            req_cancel.add_header("Cookie", f"access_token=Bearer {token}")
            with urllib.request.urlopen(req_cancel) as resp:
                cancel_resp = json.loads(resp.read().decode())
                print(f"Resposta Cancelar Ingresso: {cancel_resp}")
            
            # Checar no banco se o ingresso tem deleted_at
            ing_db = await session.get(Ingresso, ing_id)
            print(f"Ingresso pós cancelamento: ID={ing_db.id} | DeletedAt={ing_db.deleted_at}")
            assert ing_db.deleted_at is not None, "ERRO: ingresso.deleted_at não foi preenchido!"
            print("✅ Soft delete de ingresso funcionando 100%!")

if __name__ == "__main__":
    asyncio.run(test_all())
